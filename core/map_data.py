"""Aggregate-only model shared by map, compass and time controls."""
import json
import math
from pathlib import Path
import pandas as pd
from .config import ZONE_PUBLIC_NAMES, now_kst
from .geo import haversine_km

ROOT = Path(__file__).resolve().parents[1]
TYPES = {'livestock': ('축산계', '#D97706'), 'sewage': ('하수계', '#7C3AED'),
         'other': ('기타', '#0F766E'), 'unknown': ('미확인', '#64748B')}


def boundary():
    return json.loads((ROOT / 'data/geo/gimpo.geojson').read_text(encoding='utf-8'))


def in_ring(lat, lon, ring):
    inside = False
    for a, b in zip(ring, ring[1:] + ring[:1]):
        x, y = a[:2]; xx, yy = b[:2]
        if (y > lat) != (yy > lat) and lon < (xx-x)*(lat-y)/(yy-y)+x:
            inside = not inside
    return inside


def in_service(lat, lon, geo=None):
    if not math.isfinite(lat) or not math.isfinite(lon): return False
    for feature in (geo or boundary())['features']:
        geom = feature['geometry']
        polygons = geom['coordinates'] if geom['type'] == 'MultiPolygon' else [geom['coordinates']]
        for rings in polygons:
            if in_ring(lat, lon, rings[0]) and not any(in_ring(lat, lon, h) for h in rings[1:]): return True
    return False


def classify_type(value):
    text = str(value)
    if any(word in text for word in ('분뇨', '축산')): return 'livestock'
    if '하수' in text: return 'sewage'
    if text in ('기타', '탄내', '화학물질과 비슷함'): return 'other'
    return 'unknown'


def stamp(value):
    dt = pd.Timestamp(value)
    return (dt.tz_localize('Asia/Seoul') if dt.tzinfo is None else dt.tz_convert('Asia/Seoul')).isoformat()


def _wind_at(wx, time):
    near = wx[(wx.weather_at <= time) & (wx.weather_at >= time-pd.Timedelta(hours=1))] if not wx.empty else wx
    if near.empty:
        return None, None
    row = near.iloc[-1]
    basis = row.get('weather_basis') if 'weather_basis' in near else None
    if pd.isna(row.ws) or pd.isna(row.wd):
        return None, basis
    return {'from': float(row.wd) % 360, 'to': (float(row.wd)+180) % 360,
            'speed': float(row.ws), 'at': stamp(row.weather_at)}, basis


EMPTY_STATS = {'n': 0, 'detected': 0, 'status': '자료 없음', 'type': 'unknown', 'rate': None,
               'odor_evidence': False, 'median': None}


def _zone_stats(rows):
    valid = rows[rows.odor.notna()]
    n = int(valid.observer_code.nunique())
    detected = valid[valid.odor == 1]
    d = len(detected)
    ratio = d/n if n else None
    status = '자료 부족' if n < 3 else ('집단 감지' if ratio >= .5 else '일부 감지' if ratio >= .2 else '감지 낮음')
    counts = detected.odor_type.map(classify_type).value_counts().to_dict() if not detected.empty else {}
    ordered = sorted(counts.items(), key=lambda item: item[1], reverse=True)
    kind = ordered[0][0] if ordered and ordered[0][1] >= 2 and (len(ordered) == 1 or ordered[0][1] > ordered[1][1]) else 'unknown'
    return {'n': n, 'detected': d, 'status': status, 'type': kind, 'rate': round(ratio, 3) if ratio is not None else None,
            'odor_evidence': n >= 3 and d >= 2,
            'median': float(valid.intensity.median()) if n and valid.intensity.notna().any() else None}


def _index(predictions):
    if predictions is None or predictions.empty:
        return {}
    return {(stamp(r['window_start']), r['app_zone_id']): r for r in predictions.to_dict('records')}


def _attach(frame, index, settings):
    """One prediction and one arrow rule per zone, shared by map, compass and panels."""
    from .analysis_service import arrow_kind, compact
    for zone_id, stats in frame['zones'].items():
        pred = compact(index.get((frame['at'], zone_id)))
        rate = stats['rate'] if stats['n'] >= 3 else frame.get('window_rate')
        stats['pred'] = pred
        stats['arrow'] = arrow_kind(pred, frame['wind'], rate, settings)


