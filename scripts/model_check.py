"""case-crossover 로지스틱: 사건 창(1) vs 대조 창(0)
사용: python model_check.py <data_dir> <weather_csv>
"""
import sys, math, warnings, datetime as dt
import numpy as np, pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import GroupKFold
from sklearn.metrics import roc_auc_score
from statsmodels.discrete.conditional_models import ConditionalLogit
warnings.filterwarnings('ignore')

D, WX = sys.argv[1], sys.argv[2]
GUSAN_BEARING = {'U01': 11.0, 'U02': 16.0, 'U03': 358.0, 'G01': 322.0}   # 구역 대표점 → 구산동 중심 방위

# ---------- 기상 ----------
w = pd.read_csv(WX); w['t'] = pd.to_datetime(w['일시'])
w = w.rename(columns={'기온(°C)': 'temp', '풍향(deg)': 'wd', '풍속(m/s)': 'ws', '강수량(mm)': 'rain', '습도(%)': 'RH'})
g = w[w['지점명'] == '김포'].set_index('t')[['temp', 'wd', 'ws', 'rain', 'RH']]
y = w[w['지점명'] == '양촌'].set_index('t')[['temp', 'wd', 'ws', 'rain', 'RH']]
idx = pd.date_range('2026-06-17', '2026-09-30 23:00', freq='h')
W = g.reindex(idx).fillna(y.reindex(idx)).interpolate(limit=3)

def feats(t, zone):
    b = GUSAN_BEARING[zone]
    def row(h): return W.loc[t - pd.Timedelta(hours=h)]
    r0, r1, r2, r3 = row(0), row(1), row(2), row(3)
    def ug(r): return r.ws * math.cos(math.radians(r.wd - b)) if r.ws >= 0.5 else 0.0   # 구산동→구역 방향 바람 성분
    d0 = math.radians(r0.wd - b)
    return dict(
        f01_align_cos=math.cos(d0) if r0.ws >= 0.5 else 0.0, f02_align_sin=math.sin(d0) if r0.ws >= 0.5 else 0.0,
        f03_ws=r0.ws, f04_ws2=r0.ws ** 2, f05_calm=float(r0.ws < 0.5),
        f06_ug0=ug(r0), f07_ug1=ug(r1), f08_ug2=ug(r2), f09_ugmax3=max(ug(r0), ug(r1), ug(r2), ug(r3)),
        f10_temp=r0.temp, f11_RH=r0.RH, f12_tempxRH=r0.temp * r0.RH / 100,
        f13_rain=r0.rain, f14_rain3=r0.rain + r1.rain + r2.rain,
        f15_hsin=math.sin(2 * math.pi * t.hour / 24), f16_hcos=math.cos(2 * math.pi * t.hour / 24),
        f17_night=float(t.hour >= 21 or t.hour < 6),
        f18_dtemp3=r0.temp - r3.temp, f19_dRH3=r0.RH - r3.RH, f20_dws3=r0.ws - r3.ws)

# ---------- 창 만들기 ----------
rep = pd.read_csv(D + 'reports.csv', dtype=str).fillna('')
rep['t'] = pd.to_datetime(rep.observed_date + ' ' + rep.observed_time)
ev = pd.read_csv(D + 'events.csv')
# 사건 시각 = 묶인 제보들의 '관측 가능 구간' 가운데값 중 가장 이른 것 (전송시각을 그대로 관측시각으로 쓰지 않음)
raw = pd.read_csv(D + 'reports_raw.csv', dtype=str).fillna('')
rep['mid'] = pd.to_datetime(rep.window_start) + (pd.to_datetime(rep.window_end) - pd.to_datetime(rep.window_start)) / 2
mid = dict(zip(rep.report_id, rep.mid))
src = dict(zip(raw.raw_id, raw.source))
STRICT_TB = {'stated_exact', 'stated_now', 'stated_hour', 'sent_at_proxy'}
ok = {r.report_id: (r.time_basis in STRICT_TB and r.place_basis == 'stated' and src[r.report_id] == 'kakao') for r in rep.itertuples()}
ev['t'] = [min(mid[i] for i in s.split(';')).floor('h') for s in ev.report_ids]
ev['strict'] = [all(ok[i] for i in s.split(';')) for s in ev.report_ids]

def build(ev_sub, n_ctrl=4, rng=None):
    rows = []
    det = rep[rep.odor_detected == 'true']
    for _, e in ev_sub.iterrows():
        if e.zone_id not in GUSAN_BEARING: continue
        zt = det[det.zone_id == e.zone_id].t
        cands = []
        for k in range(-14, 15):
            if k == 0: continue
            c = e.t + pd.Timedelta(weeks=k)
            if c < pd.Timestamp('2026-06-20') or c > pd.Timestamp('2026-09-30 23:00'): continue
            if ((zt - c).abs() <= pd.Timedelta(hours=3)).any(): continue
            cands.append((abs(k), c))
        cands = [c for _, c in sorted(cands)[:n_ctrl]]
        if not cands: continue
        rows.append(dict(stratum=e.event_id, y=1, zone=e.zone_id, t=e.t, **feats(e.t, e.zone_id)))
        for c in cands: rows.append(dict(stratum=e.event_id, y=0, zone=e.zone_id, t=c, **feats(c, e.zone_id)))
    return pd.DataFrame(rows).dropna()

