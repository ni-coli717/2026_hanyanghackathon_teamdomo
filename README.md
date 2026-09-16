# 냄새 나침반

운양동 주민의 냄새 관측과 기상 데이터를 결합해 악취 감지 조건과 가장 관련 높은 유입 방향을 탐색하는 오프라인 우선 Streamlit 앱입니다.

> 이 앱의 방향 표시는 유입 가능성 추정이며, 특정 시설이나 농가를 원인으로 판정하지 않습니다.

## 실행

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run app.py
```

첫 실행 시 `data/provided/`의 2026-09-09~2026-09-16 제공 시나리오가 로컬 `data/odor.db`에 적재됩니다. 원본 워크북의 `record_origin=simulated` 표기를 보존해 화면 상단에 가상 데이터 배너를 표시하며, 실제 주민 관측으로 표현하지 않습니다. `설정 · 데이터`에서 실데이터 영역으로 전환하거나 CSV를 가져올 수 있습니다.

## 주요 구조

- `app.py`: 상단 네비게이션과 6개 사용자 화면, 설정 화면
- `core/repo.py`: 향후 Supabase/Google Sheets 구현체로 교체 가능한 저장소 인터페이스
- `core/sample_data.py`: 고정 시드 샘플 CSV 생성기
- `core/import_workbook.py`: 제공 XLSX를 앱 스키마로 재현 가능하게 변환
- `core/features.py`: 30분 관측창, 기상 결합, 구역별 방향 정렬도
- `core/model.py`: 규칙 기준선, 로지스틱 회귀, 랜덤포레스트, 시간 기준 평가
- `ext/`: 가상 기기와 선택형 Arduino 직렬 연결
- `assets/logo.svg`: 나침반 장미와 바람 꼬리 단색 로고

샘플만 다시 만들려면:

```powershell
python -m core.sample_data --output data/sample --seed 20212
```

제공 워크북을 다시 변환하려면:

```powershell
python -m core.import_workbook "운양동_악취관측_20260909_20260916.xlsx" --output data/provided
```

검증하려면:

```powershell
pytest -q
```

## 인터넷 공개 배포

가장 간단한 경로는 Streamlit Community Cloud입니다.

1. 이 폴더를 GitHub 저장소의 `main` 브랜치에 푸시합니다.
2. <https://share.streamlit.io>에서 GitHub로 로그인하고 저장소 접근을 허용합니다.
3. **Create app → Yup, I have an app**을 선택합니다.
4. 저장소와 `main` 브랜치를 선택하고 엔트리 파일에 `app.py`를 입력합니다.
5. Advanced settings에서 Python `3.11`을 선택한 뒤 Deploy를 누릅니다.

공개 데모의 샘플·분석·AI·가상 기기는 그대로 작동합니다. 클라우드에는 물리적인 로컬 USB 포트가 없으므로 Arduino 화면은 자동으로 가상 기기 모드가 됩니다.

Community Cloud의 로컬 파일은 영구 저장소가 아닙니다. 샘플 시연에는 문제가 없지만 실제 주민 기록을 받을 때는 `core/repo.py`의 `Repository` 인터페이스에 Supabase/Postgres 또는 Google Sheets 구현체를 연결해야 합니다. 현재 화면에도 이 제한을 표시합니다.

## 실데이터 CSV

- 주민 관측: `reports.csv`
- 기상: 기상자료개방포털 AWS 형식 또는 내부 컬럼 형식
- 후보 방향: `sources.csv` — 좌표만 저장하며 방위각과 거리는 런타임 계산
- 관측 구역: `zones.csv`

실명, 주소, 연락처는 스키마에 존재하지 않습니다. `GUEST` 기록은 저장할 수 있지만 학습용 `n_observers`에서는 제외됩니다. 기기 대응 평가는 `device_log`에 저장되어 실외 관측 학습자료와 섞이지 않습니다.
