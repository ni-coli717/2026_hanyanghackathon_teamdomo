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
