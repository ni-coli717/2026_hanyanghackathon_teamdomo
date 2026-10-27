"""시연 준비: 공기청정기 연결 코드 발급(10분 유효) + 시연 가상 예보로 가동 일정 쓰기.

  python -m scripts.demo_prep            # 코드 + 시연 일정
  python -m scripts.demo_prep --code     # 코드만
결과는 화면과 data/private/demo_prep.txt 에 남는다(저장소에 올라가지 않음). 키·토큰은 출력하지 않는다.
"""
from __future__ import annotations

import argparse, datetime as dt, json, subprocess, sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.plan_devices import _secrets_section   # noqa: E402

OUT = ROOT / 'data' / 'private' / 'demo_prep.txt'


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--code', action='store_true'); a = ap.parse_args()
    db, dev = _secrets_section('database'), _secrets_section('device')
    lines = [f'[{dt.datetime.now():%Y-%m-%d %H:%M:%S}]']
    r = requests.post(db['url'].rstrip('/') + '/rest/v1/rpc/device_new_pair_code',
                      headers={'apikey': db['anon_key'], 'Content-Type': 'application/json'},
                      data=json.dumps({'p_device': dev.get('id', 'AP01'), 'p_token': dev['token']}), timeout=20)
    if r.ok:
        code = r.json()
        lines.append(f'연결 코드  기기 {dev.get("id", "AP01")} · {code[:3]} {code[3:]} · 10분 유효')
    else:
        lines.append(f'코드 발급 실패 {r.status_code} {r.text[:200]}')
    if not a.code:
        p = subprocess.run([sys.executable, '-m', 'scripts.plan_devices', '--demo'], cwd=ROOT,
                           capture_output=True, text=True, encoding='utf-8', errors='replace',
                           env={**__import__('os').environ, 'PYTHONIOENCODING': 'utf-8'})
        lines.append('시연 일정 ' + ('완료' if p.returncode == 0 else '실패'))
        lines.append((p.stdout + p.stderr).strip()[-1500:])
    text = '\n'.join(lines)
    print(text)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
