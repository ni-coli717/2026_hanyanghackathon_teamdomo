"""Air-care board integration, checked against SimulatedBoard (mirror of odor_purifier.ino)."""
import time

import pandas as pd
import pytest

from core import analysis_service as service
from core.automation import decide, make_rule
from core.device import AppDeviceLink, SIM_PORT, basis_key, device_report
from core.observations import LocalObservations, legacy_reports
from odor_model.device_service import push_prediction


def wait(cond, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


def row_at(at, zone='Z2'):
    w = pd.read_csv('data/provided/weather.csv')
    w = w[w.weather_at == at]
    res = service.predict_windows(pd.DataFrame(dict(window_start=w.weather_at, wind_from_deg=w.wd, wind_speed=w.ws,
                                                    humidity_pct=w.humidity, temperature_c=w.temp, rain_1h_mm=w.rain,
                                                    basis=w.weather_basis)))
    if set(res.status) == {'추정 보류'}:
        pytest.skip('model unavailable in this environment')
    return res[res.app_zone_id == zone].iloc[0].to_dict()


@pytest.fixture
def link(tmp_path):
    repo = LocalObservations(tmp_path / 'resident.db')
    l = AppDeviceLink(repo=repo)
    assert l.connect(SIM_PORT)
    yield l
    l.disconnect()


def test_rule_hysteresis():
    rule = {'start_level': '높음', 'start_count': 2, 'stop_level': '낮음', 'stop_count': 2}
    assert decide(['낮음', '높음', '높음'], rule)[0] == 'ON'
    assert decide(['높음', '높음', '낮음'], rule)[0] == 'ON'          # one low does not switch off
    assert decide(['높음', '높음', '낮음', '낮음'], rule)[0] == 'OFF'
    assert decide(['높음', None], rule) == ('HOLD', '판단 보류')       # 자료 없음 is not 냄새 없음
    assert decide(['높음', '높음'], rule, enabled=False) == ('HOLD', '사용 안 함')


def test_no_device_is_honest():
    l = AppDeviceLink()
    assert l.status == '연결된 기기 없음' and not l.connected
    out = push_prediction(l, make_rule(), {'status': '예비 추정', 'level': '높음', 'wind_from_sector': '동북동'}, 'synthetic_climatology')
    assert out['sent'] is None and out['connected'] is False


def test_low_estimate_sends_off_and_standby(link):
    sent = push_prediction(link, make_rule(), row_at('2026-09-14 12:30:00'), 'synthetic_climatology')['sent']
    assert sent == 'ODOR|WNW|LOW|OFF|DEMO'
    assert wait(lambda: (link.last_ack or '').startswith('ACK|LOW|OFF'))   # not the first PING ack (HOLD)
    assert link.board.lcd()[1] == ['AIRFLOW: WNW', 'SYSTEM: STANDBY']
    assert link.board.leds() == {'green': False, 'red': True, 'fan': False}


def test_two_highs_turn_fan_on(link):
    rule, row = make_rule(), row_at('2026-09-15 22:00:00')
    assert row['level'] == '높음'
    assert push_prediction(link, rule, row, 'synthetic_climatology')['sent'] == 'ODOR|ENE|HIGH|OFF|DEMO'
    assert push_prediction(link, rule, row, 'synthetic_climatology')['sent'] == 'ODOR|ENE|HIGH|ON|DEMO'
    assert wait(lambda: link.device_fan is True)
    assert link.board.lcd()[1] == ['ODOR INFLOW EST', 'PURIFYING AIR...']
    assert link.board.leds()['green']


def test_manual_override_is_not_overwritten(link):
    rule, row = make_rule(), row_at('2026-09-15 22:00:00')
    push_prediction(link, rule, row, 'synthetic_climatology'); push_prediction(link, rule, row, 'synthetic_climatology')
    assert wait(lambda: link.device_fan is True)
    link.board.press_short()                                   # resident turns it off on the board
    assert wait(lambda: link.mode == 'MANUAL' and link.device_fan is False)
    push_prediction(link, rule, row, 'synthetic_climatology')   # auto still says ON
    assert wait(lambda: link.last_ack and link.last_ack.endswith('|MANUAL'))
    assert link.board.fan_on is False and link.device_fan is False
    link.set_auto()
    assert wait(lambda: link.board.manual is False)


def test_long_press_saves_spontaneous_report(link, tmp_path):
    link.report_zone = 'Z2'
    link.board.press_long()
    assert wait(lambda: link.reports_saved == 1)
    rows = link.repo.get_recent_observations()
    assert len(rows) == 1
    r = rows[0]
    assert (r['collection_mode'], r['record_origin'], r['odor_detected'], r['intensity'], r['zone_id']) == \
           ('spontaneous', 'device_button', True, None, 'Z2')
    scheduled = legacy_reports(rows).query("report_mode == 'scheduled'")
    assert scheduled.empty                                     # never enters the scheduled detection rate
    assert link.board.lcd()[0] == ['REPORT SENT', 'THANK YOU']


def test_report_outside_zone_is_not_saved(link):
    link.report_zone = None
    link.board.press_long()
    assert wait(lambda: '관측 구역 밖' in (link.last_error or ''))
    assert link.reports_saved == 0


def test_unplug_shows_disconnect_and_board_times_out(link):
    rule, row = make_rule(), row_at('2026-09-15 22:00:00')
    push_prediction(link, rule, row, 'synthetic_climatology'); push_prediction(link, rule, row, 'synthetic_climatology')
    assert wait(lambda: link.device_fan is True)
    board = link.board
    board.unplug()
    assert wait(lambda: link.status == '연결 끊김')
    assert link.device_fan is None                             # no stale '가동 중' after unplug
    start = board.clock()
    board.clock = lambda: start + 16                           # 15 s board-side timeout
    assert board.lcd()[0] == ['NO SIGNAL', 'CHECK USB LINK'] and board.fan_on is False


def test_basis_key():
    assert basis_key({'kind': 'forecast'}, {'forecast': {'source': 'kma'}}) == 'kma_forecast'
    assert basis_key({'kind': 'forecast'}, {'forecast': {'source': 'csv'}}) == 'forecast_csv'
    assert basis_key({'kind': 'observed', 'basis': '관측'}, {'demo': True}) == 'synthetic_climatology'
    assert basis_key({'kind': 'observed', 'basis': '관측'}, {'demo': False}) == 'observed_public_reference'


def test_device_report_shape():
    r = device_report('Z1')
    assert r['participant_id'] == 'DEVICE' and r['context'] == 'indoor' and r['odor_type'] == '기기 버튼 신고'
