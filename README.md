# 냄새 나침반 / 냄새 기록

같은 저장소의 공개 앱 두 개와 인증된 운영자 앱 하나입니다.

| 진입 파일 | 대상 | 기능 |
| --- | --- | --- |
| `viewer_app.py` (`app.py`도 동일) | 주민 조회 | 전체 화면 지도·시간 재생·작은 나침반, 위치 선택, 유형 필터, 공기질 관리 준비 화면 |
| `measurement_app.py` | 주민 참여 | 기본값 없는 단계별 설문, 제출 확인, 이 세션의 최근 기록 |
| `admin_app.py` | 운영자 | 인증 후 기존 분석·모델 비교·학습·CSV 관리·기기 시연 |

공개 앱은 운영자 링크를 제공하지 않습니다. 조회 앱은 과거 시연 자료와 현재 주민 기록을 구분하고, 보정되지 않은 모델 점수를 확률로 표시하지 않습니다.

## 로컬 실행

Python 3.11 환경에서 작업 폴더를 연 후 실행합니다.

```powershell
python -m pip install -r requirements.txt
$env:APP_ENV = "local"
$env:DATA_MODE = "demo"
$env:MEASUREMENT_APP_URL = "http://localhost:8502"
python -m streamlit run viewer_app.py
```

별도 터미널에서 다음을 실행합니다.

```powershell
$env:APP_ENV = "local"
python -m streamlit run measurement_app.py --server.port 8502
```

로컬의 세 프로세스는 같은 작업 폴더의 `data/resident.db`를 공유합니다. `OBSERVATION_DB_PATH`로 경로를 지정할 수도 있습니다. 조회 앱의 `DATA_MODE=live`는 주민 제출을 표시하고 `demo`는 읽기 전용 제공 시나리오만 표시합니다. 주민 제출을 시나리오 CSV에 섞거나 덮어쓰지 않습니다.

## 설정과 공유 저장소

환경변수가 secrets보다 우선합니다. `.streamlit/secrets.example.toml`을 참고하여 로컬 `secrets.toml` 또는 Cloud의 Secrets를 설정하세요. 실제 secrets 파일은 Git에서 제외됩니다.

```toml
APP_ENV = "cloud"
DATA_MODE = "demo"
MEASUREMENT_APP_URL = "https://YOUR-MEASUREMENT-APP.streamlit.app"

[database]
url = "https://YOUR-PROJECT.supabase.co"
key = "SERVER_ONLY_SERVICE_ROLE_KEY"

[admin]
password_hash = ""
```

환경변수 대응: `DATABASE_URL`, `DATABASE_KEY`, `ADMIN_PASSWORD_HASH`.
공유 저장소가 없는 클라우드 모드에서는 제출 버튼이 비활성화되고 저장된 것처럼 표시하지 않습니다. 로컬 디스크 저장을 원하면 명시적으로 `APP_ENV=local`을 설정하세요.

`deployment/supabase.sql`을 본인 Supabase 프로젝트에서 실행하고 두 앱의 database 설정에 같은 URL/key를 입력합니다. RLS가 켜지고 anon/authenticated의 테이블 권한은 차단됩니다. 키는 Python 서버에서만 사용하며 사용자 화면이나 URL에 전달하지 않습니다. 이 작업에서는 실제 외부 서비스 설정을 변경하지 않았습니다.

서로 다른 Streamlit Cloud 앱의 SQLite는 공유되지 않습니다. 두 앱을 운영하려면 공통 Supabase를 설정해야 합니다. 운영자 앱도 동일한 설정으로 주민 제출을 읽습니다.

## 두 공개 앱 배포

같은 GitHub 저장소 / main 브랜치로 Community Cloud 앱을 두 개 생성합니다.

