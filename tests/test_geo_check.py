"""GPS 교차검증 규칙(core/geo_check)과 관측 레코드의 위치 필드."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from core.geo_check import check_location, haversine_m, ZONE_POINTS


def test_haversine_sanity():
    assert abs(haversine_m(37.662, 126.679, 37.654, 126.680) - 894) < 20


def test_inside_zone_is_verified_and_rounded():
    r = check_location(37.6545, 126.6804, accuracy_m=25)
    assert r['status'] == 'verified' and r['zone_id'] == 'Z2'
    assert r['lat'] == 37.654 and r['lon'] == 126.68 and r['accuracy_m'] == 25
    assert r['distance_m'] < 100


def test_far_away_is_rejected_with_nearest_zone():
    r = check_location(37.5665, 126.9780, accuracy_m=20)   # 서울시청
    assert r['status'] == 'rejected' and r['zone_id'] is None
    assert r['nearest_zone'] in ZONE_POINTS and '구역 밖' in r['reason']


def test_poor_accuracy_is_rejected():
    r = check_location(37.654, 126.680, accuracy_m=800)
    assert r['status'] == 'rejected' and '정확도' in r['reason']


def test_missing_or_bad_coords():
    assert check_location(None, None)['reason'] == '위치 없음'
    assert check_location(95, 0)['reason'] == '좌표 범위 밖'


def test_observation_carries_location_fields():
    from core.observations import build_observation
    loc = check_location(37.6545, 126.6804, accuracy_m=25)
    o = build_observation('P01', loc['zone_id'], 'outdoor', True, 3, '분뇨와 비슷함', 'k1', location=loc)
    assert o['location_check'] == 'verified' and o['lat'] == 37.654 and o['accuracy_m'] == 25
    o2 = build_observation('P01', 'Z2', 'outdoor', False, None, None, 'k2')
    assert o2['location_check'] == 'unverified' and o2['lat'] is None
