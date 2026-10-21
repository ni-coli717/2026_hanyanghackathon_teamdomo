# 실외 센서 노드 (ESP32)

## 배선 (ESP32 DevKit V1 30핀)
```
VIN(5V) ── MQ-137 VCC            3V3 ── SGP40 VCC, SHT31 VCC         GND 공통
MQ-137 AO ─┬─ 10kΩ ─┬─ GPIO34
           │        ├─ 10kΩ ─┬─ GND   (10kΩ 두 개 직렬 = 20kΩ → 5V가 3.33V로)
           │        └────────┘
GPIO21 SDA ── SGP40 SDA, SHT31 SDA     GPIO22 SCL ── SGP40 SCL, SHT31 SCL
```
MQ-137 DO 는 사용하지 않는다. ADC2 핀(GPIO0,2,4,12~15,25~27)은 WiFi 중 읽히지 않으므로 GPIO34 고정.

## 설치
1. Arduino IDE → 보드 매니저 "esp32" 설치, 보드 "ESP32 Dev Module".
2. 라이브러리: Adafruit SHT31, Adafruit SGP40, Adafruit BusIO, ArduinoJson(7.x).
3. `config.example.h` → `config.h` 복사 후 SITE_ID·WiFi·Supabase URL·**anon 키** 입력.
4. 업로드 후 시리얼 모니터(115200)에서 `SHT31 1 SGP40 1` 과 POST 결과 확인.

## 동작
- 10초 샘플 × 6 = 1분 평균 1행, Supabase `sensor_readings` INSERT. 실패 시 최대 6시간 RAM 버퍼.
- LED: 켜짐=정상 / 1초 점멸=WiFi 없음 / 빠른 점멸=전송 실패 4회 이상.
- 예열: 전원 후 48시간은 `heater_sec` 로 서버가 자동 제외. 3대를 같은 자리에 나란히 두고 48시간 공동 예열 후 설치.

## 시뮬레이터
보드 없이 파이프라인을 돌릴 때: `python -m scripts.sensor_sim --site S1 --minutes 120` (서버 집계·화면 검증용, "시뮬레이터" 표기).
