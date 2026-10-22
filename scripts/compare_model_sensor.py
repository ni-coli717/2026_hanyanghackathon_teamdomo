"""모델 추정 ↔ 센서 실측 대조표 만들기, 원하면 낮음/보통/높음 경계 보정.  (설계 v3 ②④)

사용(저장소 루트):
  python -m scripts.compare_model_sensor                  # 최근 14일, 기상은 저장소의 기상청 실황(log_weather 기록)
  python -m scripts.compare_model_sensor --days 7 --weather-csv data/external/aws/weather_441.csv
  python -m scripts.compare_model_sensor --apply          # 보정이 성립하면 data/model_settings.json 의 thr_mid·thr_high 갱신

출력: artifacts/sensor_compare/<시각>/ pairs.csv · calibration.json · report.md
모델 가중치는 건드리지 않는다. --apply 없이 실행하면 설정도 바꾸지 않는다.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from core.analysis_service import load_model, load_settings, predict_windows, save_settings
from core.config import now_kst
from core.sensor_store import open_sensor_store
from odor_model.predict import read_forecast_csv
from odor_model.sensor_compare import calibrate_thresholds, pair_windows, report_markdown
from odor_model.sensor_index import aggregate_10min, compute_index

ROOT = Path(__file__).resolve().parents[1]


def weather_from_store(store, since) -> pd.DataFrame:
    """log_weather 가 쌓은 초단기실황(ncst) → 모델 입력 표."""
    w = store.weather(kind='ncst', since=since)
    if w is None or w.empty:
        return pd.DataFrame()
    w = w.sort_values('base_dt').drop_duplicates('fcst_dt', keep='last')
    return pd.DataFrame(dict(window_start=w.fcst_dt.dt.tz_localize(None) if w.fcst_dt.dt.tz is not None else w.fcst_dt,
                             wind_from_deg=w.wind_dir_deg, wind_speed=w.wind_speed_ms, humidity_pct=w.humidity_pct,
                             temperature_c=w.temperature_c, rain_1h_mm=w.rain_1h_mm.fillna(0),
                             basis='kma_ncst', source='기상청 초단기실황')).reset_index(drop=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--days', type=int, default=14)
    ap.add_argument('--weather-csv', help='window_start·풍향·풍속·습도·기온·강수 열이 있는 CSV(예: AWS 변환본)')
    ap.add_argument('--apply', action='store_true', help='보정이 성립하면 설정 파일의 경계를 갱신')
    ap.add_argument('--out', default=str(ROOT / 'artifacts' / 'sensor_compare'))
    a = ap.parse_args()

    now = pd.Timestamp(now_kst()); since = now - pd.Timedelta(days=a.days)
    store, label = open_sensor_store()
    rd = store.readings(since=since)
    simulated = bool(len(rd)) and (rd.get('fw_version', pd.Series(dtype=str)).astype(str) == 'sim').any()
    idx = store.index(since=since)
    if idx.empty and len(rd):
        idx = compute_index(aggregate_10min(rd), store.calibration(), store.events())
    if idx.empty:
        print(f'{label}: 센서 지수 없음(최근 {a.days}일). 먼저 python -m scripts.build_sensor_index'); return

    if a.weather_csv:
        weather = read_forecast_csv(a.weather_csv)
        weather = weather[(weather.window_start >= since.tz_localize(None)) & (weather.window_start <= now.tz_localize(None))]
    else:
        weather = weather_from_store(store, since)
    if weather.empty:
        print('기상 자료 없음. log_weather 를 매시 돌리거나 --weather-csv 를 주세요.'); return

    settings = load_settings(); _, info = load_model()
    current = (round(float(settings.get('thr_mid') or 0.5), 3), round(float(settings.get('thr_high') or info.get('thr_valid', 0.75)), 3))
    pred = predict_windows(weather)
    pairs = pair_windows(pred, idx)
    cal = calibrate_thresholds(pairs, current=current)
    cal.update(sensor_store=label, simulated=simulated, weather=a.weather_csv or 'kma_ncst', days_requested=a.days)

    out = Path(a.out) / now.strftime('%Y%m%d_%H%M'); out.mkdir(parents=True, exist_ok=True)
    pairs.to_csv(out / 'pairs.csv', index=False, encoding='utf-8-sig')
    (out / 'calibration.json').write_text(json.dumps(cal, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    title = '모델–센서 대조' + (' (시뮬레이터 자료 — 실측 아님)' if simulated else '')
    (out / 'report.md').write_text(report_markdown(cal, title), encoding='utf-8')
    b = cal.get('before', {})
    print(f"{label}: 대조 {b.get('n_windows', 0)}창 · {b.get('days', 0)}일 · 센서 사건 {b.get('n_episodes', 0)}건"
          f" · 현재 경계 {current[0]}/{current[1]} → " + (f"제안 {cal['thr_mid']}/{cal['thr_high']}" if cal['ok'] else f"보정 보류({cal['reason']})"))
    print(f'저장: {out}')

    if a.apply:
        if not cal['ok']:
            print('보정이 성립하지 않아 설정을 바꾸지 않았습니다.'); return
        if simulated:
            print('시뮬레이터 자료라 설정을 바꾸지 않았습니다.'); return
        settings.update(thr_mid=cal['thr_mid'], thr_high=cal['thr_high'],
                        calibration=dict(fitted_at=cal['fitted_at'], n_days=cal['n_days'], n_episodes=cal['n_episodes'],
                                         sites=cal['sites'], previous=list(current), report=str(out.relative_to(ROOT))))
        save_settings(settings)
        print(f"설정 갱신: 보통 ≥ {cal['thr_mid']}, 높음 ≥ {cal['thr_high']} (실측 보정 {cal['n_days']}일)")


if __name__ == '__main__':
    main()
