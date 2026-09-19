import json

import pandas as pd
import pytest

from core import analysis_service as service
from core.automation import decide, get_auto_action
from core.map_data import prepare_payload
from core.public_data import dashboard, window_slots


@pytest.fixture(scope='module')
def demo():
    reports, weather, zones, _, windows, _ = dashboard('demo')
    slots = window_slots('demo')
    model, info = service.load_model()
    if model is None:
        pytest.skip(f"model unavailable in this environment: {info['reason']} (requirements pin scikit-learn==1.8.0)")
    predictions = service.predict_windows(service.weather_inputs(weather, slots.window_start))
    rows, meta = service.forecast_inputs()
    ahead = service.predict_windows(rows)
    payload = prepare_payload(reports, weather, zones, windows, True, slots=slots, predictions=predictions,
                              forecast=meta, forecast_predictions=ahead, model_info=info)
    return dict(payload=payload, predictions=predictions, slots=slots, weather=weather, zones=zones,
                reports=reports, windows=windows)


def frame(payload, at):
    return next(f for f in payload['frames'] if f['at'].startswith(at))


def test_slider_uses_workbook_windows_then_forecast(demo):
    p, slots = demo['payload'], demo['slots']
    assert len(slots) == 364
    observed = [f for f in p['frames'] if f['kind'] == 'observed']
    assert len(observed) == 364 and p['latest_index'] == 363
    assert observed[0]['at'].startswith('2026-06-18T07:30') and observed[-1]['at'].startswith('2026-09-16T22:00')
    forecast = [f for f in p['frames'] if f['kind'] == 'forecast']
    assert forecast and all(f['basis'] == '시연 예보' for f in forecast)
    assert all(pd.Timestamp(f['at']) > pd.Timestamp(observed[-1]['at']) for f in forecast)


def test_weather_basis_preserved(demo):
    labels = {f['basis'] for f in demo['payload']['frames'] if f['kind'] == 'observed'}
    assert labels == {'관측', '추정', '시연'}
    assert frame(demo['payload'], '2026-09-15T22:00')['basis'] == '관측'
    assert frame(demo['payload'], '2026-06-18T07:30')['basis'] == '시연'


def test_calm_group_detection_hides_arrow(demo):
    f = frame(demo['payload'], '2026-09-11T22:00')
    assert f['wind']['speed'] == pytest.approx(0.2)
    z2 = f['zones']['Z2']
    assert z2['status'] == '집단 감지'
    assert z2['pred']['direction'] == '방향 보류(약풍)'
    assert all(z['arrow'] == 'calm' for z in f['zones'].values())


def test_ene_wind_draws_wsw_livestock_arrow(demo):
    f = frame(demo['payload'], '2026-09-15T22:00')
    assert f['wind']['from'] == 67.5 and f['wind']['to'] == 247.5
    z2 = f['zones']['Z2']
    assert z2['arrow'] == 'odor' and z2['pred']['type'] == 'livestock' and z2['pred']['from_sector'] == '동북동'
    assert service.load_geo()['candidates']['C1']['name'] in json.dumps(z2['pred'], ensure_ascii=False)


def test_low_estimate_without_detection_is_wind_only(demo):
    f = frame(demo['payload'], '2026-09-14T12:30')
    assert f['window_rate'] == 0
    assert all(z['pred']['level'] == '낮음' and z['arrow'] == 'wind' for z in f['zones'].values())


def test_no_probabilities_reach_browser(demo):
    text = json.dumps(demo['payload'], ensure_ascii=False)
    for word in ('p_detect', 'type_probs', 'align_score', 'observer_code', '%'):
        assert word not in text
    assert all(',0.' not in c['name'] for f in demo['payload']['frames'] for z in f['zones'].values()
               for c in (z['pred'] or {}).get('candidates', []))


def test_missing_model_holds_estimates(demo, monkeypatch, tmp_path):
    monkeypatch.setattr(service, 'model_path', lambda name=None: tmp_path / 'missing.joblib')
    held = service.predict_windows(service.weather_inputs(demo['weather'], demo['slots'].window_start[-3:]))
    assert set(held.status) == {'추정 보류'} and set(held.reason) == {'모델 없음'}
    _, info = service.load_model()
    p = prepare_payload(demo['reports'], demo['weather'], demo['zones'], demo['windows'], True,
                        slots=demo['slots'].tail(3), predictions=held, model_info=info)
    z = p['frames'][-1]['zones']['Z2']
    assert z['pred']['status'] == '추정 보류' and z['arrow'] in ('wind', 'calm')
    assert p['model']['ok'] is False and '추정 보류' in p['info']['추정 모델']


def test_corrupt_model_file_does_not_crash(monkeypatch, tmp_path):
    bad = tmp_path / 'odor_model.joblib'
    bad.write_bytes(b'not a pickle')
    monkeypatch.setattr(service, 'model_path', lambda name=None: bad)
    model, info = service.load_model()
    assert model is None and info['reason'].startswith('모델 로딩 실패')


def test_failed_kma_call_falls_back_visibly(monkeypatch):
    import core.config as config
    import odor_model.predict as predict
    monkeypatch.setattr(config, 'nested_setting', lambda section, key, default='': 'KEY' if key == 'service_key' else default)
    monkeypatch.setattr(predict, 'fetch_kma_forecast', lambda *a, **k: (_ for _ in ()).throw(ConnectionError()))
    rows, meta = service.forecast_inputs()
    assert not rows.empty and meta['source'] == 'csv' and meta['label'] == '시연 예보'
    assert '기상청 예보 연결 실패' in meta['error']
    assert set(rows.basis) == {'forecast_csv'}


def test_hysteresis_rule():
    rule = {'start_level': '높음', 'start_count': 2, 'stop_level': '낮음', 'stop_count': 2}
    assert decide(['낮음', '높음', '높음'], rule)[0] == 'ON'
    assert decide(['높음', '높음', '낮음'], rule)[0] == 'ON'
    assert decide(['높음', '높음', '낮음', '낮음'], rule)[0] == 'OFF'
    assert decide(['높음', None], rule)[0] == 'HOLD'
    assert decide(['높음', '높음'], rule, enabled=False) == ('HOLD', '사용 안 함')


def test_get_auto_action_interface(demo):
    for zone in ('Z1', 'U01'):
        assert get_auto_action(zone, demo['predictions']) in ('ON', 'OFF', 'HOLD')


def test_outlook_phrase(demo):
    text = demo['payload']['outlook']['Z2']
    assert text.startswith('09.16 22:00 ') and '(예보)' in text


def test_direction_rule_matches_ne_example():
    rows = pd.DataFrame([dict(window_start=pd.Timestamp('2026-09-15 22:00'), wind_from_deg=45.0, wind_speed=2.0,
                              humidity_pct=70.0, temperature_c=20.0, rain_1h_mm=0.0, basis='observed_public_reference')])
    res = service.predict_windows(rows)
    if set(res.status) == {'추정 보류'}:
        pytest.skip('model unavailable')
    assert set(res.move_to_deg) == {225.0} and set(res.wind_from_sector) == {'북동'}