1. 조회 앱: `viewer_app.py`. 기존 `app.py` 진입점도 조회 앱만 실행합니다.
2. 측정 앱: `measurement_app.py`.
3. 두 앱의 Python 버전과 database 설정을 동일하게 맞춥니다.
4. 조회 앱의 `MEASUREMENT_APP_URL`에 측정 앱 주소를 넣습니다.
5. 실제 주민 기록 조회를 시작할 때 조회 앱의 `DATA_MODE=live`를 설정합니다.

관리자 앱은 공개 배포하지 않고 로컬에서 실행합니다. 기존 조회 사이트는 main 브랜치의 app.py를 사용하므로 main 푸시가 배포 업데이트로 이어집니다. 기록 앱 생성과 공유 DB 설정은 별도로 필요합니다.

## 관리자 인증

```powershell
python -m core.auth
```

숨김 입력으로 비밀번호를 입력하면 PBKDF2 해시가 생성됩니다. 해시를 secrets의 `admin.password_hash` 또는 `ADMIN_PASSWORD_HASH` 환경변수에 설정한 뒤 실행하세요.

```powershell
python -m streamlit run admin_app.py --server.port 8503
```

인증 설정이 없으면 데이터 접근 전에 앱이 잠깁니다. 기존 `data/odor.db`, 모델, 통계 코드, CSV 설정, Arduino 스케치를 보존합니다. 운영자 실데이터 분석은 공통 주민 제출을 사용하며, CSV로 가져온 기상은 운영자 로컬 분석용입니다.

## 데이터 규칙과 출처

- 제공 시나리오: `data/provided/운양동_악취관측_20260618_20260916.xlsx` — 관측 7,143건, 시간창 364개, 427 양촌 기상 364건. 원본 `record_origin=simulated`이므로 실제 관측 결과로 표현하지 않습니다. `python -m core.import_workbook <xlsx>`로 `reports.csv`·`weather.csv`·`windows.csv`를 다시 만듭니다.
- 기상 구분(`weather_basis`)을 보존합니다: observed_public_reference → 관측(30) · estimated_from_adjacent_actuals → 추정(2) · synthetic_climatology → 시연(332).
- 주민 입력: `record_origin=resident`, UUID 기반 `idempotency_key`로 중복 제출 방지.
- `odor_detected`: true / false / null을 그대로 보존. 무응답은 행 자체가 없음.
- `scheduled` / `spontaneous` / `followup` 및 실내·실외를 구분. 정기 실외의 판단 가능한 관측만 기본 감지율에 사용.
- 시각은 KST, 정기 시간은 07:30 / 12:30 / 18:30 / 22:00, ±15분. `core/config.py`에서 관리.
- 공개 지도에는 구역 대표점만 표시. 개인 위치·실명·연락처는 수집하지 않음.
- 코드만으로는 본인 인증이 되지 않으므로 ‘내 최근 기록’은 현재 코드 + 현재 세션에서 제출한 기록만 공개.

`core/observations.py`의 공통 인터페이스를 두 앱이 사용합니다. `LocalObservations`와 `SharedObservations`는 같은 저장·조회·집계 메서드를 제공하고 기존 분석 컬럼은 어댑터로 연결합니다.

## 검증

```powershell
python -m compileall app.py viewer_app.py measurement_app.py admin_app.py core ext tests
python -m pytest -q
```

브라우저 검증용 추가 의존성과 실행법:

```powershell
python -m pip install playwright
python -m playwright install chromium
python tests/browser_check.py
```

브라우저 검증은 조회 8511 / 측정 8512 로컬 서버가 실행 중일 때 사용합니다. 테스트용 측정 DB는 `artifacts/browser-resident.db`로 별도 설정하세요. 스크린샷은 `artifacts/`에 저장됩니다.

## 알려진 한계

