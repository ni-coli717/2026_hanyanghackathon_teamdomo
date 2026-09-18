# 냄새 나침반 / 냄새 기록

같은 저장소의 공개 앱 두 개와 인증된 운영자 앱 하나입니다.

| 진입 파일 | 대상 | 기능 |
| --- | --- | --- |
| `viewer_app.py` (`app.py`도 동일) | 주민 조회 | 지도·나침반, 구역별 관측, 지난 기록, 생활 대응, 서비스 정보 |
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

- 제공 시나리오: 2026-09-09~16, 관측 655건과 기상 32건. 원본 `record_origin=simulated`이므로 실제 관측 결과로 표현하지 않습니다.
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
- 실시간 기상 API는 연결되지 않았습니다. live 주민 화면은 실제 기상이 없으면 방향을 보류합니다. 시연 기상을 실제 기상으로 대체하지 않습니다.
- 배경 지도와 웹폰트는 인터넷이 필요합니다. 지도 배경을 못 불러오면 구역 선택과 텍스트 요약으로 조회할 수 있습니다.
- 구역 이름·대표 좌표는 기존 사용자 제공 임시값입니다. 실제 경계 검증은 남아 있습니다.
- 알림, 오프라인 저장/재전송, 실제 공기청정기 효과 검증은 구현하지 않았습니다.
- Arduino는 운영자 로컬 시연 기능이며 실제 하드웨어 검증은 별도입니다.
- 주민 코드 로그인은 없습니다. 영구 개인 기록 조회에는 별도 인증 설계가 필요합니다.
