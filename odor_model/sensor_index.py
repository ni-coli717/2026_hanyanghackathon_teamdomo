"""센서 원값 → 10분 지수 → 악취 사건.  (최종설계 v2 §1.2)

지수 정의(지점별):
  MQ-137: Rs/R0 대신 ADC 를 그대로 Rs 대리값으로 쓴다(저항 분압이 고정이므로 단조). 
          기준선 = 최근 24시간(144창) 상위 90% 분위(깨끗한 공기의 Rs) → mq_index = (baseline − rs)/baseline  (냄새가 오면 Rs 가 내려가 지수가 올라감)
  SGP40 : VOC index(자체 기준선) → 24시간 하위 10% 분위 대비 상대 상승 voc_index_rel = (voc − base)/max(base, 20)
습도·기온 보정: calibration 의 rh_coef/temp_coef 가 있으면 잔차로 교체.
사건: 지점·센서별 최근 7일 보정 지수의 중앙값 + 3×MAD 를 20분(2창) 이상 연속 초과.
등급: sure(두 센서 60분 내 함께) / inflow(S1·S2 60분 내 함께) / local(그 외) / none
품질: preheat(heater_sec<48h) · gap(n<5) · rh_high(>90%) · event(현장 이벤트 구간) · ok
절대 농도(ppm)는 계산하지 않는다.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

PREHEAT_SEC = 48 * 3600
WINDOW_BASE = 144          # 24h of 10-min windows
WINDOW_THR = 7 * 144       # 7 days
MIN_N = 5
RH_HIGH = 90.0
MAD_K = 3.0
PERSIST = 2                # windows (20 min)
COINCIDE = pd.Timedelta('60min')


def aggregate_10min(readings: pd.DataFrame) -> pd.DataFrame:
    """1분 원값 → 지점·10분 창 집계."""
    if readings.empty:
        return pd.DataFrame(columns=['site_id', 'ts', 'n', 'mq_rs_mean', 'mq_rs_min', 'voc_mean', 'voc_max', 'humidity_pct', 'temperature_c', 'heater_min'])
    df = readings.copy()
    df['ts'] = pd.to_datetime(df['ts']); df['win'] = df['ts'].dt.floor('10min')
    g = df.groupby(['site_id', 'win'])
    out = g.agg(n=('ts', 'size'), mq_rs_mean=('adc_mq137', 'mean'), mq_rs_min=('adc_mq137', 'min'),
                voc_mean=('voc_index', 'mean'), voc_max=('voc_index', 'max'),
                humidity_pct=('humidity_pct', 'mean'), temperature_c=('temperature_c', 'mean'),
                heater_min=('heater_sec', 'min')).reset_index().rename(columns={'win': 'ts'})
    return out


def _rolling_high(s: pd.Series, win: int) -> pd.Series:
    """깨끗한 공기 기준선(Rs 는 냄새가 오면 내려가므로 상위 90% 분위)."""
    return s.rolling(win, min_periods=max(6, win // 24)).quantile(0.9)


def _rolling_low(s: pd.Series, win: int) -> pd.Series:
    """VOC 기준선(냄새가 오면 올라가므로 하위 10% 분위)."""
    return s.rolling(win, min_periods=max(6, win // 24)).quantile(0.1)


def _robust_thr(s: pd.Series, win: int) -> pd.Series:
    med = s.rolling(win, min_periods=144).median()
    mad = (s - med).abs().rolling(win, min_periods=144).median() * 1.4826
    return med + MAD_K * mad


def compute_index(agg: pd.DataFrame, calibration: pd.DataFrame | None = None, events: pd.DataFrame | None = None) -> pd.DataFrame:
    """집계 → 기준선·지수·임계·사건·품질. 지점별로 시간순 처리."""
    if agg.empty:
        return agg
    cal = {} if calibration is None or calibration.empty else calibration.set_index('site_id').to_dict('index')
    frames = []
    for site, d in agg.sort_values('ts').groupby('site_id'):
        d = d.copy().reset_index(drop=True)
        c = cal.get(site, {})
        rs = d['mq_rs_mean'] * float(c.get('mq_gain', 1) or 1) + float(c.get('mq_offset', 0) or 0)
        base = _rolling_high(rs, WINDOW_BASE)
        idx = (base - rs) / base.replace(0, np.nan)
        voc = d['voc_mean'] * float(c.get('voc_gain', 1) or 1) + float(c.get('voc_offset', 0) or 0)
        vbase = _rolling_low(voc, WINDOW_BASE)
        vrel = (voc - vbase) / vbase.clip(lower=20)
        rh_coef, t_coef = float(c.get('rh_coef', 0) or 0), float(c.get('temp_coef', 0) or 0)
        if rh_coef or t_coef:   # 선형 보정(수집 1주차 회귀로 산출): 잔차 사용
            idx = idx - rh_coef * (d['humidity_pct'] - 60) - t_coef * (d['temperature_c'] - 15)
        d['mq_baseline'], d['mq_index'] = base, idx
        d['voc_baseline'], d['voc_index_rel'] = vbase, vrel
        thr_mq, thr_voc = _robust_thr(idx, WINDOW_THR), _robust_thr(vrel, WINDOW_THR)
        d['thr_mq'], d['thr_voc'] = thr_mq, thr_voc
        over_mq, over_voc = (idx > thr_mq).fillna(False), (vrel > thr_voc).fillna(False)
        d['event_mq'] = _persist(over_mq); d['event_voc'] = _persist(over_voc)
        # 품질
        q = np.where(d['heater_min'].fillna(PREHEAT_SEC) < PREHEAT_SEC, 'preheat',
            np.where(d['n'] < MIN_N, 'gap', np.where(d['humidity_pct'] > RH_HIGH, 'rh_high', 'ok')))
        d['quality_flag'] = q
        frames.append(d)
    out = pd.concat(frames, ignore_index=True)
    if events is not None and len(events):
        for _, e in events.iterrows():
            end = e['end_ts'] if pd.notna(e.get('end_ts')) else out['ts'].max()
            m = (out['site_id'] == e['site_id']) & (out['ts'] >= e['start_ts']) & (out['ts'] <= end)
            out.loc[m, 'quality_flag'] = 'event'
    out['event_grade'] = grade_events(out)
    return out


def _persist(flag: pd.Series) -> pd.Series:
    """PERSIST 창 이상 연속 True 인 구간만 True."""
    run = flag.groupby((~flag).cumsum()).cumsum()
    keep = run.groupby((~flag).cumsum()).transform('max') >= PERSIST
    return (flag & keep).astype(bool)


def grade_events(df: pd.DataFrame) -> pd.Series:
    """none / local / sure / inflow.  sure: 같은 지점 두 센서 60분 내 함께. inflow: S1·S2 가 60분 내 함께(센서 무관)."""
    grade = pd.Series('none', index=df.index)
    any_ev = df['event_mq'] | df['event_voc']
    grade[any_ev] = 'local'
    for site, d in df[any_ev].groupby('site_id'):
        mq_t = d.loc[d['event_mq'], 'ts']; voc_t = d.loc[d['event_voc'], 'ts']
        for i, r in d.iterrows():
            other = voc_t if r['event_mq'] else mq_t
            if len(other) and (other.sub(r['ts']).abs() <= COINCIDE).any():
                grade[i] = 'sure'
    s1 = df.loc[any_ev & (df['site_id'] == 'S1'), 'ts']; s2 = df.loc[any_ev & (df['site_id'] == 'S2'), 'ts']
    for i, r in df[any_ev & df['site_id'].isin(['S1', 'S2'])].iterrows():
        other = s2 if r['site_id'] == 'S1' else s1
        if len(other) and (other.sub(r['ts']).abs() <= COINCIDE).any():
            grade[i] = 'inflow'
    return grade


def level_from_index(row) -> str:
    """화면용 3수준: 임계 미만 낮음 / 임계~2×임계 보통 / 그 이상 높음. 임계가 없으면 '보류'."""
    thr = row.get('thr_mq'); idx = row.get('mq_index')
    if pd.isna(thr) or pd.isna(idx) or thr <= 0:
        return '보류'
    return '낮음' if idx < thr else ('보통' if idx < 2 * thr else '높음')


def fit_rh_temp(index_df: pd.DataFrame) -> dict:
    """수집 1주차 자료로 습도·기온 선형 회귀계수 산출(사건 아닌 창만). {site_id: (rh_coef, temp_coef)}"""
    out = {}
    for site, d in index_df.groupby('site_id'):
        d = d[(d['quality_flag'] == 'ok') & ~(d['event_mq'] | d['event_voc'])].dropna(subset=['mq_index', 'humidity_pct', 'temperature_c'])
        if len(d) < 144:
            continue
        X = np.column_stack([d['humidity_pct'] - 60, d['temperature_c'] - 15, np.ones(len(d))])
        coef, *_ = np.linalg.lstsq(X, d['mq_index'].values, rcond=None)
        out[site] = (float(coef[0]), float(coef[1]))
    return out


def colocation_offsets(agg: pd.DataFrame, reference='S1') -> dict:
    """공동 예열 뒤 24시간: 기준 지점 대비 gain/offset(중앙값 비율). {site: dict(mq_gain, mq_offset, voc_gain, voc_offset)}"""
    piv_mq = agg.pivot_table(index='ts', columns='site_id', values='mq_rs_mean')
    piv_voc = agg.pivot_table(index='ts', columns='site_id', values='voc_mean')
    out = {}
    for site in piv_mq.columns:
        if site == reference: out[site] = dict(mq_gain=1.0, mq_offset=0.0, voc_gain=1.0, voc_offset=0.0); continue
        both = piv_mq[[reference, site]].dropna(); vb = piv_voc[[reference, site]].dropna()
        mg = float((both[reference] / both[site]).median()) if len(both) else 1.0
        vg = float((vb[reference] / vb[site].replace(0, np.nan)).median()) if len(vb) else 1.0
        out[site] = dict(mq_gain=mg, mq_offset=0.0, voc_gain=vg if np.isfinite(vg) else 1.0, voc_offset=0.0)
    return out
