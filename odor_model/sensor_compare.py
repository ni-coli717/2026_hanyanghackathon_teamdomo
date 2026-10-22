"""모델 추정 ↔ 센서 실측 대조·경계 보정·센서 우선 반영.  (설계 v3 ②③④)

역할 구분
  ① 감지 모델(odor_model.predict)은 그대로 둔다. 가중치를 다시 배우지 않는다.
  ② 경계 보정: p_detect 를 낮음/보통/높음으로 끊는 thr_mid·thr_high 만 센서 사건에 맞춘다.
  ③ 센서 우선: 지금 S1·S2 에서 사건(inflow/sure)이면 현재 수준을 '높음 · 센서 감지'로 덮는다(예보 구간 제외).
  ④ 대조 장부: 10분 창마다 (모델 수준, 센서 사건) 쌍을 남기고 일치율 표를 만든다.

센서는 '정답'이 아니라 대조·보정 자료다. 센서 사건 = event_grade 가 inflow 또는 sure 인 창.
local(한 지점·한 센서만)은 국지 요인(요리·배기)일 수 있어 사건으로 세지 않고 따로 집계한다.
모든 수치는 화면에 확률(%)로 내보내지 않는다. 비율은 운영자 대조표에서만 쓴다.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

ZONE_SITE = {'U01': 'S1', 'U02': 'S2'}          # 모델 구역 ↔ 센서 지점. U03 은 센서 없음
NEIGHBOR_ZONES = ('U03',)                         # S1·S2 가 함께 오를 때(inflow)만 인접 지점 기준으로 반영
POSITIVE = ('inflow', 'sure')
USABLE_QUALITY = ('ok', 'rh_high')                # preheat·gap·event(현장 기록 구간)는 대조에서 뺀다
LEVELS = ('낮음', '보통', '높음')
BANDS = (('새벽', 0, 6), ('오전', 6, 12), ('오후', 12, 18), ('저녁', 18, 24))
EPISODE_GAP = pd.Timedelta('30min')               # 이 간격 안에 붙은 사건 창은 사건 1건
MIN_EPISODES = 5                                  # 보정에 필요한 최소 사건 수
MIN_EVENT_WINDOWS = 12
RECALL_MID_TARGET = 0.8                           # '보통 이상'이 센서 사건 창의 80% 이상을 덮도록
SENSOR_FRESH = pd.Timedelta('20min')


def _naive(s: pd.Series) -> pd.Series:
    s = pd.to_datetime(s)
    return s.dt.tz_convert('Asia/Seoul').dt.tz_localize(None) if s.dt.tz is not None else s


def level_of(p: float, thr_mid: float, thr_high: float) -> str:
    if p >= thr_high: return '높음'
    if p >= thr_mid: return '보통'
    return '낮음'


# ------------------------------------------------------------------ ④ 대조 장부
def pair_windows(pred: pd.DataFrame, index_df: pd.DataFrame, zone_site: dict | None = None,
                 tolerance: str = '60min') -> pd.DataFrame:
    """모델 추정(window_start, zone_id, p_detect, level, status) × 센서 10분 지수(site_id, ts, event_grade, quality_flag).
    모델 추정은 보통 1시간 간격이므로 각 센서 창에 '직전 추정'을 붙인다(tolerance 안에서).
    반환: ts, zone_id, site_id, p_detect, level, sensor_grade, sensor_event, quality_flag, hour"""
    zone_site = zone_site or ZONE_SITE
    cols = ['ts', 'zone_id', 'site_id', 'p_detect', 'level', 'sensor_grade', 'sensor_event', 'quality_flag', 'hour']
    if pred is None or pred.empty or index_df is None or index_df.empty:
        return pd.DataFrame(columns=cols)
    p = pred[pred.get('status', pd.Series('예비 추정', index=pred.index)) == '예비 추정'].copy()
    p = p.dropna(subset=['p_detect'])
    p['window_start'] = _naive(p['window_start'])
    s = index_df.copy(); s['ts'] = _naive(s['ts'])
    out = []
    for zone, site in zone_site.items():
        pz = p[p.zone_id == zone][['window_start', 'p_detect', 'level']].sort_values('window_start')
        sz = s[(s.site_id == site) & s.quality_flag.isin(USABLE_QUALITY)][['ts', 'event_grade', 'quality_flag']].sort_values('ts')
        if pz.empty or sz.empty:
            continue
        m = pd.merge_asof(sz, pz, left_on='ts', right_on='window_start', direction='backward',
                          tolerance=pd.Timedelta(tolerance)).dropna(subset=['p_detect'])
        m['zone_id'], m['site_id'] = zone, site
        out.append(m)
    if not out:
        return pd.DataFrame(columns=cols)
    df = pd.concat(out, ignore_index=True).rename(columns={'event_grade': 'sensor_grade'})
    df['sensor_event'] = df.sensor_grade.isin(POSITIVE)
    df['hour'] = df.ts.dt.hour
    return df[cols].sort_values(['ts', 'zone_id']).reset_index(drop=True)


def count_episodes(pairs: pd.DataFrame) -> int:
    """구역별로 EPISODE_GAP 안에 이어지는 사건 창을 1건으로 센다."""
    n = 0
    for _, d in pairs[pairs.sensor_event].groupby('zone_id'):
        t = d.ts.sort_values()
        n += int((t.diff().isna() | (t.diff() > EPISODE_GAP)).sum())
    return n


def _rate(num, den):
    return None if den == 0 else round(float(num) / float(den), 3)


def agreement(pairs: pd.DataFrame, levels: pd.Series | None = None) -> dict:
    """대조 요약. levels 를 주면(보정 후 재판정 등) 그것으로 계산한다."""
    if pairs.empty:
        return dict(n_windows=0, n_event_windows=0, n_episodes=0, base_rate=None, by_level={}, high_precision=None,
                    high_recall=None, mid_recall=None, false_alarm_high=None, lift_high=None, local_windows=0, bands=[], days=0)
    lv = pairs.level if levels is None else levels
    ev = pairs.sensor_event
    base = ev.mean()
    by_level = {L: dict(windows=int((lv == L).sum()), event_windows=int(((lv == L) & ev).sum()),
                        event_rate=_rate(((lv == L) & ev).sum(), (lv == L).sum())) for L in LEVELS}
    hi, mid = lv == '높음', lv.isin(['보통', '높음'])
    prec = _rate((hi & ev).sum(), hi.sum())
    bands = []
    for name, a, b in BANDS:
        m = (pairs.hour >= a) & (pairs.hour < b)
        agree = ((mid & ev) | (~mid & ~ev))[m]
        bands.append(dict(band=name, windows=int(m.sum()), event_windows=int((ev & m).sum()),
                          event_rate=_rate((ev & m).sum(), m.sum()), agreement=_rate(agree.sum(), m.sum())))
    return dict(
        n_windows=int(len(pairs)), n_event_windows=int(ev.sum()), n_episodes=count_episodes(pairs),
        base_rate=round(float(base), 3), by_level=by_level,
        high_precision=prec,                                   # 모델 '높음' 중 센서 사건 비율
        high_recall=_rate((hi & ev).sum(), ev.sum()),          # 센서 사건 중 모델 '높음' 비율
        mid_recall=_rate((mid & ev).sum(), ev.sum()),          # 센서 사건 중 모델 '보통 이상' 비율
        false_alarm_high=None if prec is None else round(1 - prec, 3),
        lift_high=None if prec is None or base == 0 else round(prec / base, 2),
        local_windows=int((pairs.sensor_grade == 'local').sum()),
        bands=bands,
        days=int(pairs.ts.dt.normalize().nunique()),
    )


# ------------------------------------------------------------------ ② 경계 보정
def calibrate_thresholds(pairs: pd.DataFrame, current: tuple[float, float] = (0.5, 0.75),
                         recall_mid_target: float = RECALL_MID_TARGET) -> dict:
    """모델 가중치는 그대로, 경계 두 개만 센서 사건에 맞춘다.
    thr_high: (p ≥ t) 와 센서 사건의 F1 이 최대인 t (같으면 큰 t — 오경보를 줄이는 쪽).
    thr_mid : thr_high 보다 작으면서 '보통 이상'이 센서 사건 창을 max(recall_mid_target, 높음 recall + 놓친 몫의 절반)
              이상 덮는 가장 큰 t.
    사건이 적으면 보정하지 않고 이유를 돌려준다(ok=False)."""
    res = dict(ok=False, reason='', thr_mid=current[0], thr_high=current[1], before={}, after={},
               platt=None, fitted_at=pd.Timestamp.now(tz='Asia/Seoul').strftime('%Y-%m-%d %H:%M'))
    if pairs.empty:
        res['reason'] = '대조 자료 없음'; return res
    res['before'] = agreement(pairs, pairs.p_detect.map(lambda p: level_of(p, *current)))
    n_ev, n_ep = int(pairs.sensor_event.sum()), count_episodes(pairs)
    if n_ep < MIN_EPISODES or n_ev < MIN_EVENT_WINDOWS:
        res['reason'] = f'센서 사건 부족(사건 {n_ep}건·창 {n_ev}개, 필요 {MIN_EPISODES}건·{MIN_EVENT_WINDOWS}창)'; return res
    if n_ev == len(pairs):
        res['reason'] = '사건 없는 창이 없어 경계를 정할 수 없음'; return res
    p, y = pairs.p_detect.to_numpy(float), pairs.sensor_event.to_numpy(bool)
    cand = np.unique(np.round(p, 3))
    best_t, best_f1 = None, -1.0
    for t in cand:
        pred = p >= t
        tp = (pred & y).sum(); fp = (pred & ~y).sum(); fn = (~pred & y).sum()
        f1 = 0.0 if tp == 0 else 2 * tp / (2 * tp + fp + fn)
        if f1 >= best_f1:
            best_t, best_f1 = float(t), f1
    if best_f1 <= 0:
        res['reason'] = '모델 점수와 센서 사건이 겹치지 않음(보정 보류)'; return res
    thr_high = best_t
    # '보통'은 '높음'이 놓친 사건의 절반 이상을 더 잡아야 하고, 경계는 항상 높음보다 낮다(보통 구간이 사라지지 않게).
    rec_high = float((p[y] >= thr_high).mean())
    target = max(recall_mid_target, rec_high + 0.5 * (1 - rec_high))
    lower = [float(t) for t in cand if t < thr_high]
    mids = [t for t in lower if (p[y] >= t).mean() >= target]
    thr_mid = max(mids) if mids else (max(lower) if lower else thr_high)
    res.update(ok=True, thr_mid=round(thr_mid, 3), thr_high=round(thr_high, 3), f1_high=round(best_f1, 3),
               after=agreement(pairs, pairs.p_detect.map(lambda q: level_of(q, thr_mid, thr_high))),
               n_days=int(pairs.ts.dt.normalize().nunique()), n_event_windows=n_ev, n_episodes=n_ep,
               sites=sorted(pairs.site_id.unique().tolist()))
    res['platt'] = _platt(p, y)
    return res


def _platt(p: np.ndarray, y: np.ndarray) -> dict | None:
    """참고용: 센서 사건 ~ logit(p_detect) 로지스틱(a, b). 화면 확률 표시에 쓰지 않는다."""
    try:
        from sklearn.linear_model import LogisticRegression
        x = np.log(np.clip(p, 1e-4, 1 - 1e-4) / (1 - np.clip(p, 1e-4, 1 - 1e-4))).reshape(-1, 1)
        lr = LogisticRegression(C=1e6).fit(x, y.astype(int))
        return dict(a=round(float(lr.coef_[0][0]), 3), b=round(float(lr.intercept_[0]), 3))
    except Exception:  # noqa: BLE001
        return None


# ------------------------------------------------------------------ ③ 센서 우선
def latest_sensor(index_df: pd.DataFrame, now, fresh: pd.Timedelta = SENSOR_FRESH) -> dict:
    """지점별 최근 창(now − fresh 이후, 사용 가능 품질). {site_id: dict(ts, grade)}"""
    if index_df is None or index_df.empty:
        return {}
    s = index_df.copy(); s['ts'] = _naive(s['ts'])
    now = pd.Timestamp(now)
    now = now.tz_convert('Asia/Seoul').tz_localize(None) if now.tzinfo else now
    s = s[(s.ts > now - fresh) & (s.ts <= now) & s.quality_flag.isin(USABLE_QUALITY)]
    out = {}
    for site, d in s.sort_values('ts').groupby('site_id'):
        r = d.iloc[-1]; out[site] = dict(ts=r.ts, grade=r.event_grade)
    return out


def apply_sensor_override(pred_now: pd.DataFrame, index_df: pd.DataFrame, now, zone_site: dict | None = None) -> pd.DataFrame:
    """현재 시각 추정 행에만 쓴다(예보 행에는 쓰지 않는다). level_source 열을 붙인다.
    구역 지점이 inflow/sure → '높음', '센서 감지'. 센서 없는 구역은 S1·S2 가 함께 오른 inflow 일 때만 '센서 감지(인접 지점)'."""
    zone_site = zone_site or ZONE_SITE
    out = pred_now.copy()
    if out.empty:
        return out
    out['level_source'] = np.where(out.get('status', '') == '예비 추정', '모델', '없음')
    live = latest_sensor(index_df, now)
    inflow = any(v['grade'] == 'inflow' for k, v in live.items() if k in zone_site.values())
    for i, r in out.iterrows():
        site = zone_site.get(r.zone_id)
        hit = site in live and live[site]['grade'] in POSITIVE
        if hit:
            out.at[i, 'level'] = '높음'; out.at[i, 'level_source'] = '센서 감지'
        elif r.zone_id in NEIGHBOR_ZONES and inflow:
            out.at[i, 'level'] = '높음'; out.at[i, 'level_source'] = '센서 감지(인접 지점)'
    return out


# ------------------------------------------------------------------ 보고
def report_markdown(cal: dict, title: str = '모델–센서 대조') -> str:
    """운영자·발표용 표. 생성(시뮬레이터) 자료로 만든 결과면 호출 쪽에서 title 에 표시할 것."""
    def table(a: dict) -> list[str]:
        if not a or not a.get('n_windows'):
            return ['(자료 없음)']
        L = ['| 모델 수준 | 창 수 | 센서 사건 창 | 사건 비율 |', '|---|---:|---:|---:|']
        for k in LEVELS:
            b = a['by_level'][k]; L.append(f"| {k} | {b['windows']} | {b['event_windows']} | {b['event_rate'] if b['event_rate'] is not None else '-'} |")
        L += ['', f"- 전체 {a['n_windows']}창 · {a['days']}일 · 센서 사건 {a['n_episodes']}건({a['n_event_windows']}창) · 기준 비율 {a['base_rate']}",
              f"- 모델 '높음' 중 센서 사건 비율 {a['high_precision']} (기준 대비 {a['lift_high']}배)",
              f"- 센서 사건 중 모델 '높음' {a['high_recall']} · '보통 이상' {a['mid_recall']}",
              f"- 국지(local) 창 {a['local_windows']}개는 사건에서 제외", '',
              '| 시간대 | 창 수 | 사건 창 | 사건 비율 | 일치율(보통 이상 ↔ 사건) |', '|---|---:|---:|---:|---:|']
        L += [f"| {b['band']} | {b['windows']} | {b['event_windows']} | {b['event_rate'] if b['event_rate'] is not None else '-'} | {b['agreement'] if b['agreement'] is not None else '-'} |" for b in a['bands']]
        return L
    lines = [f'# {title}', '', f"작성 {cal.get('fitted_at', '')}. 모델 가중치는 바꾸지 않았고, 낮음/보통/높음 경계만 대조 대상입니다.", '',
             '## 현재 경계로 본 대조', *table(cal.get('before', {})), '']
    if cal.get('ok'):
        lines += ['## 실측 보정 결과', f"- 경계: 보통 ≥ {cal['thr_mid']}, 높음 ≥ {cal['thr_high']} (높음 F1 {cal.get('f1_high')})",
                  f"- 근거: {cal['n_days']}일 · 사건 {cal['n_episodes']}건 · 지점 {', '.join(cal['sites'])}", '', *table(cal['after'])]
        if cal.get('platt'):
            lines += ['', f"참고(화면 미사용): Platt a={cal['platt']['a']}, b={cal['platt']['b']}"]
    else:
        lines += ['## 실측 보정', f"- 보류: {cal.get('reason')}"]
    return '\n'.join(lines) + '\n'
