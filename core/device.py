"""App-side glue for the air-care board (odor_model.device_service).

- One DeviceLink per server process (st.cache_resource in viewer_app), because reopening a
  serial port on every rerun locks it.
- Link status, last ACK/error and a short TX/RX log are written to data/device_status.json so
  the separate operator process can show them.
- REPORT|SMELL from the board is stored as a spontaneous, device_button observation; it never
  enters the scheduled detection rate.
- SimulatedBoard mirrors ext/arduino/odor_purifier/odor_purifier.ino for testing without
  hardware. It is only offered when ODOR_DEVICE_SIM=1 and is always labelled '시뮬레이터'.
"""
from __future__ import annotations

import json
import os
import threading
import time
from collections import deque
from pathlib import Path
from uuid import uuid4

from odor_model.device_service import BASIS_EN, DeviceLink

ROOT = Path(__file__).resolve().parents[1]
STATUS_PATH = ROOT / 'data/device_status.json'
SIM_PORT = 'SIMULATOR'


def simulator_enabled() -> bool:
    return os.getenv('ODOR_DEVICE_SIM', '') == '1'


# ------------------------------------------------------------------ board simulator
class SimulatedBoard:
    """Serial-like object following odor_purifier.ino: ACK, manual override, link timeout, LCD pages."""
    LINK_TIMEOUT = 15.0
    PAGE_SEC = 5.0          # sketch redraws its LCD page every PAGE_MS, replacing 'REPORT SENT'

    def __init__(self):
        self.fan_on = False
        self.manual = False
        self.link_alive = False
        self.wind, self.risk, self.basis = 'NA', 'HOLD', 'DEMO'
        self.last_rx = 0.0
        self.unplugged = False
        self.report_at = None
        self._out = deque()
        self._lock = threading.Lock()
        self.clock = time.monotonic

    # serial API
    def reset_input_buffer(self):
        with self._lock: self._out.clear()

    def write(self, data: bytes):
        if self.unplugged:
            raise OSError('USB 분리됨')
        for line in data.decode(errors='ignore').splitlines():
            self._handle(line.strip().upper())
        return len(data)

    def readline(self) -> bytes:
        if self.unplugged:
            raise OSError('USB 분리됨')
        self.tick()
        with self._lock:
            if self._out:
                return (self._out.popleft() + '\n').encode()
        time.sleep(0.05)
        return b''

    def close(self):
        pass

    # board logic
    def _emit(self, line):
        with self._lock: self._out.append(line)

    def _ack(self):
        self._emit(f"ACK|{self.risk}|{'ON' if self.fan_on else 'OFF'}|{'MANUAL' if self.manual else 'AUTO'}")

    def _handle(self, line):
        if not line:
            return
        self.last_rx = self.clock(); self.link_alive = True
        if line == 'PING':
            self._ack(); return
        if line.startswith('MODE|AUTO'):
            self.manual = False; return
        if not line.startswith('ODOR|'):
            return
        f = (line[5:].split('|') + ['', '', '', ''])[:4]
        if f[0]: self.wind = f[0]
        if f[1]: self.risk = f[1]
        if f[3]: self.basis = f[3]
        if not self.manual:
            if f[2] == 'ON': self.fan_on = True
            elif f[2] == 'OFF': self.fan_on = False
        self._ack()

    def tick(self):
        if self.link_alive and self.clock() - self.last_rx > self.LINK_TIMEOUT:
            self.link_alive = False
            if not self.manual:
                self.fan_on = False; self.risk = 'HOLD'

    def press_short(self):
        self.manual = True; self.fan_on = not self.fan_on
        self._emit('OVERRIDE|ON' if self.fan_on else 'OVERRIDE|OFF')

    def press_long(self):
        self.report_at = self.clock()
        self._emit('REPORT|SMELL')

    def unplug(self):
        """Board side keeps running on its own power in this model; host loses the port."""
        self.unplugged = True

    def lcd(self) -> list[list[str]]:
        """Both LCD pages [[line1, line2], [line1, line2]] as the sketch would draw them."""
        self.tick()
        if self.report_at is not None and self.clock() - self.report_at < self.PAGE_SEC:
            return [['REPORT SENT', 'THANK YOU']] * 2
        if not self.link_alive and not self.manual:
            return [['NO SIGNAL', 'CHECK USB LINK']] * 2
        page0 = [f'WIND FROM:{self.wind}', f"EST:{self.risk}".ljust(11) + ('MANUAL' if self.manual else self.basis)]
        if self.fan_on:
            page1 = ['MANUAL RUN' if self.manual else 'ODOR INFLOW EST', 'PURIFYING AIR...']
        elif self.risk == 'HOLD':
            page1 = ['NO ESTIMATE', 'DATA HOLD']
        else:
            page1 = [f'AIRFLOW: {self.wind}', 'SYSTEM: STANDBY']
        return [page0, page1]

    def leds(self) -> dict:
        return {'green': self.fan_on, 'red': not self.fan_on, 'fan': self.fan_on}


