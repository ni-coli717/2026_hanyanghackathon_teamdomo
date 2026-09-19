"""Single entry point for odor_model results.

Map arrows, compass, air-care panel and admin screens all read predict_windows();
no screen computes its own estimate. A missing or unloadable model degrades to
'추정 보류' instead of crashing the app.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

import pandas as pd

from odor_model.features import DEFAULT_GEO, ZONES
from odor_model.predict import predict_rows, read_forecast_csv

ROOT = Path(__file__).resolve().parents[1]
BUNDLED_MODEL = ROOT / 'odor_model/artifacts/odor_model.joblib'
BUNDLED_EVALUATION = ROOT / 'odor_model/artifacts/evaluation.md'
RETRAINED_DIR = ROOT / 'data/models/odor'
SETTINGS_PATH = ROOT / 'data/model_settings.json'
GEO_PATH = ROOT / 'data/geo/model_geo.json'
SAMPLE_FORECAST = ROOT / 'odor_model/sample_forecast.csv'
MODEL_STATUS = '예비 실험·미보정'

DEFAULT_SETTINGS = {
    'active_model': 'bundled',   # 'bundled' 또는 data/models/odor/<run> 이름. 운영자가 명시적으로 선택할 때만 바뀐다.
    'thr_mid': 0.5,              # 보통 이상
    'thr_high': None,            # 높음 이상. None이면 활성 모델의 검증 임계값(번들 0.75)
    'calm_ms': 0.5,              # 이 풍속 미만은 방향 보류
    'align_min': 0.5,            # 정렬 후보 최소 정렬도
    'align_tie': 0.15,           # 상위 두 후보 차이가 이보다 작으면 여러 방향 가능
    'obs_rate_min': 0.25,        # 예측 낮음 + 실제 감지율이 이보다 낮으면 바람 레이어만
    'auto': {'start_level': '높음', 'start_count': 2, 'stop_level': '낮음', 'stop_count': 2},
}
BASIS_LABELS = {
    'observed_public_reference': '관측',
    'estimated_from_adjacent_actuals': '추정',
    'synthetic_climatology': '시연',
    'kma_forecast': '예보',
    'forecast_csv': '시연 예보',
}
TYPE_KEYS = {'축산계 추정': 'livestock', '하수계 추정': 'sewage', '기타/미확인': 'unknown'}
LEVELS = ('낮음', '보통', '높음')


# ------------------------------------------------------------------ settings & geo
def load_settings() -> dict:
    values = json.loads(json.dumps(DEFAULT_SETTINGS))
    try:
        stored = json.loads(SETTINGS_PATH.read_text(encoding='utf-8'))
        values.update({k: v for k, v in stored.items() if k != 'auto'})
        values['auto'].update(stored.get('auto', {}))
    except (OSError, ValueError):
        pass
    return values


def save_settings(values: dict) -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(values, ensure_ascii=False, indent=2), encoding='utf-8')


def load_geo() -> dict:
    try:
        return json.loads(GEO_PATH.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return DEFAULT_GEO


def save_geo(geo: dict) -> None:
    """Persist edited coordinates and keep the map's zone table in sync."""
    GEO_PATH.write_text(json.dumps(geo, ensure_ascii=False, indent=2), encoding='utf-8')
    zones_csv = ROOT / 'data/sample/zones.csv'
    zones = pd.read_csv(zones_csv)
    for info in geo['zones'].values():
        mask = zones.zone_id == info.get('app_zone_id')
        zones.loc[mask, ['rep_lat', 'rep_lon']] = [info['lat'], info['lon']]
    zones.to_csv(zones_csv, index=False, encoding='utf-8-sig')


def app_zone_ids(geo: dict | None = None) -> dict:
    geo = geo or load_geo()
    return {u: info.get('app_zone_id', u) for u, info in geo['zones'].items()}


# ------------------------------------------------------------------ model
def retrained_runs() -> list[str]:
    if not RETRAINED_DIR.exists():
        return []
    return sorted((p.name for p in RETRAINED_DIR.iterdir() if (p / 'odor_model.joblib').exists()), reverse=True)


def model_path(name: str | None = None) -> Path:
    name = name or load_settings()['active_model']
    return BUNDLED_MODEL if name == 'bundled' else RETRAINED_DIR / name / 'odor_model.joblib'


