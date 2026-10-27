"""참여 탭 집계와 ＋기록 저장. 판정(위치·이동·중복)은 전부 여기(서버)에서 한다."""
from __future__ import annotations

from uuid import uuid4

import pandas as pd

from .config import KST, SCHEDULED_TIMES, ZONE_PUBLIC_NAMES, classify_collection_mode, now_kst
from .geo_check import check_location, movement_check
from .observations import build_observation

DAYS = ['월', '화', '수', '목', '금', '토', '일']


def _ts(v):
    t = pd.Timestamp(v)
    return t.tz_localize(KST) if t.tzinfo is None else t.tz_convert(KST)


def when_text(iso, now):
    t = _ts(iso); d = (now.date() - t.date()).days
    day = '오늘' if d == 0 else '어제' if d == 1 else f'{t:%m.%d}'
    return f'{day} {t:%H:%M}'


def row_label(r):
    if r.get('odor_detected') is True: return f"나요 · {r.get('intensity') or ''}".strip(' ·')
    if r.get('odor_detected') is False: return '안 나요'
    return '모르겠어요'


def summary(repo, code, legacy_code=None, now=None):
    """참여 탭 자료. repo 가 없으면 빈 집계."""
    now = now or now_kst()
    out = {'week': {'done': 0, 'total': 28, 'days': []}, 'my_count': 0, 'verified_pct': None, 'neighbors_week': 0, 'recent': [], 'legacy_count': 0}
    monday = (now - pd.Timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    out['week']['days'] = [{'d': DAYS[i], 'n': 0, 'future': i > now.weekday()} for i in range(7)]
    if repo is None or not code:
        return out
    try:
        mine = repo.get_observations_by_participant(code, limit=500)
        everyone = repo.get_recent_observations()
    except Exception:
        return out
    mine = [r for r in mine if r.get('participant_id') == code]
    out['my_count'] = len(mine)
    if mine:
        out['verified_pct'] = round(100 * sum(r.get('location_check') == 'verified' for r in mine) / len(mine))
    seen = set()
    for r in mine:
        t = _ts(r['observed_at'])
        if t >= monday and r.get('collection_mode') == 'scheduled' and r.get('location_check') == 'verified':
            k = (t.date(), r.get('window_id'))
            if k not in seen:
                seen.add(k); out['week']['days'][t.weekday()]['n'] = min(4, out['week']['days'][t.weekday()]['n'] + 1)
    out['week']['done'] = sum(d['n'] for d in out['week']['days'])
    out['recent'] = [{'when': when_text(r['observed_at'], now), 'label': row_label(r), 'mode': r.get('collection_mode'),
                      'check': r.get('location_check')} for r in sorted(mine, key=lambda r: r['observed_at'], reverse=True)[:5]]
    week_rows = [r for r in everyone if _ts(r['observed_at']) >= monday]
    out['neighbors_week'] = len({r.get('participant_id') for r in week_rows})
    if legacy_code:
        out['legacy_count'] = sum(r.get('participant_id') == legacy_code for r in everyone)
    return out


def save_record(repo, code, cmd, now=None):
    """＋기록 명령 → 저장. 반환 dict 는 그대로 브라우저로 간다(개인 위치 없음)."""
    now = now or now_kst()
    res = {'cmd_id': cmd.get('id'), 'ok': False}
    if repo is None:
        res['error'] = '기록 저장 연결이 아직 없어요'; return res
    odor = cmd.get('odor'); odor = None if odor is None else bool(odor)
    context = 'indoor' if cmd.get('context') == 'indoor' else 'outdoor'
    intensity = cmd.get('intensity')
    loc = None
    if cmd.get('lat') is not None and cmd.get('lon') is not None:
        loc = check_location(cmd['lat'], cmd['lon'], cmd.get('accuracy'))
    zone = loc['zone_id'] if loc and loc['status'] == 'verified' else (loc['nearest_zone'] if loc else None)
    if zone is None:
        res['error'] = '위치를 알 수 없어 구역을 정할 수 없어요'; return res
    try:
        prev = next((r for r in repo.get_observations_by_participant(code, limit=5) if r.get('lat') is not None), None)
    except Exception:
        prev = None
    if loc is not None and loc['status'] == 'verified':
        mv = movement_check(prev, loc, now)
        if not mv['ok']:
            res['error'] = mv['reason']; return res
    try:
        draft = build_observation(code, zone, context, odor, intensity, None, str(uuid4()), location=loc)
    except ValueError as e:
        res['error'] = str(e); return res
    draft['received_at'] = now.isoformat(); draft['collection_mode'] = classify_collection_mode(now)[0]
    try:
        repo.save_observation(draft)
    except Exception:
        res['error'] = '서버 연결 실패 · 잠시 후 다시'; return res
    res.update(ok=True, id=draft['observation_id'], zone=zone, zone_name=ZONE_PUBLIC_NAMES.get(zone, zone), check=draft['location_check'],
               mode=draft['collection_mode'], odor=odor, intensity=intensity if odor is True else None, context=context, at=draft['observed_at'])
    return res
