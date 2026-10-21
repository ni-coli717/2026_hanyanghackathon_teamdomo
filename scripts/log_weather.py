"""기상청 실황·초단기예보·단기예보를 받아 저장소(weather_fcst)에 누적. Windows 작업 스케줄러로 매시 실행.
사용: python -m scripts.log_weather          (.streamlit/secrets.toml [kma] 사용)
"""
from __future__ import annotations
import datetime as dt, re
from pathlib import Path
from zoneinfo import ZoneInfo
import requests
from core.sensor_store import open_sensor_store

ROOT = Path(__file__).resolve().parents[1]
BASE = 'https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0'
KST = ZoneInfo('Asia/Seoul')


def load_kma():
    txt = (ROOT / '.streamlit' / 'secrets.toml').read_text(encoding='utf-8').split('[kma]', 1)[1]
    return (re.search(r'service_key\s*=\s*"([^"]+)"', txt).group(1), int(re.search(r'nx\s*=\s*(\d+)', txt).group(1)), int(re.search(r'ny\s*=\s*(\d+)', txt).group(1)))


def call(path, key, **p):
    r = requests.get(f'{BASE}/{path}', params=dict(serviceKey=key, pageNo=1, numOfRows=1000, dataType='JSON', **p), timeout=20)
    js = r.json(); return js['response']['body']['items']['item']


def _num(v):
    try: return float(str(v).replace('mm', '').replace('미만', '').replace('강수없음', '0').strip())
    except Exception: return None


def rows_from(items, kind, nx, ny, base_dt):
    piv = {}
    for it in items:
        if kind == 'ncst':
            k = base_dt; piv.setdefault(k, {})[it['category']] = it['obsrValue']
        else:
            k = dt.datetime.strptime(it['fcstDate'] + it['fcstTime'], '%Y%m%d%H%M').replace(tzinfo=KST)
            piv.setdefault(k, {})[it['category']] = it['fcstValue']
    out = []
    for fdt, c in piv.items():
        out.append(dict(kind=kind, nx=nx, ny=ny, base_dt=base_dt.isoformat(), fcst_dt=fdt.isoformat(),
                        wind_dir_deg=_num(c.get('VEC')), wind_speed_ms=_num(c.get('WSD')),
                        temperature_c=_num(c.get('T1H', c.get('TMP'))), humidity_pct=_num(c.get('REH')),
                        rain_1h_mm=_num(c.get('RN1', c.get('PCP'))), pop_pct=_num(c.get('POP')), sky=c.get('SKY'), pty=c.get('PTY')))
    return out


def main():
    key, nx, ny = load_kma(); now = dt.datetime.now(KST); store, label = open_sensor_store(); total = 0
    bt = (now - dt.timedelta(minutes=45)).replace(minute=0, second=0, microsecond=0)
    total += store.insert_weather(rows_from(call('getUltraSrtNcst', key, base_date=bt.strftime('%Y%m%d'), base_time=bt.strftime('%H00'), nx=nx, ny=ny), 'ncst', nx, ny, bt))
    bu = (now - dt.timedelta(minutes=50)).replace(minute=30, second=0, microsecond=0)
    total += store.insert_weather(rows_from(call('getUltraSrtFcst', key, base_date=bu.strftime('%Y%m%d'), base_time=bu.strftime('%H30'), nx=nx, ny=ny), 'ultra_fcst', nx, ny, bu))
    hours = [2, 5, 8, 11, 14, 17, 20, 23]; h = max([x for x in hours if x <= now.hour - (1 if now.minute < 10 else 0)] or [23])
    bv = (now if h <= now.hour else now - dt.timedelta(days=1)).replace(hour=h, minute=0, second=0, microsecond=0)
    total += store.insert_weather(rows_from(call('getVilageFcst', key, base_date=bv.strftime('%Y%m%d'), base_time=bv.strftime('%H00'), nx=nx, ny=ny), 'vilage_fcst', nx, ny, bv))
    print(f'{now:%Y-%m-%d %H:%M} {label}: {total}행 저장')


if __name__ == '__main__':
    main()
