"""냄새 나침반 — 공기질 관리 기기 연동 서비스.

웹앱(Streamlit)과 Arduino Uno를 USB 시리얼로 잇는다. 역할 분리:
  - 모델(predict.py)은 구역별 유입 가능성 level만 추정한다.
  - 제어 규칙(AutoRule)은 level 이력을 보고 ON/OFF를 결정한다. 모델이 직접 기기를 켜지 않는다.
  - 보드는 받은 ACTION만 수행한다. 보드가 풍향을 보고 스스로 판단하지 않는다.

기기가 없어도 웹앱은 정상 동작해야 하므로, 포트가 없으면 DEMO 모드로 떨어지고
'연결된 기기 없음'을 그대로 표시한다. 가짜 연결 성공을 만들지 않는다.
"""
from __future__ import annotations
import threading, time, queue, dataclasses
from typing import Optional, Callable

SECTOR_EN = {"북": "N", "북북동": "NNE", "북동": "NE", "동북동": "ENE", "동": "E", "동남동": "ESE",
             "남동": "SE", "남남동": "SSE", "남": "S", "남남서": "SSW", "남서": "SW", "서남서": "WSW",
             "서": "W", "서북서": "WNW", "북서": "NW", "북북서": "NNW"}
LEVEL_EN = {"높음": "HIGH", "보통": "MID", "낮음": "LOW"}
BASIS_EN = {"observed_public_reference": "OBS", "estimated_from_adjacent_actuals": "EST",
            "synthetic_climatology": "DEMO", "kma_forecast": "FCST", "forecast_csv": "DEMO"}

BAUD = 9600
PING_SEC = 5.0


# --------------------------------------------------------------- 자동 제어 규칙
@dataclasses.dataclass
class AutoRule:
    """히스테리시스: 높음 2회 연속이면 켜고, 낮음 2회 연속이면 끈다.
    자료 없음(HOLD)은 직전 상태를 유지한다 — '자료 없음'을 '냄새 없음'으로 바꾸지 않기 위해서다."""
    on_streak: int = 2
    off_streak: int = 2
    enabled: bool = True

    _hi: int = 0
    _lo: int = 0
    _state: bool = False

    def decide(self, level: Optional[str]) -> str:
        if not self.enabled:
            return "HOLD"
        if level is None or level == "HOLD":
            self._hi = self._lo = 0
            return "HOLD"
        if level == "높음":
            self._hi += 1; self._lo = 0
        elif level == "낮음":
            self._lo += 1; self._hi = 0
        else:
            self._hi = self._lo = 0
        if not self._state and self._hi >= self.on_streak:
            self._state = True; return "ON"
        if self._state and self._lo >= self.off_streak:
            self._state = False; return "OFF"
        return "ON" if self._state else "OFF"

    def reset(self):
        self._hi = self._lo = 0; self._state = False