def outlook(frames, zone_ids, now):
    """Per zone: '09.16 22:00 낮음 · 오늘 밤 높음(예보)' from the same frame predictions."""
    from .analysis_service import LEVELS, day_phrase
    now = pd.Timestamp(now).tz_convert('Asia/Seoul').tz_localize(None)
    local = lambda f: pd.Timestamp(f['at']).tz_localize(None)
    observed = [f for f in frames if f['kind'] == 'observed']
    ahead = [f for f in frames if f['kind'] == 'forecast']
    later = [f for f in ahead if local(f) >= now]
    anchor = local((later or ahead)[0]) if ahead else None
    window = [f for f in ahead if anchor is not None and anchor <= local(f) < anchor + pd.Timedelta(hours=6)]
    result = {}
    for zone_id in zone_ids:
        parts = []
        last = observed[-1] if observed else None
        pred = last['zones'].get(zone_id, {}).get('pred') if last else None
        if pred and pred.get('level'):
            at = local(last)
            parts.append(f"{'지금' if now - at <= pd.Timedelta(hours=1) else at.strftime('%m.%d %H:%M')} {pred['level']}")
        levels = []
        for f in window:
            p = f['zones'].get(zone_id, {}).get('pred')
            if p and p.get('level'):
                levels.append((LEVELS.index(p['level']), local(f)))
        if levels:
            top = max(rank for rank, _ in levels)
            first_at = next(at for rank, at in levels if rank == top)
            parts.append(f'{day_phrase(first_at, now)} {LEVELS[top]}(예보)')
        result[zone_id] = ' · '.join(parts) if parts else '추정 보류'
    return result


