"""주민 제보 사건(events.csv) × AWS 실측 기상 — 풍향 장미도·시간대·월별·대조군 비교.
사용: python -m scripts.analyze_reports [--strict]   (저장소 루트, data/private 필요)
출력: artifacts/reports_analysis/<시각>/ figures(png) + summary.md + event_weather.csv
--strict : 엄격 집합(카톡 원문 대조 가능 + 장소 명시 + 시각 근거 양호)만.
풍향 기준: 각 사건의 창(window_start~end_at)에 걸친 김포(441) 시간값의 벡터 평균, 441 결측이면 양촌(427).
"""
from __future__ import annotations
import argparse, csv, math
from collections import Counter
from pathlib import Path
import numpy as np, pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PRIV = ROOT / 'data/private'
SECTORS = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW']
STRICT_TIME = {'stated_exact', 'stated_now', 'stated_hour', 'sent_at_proxy'}
CALM = 0.5
GUSAN_SECTORS = {'N', 'NNE', 'NE'}          # 구산동·법곳동 축산지(구역 기준 방위 약 358~16°)


def sector(deg):
    return SECTORS[int(((deg + 11.25) % 360) // 22.5)]


def load_weather(primary='441'):
    w = {}
    for sid in ('441', '427'):
        df = pd.read_csv(ROOT / f'data/external/aws/weather_{sid}.csv', parse_dates=['window_start'])
        w[sid] = df.set_index('window_start')
    other = '427' if primary == '441' else '441'
    base = w[primary].copy()
    for c in ('wind_from_deg', 'wind_speed', 'temperature_c', 'humidity_pct', 'rain_1h_mm'):
        base[c] = base[c].fillna(w[other][c])
    return base


def vector_mean(rows: pd.DataFrame):
    ws, wd = rows.wind_speed.to_numpy(float), rows.wind_from_deg.to_numpy(float)
    ok = ~np.isnan(ws) & ~np.isnan(wd)
    if not ok.any(): return None, None
    u = -(ws[ok] * np.sin(np.radians(wd[ok]))).mean(); v = -(ws[ok] * np.cos(np.radians(wd[ok]))).mean()
    spd = math.hypot(u, v); deg = (math.degrees(math.atan2(-u, -v)) + 360) % 360
    return deg, spd


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--strict', action='store_true')
    ap.add_argument('--station', default='441', choices=['441', '427'], help='441 김포(시내) / 427 양촌(운양 북서쪽, 구산동에 가까움)')
    a = ap.parse_args()
    rep = {r['report_id']: r for r in csv.DictReader(open(PRIV / 'reports.csv', encoding='utf-8-sig'))}
    ev = list(csv.DictReader(open(PRIV / 'events.csv', encoding='utf-8-sig')))
    W = load_weather(a.station)
    rows = []
    for e in ev:
        ids = e['report_ids'].split(';')
        if a.strict and not all(rep[i]['source_check'] == 'kakao_export' and rep[i]['place_basis'] == 'stated' and rep[i]['time_basis'] in STRICT_TIME for i in ids):
            continue
        ws_ = [rep[i]['window_start'] for i in ids if rep[i].get('window_start')]
        t0 = pd.Timestamp(min(ws_)) if ws_ else pd.Timestamp(e['start_at'])
        t1 = pd.Timestamp(e['end_at'])
        hours = pd.date_range(t0.floor('h'), t1.ceil('h'), freq='h')
        sub = W.reindex(hours).dropna(subset=['wind_speed'])
        deg, spd = vector_mean(sub)
        rows.append(dict(event_id=e['event_id'], zone=e['zone_id'], start=e['start_at'], hour=pd.Timestamp(e['start_at']).hour,
                         month=e['start_at'][:7], n_participants=int(e['n_participants']), intensity_max=e['intensity_max'],
                         wind_deg=deg, wind_ms=spd, sector=None if deg is None or spd < CALM else sector(deg),   # 무풍은 방위 없음
                         calm=None if spd is None else spd < CALM, temp=sub.temperature_c.mean(), rh=sub.humidity_pct.mean(), rain=sub.rain_1h_mm.sum()))
    E = pd.DataFrame(rows)
    period = W.loc['2026-06-20':'2026-09-30 23:00'].dropna(subset=['wind_speed']).copy()
    period['calm'] = period.wind_speed < CALM
    period['sector'] = np.where(period.calm, None, period.wind_from_deg.map(sector))   # AWS 는 무풍을 풍향 0(N)으로 적으므로 제외

    # 기준선 1: 기간 전체 시간, 기준선 2: 사건과 같은 시각대 분포로 가중(재실 편향 상쇄)
    uz = E[E.zone.isin(['U01', 'U02', 'U03'])].dropna(subset=['wind_ms'])      # 운양동 사건(무풍 포함)
    ue = uz.dropna(subset=['sector'])                                            # 방위가 있는 사건
    hw = uz.hour.value_counts(normalize=True)
    period['w'] = period.index.hour.map(hw).fillna(0)
    def dist(df, w=None):
        df = df.dropna(subset=['sector'])
        s = df.groupby('sector')['w'].sum() if w else df.sector.value_counts()
        return (s.reindex(SECTORS).fillna(0) / s.sum())
    d_ev, d_all, d_tm = dist(ue), dist(period), dist(period, True)
    tab = pd.DataFrame({'사건': (d_ev * len(ue)).round().astype(int), '사건 비율': d_ev.round(3), '전체 시간 비율': d_all.round(3), '시각 맞춘 기준 비율': d_tm.round(3)})
    tab['lift(시각 맞춤)'] = (d_ev / d_tm.replace(0, np.nan)).round(2)
    windy = period.dropna(subset=['sector'])                                     # 기준도 바람 있는 시간만(사건과 같은 조건)
    ne_ev = ue.sector.isin(GUSAN_SECTORS).mean(); ne_tm = windy.loc[windy.sector.isin(GUSAN_SECTORS), 'w'].sum() / windy.w.sum()
    calm_ev = uz.calm.mean(); calm_tm = period.loc[period.calm, 'w'].sum() / period.w.sum()

    NORTH = {'WNW', 'NW', 'NNW', 'N', 'NNE', 'NE', 'ENE'}
    nh_ev = ue.sector.isin(NORTH).mean(); nh_tm = windy.loc[windy.sector.isin(NORTH), 'w'].sum() / windy.w.sum()
    rng = np.random.default_rng(0); x = ue.sector.isin(NORTH).to_numpy()
    nh_ci = np.percentile([rng.choice(x, len(x)).mean() for _ in range(2000)], [2.5, 97.5])
    st_name = {'441': '김포(441, 시내)', '427': '양촌(427, 운양 북서쪽)'}[a.station]
    out = ROOT / 'artifacts/reports_analysis' / (pd.Timestamp.now().strftime('%Y%m%d_%H%M') + f'_{a.station}' + ('_strict' if a.strict else ''))
    out.mkdir(parents=True, exist_ok=True)
    E.to_csv(out / 'event_weather.csv', index=False, encoding='utf-8-sig')

    import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
    import matplotlib.font_manager as fm; _f = [f for f in ('Malgun Gothic', 'NanumGothic', 'Noto Sans CJK KR', 'Noto Sans CJK JP', 'Noto Sans CJK HK', 'Noto Sans CJK SC', 'AppleGothic') if any(x.name == f for x in fm.fontManager.ttflist)]; plt.rcParams['font.family'] = (_f[:1] or ['DejaVu Sans']) + ['DejaVu Sans']; plt.rcParams['axes.unicode_minus'] = False
    ink, quiet, acc, base = '#1f2328', '#8b949e', '#2e86c1', '#c9ccd1'
    # 그림 1: 풍향 분포 — 사건 vs 시각 맞춘 기준
    th = np.radians(np.arange(16) * 22.5); wdt = np.radians(22.5) * 0.42
    fig = plt.figure(figsize=(6.4, 6.4)); ax = fig.add_subplot(111, polar=True)
    ax.set_theta_zero_location('N'); ax.set_theta_direction(-1)
    ax.bar(th - wdt / 2, d_tm.values, width=wdt, color=base, label='기준(기간 전체, 사건 시각대 가중)')
    ax.bar(th + wdt / 2, d_ev.values, width=wdt, color=acc, label=f'제보 사건(바람 있음) n={len(ue)}')
    ax.set_xticks(th); ax.set_xticklabels(SECTORS, fontsize=9, color=ink); ax.set_yticklabels([]); ax.grid(color='#e6e8eb')
    ax.set_title(f'사건 시각의 풍향(불어오는 방향) 분포 — 운양동 3구역 · AWS {st_name}', fontsize=10.5, color=ink, pad=16)
    ax.legend(loc='lower center', bbox_to_anchor=(0.5, -0.14), fontsize=9, frameon=False, ncol=1)
    fig.text(0.5, 0.005, f'북쪽 반원(WNW~ENE): 사건 {nh_ev:.0%} vs 기준 {nh_tm:.0%} · N~NE: {ne_ev:.0%} vs {ne_tm:.0%} · 무풍: {calm_ev:.0%} vs {calm_tm:.0%} · AWS {st_name}', ha='center', fontsize=8, color=quiet)
    fig.savefig(out / 'fig1_windrose.png', dpi=160, bbox_inches='tight'); plt.close(fig)
    # 그림 2: 시간대·월별
    fig, axs = plt.subplots(1, 2, figsize=(9, 3.2))
    hc = uz.hour.value_counts().reindex(range(24)).fillna(0)
    axs[0].bar(hc.index, hc.values, color=acc, width=0.8); axs[0].set_title('시간대별 사건 수', fontsize=10, color=ink); axs[0].set_xticks(range(0, 24, 3)); axs[0].set_xlabel('시(KST)', fontsize=9)
    mc = uz.month.value_counts().sort_index()
    axs[1].bar(mc.index.str[5:], mc.values, color=acc, width=0.6); axs[1].set_title('월별 사건 수', fontsize=10, color=ink); axs[1].set_xlabel('월', fontsize=9)
    for ax_ in axs: ax_.spines[['top', 'right']].set_visible(False); ax_.grid(axis='y', color='#e6e8eb'); ax_.set_axisbelow(True)
    fig.tight_layout(); fig.savefig(out / 'fig2_time_month.png', dpi=160, bbox_inches='tight'); plt.close(fig)

    # 대조군(고촌 G01)과 운양동
    g = E[E.zone == 'G01']
    md = [f"# 주민 제보 사건 × 실측 기상 ({'엄격 집합' if a.strict else '전체 집합'})", '',
          f"사건 {len(E)}건(운양동 3구역 {len(uz)}건, 고촌 대조 {len(g)}건, 운양동 밖 {int((E.zone == 'OUT').sum())}건) · 기간 2026-06-20~09-30 · AWS {st_name}, 결측은 다른 관측소로 보완", '',
          '## 풍향(16방위): 사건 vs 기준', '', tab.to_markdown(), '',
          f"- 바람 있는 사건 {len(ue)}건 중 N~NE(구산동 방향) 비율: **{ne_ev:.0%}** vs 시각 맞춘 기준 {ne_tm:.0%} (lift {ne_ev / ne_tm:.2f})",
          f"- **북쪽 반원(WNW~ENE)** 비율: 사건 **{nh_ev:.0%}** (95% CI {nh_ci[0]:.0%}~{nh_ci[1]:.0%}) vs 기준 {nh_tm:.0%}",
          f"- 무풍(<0.5 m/s) 비율: 사건 {calm_ev:.0%} ({int(uz.calm.sum())}/{len(uz)}) vs 기준 {calm_tm:.0%}",
          f"- 사건 시 풍속 중앙값 {uz.wind_ms.median():.1f} m/s vs 기간 중앙값 {period.wind_speed.median():.1f} m/s",
          f"- 사건 시 평균 기온 {ue.temp.mean():.1f} ℃ · 습도 {ue.rh.mean():.0f} % vs 기간 평균 {period.temperature_c.mean():.1f} ℃ · {period.humidity_pct.mean():.0f} %", '',
          '## 시간대·월', '', f"- 시간대: {dict(sorted((int(k), int(v)) for k, v in Counter(uz.hour // 6).items()))} (0 새벽 1 오전 2 오후 3 저녁)",
          f"- 월: {dict((k, int(v)) for k, v in uz.month.value_counts().sort_index().items())}", f"- 집단 사건(2명 이상): {int((uz.n_participants >= 2).sum())}건", '',
          '## 대조군(고촌, P05)', '', f"- 고촌 사건 {len(g)}건 — 운양동 {len(uz)}건. 고촌 거주자는 운양동 방문일(금요일)에만 운양 구역 제보.", '',
          '## 읽을 때 주의', '',
          '- 자발 제보라 분모(관측 시도 수)가 없다. 비율은 "사건 중"의 비율이고 감지 확률이 아니다.',
          '- 시각의 82%가 전송 시각 대용(±1시간)이라 풍향은 사건 창 전체의 벡터 평균을 썼다. AWS 는 무풍을 풍향 0(N)으로 적으므로 무풍 시간은 방위 집계에서 뺐다.',
          '- 김포(441)와 양촌(427) 관측소의 풍향 분포가 서로 달라, 특정 16방위보다 "북쪽 반원 vs 남쪽 반원"처럼 넓은 구분이 더 믿을 만하다. 두 관측소 결과를 모두 보고한다.',
          '- 기준 분포는 사건과 같은 시각대 비중으로 가중해 "밤에 많이 쓴다"는 재실 편향을 상쇄했다.',
          '- 인스타 DM 54건은 캡처 이미지가 없어 원문 대조를 못 했다(엄격 집합에서 제외).']
    (out / 'summary.md').write_text('\n'.join(md), encoding='utf-8')
    print('\n'.join(md)); print('\n저장:', out)


if __name__ == '__main__':
    main()
