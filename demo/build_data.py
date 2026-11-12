"""시연 웹(demo/)용 자료 만들기 — 2026-09-03 저녁을 실제 모델로 다시 계산한다.

실행(저장소 루트에서):  python -m demo.build_data
결과: demo/data.js  (window.DEMO = {...})

지어낸 값 없음.
- 기상: data/external/aws/weather_<STATION>.csv (모델을 학습한 관측소 AWS 441, 그날 실제 관측값) 을 '그날의 예보'로 넣는다.
- 단계: 앱과 같은 함수 core.analysis_service.predict_windows() 결과.
- 화면 자료: 앱과 같은 함수 core.map_data.prepare_payload() 결과.
- 기기 일정: 앱과 같은 규칙 odor_model.prerun.plan().
- 주민 기록: data/private/reports.csv 에서 그날 15시 이후 '냄새 남' 제보의 시각·구역·강도만 읽는다(참여자 코드·장소 글·좌표는 읽지 않고 내보내지 않음).
- 평가: odor_model/artifacts/evaluation_cc_<관측소>.md 의 교차검증 set AUC 와 사건 수.
"""
from __future__ import annotations

import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')
ROOT = Path(__file__).resolve().parents[1]
DAY = '2026-08-19'
STATION = '441'           # 모델을 학습한 관측소와 같게
START, END = f'{DAY} 12:00', (pd.Timestamp(DAY) + pd.Timedelta(hours=30)).strftime('%Y-%m-%d %H:%M')
HOME_ZONE = 'Z2'          # 시연 속 '우리 집' 구역(운양역)
KST = '+09:00'
REPORTS_FROM = '15:00'