# --------------------------------------------------------------- 기기 연결
class DeviceLink:
    """백그라운드 스레드로 시리얼을 읽고 쓴다. Streamlit 재실행에도 살아 있도록
    st.cache_resource로 한 번만 만든다."""

    def __init__(self, port: Optional[str] = None, baud: int = BAUD,
                 on_report: Optional[Callable[[str], None]] = None):
        self.port = port; self.baud = baud
        self.on_report = on_report
        self.ser = None
        self.status = "연결된 기기 없음"
        self.mode = "AUTO"          # AUTO | MANUAL (보드 버튼으로 바뀜)
        self.device_fan = None      # 보드가 보고한 실제 상태
        self.last_ack = None
        self.last_error = None
        self._tx = queue.Queue()
        self._stop = threading.Event()
        self._thread = None

    # ---- 연결
    @staticmethod
    def list_ports() -> list[str]:
        try:
            from serial.tools import list_ports
            return [p.device for p in list_ports.comports()]
        except Exception:
            return []

    @staticmethod
    def autodetect() -> Optional[str]:
        try:
            from serial.tools import list_ports
            for p in list_ports.comports():
                blob = f"{p.description} {p.manufacturer or ''} {p.hwid}".lower()
                if any(k in blob for k in ("arduino", "ch340", "wch", "usb-serial", "usbmodem")):
                    return p.device
        except Exception:
            pass
        return None

    def connect(self, port: Optional[str] = None) -> bool:
        self.close()
        self.port = port or self.port or self.autodetect()
        if not self.port:
            self.status = "연결된 기기 없음"; self.last_error = "포트를 찾지 못했습니다"; return False
        try:
            import serial
            self.ser = serial.Serial(self.port, self.baud, timeout=0.2)
            time.sleep(2.0)                     # 보드 리셋 대기
            self.ser.reset_input_buffer()
            self.status = "연결됨"; self.last_error = None
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
            return True
        except Exception as e:
            self.ser = None; self.status = "연결 실패"; self.last_error = str(e); return False

    def close(self):
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        if self.ser:
            try: self.ser.close()
            except Exception: pass
        self.ser = None; self._thread = None
        if self.status == "연결됨": self.status = "연결된 기기 없음"

    @property
    def connected(self) -> bool:
        return self.ser is not None and self.status == "연결됨"

    # ---- 송신
    def send_state(self, wind_sector_ko: Optional[str], level_ko: Optional[str],
                   action: str, basis_key: str = "synthetic_climatology", calm: bool = False):
        wind = "CALM" if calm else SECTOR_EN.get(wind_sector_ko or "", "NA")
        lvl = "HOLD" if level_ko is None else LEVEL_EN.get(level_ko, "HOLD")
        line = f"ODOR|{wind}|{lvl}|{action}|{BASIS_EN.get(basis_key, 'DEMO')}"
        self._tx.put(line)
        return line

    def set_auto(self):
        """보드를 수동 모드에서 자동 모드로 되돌린다."""
        self._tx.put("MODE|AUTO")

    # ---- 스레드
    def _run(self):
        last_ping = 0.0
        while not self._stop.is_set():
            try:
                while not self._tx.empty():
                    line = self._tx.get_nowait()
                    self.ser.write((line + "\n").encode())
                if time.time() - last_ping > PING_SEC:
                    self.ser.write(b"PING\n"); last_ping = time.time()
                raw = self.ser.readline().decode(errors="ignore").strip()
                if raw:
                    self._handle(raw)
            except Exception as e:
                self.status = "연결 끊김"; self.last_error = str(e); break
            time.sleep(0.05)

    def _handle(self, line: str):
        if line.startswith("ACK|"):
            p = line.split("|")
            self.last_ack = line
            if len(p) >= 4:
                self.device_fan = (p[2] == "ON"); self.mode = p[3]
        elif line.startswith("OVERRIDE|"):
            self.mode = "MANUAL"; self.device_fan = line.endswith("ON")
        elif line.startswith("REPORT|"):
            self.mode = self.mode
            if self.on_report:
                try: self.on_report(line.split("|", 1)[1])
                except Exception: pass


# --------------------------------------------------------------- 웹앱에서 쓰는 헬퍼
def push_prediction(link: DeviceLink, rule: AutoRule, pred_row, basis_key: str) -> dict:
    """predict_windows 결과 한 행(등록 구역)을 규칙에 넣고 보드로 보낸다.
    pred_row: status, level, wind_from_sector, direction_status 를 가진 dict/Series."""
    status = pred_row.get("status")
    level = None if status != "예비 추정" else pred_row.get("level")
    action = rule.decide(level)
    calm = pred_row.get("direction_status") == "방향 보류(약풍)"
    sent = None
    if link.connected:
        sent = link.send_state(pred_row.get("wind_from_sector"), level, action, basis_key, calm)
    return dict(level=level, action=action, sent=sent, connected=link.connected,
                mode=link.mode, device_fan=link.device_fan, rule_enabled=rule.enabled)