def prepare_payload(reports, weather, zones, windows, demo, slots=None, predictions=None,
                    forecast=None, forecast_predictions=None, model_info=None, settings=None):
    """No participant codes, individual reports, p values or candidate scores reach the browser.

    slots: workbook window list (시간창집계). When given, only those times become frames.
    predictions / forecast_predictions: analysis_service.predict_windows() output.
    """
    from .analysis_service import BASIS_LABELS, load_settings
    from .features import window_id_time
    settings = settings or load_settings()
    r = reports.copy()
    times = set()
    if not r.empty:
        r['observed_at'] = pd.to_datetime(r.observed_at)
        r['submitted_at'] = pd.to_datetime(r.submitted_at)
        r['window_at'] = r.observed_at.dt.round('30min')
        if 'window_id' in r: r['window_at'] = window_id_time(r.window_id).fillna(r.window_at)
        if slots is None or slots.empty: times.update(r.window_at.dropna())
        r = r[(r.report_mode == 'scheduled') & (r.environment == 'outdoor') & (r.observer_code != 'GUEST')]
        r = r.sort_values('submitted_at').drop_duplicates(['observer_code','zone_id','window_at'], keep='last')
    slot_rates = {}
    if slots is not None and not slots.empty:
        times.update(pd.to_datetime(slots.window_start))
        slot_rates = {pd.Timestamp(t): (float(v) if pd.notna(v) else None) for t, v in zip(slots.window_start, slots.detection_rate)}
    elif not windows.empty:
        times.update(windows.window_at.dropna())
    wx = weather.copy()
    if not wx.empty:
        wx['weather_at'] = pd.to_datetime(wx.weather_at)
        if 'quality_flag' in wx: wx = wx[wx.quality_flag == 'ok']
        wx = wx.sort_values('weather_at')
    groups = {key: g for key, g in r.groupby(['zone_id', 'window_at'])} if not r.empty else {}
    frames = []
    for time in sorted(times):
        wind, basis = _wind_at(wx, time)
        stats = {z: _zone_stats(groups[(z, time)]) if (z, time) in groups else dict(EMPTY_STATS) for z in zones.zone_id}
        frames.append({'at': stamp(time), 'kind': 'observed', 'wind': wind, 'zones': stats,
                       'window_rate': slot_rates.get(pd.Timestamp(time)),
                       'basis': BASIS_LABELS.get(basis, '시연' if demo else '관측') if wind else '자료 없음'})
    index = _index(predictions)
    for f in frames: _attach(f, index, settings)
    latest_index = len(frames) - 1
    meta = forecast or {'source': 'none', 'label': '예보 없음', 'issued': '', 'error': ''}
    if forecast_predictions is not None and not forecast_predictions.empty:
        index = _index(forecast_predictions)
        last = pd.Timestamp(frames[-1]['at']) if frames else None
        for time, rows in forecast_predictions.groupby('window_start'):
            at = stamp(time)
            if last is not None and pd.Timestamp(at) <= last: continue
            first = rows.iloc[0]
            wind = None
            if pd.notna(first.get('wind_from_deg')) and pd.notna(first.get('wind_speed')):
                wind = {'from': float(first.wind_from_deg) % 360, 'to': (float(first.wind_from_deg)+180) % 360,
                        'speed': float(first.wind_speed), 'at': at}
            frame = {'at': at, 'kind': 'forecast', 'wind': wind, 'window_rate': None, 'basis': meta['label'],
                     'zones': {z: dict(EMPTY_STATS) for z in zones.zone_id}}
            _attach(frame, index, settings)
            frames.append(frame)
    period = '—' if not times else f'{min(times):%Y.%m.%d}–{max(times):%Y.%m.%d}'
    basis_counts = weather['weather_basis'].map(BASIS_LABELS).value_counts() if 'weather_basis' in weather else pd.Series(dtype=int)
    weather_info = ' · '.join(f'{k} {v}건' for k, v in basis_counts.items()) if not basis_counts.empty else ('제공 파일' if demo else '미연결')
    model_info = model_info or {'ok': False, 'reason': '모델 없음'}
    forecast_info = {'kma': f"기상청 단기예보 · {meta.get('issued', '')}", 'csv': '시연 예보 · 예시 파일',
                     'none': '없음'}[meta['source']] + (f" · {meta['error']}" if meta.get('error') else '')
    return {'frames': frames, 'latest_index': latest_index, 'demo': demo, 'now': now_kst().isoformat(),
            'zones': [{'id': z.zone_id, 'name': ZONE_PUBLIC_NAMES.get(z.zone_id, z['name']),
                       'lat': float(z.rep_lat), 'lon': float(z.rep_lon)} for _, z in zones.iterrows()],
            'boundary': boundary(), 'types': TYPES, 'forecast': meta, 'calm_ms': float(settings['calm_ms']),
            'model': {'ok': bool(model_info.get('ok')), 'reason': model_info.get('reason', ''), 'status': '예비 실험·미보정'},
            'outlook': outlook(frames, list(zones.zone_id), now_kst()),
            'info': {'자료 유형': '시연' if demo else '주민 관측', '기간': period, '기록 수': f'{len(reports):,}건',
                     '주민 기록': '가상 생성 · simulated' if demo else '직접 제출',
                     '기상 자료': weather_info, '기상 관측소': '427 양촌' if demo else '미연결',
                     '예보': forecast_info,
                     '추정 모델': '예비 실험·미보정' if model_info.get('ok') else f"추정 보류 · {model_info.get('reason', '')}",
                     '행정경계': 'KOSTAT 공개자료 · 2018', '관측 위치': '구역 대표점 · 임시'}}


def resolve_selection(payload, state):
    position = state.get('position', [37.654,126.680])
    try: lat, lon = map(float, position)
    except (TypeError, ValueError): lat, lon = 37.654,126.680
    if not in_service(lat,lon,payload['boundary']): lat,lon=37.654,126.680
    nearest = min(payload['zones'], key=lambda z:haversine_km(lat,lon,z['lat'],z['lon']))
    distance = haversine_km(lat,lon,nearest['lat'],nearest['lon'])
    zone = nearest if distance <= 2 else None
    frames = payload['frames']
    latest = payload.get('latest_index', len(frames)-1)
    index = next((i for i,f in enumerate(frames) if f['at']==state.get('at')), latest)
    return {'position':[lat,lon], 'zone_id':zone['id'] if zone else None,
            'zone_name':zone['name'] if zone else '관측 구역 밖',
            'distance_km':round(distance,2), 'at':frames[index]['at'] if frames else None,
            'index':index, 'sequence':state.get('sequence',0)}