# ------------------------------------------------------------------ app link
class AppDeviceLink(DeviceLink):
    def __init__(self, repo=None, **kwargs):
        super().__init__(on_report=self._report, **kwargs)
        self.repo = repo
        self.report_zone = None          # registered zone of the most recent viewer session
        self.log = deque(maxlen=60)
        self.events = 0                  # bumps on anything a viewer should redraw for
        self.reports_saved = 0
        self.board = None

    # ports
    def ports(self) -> list[str]:
        found = self.list_ports()
        return found + ([SIM_PORT] if simulator_enabled() else [])

    def autodetect(self):
        return DeviceLink.autodetect() or (SIM_PORT if simulator_enabled() and not DeviceLink.list_ports() else None)

    def connect(self, port=None) -> bool:
        self.close()
        target = port or self.autodetect()
        if target != SIM_PORT:
            ok = super().connect(target)
            self._note('SYS', f"연결 {'성공' if ok else '실패'} · {self.port or '포트 없음'}")
            return ok
        self.port, self.board, self.ser = SIM_PORT, SimulatedBoard(), None
        self.ser = self.board
        self.status, self.last_error = '연결됨', None
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._note('SYS', '연결 성공 · 시뮬레이터')
        return True

    def disconnect(self):
        was = self.port
        self.close()
        self.status, self.port, self.board = '연결된 기기 없음', None, None
        if was:
            self._note('SYS', f'해제 · {was}')
        self.mode, self.device_fan = 'AUTO', None
        self._bump()

    @property
    def simulator(self) -> bool:
        return self.port == SIM_PORT

    # traffic hooks
    def send_state(self, *args, **kwargs):
        line = super().send_state(*args, **kwargs)
        self._note('TX', line)
        return line

    def set_auto(self):
        super().set_auto()
        self._note('TX', 'MODE|AUTO')

    def _handle(self, line):
        previous = self.last_ack
        super()._handle(line)
        if line.startswith('ACK|'):
            self.last_ack_at = time.strftime('%H:%M:%S')
            if line == previous:        # repeated PING acks: record the time, no redraw
                self._persist()
                return
        self._note('RX', line)

    def _run(self):
        super()._run()
        if self.status == '연결 끊김':
            self.device_fan = None      # board state is unknown once the link drops
            self._note('SYS', f'연결 끊김 · {self.last_error}')
            self._bump()

    def _report(self, kind):
        """Board long press: store one spontaneous device_button record for the registered zone."""
        if not self.repo:
            self.last_error = '제보 저장소 없음 · 저장하지 않았습니다'
        elif not self.report_zone:
            self.last_error = '등록 위치가 관측 구역 밖 · 제보를 저장하지 않았습니다'
        else:
            try:
                self.repo.save_observation(device_report(self.report_zone))
                self.reports_saved += 1
            except Exception as exc:  # noqa: BLE001
                self.last_error = f'제보 저장 실패 · {exc}'
        self._bump()

    # status for viewer and operator
    def _note(self, direction, text):
        self.log.append({'at': time.strftime('%H:%M:%S'), 'dir': direction, 'line': text})
        self._bump()

    def _bump(self):
        self.events += 1
        self._persist()

    def signature(self):
        return (self.status, self.mode, self.device_fan, self.events)

    def snapshot(self) -> dict:
        return {'status': self.status, 'connected': self.connected, 'port': self.port, 'simulator': self.simulator,
                'mode': self.mode, 'device_fan': self.device_fan, 'last_ack': self.last_ack,
                'last_ack_at': getattr(self, 'last_ack_at', None), 'last_error': self.last_error,
                'reports_saved': self.reports_saved, 'log': list(self.log)[-30:],
                'lcd': self.board.lcd() if self.board else None, 'leds': self.board.leds() if self.board else None}

    def _persist(self):
        try:
            STATUS_PATH.write_text(json.dumps({**self.snapshot(), 'updated': time.strftime('%Y-%m-%d %H:%M:%S')},
                                              ensure_ascii=False, indent=1), encoding='utf-8')
        except OSError:
            pass


def device_report(zone_id: str) -> dict:
    """Board button '냄새 남': spontaneous, device_button, no intensity. Excluded from scheduled rates."""
    from .config import now_kst, observation_window
    moment = now_kst()
    key = str(uuid4())
    return dict(observation_id=key, participant_id='DEVICE', zone_id=zone_id,
                observed_at=moment.isoformat(), received_at=moment.isoformat(),
                context='indoor', odor_detected=True, intensity=None, odor_type='기기 버튼 신고',
                collection_mode='spontaneous', prediction_seen=False,
                window_id=observation_window(moment).isoformat(), record_origin='device_button',
                idempotency_key=key)


def read_status() -> dict | None:
    try:
        return json.loads(STATUS_PATH.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def basis_key(frame: dict, payload: dict) -> str:
    """Board BASIS: forecast frames by source; demo data is DEMO as a whole; live uses the weather basis."""
    if frame.get('kind') == 'forecast':
        return 'kma_forecast' if payload.get('forecast', {}).get('source') == 'kma' else 'forecast_csv'
    if payload.get('demo'):
        return 'synthetic_climatology'
    return {'관측': 'observed_public_reference', '추정': 'estimated_from_adjacent_actuals'}.get(frame.get('basis'), 'synthetic_climatology')


assert set(BASIS_EN) >= {'kma_forecast', 'forecast_csv', 'synthetic_climatology'}