def _smoke_row() -> pd.DataFrame:
    return pd.DataFrame([dict(window_start=pd.Timestamp('2026-09-15 22:00'), wind_from_deg=67.5, wind_speed=1.0,
                              humidity_pct=80.0, temperature_c=20.0, rain_1h_mm=0.0, basis='smoke')])


@lru_cache(maxsize=4)
def _load(path: str, mtime: float, geo_json: str):
    import joblib
    model = joblib.load(path)
    geo = json.loads(geo_json)
    needed = {c[6:] for c in model['feature_columns'] if c.startswith('align_')}
    if needed <= set(geo['candidates']) and set(ZONES) <= set(geo['zones']):
        model = {**model, 'geo': geo}
    predict_rows(_smoke_row(), model)  # a version-incompatible pickle fails here, not in a resident's request
    return model


def load_model(name: str | None = None) -> tuple[dict | None, dict]:
    path = model_path(name)
    info = {'name': name or load_settings()['active_model'], 'path': str(path), 'status': MODEL_STATUS}
    if not path.exists():
        return None, {**info, 'ok': False, 'reason': '모델 없음'}
    try:
        model = _load(str(path), path.stat().st_mtime, json.dumps(load_geo(), ensure_ascii=False, sort_keys=True))
    except Exception as exc:  # noqa: BLE001 - any unpickling/version error means '추정 보류'
        return None, {**info, 'ok': False, 'reason': f'모델 로딩 실패 · {type(exc).__name__}'}
    return model, {**info, 'ok': True, 'reason': '', 'trained_on': model.get('trained_on', ''),
                   'thr_valid': float(model.get('thr_valid', 0.75))}


# ------------------------------------------------------------------ inputs
def weather_inputs(weather: pd.DataFrame, times) -> pd.DataFrame:
    """App weather table -> model input rows, one per window time (latest record within the hour before)."""
    rows = []
    wx = weather.copy()
    if not wx.empty:
        wx['weather_at'] = pd.to_datetime(wx.weather_at)
        if 'quality_flag' in wx:
            wx = wx[wx.quality_flag.fillna('ok') == 'ok']
        wx = wx.sort_values('weather_at')
    for time in times:
        time = pd.Timestamp(time)
        near = wx[(wx.weather_at <= time) & (wx.weather_at >= time - pd.Timedelta(hours=1))] if not wx.empty else wx
        if near.empty:
            rows.append(dict(window_start=time, basis='missing'))
            continue
        r = near.iloc[-1]
        rows.append(dict(window_start=time, wind_from_deg=r.get('wd'), wind_speed=r.get('ws'),
                         humidity_pct=r.get('humidity'), temperature_c=r.get('temp'),
                         rain_1h_mm=r.get('rain') if pd.notna(r.get('rain')) else 0.0,
                         basis=r.get('weather_basis') if pd.notna(r.get('weather_basis', None)) else 'unknown'))
    return pd.DataFrame(rows)


def _candidates(text) -> list[dict]:
    """'이름(유형,0.78); …' -> names and types only. Scores never reach resident screens."""
    return [{'name': n.strip(), 'type': t} for n, t, _ in re.findall(r'([^;]+?)\(([^,()]+),([\d.]+)\)', str(text or ''))]


def _held(weather_df: pd.DataFrame, reason: str) -> pd.DataFrame:
    geo = load_geo()
    out = []
    for _, r in weather_df.iterrows():
        for z in ZONES:
            out.append(dict(window_start=pd.Timestamp(r.window_start), zone_id=z, zone_name=geo['zones'][z]['name'],
                            basis=r.get('basis', 'input'), status='추정 보류', reason=reason,
                            wind_from_deg=r.get('wind_from_deg'), wind_speed=r.get('wind_speed')))
    return pd.DataFrame(out)


