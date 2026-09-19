# 운양동 악취 예측 모델 (odor_model)

주민 관측 3개월(6/18~9/16) 자료로 학습한 **구역별 집단 감지 예측기**와 **유입 방향·유형 추정기**. 상태: 예비 실험·미보정.

## 구성

| 파일 | 역할 |
|---|---|
| `features.py` | 관측 → 구역×시간창 학습표, 특징 생성, 구역→후보 방위·정렬도, 임시 좌표 |
| `train.py` | 학습·시간순 평가 → `artifacts/odor_model.joblib`, `evaluation.md` |
| `predict.py` | 현재 기상(now) / 예보 CSV(forecast) / 기상청 단기예보 API(kma)로 예측 |
| `artifacts/` | 학습 결과, 평가표, 학습표 CSV, 후보 방위표, 예보 예측 예시 |
| `sample_forecast.csv` | 예보 입력 형식 예시(가상값) |

## 모델이 답하는 것

1. **감지 여부**: 구역별로 "이 기상이면 주민 절반 이상이 냄새를 감지할 가능성"을 p로 추정 → 낮음 / 보통(≥0.5) / 높음(≥검증 임계값 0.75)
2. **어디서 오는지**: 풍향(불어오는 방향)과 각 구역에서 본 후보 지역 방위의 정렬도. 정렬 / 여러 방향 가능 / 정렬 후보 없음 / 방향 보류(약풍 <0.5 m/s)
3. **어떤 냄새로 느껴질지**: 축산계 추정 / 하수계 추정 / 기타·미확인 (주민 주관 분류를 재현하는 보조 모델, 약함)
4. **미래**: 기상청 단기예보(VEC·WSD·REH·TMP·PCP)를 같은 입력으로 넣으면 시각별 예측. `basis=kma_forecast`로 구분 표시.

## 사용

```bash
pip install scikit-learn pandas openpyxl joblib requests
python train.py --data ../운양동_악취관측_20260618_20260916.xlsx --out artifacts
python predict.py now --time "2026-09-19 22:00" --wind-dir 동북동 --wind-speed 0.8 --humidity 82 --temp 21
python predict.py forecast --csv sample_forecast.csv --out out.csv
python predict.py kma --key <공공데이터포털 서비스키> --nx 55 --ny 128 --out out.csv   # 격자 좌표는 운영자 확인
```

Streamlit 앱에서는 직접 부르지 말고 `core.analysis_service.predict_windows()`를 쓴다(모델 없음·버전 불일치 시 추정 보류). 패키지로 쓸 때:

```python
from odor_model.predict import load_model, predict_rows
m = load_model()
res = predict_rows(weather_df, m)   # 열: window_start, wind_from_deg, wind_speed, humidity_pct, temperature_c, rain_1h_mm
```

`res` 열: `zone_id, zone_name, status, p_detect, level, wind_from_sector, move_to_sector, direction_status, aligned_candidates, type_top, type_probs, basis`

## 방향 규칙 (지도·나침반 공통)

- 기상청 풍향 = 불어오는 방향. 나침반 강조 = `wind_from_deg`. 지도 화살표 = `move_to_deg = (wind_from_deg+180)%360`.
- 예: 북동풍 45° → 나침반 북동 강조, 지도 화살표 남서 225°로 이동.

## 화면에 반드시 남길 표시

- 모든 결과에 "예비 실험·미보정" (`model_status`). p는 보정된 확률이 아니므로 % 표기 금지.
- `status=추정 보류`(핵심 기상 결측), `direction_status=방향 보류(약풍)`, `여러 방향 가능`은 그대로 노출.
- 후보 지역명은 상세 화면에서만. 첫 화면은 "북동쪽에서 유입 추정"처럼 방향만.
- 정렬도·유형은 발생원 판정이 아니다.

## 평가 요약 (`artifacts/evaluation.md`)

- 평가 구간 9/9~9/16(96건, 양성 8): 로지스틱 회귀 AUC 0.76, 임계값 0.75에서 재현율 0.63·정밀도 0.14. 지속성 기준선(재현율 0.13)보다 놓치는 사건은 적지만 오경보가 많다.
- 자동 제어(창문·공기청정기)는 재현율 우선 + 사용자 해제 + 히스테리시스로 잦은 on/off를 막는 별도 규칙이 결정한다.
- 생성 자료로 학습·평가했으므로 수치는 파이프라인 검증용이다. 실제 관측이 쌓이면 `train.py`를 그대로 다시 돌린다.

## 임시 좌표

`features.DEFAULT_GEO`의 구역 대표점·후보 좌표는 임시값이다. `--geo geo.json`으로 교체하고, 후보는 지역·시설 유형 수준으로만 표시한다.
