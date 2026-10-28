import time
from scripts.device_bridge import plan_to_state


def test_plan_to_state_uses_active_episode():
    off = time.strftime('%Y-%m-%dT%H:%M:%S+09:00', time.localtime(time.time() + 3600))
    info = {'command': 'ON', 'source': 'plan', 'plan': {'state': 'running', 'basis': 'kma', 'episodes': [
        {'on_at': '2026-10-27T11:20:00+09:00', 'off_at': off, 'odor_start': '2026-10-27T12:00:00+09:00', 'peak_level': '높음', 'wind_sector': '북북동'}]}}
    assert plan_to_state(info) == ('북북동', '높음', 'ON', 'kma_forecast')
    # 저장된 action 이 OFF 라도 지금이 가동 구간 안이면 ON, 구간 밖이면 OFF
    assert plan_to_state({**info, 'command': 'OFF'})[2] == 'ON'
    later = {**info, 'command': 'ON', 'plan': {**info['plan'], 'episodes': [{**info['plan']['episodes'][0], 'on_at': off}]}}
    assert plan_to_state(later)[2] == 'OFF'
    assert plan_to_state({'command': 'ON', 'source': 'manual', 'plan': {'state': 'standby', 'episodes': []}})[2] == 'ON'
    assert plan_to_state({'command': 'HOLD', 'plan': None}) == (None, None, 'HOLD', 'kma_forecast')
    assert plan_to_state({'command': 'OFF', 'plan': {'state': 'standby', 'basis': 'demo', 'episodes': []}}) == (None, '낮음', 'OFF', 'forecast_csv')


def test_plan_stale():
    from scripts.device_bridge import plan_stale
    fresh = time.strftime('%Y-%m-%dT%H:%M:%S+09:00', time.localtime(time.time() - 300))
    old = time.strftime('%Y-%m-%dT%H:%M:%S+09:00', time.localtime(time.time() - 3600))
    assert not plan_stale({'plan': {'computed_at': fresh}})
    assert plan_stale({'plan': {'computed_at': old}}) and plan_stale({'plan': None})
    assert not plan_stale({'plan': {'computed_at': old, 'basis': 'demo'}})