def predict_windows(weather_df: pd.DataFrame, model_name: str | None = None) -> pd.DataFrame:
    """Shared estimate for every screen. Columns follow odor_model.predict.predict_rows plus
    app_zone_id, model_status, basis_label, type_key, candidates."""
    if weather_df is None or weather_df.empty:
        return pd.DataFrame()
    settings = load_settings()
    model, info = load_model(model_name)
    if model is None:
        res = _held(weather_df, info['reason'])
    else:
        try:
            res = predict_rows(weather_df, model, {k: v for k, v in settings.items() if v is not None})
        except Exception as exc:  # noqa: BLE001
            res = _held(weather_df, f'모델 오류 · {type(exc).__name__}')
    ids = app_zone_ids()
    res['app_zone_id'] = res.zone_id.map(ids)
    res['model_status'] = MODEL_STATUS
    res['basis_label'] = res.basis.map(BASIS_LABELS).fillna('미확인')
    res['type_key'] = res.get('type_top', pd.Series(index=res.index, dtype=object)).map(TYPE_KEYS).fillna('unknown')
    res['candidates'] = res.get('aligned_candidates', pd.Series('', index=res.index)).map(_candidates)
    return res


# ------------------------------------------------------------------ forecast
def forecast_inputs(now=None) -> tuple[pd.DataFrame, dict]:
    """KMA short-term forecast when a key is configured; otherwise the sample CSV, labelled '시연 예보'.
    A failed KMA call is reported in meta['error'], never hidden."""
    from .config import nested_setting, now_kst
    now = now or now_kst()
    key = nested_setting('kma', 'service_key', '')
    error = ''
    if key:
        try:
            from odor_model.predict import fetch_kma_forecast
            nx, ny = int(nested_setting('kma', 'nx', '55') or 55), int(nested_setting('kma', 'ny', '128') or 128)
            rows = fetch_kma_forecast(key, nx, ny, base=now.replace(tzinfo=None))
            rows = rows[rows.window_start >= pd.Timestamp(now.replace(tzinfo=None)).floor('h')]
            if not rows.empty:
                return rows.reset_index(drop=True), {'source': 'kma', 'label': '예보', 'issued': rows.source.iloc[0], 'error': ''}
            error = '기상청 예보 없음'
        except Exception as exc:  # noqa: BLE001
            error = f'기상청 예보 연결 실패 · {type(exc).__name__}'
    try:
        rows = read_forecast_csv(str(SAMPLE_FORECAST))
    except Exception as exc:  # noqa: BLE001
        return pd.DataFrame(), {'source': 'none', 'label': '예보 없음', 'issued': '', 'error': error or f'예보 파일 오류 · {type(exc).__name__}'}
    rows['source'] = '시연 예보 파일'
    return rows, {'source': 'csv', 'label': '시연 예보', 'issued': '', 'error': error}


# ------------------------------------------------------------------ shared display rules
def arrow_kind(pred: dict | None, wind: dict | None, observed_rate, settings: dict | None = None) -> str:
    """odor: colored inflow estimate · wind: neutral wind layer · calm: 방향 보류 · none: 자료 없음."""
    settings = settings or load_settings()
    if not wind:
        return 'none'
    if wind['speed'] < float(settings['calm_ms']) or (pred and pred.get('direction') == '방향 보류(약풍)'):
        return 'calm'
    if not pred or pred.get('status') != '예비 추정':
        return 'wind'
    if pred.get('level') == '낮음' and (observed_rate is None or observed_rate < float(settings['obs_rate_min'])):
        return 'wind'
    return 'odor'


def compact(row) -> dict:
    """Prediction row -> browser payload. No p values or probabilities."""
    if row is None:
        return None
    # basis and model status live once per frame / payload to keep the payload small.
    if row['status'] != '예비 추정':
        return {'status': row['status'], 'reason': row.get('reason', '')}
    pred = {'status': row['status'], 'level': row['level'], 'from_sector': row['wind_from_sector'],
            'direction': row['direction_status'], 'type': row['type_key'], 'type_label': row['type_top']}
    if row['candidates']:
        pred['candidates'] = row['candidates']
    return pred


def day_phrase(moment, now) -> str:
    moment, now = pd.Timestamp(moment), pd.Timestamp(now)
    days = (moment.normalize() - now.normalize()).days
    day = {0: '오늘', 1: '내일', 2: '모레'}.get(days, moment.strftime('%m.%d'))
    part = '새벽' if moment.hour < 6 else '오전' if moment.hour < 12 else '오후' if moment.hour < 18 else '밤'
    return f'{day} {part}'
