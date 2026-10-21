"""원값 → 10분 지수·사건 재계산 후 저장. 매시 실행(log_weather 와 같은 스케줄) 또는 수동.
사용: python -m scripts.build_sensor_index [--days 14]"""
from __future__ import annotations
import argparse
import pandas as pd
from core.config import now_kst
from core.sensor_store import open_sensor_store
from odor_model.sensor_index import aggregate_10min, compute_index


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--days', type=int, default=14); a = ap.parse_args()
    store, label = open_sensor_store()
    since = pd.Timestamp(now_kst()) - pd.Timedelta(days=a.days)
    rd = store.readings(since=since)
    if rd.empty: print('원값 없음'); return
    idx = compute_index(aggregate_10min(rd), store.calibration(), store.events())
    n = store.upsert_index(idx)
    ev = idx[idx['event_grade'] != 'none']
    print(f'{label}: 원값 {len(rd)}행 → 10분 {len(idx)}창 저장({n}). 사건 창 {len(ev)} (inflow {int((ev.event_grade=="inflow").sum())}, sure {int((ev.event_grade=="sure").sum())})')


if __name__ == '__main__':
    main()
