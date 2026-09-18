"""Canonical resident records; scenario CSVs are never written through this API."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from uuid import uuid4

import pandas as pd
import requests

from .config import KST, classify_collection_mode, nested_setting, now_kst, setting, observation_window

FIELDS = ['observation_id','participant_id','zone_id','observed_at','received_at',
          'context','odor_detected','intensity','odor_type','collection_mode',
          'prediction_seen','window_id','record_origin','idempotency_key']


def kst(value):
    stamp = pd.Timestamp(value)
    return stamp.tz_localize(KST) if stamp.tzinfo is None else stamp.tz_convert(KST)


def build_observation(participant, zone, context, odor, intensity, odor_type, key, moment=None):
    moment = kst(moment or now_kst())
    if odor not in (True, False, None) or context not in ('outdoor', 'indoor'):
        raise ValueError('관측 항목을 선택하세요.')
    if odor is True and (intensity not in range(1, 6) or not odor_type):
        raise ValueError('강도와 냄새 느낌을 선택하세요.')
    mode, _ = classify_collection_mode(moment.to_pydatetime())
    return dict(observation_id=key, participant_id=participant, zone_id=zone,
                observed_at=moment.isoformat(), received_at=now_kst().isoformat(),
                context=context, odor_detected=odor,
                intensity=intensity if odor is True else (0 if odor is False else None),
                odor_type=odor_type if odor is True else ('없음' if odor is False else '판단 어려움'),
                collection_mode=mode, prediction_seen=False,
                window_id=observation_window(moment.to_pydatetime()).isoformat(),
                record_origin='resident', idempotency_key=key)


def legacy_reports(rows):
    df = pd.DataFrame(rows, columns=FIELDS).rename(columns={
        'observation_id':'report_id', 'participant_id':'observer_code',
        'received_at':'submitted_at', 'context':'environment',
        'odor_detected':'odor', 'collection_mode':'report_mode', 'prediction_seen':'saw_forecast'})
    for col in ('observed_at','submitted_at'):
        df[col] = df[col].map(lambda x: kst(x).tz_localize(None))
    df['window_id'] = df['window_id'].map(lambda x: kst(x).tz_localize(None))
    df['odor'] = df['odor'].map({True:1, False:0})
    return df


class ObservationRepository:
    def save_observation(self, observation):
        raise NotImplementedError

    def get_recent_observations(self):
        raise NotImplementedError

    def get_observations_by_participant(self, participant_id, limit=20):
        return [r for r in self.get_recent_observations() if r['participant_id'] == participant_id][:limit]

    def get_window_aggregates(self, weather, zones, sources):
        from .features import make_windows
        return make_windows(legacy_reports(self.get_recent_observations()), weather, zones, sources)


class LocalObservations(ObservationRepository):
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as conn:
            conn.execute('CREATE TABLE IF NOT EXISTS observations (idempotency_key TEXT PRIMARY KEY, participant_id TEXT NOT NULL, observed_at TEXT NOT NULL, payload TEXT NOT NULL)')

    def save_observation(self, observation):
        with sqlite3.connect(self.path, timeout=30) as conn:
            return conn.execute('INSERT OR IGNORE INTO observations VALUES (?, ?, ?, ?)',
                (observation['idempotency_key'], observation['participant_id'], observation['observed_at'], json.dumps(observation, ensure_ascii=False))).rowcount == 1

    def get_recent_observations(self):
        with sqlite3.connect(self.path) as conn:
            return [json.loads(row[0]) for row in conn.execute('SELECT payload FROM observations ORDER BY observed_at DESC')]

    def get_observations_by_participant(self, participant_id, limit=20):
        with sqlite3.connect(self.path) as conn:
            return [json.loads(row[0]) for row in conn.execute('SELECT payload FROM observations WHERE participant_id=? ORDER BY observed_at DESC LIMIT ?', (participant_id, limit))]


class SharedObservations(ObservationRepository):
    """Supabase REST, invoked on the server only; service role key never reaches UI."""
    def __init__(self, url, key):
        if not url.startswith('https://') or not key:
            raise ValueError('공유 저장소 설정을 확인하세요.')
        self.url = url.rstrip('/') + '/rest/v1/observations'
        self.headers = {'apikey':key, 'Authorization':f'Bearer {key}'}

    def _request(self, method, **kwargs):
        headers = {**self.headers, **kwargs.pop('headers', {})}
        try:
            r = requests.request(method, self.url, headers=headers, timeout=15, **kwargs)
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError):
            raise RuntimeError('서버 연결 실패 — 잠시 후 다시 시도해 주세요.') from None

    def save_observation(self, observation):
        result = self._request('POST', params={'on_conflict':'idempotency_key'}, json=observation,
                              headers={'Prefer':'resolution=ignore-duplicates,return=representation'})
        return bool(result)

    def _read(self, participant=None, limit=None):
        rows, offset = [], 0
        while True:
            size = min(limit or 500, 500)
            params = {'select':','.join(FIELDS), 'order':'observed_at.desc,observation_id.asc', 'limit':size, 'offset':offset}
            if participant: params['participant_id'] = f'eq.{participant}'
            page = self._request('GET', params=params)
            rows.extend(page)
            if limit or len(page) < size: return rows
            offset += size

    def get_recent_observations(self):
        return self._read()

    def get_observations_by_participant(self, participant_id, limit=20):
        return self._read(participant_id, limit)


def observation_repository():
    url, key = nested_setting('database','url'), nested_setting('database','key')
    if url or key:
        return SharedObservations(url, key), '공유 저장소에 기록됩니다.'
    # Explicit opt-in for local disk; cloud with no shared backend must not fake persistence.
    if setting('APP_ENV', 'cloud') == 'local':
        return LocalObservations(setting('OBSERVATION_DB_PATH', 'data/resident.db')), '이 컴퓨터에 기록됩니다.'
    return None, '현재는 조회 시연만 가능합니다. 기록 저장 연결을 준비 중입니다.'
