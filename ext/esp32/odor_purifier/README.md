# 공기청정기 모듈 (ESP32, Wi-Fi 직결)

PC 브리지(`scripts/device_bridge.py`) 없이 보드가 Supabase 에 직접 붙는 판. 서버 쪽(device_get/device_report/device_set)과
앱 '기기' 시트는 Uno+브리지 판과 그대로 공유한다.

## 1단계 — 보드만으로 연결 확인 (부품 없이)
1. Arduino IDE → 보드 매니저 "esp32"(Espressif) 설치 → 보드 "ESP32 Dev Module", Upload Speed 921600.
2. 라이브러리 관리자: **ArduinoJson** 7.x.
3. `config.h` 에서 `WIFI_SSID`, `WIFI_PASS` 두 줄만 채운다 (나머지는 secrets.toml 에서 자동 생성됨. git 에 안 올라감).
4. 업로드 → 시리얼 모니터 115200. 아래처럼 나오면 연결 성공:
   ```
   wifi 192.168.x.x
   odor purifier esp32-purifier-1 device XXXX
   get command=OFF source=plan mode=auto level=LOW wind=ENE
   ```
   - 보드 내장 파란 LED = 팬 상태. 앱 '기기' 시트에서 수동 켜기 → 20초 안에 LED 켜짐.
   - `device_get fail 401` → config.h 의 DEVICE_ID/TOKEN 확인. `wifi FAIL` → 2.4GHz 와이파이인지 확인(5GHz 불가).
   - 업로드가 "Connecting....." 에서 멈추면 BOOT 버튼을 누른 채 시작.

## 2단계 — 배선 (ESP32 DevKit V1 30핀)
```
GPIO26 ── 릴레이 모듈 IN (또는 팬 모듈 신호)      릴레이 VCC=5V(VIN), GND 공통
GPIO27 ── 220Ω ── 초록 LED ── GND                 (가동)
GPIO25 ── 220Ω ── 빨간 LED ── GND                 (대기)
GPIO33 ── 택트 스위치 ── GND                      (내부 풀업)
GPIO21/22 ── I2C LCD SDA/SCL (선택, config.h USE_LCD 1, 라이브러리 "LiquidCrystal I2C")
```
- 팬/공기청정기 전원은 보드에서 끌어오지 않는다. 릴레이 접점으로 외부 전원(또는 청정기 전원선)을 끊고 잇는다.
- 릴레이가 LOW 에서 붙는 제품이면 `FAN_ACTIVE_LOW 1`.
- 0, 2, 12, 15 는 부팅 스트랩 핀 → 입력에 쓰지 않는다. 34~39 는 풀업 없음.

## 동작 규칙 (Uno 판과 동일)
- 20초마다 `device_get` 의 command(ON/OFF/HOLD)만 따른다. 보드는 풍향으로 판단하지 않는다. HOLD = 직전 상태 유지.
- 5분 동안 서버 응답이 없으면 팬 OFF + NO SIGNAL.
- 버튼 짧게 = 수동 켜기/끄기(서버 mode on/off 2시간 → 앱에 '수동' 표시). 길게 0.8초 = 냄새 신고(device_status.note).
- 60초마다·상태 바뀔 때 `device_report`(fan, mode, fw, rssi) → 앱 기기 카드 "가동 중 · 응답 hh:mm".

## 시연 리허설
`run_demo_prep.bat` → 앱·보드 모두 같은 시연 예보. 가동 예정 시각에 보드 LED(팬) ON 확인 → `run_demo_off.bat`.
브리지(run_device_bridge/sim.bat)와 ESP32 를 **동시에** 켜면 둘 다 같은 기기로 보고하므로 하나만 켠다.
