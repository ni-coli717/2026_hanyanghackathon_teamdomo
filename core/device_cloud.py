"""운영자용 Supabase 기기 함수 호출 (연결 코드 발급, 일정 조회). 키·토큰은 .streamlit/secrets.toml 에서만 읽는다."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import requests

from .config import nested_setting

ROOT = Path(__file__).resolve().parents[1]


def configured() -> bool:
    return nested_setting('database', 'url').startswith('https://') and bool(nested_setting('database', 'anon_key')) \
        and bool(nested_setting('device', 'token'))


def device_id() -> str:
    return nested_setting('device', 'id', 'AP01')


def rpc(name: str, body: dict):
    url = nested_setting('database', 'url').rstrip('/') + f'/rest/v1/rpc/{name}'
    r = requests.post(url, headers={'apikey': nested_setting('database', 'anon_key'), 'Content-Type': 'application/json'},
                      data=json.dumps(body), timeout=15)
    if not r.ok:
        raise RuntimeError(r.json().get('message', r.text) if r.headers.get('content-type', '').startswith('application/json') else r.text)
    return r.json() if r.text else None


def new_pair_code() -> str:
    """기기 대신 운영자가 6자리 연결 코드를 만든다(10분 유효). 기기 LCD 표시가 생기면 기기가 직접 만든다."""
    return rpc('device_new_pair_code', {'p_device': device_id(), 'p_token': nested_setting('device', 'token')})


def current() -> dict:
    return rpc('device_get', {'p_device': device_id(), 'p_token': nested_setting('device', 'token')})


def run_plan(demo: bool) -> tuple[bool, str]:
    """서버 정기 작업과 같은 계산을 지금 한 번 돌린다. demo=True 면 시연 가상 예보."""
    cmd = [sys.executable, '-m', 'scripts.plan_devices'] + (['--demo'] if demo else [])
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=120,
                       env={**__import__('os').environ, 'PYTHONIOENCODING': 'utf-8'})
    return p.returncode == 0, (p.stdout + p.stderr)[-3000:]
