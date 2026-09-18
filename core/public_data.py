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
        # Live weather is never substituted with scenario weather.
        weather = normalize_weather(pd.DataFrame(columns=['weather_at']))
    windows = make_windows(reports, weather, zones, sources)
    return reports, weather, zones, sources, windows, source_geometry(zones, sources)
