"""모델–센서 대조·경계 보정·센서 우선 반영 검증(시뮬레이터 자료, 네트워크 없음)."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import numpy as np
import pandas as pd
from scripts.sensor_sim import simulate
from odor_model.sensor_index import aggregate_10min, compute_index
from odor_model.sensor_compare import (pair_windows, agreement, calibrate_thresholds, apply_sensor_override,
                                       latest_sensor, report_markdown, count_episodes, ZONE_SITE)

END = pd.Timestamp('2026-11-01 00:00', tz='Asia/Seoul')
_CACHE = {}


def _index(hours=240):
    if hours not in _CACHE:
        rows = [r for s in ('S1', 'S2', 'S3') for r in simulate(s, hours, end=END)]
        rd = pd.DataFrame(rows); rd['ts'] = pd.to_datetime(rd['ts'])
        _CACHE[hours] = compute_index(aggregate_10min(rd))
    return _CACHE[hours]


def _pred(index_df, informative=True, seed=0):
    """시간별 모델 추정. informative: 센서 사건이 있던 시각에 점수가 높은 모델 / 아니면 무관한 난수."""
    rng = np.random.default_rng(seed)
    hours = pd.date_range(END - pd.Timedelta(hours=240), END, freq='h').tz_localize(None)
    ev = index_df[index_df.event_grade.isin(['inflow', 'sure'])].copy()
    ev_hours = set(pd.to_datetime(ev.ts).dt.tz_convert('Asia/Seoul').dt.tz_localize(None).dt.floor('h'))
    rows = []
    for h in hours:
        for z in ('U01', 'U02', 'U03'):
            p = (0.55 + 0.4 * rng.random()) if (informative and h in ev_hours) else 0.6 * rng.random()
            if not informative: p = rng.random()
            rows.append(dict(window_start=h, zone_id=z, status='예비 추정', p_detect=round(p, 3),
                             level='높음' if p >= .75 else '보통' if p >= .5 else '낮음'))
    return pd.DataFrame(rows)


def test_pairs_use_mapped_sites_and_usable_quality():
    idx = _index(); pairs = pair_windows(_pred(idx), idx)
    assert set(pairs.zone_id) == set(ZONE_SITE) and set(pairs.site_id) == {'S1', 'S2'}
    assert set(pairs.quality_flag) <= {'ok', 'rh_high'}            # 예열 48시간 제외
    assert pairs.ts.min() >= pd.Timestamp('2026-10-24 00:00')
    assert pairs.sensor_event.equals(pairs.sensor_grade.isin(['inflow', 'sure']))
    assert pairs.sensor_event.sum() > 20


def test_agreement_counts_add_up():
    idx = _index(); pairs = pair_windows(_pred(idx), idx); a = agreement(pairs)
    assert sum(b['windows'] for b in a['by_level'].values()) == a['n_windows'] == len(pairs)
    assert sum(b['windows'] for b in a['bands']) == a['n_windows']
    assert a['n_episodes'] >= 5 and a['n_episodes'] < a['n_event_windows']
    assert a['lift_high'] > 1.5                                     # 정보 있는 모델은 '높음'에 사건이 몰림


def test_calibration_moves_only_thresholds_and_helps():
    idx = _index(); pairs = pair_windows(_pred(idx), idx)
    cal = calibrate_thresholds(pairs, current=(0.5, 0.75))
    assert cal['ok'], cal['reason']
    assert 0 < cal['thr_mid'] < cal['thr_high'] < 1                 # 보통 구간이 사라지지 않음
    assert cal['after']['by_level']['보통']['windows'] > 0
    assert cal['after']['mid_recall'] >= 0.8
    assert cal['after']['mid_recall'] > cal['after']['high_recall']
    f1 = lambda a: 2 * a['high_precision'] * a['high_recall'] / (a['high_precision'] + a['high_recall'])
    assert f1(cal['after']) >= f1(cal['before']) - 1e-9
    assert cal['platt'] is None or set(cal['platt']) == {'a', 'b'}


def test_uninformative_model_gains_little():
    idx = _index(); pairs = pair_windows(_pred(idx, informative=False, seed=3), idx)
    a = agreement(pairs)
    assert a['lift_high'] < 1.5                                     # 무관한 모델은 기준 비율 근처


def test_calibration_refuses_with_few_events():
    idx = _index(); pairs = pair_windows(_pred(idx), idx)
    first_ep = pairs[pairs.sensor_event].ts.min()
    few = pairs[pairs.ts < first_ep + pd.Timedelta('3h')]
    cal = calibrate_thresholds(few)
    assert not cal['ok'] and '부족' in cal['reason']
    assert (cal['thr_mid'], cal['thr_high']) == (0.5, 0.75)


def test_sensor_override_now():
    idx = _index()
    ev = idx[(idx.event_grade == 'inflow') & (idx.site_id == 'S1')].ts
    t_ev = pd.Timestamp(ev.iloc[len(ev) // 2]) + pd.Timedelta('5min')
    now_rows = pd.DataFrame([dict(window_start=t_ev.floor('h'), zone_id=z, status='예비 추정', p_detect=0.1, level='낮음')
                             for z in ('U01', 'U02', 'U03')])
    live = latest_sensor(idx, t_ev)
    out = apply_sensor_override(now_rows, idx, t_ev).set_index('zone_id')
    assert live['S1']['grade'] == 'inflow'
    assert out.loc['U01', 'level'] == '높음' and out.loc['U01', 'level_source'] == '센서 감지'
    if live.get('S2', {}).get('grade') in ('inflow', 'sure'):
        assert out.loc['U02', 'level_source'] == '센서 감지'
    assert out.loc['U03', 'level_source'] == '센서 감지(인접 지점)'
    # 조용한 낮 시각: 모델 값 유지
    quiet = pd.Timestamp('2026-10-30 14:05', tz='Asia/Seoul')
    q = apply_sensor_override(now_rows, idx, quiet).set_index('zone_id')
    assert (q.level == '낮음').all() and (q.level_source == '모델').all()
    # 자료가 오래되면(20분 초과) 반영하지 않음
    stale = apply_sensor_override(now_rows, idx, END + pd.Timedelta(hours=3))
    assert (stale.level_source == '모델').all()


def test_report_has_no_percent_and_marks_hold():
    idx = _index(); pairs = pair_windows(_pred(idx), idx)
    md = report_markdown(calibrate_thresholds(pairs), title='모델–센서 대조 (시뮬레이터)')
    assert '%' not in md and '실측 보정 결과' in md
    md2 = report_markdown(calibrate_thresholds(pairs.iloc[:0]))
    assert '보류' in md2


def test_empty_inputs():
    assert pair_windows(pd.DataFrame(), _index()).empty
    assert agreement(pd.DataFrame(columns=['ts'])) ['n_windows'] == 0