def read_reports(ids: dict) -> list[dict]:
    """그날 15시 이후 '냄새 남' 제보. 시각·구역·강도만 꺼낸다."""
    import csv
    out = []
    with open(ROOT / 'data/private/reports.csv', encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            if r['observed_date'] != DAY or r['zone_id'] not in ids or r['odor_detected'] != 'true':
                continue
            if not r['observed_time'] or r['observed_time'][:5] < REPORTS_FROM:
                continue
            out.append({'at': f"{DAY}T{r['observed_time'][:5]}:00{KST}", 'zone': ids[r['zone_id']],
                        'intensity': int(r['intensity']) if r['intensity'] else None, 'n': 1})
    return sorted(out, key=lambda x: x['at'])


def inner_point(ring, avoid, keep_km=0.35):
    """구역 면 안에서 경계와 가장 먼 점(대표점 둘레 keep_km 는 이름표·집 표시가 있어 피함). 시연 속 주민 위치."""
    lat0 = sum(p[0] for p in ring) / len(ring)
    kx = 111.32 * np.cos(np.radians(lat0))
    xy = np.array([[(p[1]) * kx, p[0] * 110.57] for p in ring])
    ax, ay = avoid[1] * kx, avoid[0] * 110.57

    def inside(x, y):
        c = False
        for i in range(len(xy)):
            (x1, y1), (x2, y2) = xy[i], xy[i - 1]
            if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
                c = not c
        return c

    def edge(x, y):
        best = 1e9
        for i in range(len(xy)):
            (x1, y1), (x2, y2) = xy[i - 1], xy[i]
            dx, dy = x2 - x1, y2 - y1
            t = max(0, min(1, ((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy or 1)))
            best = min(best, np.hypot(x - x1 - t * dx, y - y1 - t * dy))
        return best
    xs, ys = np.linspace(xy[:, 0].min(), xy[:, 0].max(), 60), np.linspace(xy[:, 1].min(), xy[:, 1].max(), 60)
    cand = [(edge(x, y), x, y) for x in xs for y in ys if inside(x, y) and np.hypot(x - ax, y - ay) > keep_km]
    d, x, y = max(cand)
    return [round(float(y / 110.57), 6), round(float(x / kx), 6)], round(float(d), 3)

GROUPS = {   # 모델 특징 → 화면에 보여 줄 묶음. 풍향·풍속과 발생원 정렬은 서로 얽혀 있어 한 묶음으로 본다.
    '바람': ['wind_sin', 'wind_cos', 'wind_speed', 'calm', 'wind_u', 'wind_v', 'align_C1', 'align_C2', 'align_C3', 'align_C4'],
    '습도': ['humidity'], '기온': ['temperature'], '비': ['rain'],
}


def evaluation(model) -> dict:
    """모델 평가 파일(odor_model/artifacts/evaluation_cc_<관측소>[_strict].md)에서 교차검증 set AUC 와 사건 수를 읽는다."""
    import re
    name = f"evaluation_cc_{model.get('station', '')}{'_strict' if model.get('strict') else ''}.md"
    text = (ROOT / 'odor_model/artifacts' / name).read_text(encoding='utf-8')
    cv = text.split('## 교차검증', 1)[1]
    auc = re.search(r'set AUC\):\s*\*\*([0-9.]+)\*\*', cv)
    ev = re.search(r'사건 (\d+)', text)
    if not (auc and ev):
        raise SystemExit(f'{name}: set AUC 또는 사건 수를 찾지 못함')
    return {'auc': float(auc.group(1)), 'events': int(ev.group(1)), 'file': name}


def iso(t) -> str:
    return pd.Timestamp(t).strftime('%Y-%m-%dT%H:%M:%S') + KST


def main():
    from core import analysis_service as service
    from core.map_data import prepare_payload, outlook
    from odor_model.features import make_features, candidate_table
    from odor_model.prerun import plan

    wx = pd.read_csv(ROOT / f'data/external/aws/weather_{STATION}.csv', encoding='utf-8-sig', parse_dates=['window_start'])
    rows = wx[(wx.window_start >= START) & (wx.window_start <= END)].copy()
    rows['basis'] = 'forecast'
    pred = service.predict_windows(rows)
    model, info = service.load_model()
    zones = pd.read_csv(ROOT / 'data/sample/zones.csv', encoding='utf-8-sig')
    if str(model_station := service.load_model()[0].get('station', '')) != STATION:
        raise SystemExit(f'모델 관측소 {model_station} 와 입력 관측소 {STATION} 가 다름')
    md = DAY[5:].replace('-', '.').lstrip('0')
    ids = service.app_zone_ids()
    reports = read_reports(ids)
    meta = {'source': 'demo', 'label': '재현 예보', 'issued': f'2026.{md} AWS {STATION} 관측값', 'error': ''}
    payload = prepare_payload(pd.DataFrame(), pd.DataFrame(), zones, pd.DataFrame(), True,
                              forecast=meta, forecast_predictions=pred, model_info=info)
    payload['info'].update({'자료 유형': f'2026.{md} 기록 재현', '기간': DAY.replace('-', '.'), '기록 수': f'그날 저녁 제보 {sum(r["n"] for r in reports)}건',
                            '주민 기록': '실제 제보 · 시각과 구역만', '기상 자료': f'AWS {STATION} 그날 관측값',
                            '기상 관측소': f'AWS {STATION}', '예보': '그날 관측값을 예보로 넣어 다시 계산'})
    hours = [pd.Timestamp(f'{DAY} {h:02d}:00') for h in range(15, 24)]
    outlooks = {f'{t:%H}': outlook(payload['frames'], list(zones.zone_id), t.tz_localize('Asia/Seoul')) for t in hours}

    # 기기 일정: 15:00 에 계산한 것(앱 규칙 그대로, 미리 켜기 40분·끄기 30분·'높음' 기준)
    now0 = pd.Timestamp(f'{DAY} 15:00')
    p = plan(pred[pred.window_start >= now0], HOME_ZONE, now0, lead_min=40, tail_min=30, trigger='높음')
    episodes = []
    for e in p['episodes']:
        e = e if isinstance(e, dict) else e.as_dict()
        episodes.append({k: (iso(v) if k.endswith('_at') or k.startswith('odor_') else v) for k, v in e.items()})

    # 모델이 본 것: 시간×구역별 특징 기여(= 계수 × 표준화 값). 합의 sigmoid 가 점수.
    geo = model['geo']
    m = model['detect_model']
    explain = []
    for _, r in rows.iterrows():
        for z in ('U01', 'U02', 'U03'):
            df = pd.DataFrame([dict(window_start=r.window_start, zone_id=z, wind_from_deg=float(r.wind_from_deg),
                                    wind_speed=float(r.wind_speed), humidity_pct=float(r.humidity_pct),
                                    temperature_c=float(r.temperature_c), rain_1h_mm=float(r.rain_1h_mm or 0))])
            X = make_features(df, geo)[m.columns]
            contrib = ((np.asarray(X, float)[0] - m.mean_) / m.scale_) * m.coef_
            by = dict(zip(m.columns, contrib))
            total = float(contrib.sum())
            explain.append({'at': iso(r.window_start), 'zone': ids[z],
                            'groups': {g: round(float(sum(by[c] for c in cols)), 3) for g, cols in GROUPS.items()},
                            'sum': round(total, 3), 'score': round(float(1 / (1 + np.exp(-total))), 3),
                            'wind_from': float(r.wind_from_deg), 'wind_speed': float(r.wind_speed),
                            'humidity': float(r.humidity_pct), 'temp': float(r.temperature_c)})
    ct = candidate_table(geo)
    bearings = [{'zone': ids[r.zone_id], 'name': geo['candidates'][r.cand_id]['name'], 'type': geo['candidates'][r.cand_id]['type'],
                 'bearing': round(float(r.bearing_deg), 1)} for r in ct.itertuples()]

    # 발표자가 ＋기록으로 대신하는 제보: 우리 집 구역에서 '높음' 시간대에 들어온 마지막 제보(없으면 우리 집 구역 마지막 제보)
    lv = {(e['zone'], e['at'][:13]): None for e in explain}
    for r in pred.itertuples():
        lv[(r.app_zone_id, iso(r.window_start)[:13])] = r.level
    home = [k for k, r in enumerate(reports) if r['zone'] == HOME_ZONE]
    high = [k for k in home if lv.get((HOME_ZONE, reports[k]['at'][:13])) == '높음']
    mine = (high or home or [None])[-1]
    hz = next(z for z in payload['zones'] if z['id'] == HOME_ZONE)
    point, margin = inner_point(hz['ring'], (hz['lat'], hz['lon']))

    out = {
        'day': DAY, 'station': STATION, 'home_zone': HOME_ZONE, 'payload': payload, 'outlook': outlooks, 'reports': reports,
        'mine': mine, 'record_point': point,
        'episodes': episodes, 'explain': explain, 'bearings': bearings,
        'thresholds': {'mid': round(float(model['thr_fixed']), 3), 'high': round(float(model['thr_valid']), 3)},
        'model': {'trained_on': model.get('trained_on', ''), 'status': model.get('status', ''), 'kind': model.get('model_kind', ''),
                  'station': str(model.get('station', '')), **evaluation(model)},
        'zone_map': {app: mid for mid, app in ids.items()},
    }
    target = ROOT / 'demo/data.js'
    target.write_text('// 자동 생성: python -m demo.build_data · 손으로 고치지 않는다\nwindow.DEMO=' +
                      json.dumps(out, ensure_ascii=False, default=str) + ';\n', encoding='utf-8')
    print('reports', [(r['at'][11:16], r['zone'], r['intensity']) for r in reports], 'mine', mine, 'point', point, f'edge {margin} km')
    print('wrote', target, f'{target.stat().st_size:,} bytes · frames {len(payload["frames"])} · episodes {len(episodes)}')
    for e in episodes:
        print(' episode', e)


if __name__ == '__main__':
    main()
