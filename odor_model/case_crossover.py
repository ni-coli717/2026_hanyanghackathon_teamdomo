"""실제 주민 제보(사건 153건)로 학습하는 case-crossover 조건부 로지스틱.  (모델 구축 방안 v3)

정답: 사건 창 = 1, 같은 구역·요일·시각의 ±1·2·3주 창 = 0(그 창 ±1시간에 같은 구역 제보가 있으면 제외).
특징: odor_model.features.make_features 의 20열을 그대로 쓴다(앱 예측 경로 재사용). 시간대·계절·구역 열은
      대조 창이 같게 맞춰 주므로 학습에서 제외한다(계수 0 고정).
모델: 조건부 로지스틱 = 짝(사건 1 + 대조 k)마다 softmax. scipy 로 최대우도 + 약한 ridge. statsmodels 불필요.
출력: sklearn 처럼 predict_proba(X) 를 가진 CCModel 을 odor_model.joblib 과 같은 묶음 형식으로 저장 →
      core/analysis_service.predict_rows 가 그대로 읽는다. 점수는 확률이 아니며 화면엔 3수준만 보인다.
사용: python -m odor_model.case_crossover [--station 427|441] [--strict] [--out data/models/odor/cc_427]
"""
from __future__ import annotations

import argparse, csv, json
from pathlib import Path
import numpy as np, pandas as pd
from scipy.optimize import minimize
from scipy.special import expit

from .cc_model import CCModel, UniformType
from .features import ZONES, load_geo, make_features

ROOT = Path(__file__).resolve().parents[1]
PRIV = ROOT / 'data/private'
PERIOD = (pd.Timestamp('2026-06-20'), pd.Timestamp('2026-09-30 23:59'))
CONTROL_WEEKS = (-3, -2, -1, 1, 2, 3)
STRICT_TIME = {'stated_exact', 'stated_now', 'stated_hour', 'sent_at_proxy'}
MATCHED_COLS = {'hour_sin', 'hour_cos', 'doy_sin', 'doy_cos', 'zone_U01', 'zone_U02', 'zone_U03'}   # 대조로 맞춘 열 → 계수 0


# ------------------------------------------------------------------ 자료
def load_weather(station='427'):
    w = {s: pd.read_csv(ROOT / f'data/external/aws/weather_{s}.csv', parse_dates=['window_start']).set_index('window_start') for s in ('427', '441')}
    other = '441' if station == '427' else '427'
    base = w[station].copy()
    for c in ('wind_from_deg', 'wind_speed', 'humidity_pct', 'temperature_c', 'rain_1h_mm'):
        base[c] = base[c].fillna(w[other][c])
    return base


def _window_weather(W, t0, t1):
    sub = W.loc[t0.floor('h'):t1.ceil('h')].dropna(subset=['wind_speed', 'wind_from_deg'])
    if sub.empty: return None
    ws, wd = sub.wind_speed.to_numpy(float), np.radians(sub.wind_from_deg.to_numpy(float))
    u, v = -(ws * np.sin(wd)).mean(), -(ws * np.cos(wd)).mean()
    spd = float(np.hypot(u, v)); deg = (np.degrees(np.arctan2(-u, -v)) + 360) % 360
    return dict(wind_from_deg=float(deg), wind_speed=spd, humidity_pct=float(sub.humidity_pct.mean()),
                temperature_c=float(sub.temperature_c.mean()), rain_1h_mm=float(sub.rain_1h_mm.fillna(0).sum()))


def build_training(station='427', strict=False) -> pd.DataFrame:
    rep = {r['report_id']: r for r in csv.DictReader(open(PRIV / 'reports.csv', encoding='utf-8-sig'))}
    ev = [e for e in csv.DictReader(open(PRIV / 'events.csv', encoding='utf-8-sig')) if e['zone_id'] in ZONES]
    W = load_weather(station)
    # 구역별 제보 시각(대조 창 제외용)
    rep_times = {z: [] for z in ZONES}
    for r in rep.values():
        if r['zone_id'] in ZONES and r['observed_date'] and r['observed_time']:
            rep_times[r['zone_id']].append(pd.Timestamp(f"{r['observed_date']} {r['observed_time']}"))
    rep_times = {z: np.array(sorted(v), dtype='datetime64[ns]') for z, v in rep_times.items()}
    rows = []
    for e in ev:
        ids = e['report_ids'].split(';')
        if strict and not all(rep[i]['source_check'] == 'kakao_export' and rep[i]['place_basis'] == 'stated' and rep[i]['time_basis'] in STRICT_TIME for i in ids):
            continue
        ws_ = [rep[i]['window_start'] for i in ids if rep[i].get('window_start')]
        t0 = pd.Timestamp(min(ws_)) if ws_ else pd.Timestamp(e['start_at']); t1 = pd.Timestamp(e['end_at'])
        if t1 < t0: t0, t1 = t1, t0
        z = e['zone_id']; wx = _window_weather(W, t0, t1)
        if wx is None: continue
        rows.append(dict(set_id=e['event_id'], zone_id=z, window_start=t0, label=1, n_participants=int(e['n_participants']), **wx))
        for k in CONTROL_WEEKS:
            c0, c1 = t0 + pd.Timedelta(weeks=k), t1 + pd.Timedelta(weeks=k)
            if not (PERIOD[0] <= c0 and c1 <= PERIOD[1]): continue
            near = np.abs((rep_times[z] - np.datetime64(c0)) / np.timedelta64(1, 'h'))
            near2 = np.abs((rep_times[z] - np.datetime64(c1)) / np.timedelta64(1, 'h'))
            if len(near) and (min(near.min(), near2.min()) <= 1.0): continue   # 그 주에도 제보가 있었으면 대조 아님
            wxc = _window_weather(W, c0, c1)
            if wxc is None: continue
            rows.append(dict(set_id=e['event_id'], zone_id=z, window_start=c0, label=0, n_participants=0, **wxc))
    df = pd.DataFrame(rows)
    keep = df.groupby('set_id').label.transform(lambda s: (s == 1).sum() == 1 and (s == 0).sum() >= 1)
    return df[keep].reset_index(drop=True)


