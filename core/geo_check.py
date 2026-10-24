"""GPS 교차검증: 제보 위치가 관측 구역 안에 있는지 서버가 판정한다. (streamlit 비의존)

규칙
- 브라우저 위치 정확도(accuracy_m)가 MAX_ACCURACY_M 를 넘으면 '위치 불확실'로 거절
- 가장 가까운 구역 대표점까지 MAX_DISTANCE_M 를 넘으면 '구역 밖'으로 거절
- 통과하면 그 구역(zone_id)을 부여한다. 주민이 구역을 고르지 않고 GPS 가 정한다.
좌표는 저장 시 소수 3자리(약 100 m)로 반올림해 개인 위치를 정밀하게 남기지 않는다.
"""
from __future__ import annotations

import math

MAX_ACCURACY_M = 150.0
MAX_DISTANCE_M = 1500.0
COORD_DECIMALS = 3

# 구역 대표점(data/sample/zones.csv 와 동일). 실측 경계가 정해지면 교체.
ZONE_POINTS = {
    'Z1': (37.662, 126.679),   # 한강변·라베니체 인근
    'Z2': (37.654, 126.680),   # 운양역 인근
    'Z3': (37.647, 126.685),   # 모담산·학교 인근
}


def haversine_m(lat1, lon1, lat2, lon2) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def check_location(lat, lon, accuracy_m=None, zones: dict | None = None,
                   max_accuracy=MAX_ACCURACY_M, max_distance=MAX_DISTANCE_M) -> dict:
    """반환: status('verified'|'rejected'), zone_id(통과 시), nearest_zone, distance_m, accuracy_m, reason, lat, lon(반올림)."""
    zones = zones or ZONE_POINTS
    out = dict(status='rejected', zone_id=None, nearest_zone=None, distance_m=None,
               accuracy_m=None if accuracy_m is None else round(float(accuracy_m)), reason='',
               lat=None, lon=None)
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        out['reason'] = '위치 없음'; return out
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        out['reason'] = '좌표 범위 밖'; return out
    out['lat'], out['lon'] = round(lat, COORD_DECIMALS), round(lon, COORD_DECIMALS)
    nearest = min(zones, key=lambda z: haversine_m(lat, lon, *zones[z]))
    dist = haversine_m(lat, lon, *zones[nearest])
    out['nearest_zone'], out['distance_m'] = nearest, round(dist)
    if accuracy_m is not None and float(accuracy_m) > max_accuracy:
        out['reason'] = f'위치 정확도 {round(float(accuracy_m))} m — {int(max_accuracy)} m 이내여야 함'; return out
    if dist > max_distance:
        out['reason'] = f'가장 가까운 관측 구역에서 {round(dist / 1000, 1)} km — 구역 밖'; return out
    out.update(status='verified', zone_id=nearest, reason='')
    return out


# ------------------------------------------------------------------ 지도용 구역 면
ZONE_COLORS = {'Z1': (46, 134, 193), 'Z2': (39, 174, 96), 'Z3': (230, 126, 34)}   # 파랑 / 초록 / 주황


def _offset(lat, lon, bearing_deg, dist_m):
    r = 6371000.0
    b = math.radians(bearing_deg); p1 = math.radians(lat); l1 = math.radians(lon); d = dist_m / r
    p2 = math.asin(math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(b))
    l2 = l1 + math.atan2(math.sin(b) * math.sin(d) * math.cos(p1), math.cos(d) - math.sin(p1) * math.sin(p2))
    return math.degrees(p2), math.degrees(l2)


def zone_polygons(zones: dict | None = None, max_distance=MAX_DISTANCE_M, step_deg=6) -> dict:
    """check_location 과 똑같은 규칙(가장 가까운 대표점, max_distance 이내)으로 나눈 구역 면.
    {zone_id: [(lon, lat), ...]} — 지도에 그대로 그리면 '이 면 안 = 이 구역' 이 성립한다."""
    zones = zones or ZONE_POINTS
    out = {}
    for z, (zlat, zlon) in zones.items():
        ring = []
        for a in range(0, 360, step_deg):
            lo, hi = 0.0, float(max_distance)
            for _ in range(14):                       # 이 방향으로 아직 z 가 최근접인 최대 거리(이분 탐색)
                mid = (lo + hi) / 2
                plat, plon = _offset(zlat, zlon, a, mid)
                nearest = min(zones, key=lambda k: haversine_m(plat, plon, *zones[k]))
                if nearest == z: lo = mid
                else: hi = mid
            plat, plon = _offset(zlat, zlon, a, lo)
            ring.append((round(plon, 6), round(plat, 6)))
        out[z] = ring
    return out


# ------------------------------------------------------------------ 이동 가능성·연타 검증
MAX_SPEED_MS = 25.0        # 90 km/h. 운양동 안에서 이보다 빠른 이동은 위치 위조로 본다
MIN_INTERVAL_S = 60        # 같은 사람 1분 안 재제출은 연타로 막는다


def movement_check(prev: dict | None, loc: dict, now, max_speed=MAX_SPEED_MS, min_interval=MIN_INTERVAL_S) -> dict:
    """prev: 같은 참여자의 직전 기록(observed_at, lat, lon, location_check) 또는 None. loc: 지금 check_location 결과.
    반환 ok(bool), reason, speed_ms, gap_s. 직전 기록이 없거나 위치가 없으면 통과."""
    import pandas as pd
    out = dict(ok=True, reason='', speed_ms=None, gap_s=None)
    if not prev or loc is None or loc.get('lat') is None or prev.get('lat') is None:
        return out
    try:
        t0 = pd.Timestamp(prev['observed_at']); t1 = pd.Timestamp(now)
        if t0.tzinfo is None: t0 = t0.tz_localize('Asia/Seoul')
        if t1.tzinfo is None: t1 = t1.tz_localize('Asia/Seoul')
        gap = (t1 - t0).total_seconds()
    except (ValueError, TypeError, KeyError):
        return out
    out['gap_s'] = round(gap)
    if gap < 0:
        return out
    if gap < min_interval:
        out.update(ok=False, reason=f'직전 기록 {round(gap)}초 전 — {min_interval}초 뒤에 다시'); return out
    dist = haversine_m(float(prev['lat']), float(prev['lon']), float(loc['lat']), float(loc['lon']))
    speed = dist / max(gap, 1.0); out['speed_ms'] = round(speed, 1)
    if speed > max_speed:
        out.update(ok=False, reason=f'직전 기록({round(gap / 60)}분 전)에서 {round(dist / 1000, 1)} km 떨어짐 — 이동 불가')
    return out