- Supabase 연결은 구현되어 있으나 실제 계정 연결·원격 통합 검증은 아직 하지 않았습니다.
- 실시간 관측 기상 API는 연결되지 않았습니다. live 주민 화면은 실제 기상이 없으면 방향을 보류합니다. 시연 기상을 실제 기상으로 대체하지 않습니다. 기상청 단기예보는 `kma.service_key`가 있을 때만 호출하며, 실제 키로는 검증하지 않았습니다.
- 배경 지도와 웹폰트는 인터넷이 필요합니다. 지도 배경을 못 불러오면 구역 선택과 텍스트 요약으로 조회할 수 있습니다.
- 구역 이름·대표 좌표는 기존 사용자 제공 임시값입니다. 실제 경계 검증은 남아 있습니다.
- 알림, 오프라인 저장/재전송, 실제 공기청정기 효과 검증은 구현하지 않았습니다.
- Arduino는 운영자 로컬 시연 기능이며 실제 하드웨어 검증은 별도입니다.
- 주민 코드 로그인은 없습니다. 영구 개인 기록 조회에는 별도 인증 설계가 필요합니다.

## 지도 중심 UI (2026-09-19)

`components/odor_map/`은 Leaflet 1.9.4 기반 양방향 Streamlit 컴포넌트입니다. Plotly 지도를 대체한 이유는 클릭 위치, 지도 카메라 유지, 브라우저 위치 권한, 좌표에 고정된 흐름선, 시간 재생을 한 상태로 관리하기 위해서입니다. npm 빌드나 지도 API 키는 필요하지 않습니다. 측정·운영자 앱은 그대로 유지합니다.

- 데스크톱: 76px 세로 메뉴, 전체 지도, 위치·유형·나침반·시간 바 오버레이.
- 모바일: 하단 메뉴, 시간 바, 접이식 나침반, 상세 바텀시트.
- 위치·시각·필터는 컴포넌트 상태로 유지하고 Python에 전달합니다. Python은 시각·위치·가까운 구역을 검증합니다. 브라우저에는 집계만 전달합니다.
- 지도 화살표는 `(풍향+180)%360`, 북쪽 고정 나침반은 불어오는 풍향입니다. 구역 대표점마다 그리는 2~4개 흐름선은 방향 참고이며 정밀 확산 경로가 아닙니다.
- 화살표 표시·색·굵기는 아래 모델 결과(유형·level)를 따르고, 구역 마커 색은 실제 주민 관측 감지율입니다.
- 관측 구역 폴리곤이 없으므로 2km 이내 가장 가까운 대표점의 자료를 참고합니다. 구역 소속이나 건물 단위 예측이라고 표시하지 않습니다. 김포 안이라도 관측 구역과 멀면 자료 없음입니다.
- `data/geo/gimpo.geojson`: southkorea/southkorea-maps에 공개된 KOSTAT 2018 행정경계에서 김포시만 추출. 최신 경계는 아닙니다. 출처·연도는 `data/geo/provenance.json`과 자료 정보에 표시합니다.
- 라이브러리는 로컬 배포하지만 배경 타일은 인터넷이 필요합니다. 타일 실패 시 안내·재시도를 표시하고 구역 마커와 자료 조회는 유지합니다. 대규모 서비스 전에는 타일 제공 정책과 제공업체를 검토하세요.
- 브라우저 위치 권한은 ‘내 위치’를 누를 때만 요청합니다. HTTPS(또는 localhost)에서 사용하며 권한 거부·서비스 지역 밖을 안내합니다. 선택 위치는 관측 DB에 저장하지 않습니다.
- 실기기 연결, 최신 행정경계 연동은 구현하지 않았습니다. 기록 앱 URL이 없으면 ‘준비 중’만 표시합니다. 예보 구간은 아래 ‘악취 예측 모델’ 참고.

검증: `python tests/browser_map_check.py` (조회 서버 8511). 전체 측정 회귀 검증은 `python tests/browser_check.py` (조회 8511 + 측정 8512, 테스트 DB 사용).
Leaflet·경계 재다운로드: `python scripts/fetch_map_assets.py` (앱 실행 시에는 다운로드하지 않음).