# ------------------------------------------------------------------ 학습
def fit_conditional(Z, y, sets, l2=0.5):
    """짝별 softmax 우도. Z 표준화 행렬, y 0/1, sets 정수 id."""
    n, p = Z.shape
    uniq, inv = np.unique(sets, return_inverse=True)

    def nll(b):
        s = Z @ b
        m = np.full(len(uniq), -np.inf); np.maximum.at(m, inv, s)
        ex = np.exp(s - m[inv]); denom = np.zeros(len(uniq)); np.add.at(denom, inv, ex)
        ll = (s[y == 1] - (m + np.log(denom))[inv[y == 1]]).sum()
        return -ll + 0.5 * l2 * (b @ b)

    def grad(b):
        s = Z @ b
        m = np.full(len(uniq), -np.inf); np.maximum.at(m, inv, s)
        ex = np.exp(s - m[inv]); denom = np.zeros(len(uniq)); np.add.at(denom, inv, ex)
        pr = ex / denom[inv]
        return -(Z[y == 1].sum(0) - (pr[:, None] * Z).sum(0)) + l2 * b

    r = minimize(nll, np.zeros(p), jac=grad, method='L-BFGS-B')
    return r.x


def set_metrics(score, y, sets):
    """짝 안에서 사건이 1등인 비율(top1), 사건>대조 쌍 비율(set AUC), 우연 기준."""
    df = pd.DataFrame(dict(s=score, y=y, g=sets))
    top1, pairs, chance = [], [], []
    for _, d in df.groupby('g'):
        c = d[d.y == 1].s.iloc[0]; ctl = d[d.y == 0].s.to_numpy()
        top1.append(float((c > ctl).all())); pairs.append(float((c > ctl).mean() + 0.5 * (c == ctl).mean())); chance.append(1 / (len(ctl) + 1))
    return dict(top1=float(np.mean(top1)), set_auc=float(np.mean(pairs)), chance_top1=float(np.mean(chance)), n_sets=len(top1))


def train(df: pd.DataFrame, geo: dict, l2=0.5, seed=0):
    X = make_features(df, geo)
    cols = [c for c in X.columns if c not in MATCHED_COLS]
    Xm = X[cols].to_numpy(float); mean, scale = Xm.mean(0), Xm.std(0); scale[scale == 0] = 1.0
    Z = (Xm - mean) / scale; y = df.label.to_numpy(int)
    _, sets = np.unique(df.set_id, return_inverse=True)
    # 5겹 교차검증(사건 단위)
    rng = np.random.default_rng(seed); folds = rng.permutation(sets.max() + 1) % 5
    cv_score = np.zeros(len(y))
    for f in range(5):
        tr = folds[sets] != f
        b = fit_conditional(Z[tr], y[tr], sets[tr], l2)
        cv_score[~tr] = Z[~tr] @ b
    cv = set_metrics(cv_score, y, sets)
    b = fit_conditional(Z, y, sets, l2)
    fit = set_metrics(Z @ b, y, sets)
    # 사건 단위 부트스트랩 계수 구간
    bs = []
    for _ in range(200):
        pick = rng.choice(sets.max() + 1, sets.max() + 1)
        idx = np.concatenate([np.where(sets == g)[0] for g in pick]); newsets = np.concatenate([np.full((sets == g).sum(), i) for i, g in enumerate(pick)])
        bs.append(fit_conditional(Z[idx], y[idx], newsets, l2))
    bs = np.array(bs); lo, hi = np.percentile(bs, [2.5, 97.5], axis=0)
    coef = pd.DataFrame(dict(feature=cols, coef=b, lo=lo, hi=hi)).sort_values('coef', key=np.abs, ascending=False)
    full_cols = list(X.columns); full_coef = np.array([b[cols.index(c)] if c in cols else 0.0 for c in full_cols])
    full_mean = np.array([mean[cols.index(c)] if c in cols else 0.0 for c in full_cols]); full_scale = np.array([scale[cols.index(c)] if c in cols else 1.0 for c in full_cols])
    model = CCModel(full_cols, full_coef, full_mean, full_scale)
    return model, dict(cv=cv, fit=fit, coef=coef, n_rows=int(len(df)), n_events=int(y.sum()), controls_per_event=float((len(y) - y.sum()) / y.sum()))


