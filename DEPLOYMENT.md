# 두 공개 앱 배포 안내

기존 조회 사이트는 GitHub main 브랜치의 app.py로 실행됩니다. main에 변경을 푸시하면 연결된 Community Cloud에서 업데이트합니다. 기록 앱은 measurement_app.py를 진입 파일로 별도 생성해야 합니다.

| 앱 | 같은 저장소의 진입 파일 |
| --- | --- |
| 냄새 나침반 (조회) | viewer_app.py — 기존 app.py도 동일한 조회 앱 |
| 냄새 기록 (측정) | measurement_app.py |
| 운영자 (로컬 비공개) | admin_app.py |

Community Cloud에서 같은 저장소로 두 앱을 만든 후 조회 앱 Secrets의 MEASUREMENT_APP_URL에 측정 앱 URL을 입력합니다. Python 3.11을 선택합니다.

두 앱에서 APP_ENV=cloud, 같은 database.url / database.key를 설정합니다. Supabase에 직접 deployment/supabase.sql을 실행해 테이블을 먼저 준비합니다. 키는 서버 전용 service role이며 공개하지 않습니다.

DATA_MODE=demo는 원본 시나리오만 읽습니다. 주민 제출은 별도 테이블에 기록됩니다. DATA_MODE=live로 전환하면 두 앱이 같은 주민 제출을 조회합니다. 독립 배포의 SQLite 파일은 공유되지 않습니다. 공유 백엔드가 없는 클라우드에서는 저장 버튼이 비활성화됩니다.

관리자 앱은 공개 메뉴에서 연결하지 않습니다. python -m core.auth로 생성한 해시를 admin.password_hash에 설정한 뒤 로컬에서 실행합니다. 비밀 설정은 Git에 커밋하지 않습니다.

현재 live 기상 API와 실제 Supabase 계정 연동 검증은 남아 있습니다. 설정 전체와 로컬 명령은 README.md 및 .streamlit/secrets.example.toml을 참고하세요.

## 로그인 · 계정 (2026-10-27, v3)
- 앱은 로그인 후에만 지도를 보여준다. 카카오·구글은 Streamlit `st.login`(OIDC), 이메일은 Supabase Auth.
- Supabase SQL: `deployment/supabase.sql`(observations) → `deployment/accounts.sql`(profiles). Authentication → Providers → Email 에서 시연 중엔 "Confirm email" 끔.
- 카카오·구글: `.streamlit/secrets.example.toml` 의 `[auth]`, `[auth.google]`, `[auth.kakao]` 를 `secrets.toml` 에 채운다 (`pip install Authlib`). 비어 있으면 그 버튼은 숨겨진다.
- 운영자 계정(`[auth] operators`)에만 안내 탭에 "기기 USB 연결 (운영)" 이 보인다.
- 로컬 점검: `run_tests.bat`(결과 data/private/pytest.txt), `http://localhost:8501/?diag=db`(APP_ENV=local 일 때만).

## 시연 모드 (2026-10-28)
- `run_demo_prep.bat`: 연결 코드 + 시연 가상 예보로 기기 일정. 같은 가상 예보를 `data/private/demo_forecast.csv`(6시간 유효)에 남겨 **앱 지도도 같은 예보**를 보여준다.
- `run_demo_off.bat`: 시연 끝. 파일을 지우고 실제 예보로 다시 계산. (15분마다 도는 GitHub Actions 도 실제 예보로 덮어쓴다 — 시연은 직전에 준비)
- 공기청정기 브리지: `run_device_bridge.bat`(Uno USB) / `run_device_sim.bat`(보드 없이). 로그 `data/private/bridge.log`.

## Streamlit Community Cloud 배포 (2026-10-28)
1. https://share.streamlit.io → Create app → 저장소 `ni-coli717/2026_hanyanghackathon_teamdomo`, branch `main`, main file `viewer_app.py`.
   Advanced settings: Python 3.11, **App URL `odor-compass`** (→ https://odor-compass.streamlit.app). 다른 이름을 쓰면 아래 redirect_uri 와 카카오·구글 Redirect URI 도 같이 바꾼다.
2. Settings > Secrets 에 `data/private/cloud_secrets.toml` 내용 통째로 붙여넣기 (APP_ENV=cloud, DATA_MODE=live, redirect_uri 가 배포 주소로 돼 있음).
3. 카카오 developers > 플랫폼 키 > REST API 키 수정 > 카카오 로그인 리다이렉트 URI 에 `https://odor-compass.streamlit.app/oauth2callback` 추가 (localhost 는 그대로 둠).
4. 배포 뒤 휴대폰에서 주소 열어 카카오 로그인 → 기록까지 확인. 서버 로그는 Cloud 의 "Manage app" 에서.
- 공기청정기 브리지(`run_device_bridge.bat`)는 PC 에서 계속 돈다(보드가 USB 로 PC 에 붙어 있으므로). 앱·서버는 Cloud, 기기 연결은 PC.