지도 출처: [OpenStreetMap 이용 정책](https://operations.osmfoundation.org/policies/tiles/), [Leaflet](https://leafletjs.com/), [행정경계 원본·이용 조건](https://github.com/southkorea/southkorea-maps). 라이브러리 라이선스는 `components/odor_map/vendor/LICENSE`에 포함합니다.

## 악취 예측 모델 (odor_model, 2026-09-19)

`odor_model/`은 첨부 패키지를 그대로 옮긴 것입니다(`features.py`, `train.py`, `predict.py`, `artifacts/`). 상태: **예비 실험·미보정**. 생성 자료로 학습·평가했으므로 평가 수치는 파이프라인 검증용입니다.

- 모든 화면은 `core/analysis_service.predict_windows(weather_df)` 결과 하나만 씁니다(지도 화살표, 나침반, 공기질 관리, 운영자 화면). 내부에서 `odor_model.predict.predict_rows`를 호출합니다. 결과는 행×구역을 한 번에 예측하도록 바꿨고 출력은 원본과 동일합니다(`sample_forecast_result.csv`로 확인).
- `requirements.txt`는 `scikit-learn==1.8.0`으로 고정했습니다. 번들 joblib이 1.8.0으로 저장되어 1.5.x에서는 예측 시 오류가 납니다. 로딩 시 1건을 시험 예측하고, 실패·파일 없음이면 앱은 계속 동작하며 ‘추정 보류’와 회색 바람 레이어만 표시합니다.
- 좌표: `data/geo/model_geo.json`(임시). 기존 `data/sample/zones.csv`·`sources.csv` 좌표를 우선 사용하고 C4만 `features.DEFAULT_GEO` 값입니다. 모델 ID(U01~U03, C1~C4)는 학습 특징과 연결되어 유지합니다(U01↔Z1, U02↔Z2, U03↔Z3).
- 운영 설정: `data/model_settings.json` — 보통 0.5 / 높음(null이면 모델 검증값 0.75) / 약풍 0.5 m/s / 정렬도 0.5 / 바람 레이어 전환 감지율 0.25 / 자동 대응 켜기·해제 연속 횟수. 공인 기준이 아닙니다.
- 화살표 규칙: 약풍(0.5 m/s 미만) → 화살표 없음·‘방향 보류’, 기상 결측 → ‘자료 없음’, 추정 낮음이면서 실제 감지율 25% 미만(또는 관측 없음) → 회색 바람 이동만, 그 외 → 유형 색(축산계 #D97706, 하수계 #7C3AED, 기타/미확인 #64748B). 예보 구간은 둥근 점선.
- 주민 화면에는 p 값·확률(%)·정렬도 점수를 보내지 않습니다. 정렬 후보 이름은 흐름선 상세에서만 보입니다.
- 예보: `st.secrets["kma"]` (`service_key`, `nx`, `ny` — 기본 55/128, 운영자 확인)가 있으면 기상청 단기예보를 1시간 캐시로 부릅니다. 키가 없거나 실패하면 `odor_model/sample_forecast.csv`를 ‘시연 예보’로 표시하고, 실패 사유를 자료 정보와 알림에 남깁니다. 환경변수 `KMA_SERVICE_KEY`/`KMA_NX`/`KMA_NY`도 됩니다.
- 공기질 관리: ‘지금(또는 최근 시각) 수준 · 향후 6시간 예보 최고 수준’과 자동 대응 판단(켜기/해제/유지)만 표시합니다. 기기 제어는 하지 않습니다. 기기 모듈용 인터페이스: `core.automation.get_auto_action(zone_id) -> "ON" | "OFF" | "HOLD"`.
- 운영자 앱 ‘⑦ 예측 모델’: 번들 평가(evaluation.md), 재학습(`python -m odor_model.train` → `data/models/odor/<시각>/`, 별도 저장), 주민 화면 모델 선택(명시적 적용 시에만 반영), 운영 설정, 임시 좌표 편집.

CLI: `python -m odor_model.predict forecast --csv odor_model/sample_forecast.csv` · `python -m odor_model.train --data data/provided/운양동_악취관측_20260618_20260916.xlsx --out <폴더> --geo data/geo/model_geo.json`.

검증: `python -m pytest -q` (모델 테스트는 scikit-learn 1.8.0 환경에서 실행, 아니면 건너뜀), `python tests/browser_map_check.py` (조회 8511), 모델 파일을 치운 상태에서 `python tests/browser_map_check.py missing`.

## 공기질 관리 기기 연동 (Arduino, 2026-09-19)

역할 분리: 모델은 구역별 `level`만 추정 → `AutoRule`(odor_model/device_service.py, 높음 2회 연속 켜기·낮음 2회 연속 끄기·자료 없음은 HOLD)이 ON/OFF를 정함 → 보드는 받은 ACTION만 수행합니다.

- 스케치: `ext/arduino/odor_purifier/odor_purifier.ino` (D7 버튼, D9 빨강 LED, D11 팬(액티브 로우), D12 초록 LED, I2C LCD 0x27, 9600bps). 기존 `ext/arduino/odor_fan.ino`(운영자 ⑥ 화면용 옛 프로토콜)는 그대로 둡니다.
- 프로토콜: `ODOR|<WIND>|<LEVEL>|<ACTION>|<BASIS>`, `PING`(5초), `MODE|AUTO` → 보드 응답 `ACK|<LEVEL>|<ACTION>|<MODE>`, `OVERRIDE|ON/OFF`(버튼 짧게), `REPORT|SMELL`(버튼 길게).
- 조회 앱: `DeviceLink`는 `st.cache_resource`로 서버 프로세스당 1개, `AutoRule`은 세션마다 `st.session_state`에 보관. 선택 시각·구역이 바뀔 때만 규칙에 1회 반영(연결·토글·자동 복귀는 현재 상태 재전송만). 보드 이벤트는 2초 주기 감시로 화면에 반영.
- 공기질 관리 패널: 등록 위치 · 주변 상태(모델) · 자동 대응 사용 중/사용 안 함 · 기기 상태(**보드 ACK 값**: 연결됨 · 가동 중/대기 중, 연결된 기기 없음, 연결 끊김, 연결 실패) · 포트 [자동 감지][연결][해제]. 보드가 MANUAL이면 "수동 조작 중 · 자동 대응 일시 중지" + [자동으로 되돌리기]. HOLD는 "판단 보류".
- 버튼 길게(`REPORT|SMELL`) → 등록 구역에 `collection_mode=spontaneous`, `record_origin=device_button`, `odor_detected=true`, 강도 없음으로 1건 저장. 정기 감지율에는 넣지 않고 지도에 "제보 N"(최근 3시간)으로 따로 표시. 공유 저장소를 쓰면 `deployment/supabase.sql`의 record_origin 제약 변경을 실행하세요.
- 보드 BASIS: 시연 모드 전체 DEMO, 예보 구간은 기상청이면 FCST·예시 파일이면 DEMO, live는 기상 구분(OBS/EST).
- 운영자 ⑦ 예측 모델 → `기기` 탭: 포트, 기기 상태, 마지막 ACK, 마지막 오류, 전송 로그(조회 앱이 쓰는 `data/device_status.json`을 읽음). on_streak/off_streak는 `운영 설정` 탭.
- **시뮬레이터(테스트 전용):** `ODOR_DEVICE_SIM=1`로 조회 앱을 실행하면 포트 목록에 `SIMULATOR`가 생깁니다. 스케치 동작(ACK, 수동 모드, 15초 무신호, LCD 문구)을 그대로 흉내 내며 화면에 "시뮬레이터 · 실제 기기 아님"으로 표시됩니다. 검증: `python -m pytest tests/test_device.py`, `python tests/browser_device_check.py`(시뮬레이터 조회 앱 8521).
- 실제 보드·LCD·LED·팬으로는 이 PC에 보드가 연결되지 않아 검증하지 못했습니다.
