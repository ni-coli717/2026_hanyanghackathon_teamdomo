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
