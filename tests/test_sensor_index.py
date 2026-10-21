"""센서 지수·사건 파이프라인 검증(시뮬레이터 자료, 네트워크 없음)."""
import os, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import pandas as pd
from scripts.sensor_sim import simulate
from odor_model.sensor_index import aggregate_10min, compute_index, level_from_index, colocation_offsets, _persist


def _idx(hours=240):
    rows = [r for s in ('S1', 'S2', 'S3') for r in simulate(s, hours, end=pd.Timestamp('2026-11-01 00:00', tz='Asia/Seoul'))]
    rd = pd.DataFrame(rows); rd['ts'] = pd.to_datetime(rd['ts'])
    return compute_index(aggregate_10min(rd))


def test_aggregate_shapes():
    idx = _idx(48)
    assert set(idx.site_id) == {'S1', 'S2', 'S3'}
    assert (idx.n <= 10).all() and idx.ts.dt.minute.isin(range(0, 60, 10)).all()


def test_preheat_flag_first_48h():
    idx = _idx(72)
    first = idx[idx.site_id == 'S1'].sort_values('ts').iloc[:200]
    assert (first.quality_flag == 'preheat').all()


def test_inflow_events_detected_on_event_nights():
    idx = _idx(240)
    ev = idx[idx.event_grade == 'inflow']
    assert len(ev) > 50, len(ev)
    assert set(ev.site_id) == {'S1', 'S2'}
    assert ev.ts.dt.hour.isin([21, 22, 23, 0, 1, 2]).all()
    assert not (idx[idx.site_id == 'S3'].event_grade == 'inflow').any()


def test_levels_and_no_percent():
    idx = _idx(240)
    levels = idx.apply(level_from_index, axis=1)
    assert set(levels) <= {'보류', '낮음', '보통', '높음'}
    assert (levels != '보류').sum() > 1000


def test_persist_requires_two_windows():
    f = pd.Series([False, True, False, True, True, False, True, True, True])
    assert _persist(f).tolist() == [False, False, False, True, True, False, True, True, True]


def test_colocation_offsets_reference_identity():
    idx = _idx(72)
    agg = aggregate_10min(pd.DataFrame([r for s in ('S1', 'S2') for r in simulate(s, 30, end=pd.Timestamp('2026-11-01', tz='Asia/Seoul'))]).assign(ts=lambda d: pd.to_datetime(d.ts)))
    off = colocation_offsets(agg)
    assert off['S1']['mq_gain'] == 1.0 and 0.8 < off['S2']['mq_gain'] < 1.2
