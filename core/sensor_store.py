"""센서 자료 저장소: Supabase REST(service_role, 서버 전용) 또는 로컬 SQLite(개발·시뮬레이터).
노드는 anon 키로 INSERT 만 하고, 앱·집계는 여기서 service_role 로 읽는다. 키는 화면·URL 에 내보내지 않는다."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd
import requests

from .config import KST, nested_setting, setting

SITES = {'S1': '운양 북측(한강변)', 'S2': '운양 남측(모담산 인근)', 'S3': '하성면'}
READING_COLS = ['site_id', 'ts', 'adc_mq137', 'voc_index', 'humidity_pct', 'temperature_c', 'heater_sec', 'rssi', 'fw_version']
INDEX_COLS = ['site_id', 'ts', 'n', 'mq_rs_mean', 'mq_rs_min', 'voc_mean', 'voc_max', 'humidity_pct', 'temperature_c',
              'mq_baseline', 'mq_index', 'voc_baseline', 'voc_index_rel', 'thr_mq', 'thr_voc', 'event_mq', 'event_voc', 'event_grade', 'quality_flag']


def _ts(df: pd.DataFrame, col='ts') -> pd.DataFrame:
    if len(df):
        s = pd.to_datetime(df[col], utc=True, errors='coerce')
        df[col] = s.dt.tz_convert(KST)
    return df


class LocalSensorStore:
    """SQLite 파일 하나. 시뮬레이터·테스트·오프라인 분석용."""

    def __init__(self, path):
        self.path = Path(path); self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as c:
            c.execute('CREATE TABLE IF NOT EXISTS sensor_readings (site_id TEXT, ts TEXT, adc_mq137 INT, voc_index INT, humidity_pct REAL, temperature_c REAL, heater_sec INT, rssi INT, fw_version TEXT, PRIMARY KEY(site_id, ts))')
            c.execute('CREATE TABLE IF NOT EXISTS sensor_index_10min (site_id TEXT, ts TEXT, n INT, mq_rs_mean REAL, mq_rs_min REAL, voc_mean REAL, voc_max REAL, humidity_pct REAL, temperature_c REAL, mq_baseline REAL, mq_index REAL, voc_baseline REAL, voc_index_rel REAL, thr_mq REAL, thr_voc REAL, event_mq INT, event_voc INT, event_grade TEXT, quality_flag TEXT, PRIMARY KEY(site_id, ts))')
            c.execute('CREATE TABLE IF NOT EXISTS site_events (id INTEGER PRIMARY KEY AUTOINCREMENT, site_id TEXT, start_ts TEXT, end_ts TEXT, event_type TEXT, note TEXT)')
            c.execute('CREATE TABLE IF NOT EXISTS sensor_calibration (site_id TEXT PRIMARY KEY, run_id TEXT, mq_gain REAL, mq_offset REAL, voc_gain REAL, voc_offset REAL, rh_coef REAL, temp_coef REAL, note TEXT)')
            c.execute('CREATE TABLE IF NOT EXISTS weather_fcst (kind TEXT, nx INT, ny INT, base_dt TEXT, fcst_dt TEXT, wind_dir_deg REAL, wind_speed_ms REAL, temperature_c REAL, humidity_pct REAL, rain_1h_mm REAL, pop_pct REAL, sky TEXT, pty TEXT, PRIMARY KEY(kind,nx,ny,base_dt,fcst_dt))')

    def insert_readings(self, rows: list[dict]) -> int:
        with sqlite3.connect(self.path, timeout=30) as c:
            cur = c.executemany('INSERT OR IGNORE INTO sensor_readings VALUES (?,?,?,?,?,?,?,?,?)',
                                [tuple(r.get(k) for k in READING_COLS) for r in rows])
            return cur.rowcount

    def readings(self, since=None, site_id=None) -> pd.DataFrame:
        q, p = 'SELECT * FROM sensor_readings WHERE 1=1', []
        if since is not None: q += ' AND ts >= ?'; p.append(pd.Timestamp(since).isoformat())
        if site_id: q += ' AND site_id = ?'; p.append(site_id)
        with sqlite3.connect(self.path) as c:
            return _ts(pd.read_sql(q + ' ORDER BY ts', c, params=p))

    def upsert_index(self, df: pd.DataFrame) -> int:
        if df.empty: return 0
        out = df.copy(); out['ts'] = out['ts'].map(lambda t: pd.Timestamp(t).isoformat())
        with sqlite3.connect(self.path, timeout=30) as c:
            cur = c.executemany('INSERT OR REPLACE INTO sensor_index_10min VALUES (' + ','.join('?' * len(INDEX_COLS)) + ')',
                                [tuple(None if pd.isna(v) else (int(v) if isinstance(v, (bool,)) else v) for v in row) for row in out[INDEX_COLS].itertuples(index=False)])
            return cur.rowcount

    def index(self, since=None, site_id=None) -> pd.DataFrame:
        q, p = 'SELECT * FROM sensor_index_10min WHERE 1=1', []
        if since is not None: q += ' AND ts >= ?'; p.append(pd.Timestamp(since).isoformat())
        if site_id: q += ' AND site_id = ?'; p.append(site_id)
        with sqlite3.connect(self.path) as c:
            df = _ts(pd.read_sql(q + ' ORDER BY ts', c, params=p))
        for col in ('event_mq', 'event_voc'):
            if col in df: df[col] = df[col].astype('boolean')
        return df

    def events(self) -> pd.DataFrame:
        with sqlite3.connect(self.path) as c:
            df = pd.read_sql('SELECT * FROM site_events', c)
        return _ts(_ts(df, 'start_ts'), 'end_ts') if len(df) else df

    def add_event(self, site_id, start_ts, end_ts, event_type, note=''):
        with sqlite3.connect(self.path, timeout=30) as c:
            c.execute('INSERT INTO site_events(site_id,start_ts,end_ts,event_type,note) VALUES (?,?,?,?,?)',
                      (site_id, pd.Timestamp(start_ts).isoformat(), pd.Timestamp(end_ts).isoformat() if end_ts is not None else None, event_type, note))

    def calibration(self) -> pd.DataFrame:
        with sqlite3.connect(self.path) as c:
            return pd.read_sql('SELECT * FROM sensor_calibration', c)

    def set_calibration(self, site_id, **kw):
        cols = ['run_id', 'mq_gain', 'mq_offset', 'voc_gain', 'voc_offset', 'rh_coef', 'temp_coef', 'note']
        vals = [kw.get(k, {'mq_gain': 1, 'voc_gain': 1}.get(k, 0 if k not in ('run_id', 'note') else '')) for k in cols]
        with sqlite3.connect(self.path, timeout=30) as c:
            c.execute('INSERT OR REPLACE INTO sensor_calibration VALUES (?,?,?,?,?,?,?,?,?)', (site_id, *vals))

    def insert_weather(self, rows: list[dict]) -> int:
        cols = ['kind', 'nx', 'ny', 'base_dt', 'fcst_dt', 'wind_dir_deg', 'wind_speed_ms', 'temperature_c', 'humidity_pct', 'rain_1h_mm', 'pop_pct', 'sky', 'pty']
        with sqlite3.connect(self.path, timeout=30) as c:
            return c.executemany('INSERT OR IGNORE INTO weather_fcst VALUES (' + ','.join('?' * len(cols)) + ')',
                                 [tuple(r.get(k) for k in cols) for r in rows]).rowcount

    def weather(self, kind=None, since=None) -> pd.DataFrame:
        q, p = 'SELECT * FROM weather_fcst WHERE 1=1', []
        if kind: q += ' AND kind = ?'; p.append(kind)
        if since is not None: q += ' AND fcst_dt >= ?'; p.append(pd.Timestamp(since).isoformat())
        with sqlite3.connect(self.path) as c:
            df = pd.read_sql(q + ' ORDER BY base_dt, fcst_dt', c, params=p)
        return _ts(_ts(df, 'base_dt'), 'fcst_dt') if len(df) else df


class SharedSensorStore:
    """Supabase PostgREST. service_role 키는 서버 프로세스에서만 쓴다."""

    def __init__(self, url, key):
        if not url.startswith('https://') or not key:
            raise ValueError('database.url / database.key 설정이 필요합니다.')
        self.base = url.rstrip('/') + '/rest/v1/'
        self.h = {'apikey': key, 'Authorization': f'Bearer {key}'}

    def _get(self, table, params):
        rows, start = [], 0
        while True:
            r = requests.get(self.base + table, headers={**self.h, 'Range': f'{start}-{start + 999}'}, params=params, timeout=30)
            r.raise_for_status(); chunk = r.json(); rows += chunk
            if len(chunk) < 1000: return pd.DataFrame(rows)
            start += 1000

    def _post(self, table, rows, prefer):
        if not rows: return 0
        r = requests.post(self.base + table, headers={**self.h, 'Content-Type': 'application/json', 'Prefer': prefer}, json=rows, timeout=30)
        r.raise_for_status(); return len(rows)

    @staticmethod
    def _json(df: pd.DataFrame, cols):
        out = df[cols].copy()
        for c in out.columns:
            if pd.api.types.is_datetime64_any_dtype(out[c]): out[c] = out[c].map(lambda t: pd.Timestamp(t).isoformat())
        return [{k: (None if (not isinstance(v, str) and pd.isna(v)) else (bool(v) if isinstance(v, (bool,)) else v)) for k, v in rec.items()} for rec in out.to_dict('records')]

    def insert_readings(self, rows):
        return self._post('sensor_readings', rows, 'resolution=ignore-duplicates,return=minimal')

    def readings(self, since=None, site_id=None):
        p = {'select': '*', 'order': 'ts.asc'}
        if since is not None: p['ts'] = f'gte.{pd.Timestamp(since).isoformat()}'
        if site_id: p['site_id'] = f'eq.{site_id}'
        return _ts(self._get('sensor_readings', p))

    def upsert_index(self, df):
        return self._post('sensor_index_10min', self._json(df, INDEX_COLS), 'resolution=merge-duplicates,return=minimal')

    def index(self, since=None, site_id=None):
        p = {'select': '*', 'order': 'ts.asc'}
        if since is not None: p['ts'] = f'gte.{pd.Timestamp(since).isoformat()}'
        if site_id: p['site_id'] = f'eq.{site_id}'
        return _ts(self._get('sensor_index_10min', p))

    def events(self):
        df = self._get('site_events', {'select': '*'})
        return _ts(_ts(df, 'start_ts'), 'end_ts') if len(df) else df

    def add_event(self, site_id, start_ts, end_ts, event_type, note=''):
        self._post('site_events', [dict(site_id=site_id, start_ts=pd.Timestamp(start_ts).isoformat(),
                                        end_ts=pd.Timestamp(end_ts).isoformat() if end_ts is not None else None,
                                        event_type=event_type, note=note)], 'return=minimal')

    def calibration(self):
        return self._get('sensor_calibration', {'select': '*'})

    def set_calibration(self, site_id, **kw):
        self._post('sensor_calibration', [dict(site_id=site_id, **kw)], 'resolution=merge-duplicates,return=minimal')

    def insert_weather(self, rows):
        return self._post('weather_fcst', rows, 'resolution=ignore-duplicates,return=minimal')

    def weather(self, kind=None, since=None):
        p = {'select': '*', 'order': 'base_dt.asc,fcst_dt.asc'}
        if kind: p['kind'] = f'eq.{kind}'
        if since is not None: p['fcst_dt'] = f'gte.{pd.Timestamp(since).isoformat()}'
        df = self._get('weather_fcst', p)
        return _ts(_ts(df, 'base_dt'), 'fcst_dt') if len(df) else df


def open_sensor_store():
    """설정에 database.url/key 가 있으면 Supabase, 없으면 로컬 SQLite(data/sensor.db). (store, label)"""
    url, key = nested_setting('database', 'url'), nested_setting('database', 'key')
    if url and key:
        return SharedSensorStore(url, key), 'Supabase'
    return LocalSensorStore(setting('SENSOR_DB_PATH', 'data/sensor.db')), '로컬 SQLite'
