"""Fetch pinned Leaflet assets and extract the published KOSTAT Gimpo boundary.

Run only when updating vendored assets, not during app startup.
"""
import json
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[1]
vendor = ROOT / 'components/odor_map/vendor'
vendor.mkdir(parents=True, exist_ok=True)
for name, url in {
    'leaflet.js': 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js',
    'leaflet.css': 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css',
    'LICENSE': 'https://raw.githubusercontent.com/Leaflet/Leaflet/v1.9.4/LICENSE',
}.items():
    response = requests.get(url, timeout=40)
    response.raise_for_status()
    (vendor / name).write_bytes(response.content)
url = 'https://raw.githubusercontent.com/southkorea/southkorea-maps/master/kostat/2018/json/skorea-municipalities-2018-geo.json'
response = requests.get(url, timeout=60)
response.raise_for_status()
features = [f for f in response.json()['features'] if f['properties'].get('name') == '김포시']
assert len(features) == 1, 'Expected exactly one Gimpo boundary'
output = ROOT / 'data/geo'
output.mkdir(parents=True, exist_ok=True)
(output / 'gimpo.geojson').write_text(json.dumps({'type':'FeatureCollection','features':features}, ensure_ascii=False), encoding='utf-8')
(output / 'provenance.json').write_text(json.dumps({
    'source': url, 'publisher':'southkorea/southkorea-maps · KOSTAT',
    'year':2018, 'license':'KOSTAT: Free to share or remix (upstream README)',
    'notice':'2018 공개 행정경계 · 최신 법정 경계 아님',
}, ensure_ascii=False, indent=2), encoding='utf-8')
print('Leaflet 1.9.4 and Gimpo boundary downloaded', features[0]['properties'])