FCOLS = None
def cv_auc(df, seed=0):
    X = df[FCOLS].values; yv = df.y.values; gr = df.stratum.values
    pred = np.zeros(len(df))
    for tr, te in GroupKFold(5).split(X, yv, gr):
        sc = StandardScaler().fit(X[tr]); m = LogisticRegression(C=0.5, max_iter=2000).fit(sc.transform(X[tr]), yv[tr])
        pred[te] = m.predict_proba(sc.transform(X[te]))[:, 1]
    return roc_auc_score(yv, pred)

def clogit(df, cols):
    X = df[cols].copy(); X = (X - X.mean()) / X.std()
    r = ConditionalLogit(df.y.values, X.values, groups=df.stratum.values).fit(disp=0)
    return pd.DataFrame({'OR(1SD)': np.exp(r.params), 'p': r.pvalues}, index=cols)

main = ev[ev.quality.isin(['A', 'B']) & (ev.zone_id != 'OUT')]
strict = ev[ev.strict & (ev.zone_id != 'OUT')]   # 카톡 원본 대조됨 + 장소를 직접 말함 + 시각이 직접 말한 것 또는 카톡 전송시각
df = build(main); FCOLS = [c for c in df.columns if c.startswith('f')]
print(f'[데이터] 사건 창 {int(df.y.sum())}개, 대조 창 {int((1 - df.y).sum())}개 (사건당 최대 4개, 같은 구역·같은 요일·같은 시각, 다른 주)')
print(f'[전체 집합 A·B] 5겹 교차검증 AUC = {cv_auc(df):.3f}')
dfs = build(strict); print(f'[엄격 집합]    5겹 교차검증 AUC = {cv_auc(dfs):.3f}  (사건 {int(dfs.y.sum())}개: 카톡 원본 대조·장소 명시·시각 직접/카톡 전송시각만)')
print('※ 대조 창은 "제보가 없던 시각"이지 "냄새가 없던 시각"이 아님. 성능이 좋아도 자료의 진위나 발생원을 증명하지 못함')

# 귀무 분포: 층 안에서 사건/대조 표시를 섞음
rng = np.random.default_rng(1); null = []
for i in range(200):
    d2 = df.copy(); d2['y'] = d2.groupby('stratum').y.transform(lambda s: rng.permutation(s.values)); null.append(cv_auc(d2))
null = np.array(null); obs = cv_auc(df)
print(f'[귀무] 표시를 섞었을 때 AUC 평균 {null.mean():.3f}, 95% 상한 {np.quantile(null, .95):.3f} → 관측 {obs:.3f}, p≈{(np.sum(null >= obs) + 1) / 201:.3f}')

print('\n[엄격 집합 조건부 로지스틱 3변수]'); print(clogit(dfs, ['f06_ug0', 'f03_ws', 'f11_RH']).round(3).to_string())
core = ['f06_ug0', 'f09_ugmax3', 'f03_ws', 'f10_temp', 'f11_RH', 'f14_rain3', 'f17_night']
print('\n[조건부 로지스틱, 핵심 변수, 표준화 1SD당 오즈비]')
print(clogit(df, [c for c in core if c != 'f17_night']).round(3).to_string())

# 특징 20개 전체 L2 로지스틱 계수
sc = StandardScaler().fit(df[FCOLS]); m = LogisticRegression(C=0.5, max_iter=2000).fit(sc.transform(df[FCOLS]), df.y)
coef = pd.Series(m.coef_[0], index=FCOLS).sort_values(key=abs, ascending=False)
print('\n[특징 20개 L2 로지스틱 계수(표준화)] 상위 8:'); print(coef.head(8).round(3).to_string())

# 검출력: 사건을 줄였을 때
print('\n[검출력] 사건 일부만 있을 때 "구산동 방향 바람(ug0)" 효과가 p<0.05로 잡히는 비율 (각 100회)')
ids = main.event_id.values
for frac in [0.15, 0.25, 0.4, 0.6]:
    hit = 0; aucs = []
    for i in range(100):
        sub = main[main.event_id.isin(rng.choice(ids, int(len(ids) * frac), replace=False))]
        d3 = df[df.stratum.isin(sub.event_id)]
        try:
            r = clogit(d3, ['f06_ug0', 'f03_ws', 'f11_RH'])
            hit += (r.loc['f06_ug0', 'p'] < 0.05 and r.loc['f06_ug0', 'OR(1SD)'] > 1)
        except Exception: pass
    print(f'  사건 {int(len(ids) * frac)}개: {hit}%')
print('\n[기간] 앞에서부터 잘라 썼을 때')
for end in ['2026-07-20', '2026-08-20', '2026-09-30']:
    sub = main[pd.to_datetime(main.start_at) < end]; d3 = df[df.stratum.isin(sub.event_id)]
    r = clogit(d3, ['f06_ug0', 'f03_ws', 'f11_RH'])
    print(f"  ~{end}: 사건 {sub.shape[0]}개, ug0 OR {r.loc['f06_ug0','OR(1SD)']:.2f} (p={r.loc['f06_ug0','p']:.3g}), 습도 OR {r.loc['f11_RH','OR(1SD)']:.2f} (p={r.loc['f11_RH','p']:.3g})")
