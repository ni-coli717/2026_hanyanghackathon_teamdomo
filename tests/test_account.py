from datetime import datetime
from uuid import uuid4
import pytest

from core import account as acc
from core.observations import LocalObservations, build_observation
from core.participation import save_record, summary


def user():
    return {'key': 'email:u1', 'provider': 'email', 'email': 'yuna@example.com', 'name': ''}


def test_profile_create_update_and_public_view(tmp_path):
    store = acc.LocalProfiles(tmp_path / 'a.db')
    assert acc.public_account(None, None)['status'] == 'anon'
    assert acc.public_account(user(), None)['status'] == 'signup'
    with pytest.raises(ValueError):
        acc.create_profile(store, user(), '운양동 주민', ['terms'])
    p = acc.create_profile(store, user(), '운양동 주민', ['terms', 'privacy', 'location'])
    assert p['participant_code'].startswith('P') and store.get('email:u1')['nickname'] == '운양동 주민'
    pub = acc.public_account(user(), p)
    assert pub['status'] == 'tutorial' and pub['email'] == 'yu**@example.com' and 'key' not in pub
    p = acc.update_profile(store, p, tutorial_done=True)
    assert acc.public_account(user(), p)['status'] == 'ok'
    with pytest.raises(ValueError):
        acc.create_profile(store, {**user(), 'key': 'email:u2'}, '다른 사람', ['terms', 'privacy', 'location'], code=p['participant_code'])


def test_save_record_verified_and_rejected(tmp_path):
    repo = LocalObservations(tmp_path / 'r.db')
    ok = save_record(repo, 'PABC', {'id': 1, 'odor': True, 'intensity': 2, 'context': 'outdoor', 'lat': 37.654, 'lon': 126.680, 'accuracy': 20})
    assert ok['ok'] and ok['zone'] == 'Z2' and ok['check'] == 'verified' and ok['zone_name'] == '운양역'
    bad = save_record(repo, 'PABC', {'id': 2, 'odor': False, 'context': 'indoor', 'lat': 37.654, 'lon': 126.680, 'accuracy': 900})
    assert bad['ok'] and bad['check'] == 'rejected'
    none = save_record(repo, 'PABC', {'id': 3, 'odor': None, 'context': 'outdoor'})
    assert not none['ok']
    rows = repo.get_recent_observations()
    assert len(rows) == 2 and {r['participant_id'] for r in rows} == {'PABC'}
    assert 'lat' not in ok and 'lon' not in ok


def test_participation_summary(tmp_path):
    repo = LocalObservations(tmp_path / 'r.db')
    now = datetime(2026, 10, 27, 13, 0)
    for i in range(3):
        repo.save_observation(build_observation('PABC', 'Z2', 'outdoor', i == 0, 2 if i == 0 else 0, None, str(uuid4()), datetime(2026, 10, 27, 7, 30 + i), location={'status': 'verified', 'lat': 37.654, 'lon': 126.68, 'accuracy_m': 10}))
    repo.save_observation(build_observation('P01', 'Z1', 'outdoor', False, 0, None, str(uuid4()), datetime(2026, 10, 26, 12, 30)))
    from zoneinfo import ZoneInfo
    s = summary(repo, 'PABC', legacy_code='P01', now=now.replace(tzinfo=ZoneInfo('Asia/Seoul')))
    assert s['my_count'] == 3 and s['verified_pct'] == 100 and s['legacy_count'] == 1
    assert s['week']['done'] == 1 and s['neighbors_week'] == 2 and s['recent'][-1]['label'] == '나요 · 2' and s['recent'][0]['label'] == '안 나요'
    assert summary(None, 'PABC')['my_count'] == 0
