from pathlib import Path
import pandas as pd
from .observations import legacy_reports, observation_repository
from .features import make_windows, normalize_weather
from .geo import source_geometry

ROOT = Path(__file__).resolve().parents[1]


def dashboard(mode='demo'):
    zones = pd.read_csv(ROOT / 'data/sample/zones.csv')
    sources = pd.read_csv(ROOT / 'data/sample/sources.csv')
    if mode == 'demo':
        reports = pd.read_csv(ROOT / 'data/provided/reports.csv')
        weather = normalize_weather(pd.read_csv(ROOT / 'data/provided/weather.csv'))
    else:
        repo, _ = observation_repository()
        reports = legacy_reports(repo.get_recent_observations() if repo else [])
        # Live weather is never substituted with scenario weather: only what the 15-minute job logged (weather_fcst).
        weather = normalize_weather(weather_history(days=7))
    windows = make_windows(reports, weather, zones, sources)
    return reports, weather, zones, sources, windows, source_geometry(zones, sources)


def weather_history(days=7) -> pd.DataFrame:
    """서버 작업(scripts/plan_devices)이 Supabase weather_fcst 에 누적한 기상청 실황·예보를 지도용 weather 표로 바꾼다.
    같은 시각에 여러 발표가 있으면 실황(ncst) > 초단기(ultra_fcst) > 단기(vilage_fcst) 순으로 가장 가까운 발표를 쓴다.
    저장소가 없거나 읽기에 실패하면 빈 표(지도는 '바람 자료 없음')."""
    empty = pd.DataFrame(columns=['weather_at'])
    try:
        from .sensor_store import open_sensor_store
        from .config import now_kst
        store, _ = open_sensor_store()
        since = (now_kst() - pd.Timedelta(days=days)).replace(minute=0, second=0, microsecond=0)
        df = store.weather(since=since)
    except Exception:  # noqa: BLE001
        return empty
    if df is None or len(df) == 0:
        return empty
    df = df.copy()
    df['fcst_dt'] = pd.to_datetime(df.fcst_dt, utc=True, errors='coerce').dt.tz_convert('Asia/Seoul').dt.tz_localize(None)
    df['base_dt'] = pd.to_datetime(df.base_dt, utc=True, errors='coerce').dt.tz_convert('Asia/Seoul').dt.tz_localize(None)
    df = df.dropna(subset=['fcst_dt', 'base_dt'])
    df = df[df.fcst_dt <= pd.Timestamp(now_kst().replace(tzinfo=None))]          # 지난 시각만: 앞으로의 예보는 forecast_inputs 가 맡는다
    rank = {'ncst': 0, 'ultra_fcst': 1, 'vilage_fcst': 2}
    df['_rank'] = df.kind.map(rank).fillna(3)
    df = df.sort_values(['fcst_dt', '_rank', 'base_dt'], ascending=[True, True, False]).drop_duplicates('fcst_dt', keep='first')
    out = pd.DataFrame({
        'station_id': 'KMA-' + df.nx.astype(str) + '-' + df.ny.astype(str),
        'weather_at': df.fcst_dt,
        'wd': df.wind_dir_deg, 'ws': df.wind_speed_ms, 'temp': df.temperature_c, 'humidity': df.humidity_pct,
        'pressure': None, 'rain': df.rain_1h_mm.fillna(0),
        'quality_flag': 'ok', 'is_sample': 0,
        'weather_basis': df.kind.map({'ncst': 'observed_public_reference'}).fillna('estimated_from_adjacent_actuals'),
    })
    return out.reset_index(drop=True)


def window_slots(mode='demo'):
    """Times the slider may show. Demo: the workbook's 시간창집계 list, never invented times."""
    path = ROOT / 'data/provided/windows.csv'
    if mode == 'demo' and path.exists():
        slots = pd.read_csv(path)
        slots['window_start'] = pd.to_datetime(slots.window_start)
        return slots.sort_values('window_start').reset_index(drop=True)
    return pd.DataFrame(columns=['window_id', 'window_start', 'valid_records', 'detected_records', 'detection_rate', 'weather_basis'])