def score_thresholds(model: CCModel, geo: dict, W: pd.DataFrame):
    """기간 전체 시간 × 3구역의 점수 분포 분위수로 보통(70%)·높음(90%) 경계."""
    rows = []
    for t, r in W.loc[PERIOD[0]:PERIOD[1]].dropna(subset=['wind_speed', 'wind_from_deg']).iterrows():
        for z in ZONES:
            rows.append(dict(window_start=t, zone_id=z, wind_from_deg=r.wind_from_deg, wind_speed=r.wind_speed, humidity_pct=r.humidity_pct, temperature_c=r.temperature_c, rain_1h_mm=r.rain_1h_mm if pd.notna(r.rain_1h_mm) else 0.0))
    P = model.predict_proba(make_features(pd.DataFrame(rows), geo))[:, 1]
    return float(np.quantile(P, 0.70)), float(np.quantile(P, 0.90)), P


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--station', default='427', choices=['427', '441']); ap.add_argument('--strict', action='store_true')
    ap.add_argument('--out', default=None); ap.add_argument('--l2', type=float, default=0.5); a = ap.parse_args()
    geo = load_geo(str(ROOT / 'data/geo/model_geo.json'))
    df = build_training(a.station, a.strict)
    model, ev = train(df, geo, a.l2)
    W = load_weather(a.station); thr_mid, thr_high, P = score_thresholds(model, geo, W)
    name = f"cc_{a.station}{'_strict' if a.strict else ''}"
    out = Path(a.out) if a.out else ROOT / 'data/models/odor' / name
    out.mkdir(parents=True, exist_ok=True)
    import joblib
    bundle = dict(detect_model=model, type_model=UniformType(['미구분']), type_classes=['미구분'], feature_columns=model.columns, geo=geo,
                  thr_fixed=thr_mid, thr_valid=thr_high, trained_on=f'실제 주민 제보 {ev["n_events"]}사건 (2026-06-20~09-30), AWS {a.station}, case-crossover',
                  status='실제 제보 학습 · 센서 보정 전', train_positive_rate=float(df.label.mean()), model_kind='conditional_logistic', station=a.station, strict=a.strict,
                  thresholds_note='점수는 확률이 아님. 기간 전체 시간 점수 분포의 70%/90% 분위수가 보통/높음 경계')
    joblib.dump(bundle, out / 'odor_model.joblib')
    df.to_csv(out / 'training_windows.csv', index=False, encoding='utf-8-sig')
    c = ev['coef']
    md = [f"# case-crossover 모델 평가 — {name}", '',
          f"학습 행 {ev['n_rows']} (사건 {ev['n_events']}, 사건당 대조 {ev['controls_per_event']:.1f}개) · AWS {a.station} · {'엄격 집합' if a.strict else '전체 집합'} · ridge λ={a.l2}", '',
          '## 교차검증 (사건 단위 5겹)', '',
          f"- 짝 안에서 사건이 1등: **{ev['cv']['top1']:.2f}** (우연 {ev['cv']['chance_top1']:.2f})",
          f"- 사건 > 대조 쌍 비율(set AUC): **{ev['cv']['set_auc']:.2f}** (우연 0.50)",
          f"- 학습 자료 그대로: top1 {ev['fit']['top1']:.2f}, set AUC {ev['fit']['set_auc']:.2f}", '',
          '## 계수 (표준화, 사건 단위 부트스트랩 95% 구간)', '', '| 특징 | 계수 | 2.5% | 97.5% | 0 포함 |', '|---|---:|---:|---:|---|']
    md += [f"| {r.feature} | {r.coef:+.2f} | {r.lo:+.2f} | {r.hi:+.2f} | {'' if r.lo > 0 or r.hi < 0 else '○'} |" for r in c.itertuples()]
    md += ['', f"## 수준 경계", '', f"- 기간 전체 시간×3구역 점수 분포: 보통 ≥ {thr_mid:.3f} (70% 분위), 높음 ≥ {thr_high:.3f} (90% 분위)",
           '- 점수는 조건부 로지스틱의 sigmoid 값으로 확률이 아니다. 화면에는 3수준만.', '',
           '## 읽을 때', '', '- wind_v 는 바람의 이동 방향 북쪽 성분(features.py). **음(−) = 북쪽에서 불어오는 바람**이 셀수록 사건. align_C1(구산동)·align_C2(하성)는 후보 방위 정렬도.',
           '- hour/doy/zone 열은 대조 창이 같게 맞춰 계수 0.', '- 자발 제보 자료라 "감지 확률"은 추정하지 않는다.']
    (out / 'evaluation.md').write_text('\n'.join(md), encoding='utf-8')
    print('\n'.join(md)); print('\n저장:', out)


if __name__ == '__main__':
    main()
