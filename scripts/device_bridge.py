"""공기청정기 브리지 (PC ↔ Uno, ESP32 전까지의 임시 연결).

서버(Supabase)의 device_get 을 주기적으로 읽어 ACTION 을 보드로 보내고, 보드 상태를 device_report 로 올린다.
보드가 버튼으로 수동 켜기·끄기를 하면 서버 모드를 on/off(2시간)로 바꿔 앱에도 '수동'이 보이게 한다.

  python scripts/device_bridge.py                # 포트 자동 감지, 20초 주기
  python scripts/device_bridge.py --port COM3
  python scripts/device_bridge.py --sim          # 보드 없이 시뮬레이터(ODOR_DEVICE_SIM=1)
  python scripts/device_bridge.py --no-plan      # 서버 일정이 오래돼도 이 PC 에서 다시 계산하지 않음

GitHub Actions 의 15분 예약 실행은 자주 늦거나 빠진다. 서버 일정이 PLAN_STALE_MIN 보다 오래되면 이 PC 가
scripts.plan_devices 를 직접 돌려 같은 Supabase 에 써 넣는다(기상청 키는 secrets [kma]).

키·토큰은 .streamlit/secrets.toml [database].url/anon_key, [device].id/token 에서만 읽는다(출력하지 않는다).
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import tomllib
from datetime import datetime
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

LEVEL_KO = {'HIGH': '높음', 'MID': '보통', 'LOW': '낮음'}
LOG = ROOT / 'data/private/bridge.log'
PLAN_STALE_MIN = 20


def log(msg):
    line = f"{datetime.now():%m-%d %H:%M:%S} {msg}"
    print(line, flush=True)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open('a', encoding='utf-8') as f: f.write(line + '\n')
    except OSError:
        pass


def secrets():
    sec = tomllib.loads((ROOT / '.streamlit/secrets.toml').read_text(encoding='utf-8'))
    db, dev = sec.get('database', {}), sec.get('device', {})
    url, key = str(db.get('url', '')).rstrip('/'), db.get('anon_key', '')
    if not url.startswith('https://') or not key or not dev.get('id') or not dev.get('token'):
        sys.exit('secrets.toml 의 [database] url/anon_key, [device] id/token 이 필요합니다')
    return url, key, dev['id'], dev['token']


class Server:
    def __init__(self, url, key, device, token):
        self.url, self.h, self.device, self.token = url, {'apikey': key, 'Content-Type': 'application/json'}, device, token

    def rpc(self, name, **body):
        r = requests.post(f'{self.url}/rest/v1/rpc/{name}', headers=self.h, timeout=15,
                          json={'p_device': self.device, 'p_token': self.token, **body})
        if r.status_code >= 400:
            raise RuntimeError(f'{name} {r.status_code} {r.text[:120]}')
        return r.json() if r.text else None


def plan_stale(info, minutes=PLAN_STALE_MIN):
    p = info.get('plan') or {}
    if p.get('basis') == 'demo':      # 시연 일정은 일부러 쓴 것이니 이 PC 가 덮어쓰지 않는다
        return False
    try:
        return time.time() - datetime.fromisoformat(p['computed_at']).timestamp() > minutes * 60
    except (KeyError, TypeError, ValueError):
        return True


def plan_to_state(info):
    """서버 응답 → 보드에 보낼 (풍향 한글, 단계 한글, ACTION, basis_key)."""
    cmd = info.get('command') or 'HOLD'
    plan = info.get('plan') or {}
    now = time.time()
    level_ko, wind_ko, active = None, None, False
    for ep in plan.get('episodes') or []:
        try:
            on, off = datetime.fromisoformat(ep['on_at']).timestamp(), datetime.fromisoformat(ep['off_at']).timestamp()
        except (KeyError, ValueError):
            continue
        if off >= now - 60 and level_ko is None:
            level_ko, wind_ko = ep.get('peak_level'), ep.get('wind_sector')
        if on <= now < off:
            active = True
    if info.get('source') == 'plan' and plan.get('state') != 'hold' and plan.get('episodes') is not None:
        # 저장된 action 은 계산 시각 기준이라 15분 사이에 낡는다. 가동 구간(on_at~off_at)과 지금 시각으로 다시 정한다.
        cmd = 'ON' if active else 'OFF'
    if level_ko is None and plan.get('state') not in (None, 'hold'):
        level_ko = '낮음'
    basis = 'forecast_csv' if plan.get('basis') == 'demo' else 'kma_forecast'
    return wind_ko, level_ko, cmd, basis


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--port'); ap.add_argument('--sim', action='store_true'); ap.add_argument('--interval', type=int, default=20)
    ap.add_argument('--no-plan', action='store_true')
    a = ap.parse_args()
    if a.sim: os.environ['ODOR_DEVICE_SIM'] = '1'
    from core.device import AppDeviceLink, SIM_PORT
    url, key, device, token = secrets()
    server = Server(url, key, device, token)
    link = AppDeviceLink(repo=None)
    port = SIM_PORT if a.sim else a.port
    if not link.connect(port):
        log(f'보드 연결 실패 · {link.last_error} (포트: {link.ports()})'); sys.exit(1)
    log(f'보드 연결 · {link.port} · 기기 {device}')
    last_poll, last_sent, reported, reported_at, override_synced, last_plan = 0.0, None, None, 0.0, None, 0.0
    while True:
        try:
            if link.status == '연결 끊김':
                log(f'연결 끊김 · {link.last_error} · 다시 연결 시도')
                time.sleep(5)
                if not link.connect(port): continue
                last_sent = None
            now = time.time()
            if now - last_poll >= a.interval:
                last_poll = now
                info = server.rpc('device_get')
                settings = info.get('settings') or {}
                if not a.no_plan and plan_stale(info) and time.time() - last_plan > 600:
                    last_plan = time.time()
                    log('서버 일정이 오래됨 · 이 PC 에서 다시 계산')
                    r = subprocess.run([sys.executable, '-m', 'scripts.plan_devices'], cwd=ROOT, capture_output=True, text=True,
                                       encoding='utf-8', errors='replace', env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
                    out = (r.stdout + r.stderr).strip().splitlines()
                    log(('일정 계산 완료' if r.returncode == 0 else '일정 계산 실패') + (' · ' + out[-1] if out else ''))
                    info = server.rpc('device_get'); settings = info.get('settings') or {}
                if link.mode == 'MANUAL':
                    if settings.get('mode') == 'auto' and override_synced is None:
                        # 보드 버튼으로 켜고 끈 것 → 서버도 수동(2시간)으로. 앱에 '수동 가동/정지'가 보인다
                        override_synced = 'on' if link.device_fan else 'off'
                        server.rpc('device_set', p_mode=override_synced)
                        log(f'보드 수동 {override_synced} → 서버 모드 {override_synced} (2시간)')
                        info = server.rpc('device_get'); settings = info.get('settings') or {}
                    elif settings.get('mode') == 'auto':
                        # 서버의 수동 시간이 끝나 자동으로 돌아옴 → 보드도 자동으로
                        link.set_auto(); override_synced = None; last_sent = None
                        log('서버 자동 복귀 → 보드 MODE|AUTO')
                else:
                    override_synced = None
                state = plan_to_state(info)
                if state != last_sent:
                    line = link.send_state(state[0], state[1], state[2], state[3])
                    log(f'→ {line} ({info.get("source")} · {(info.get("plan") or {}).get("reason", "")})')
                    last_sent = state
            snap = (link.device_fan, link.mode)
            if link.connected and link.device_fan is not None and (snap != reported or now - reported_at > 60):
                server.rpc('device_report', p_fan=bool(link.device_fan), p_mode=link.mode.lower(), p_fw='uno-bridge-1', p_note=link.last_ack)
                if snap != reported: log(f'← 팬 {"ON" if link.device_fan else "OFF"} · {link.mode}')
                reported, reported_at = snap, now
        except (requests.RequestException, RuntimeError) as e:
            log(f'서버 오류 · {e}')
            time.sleep(5)
        except KeyboardInterrupt:
            break
        time.sleep(1)
    link.close(); log('종료')


if __name__ == '__main__':
    main()
