import pytest
from core.observations import SharedObservations, observation_repository
from core.auth import password_hash,verify_password


def test_admin_hash():
    encoded=password_hash('test-only-password')
    assert verify_password('test-only-password',encoded)
    assert not verify_password('wrong',encoded)
    assert not verify_password('anything','')


def test_cloud_without_backend_disables_submission(monkeypatch):
    monkeypatch.setenv('APP_ENV','cloud')
    monkeypatch.setenv('DATABASE_URL','')
    monkeypatch.setenv('DATABASE_KEY','')
    assert observation_repository()[0] is None


def test_shared_idempotency_and_filtered_reads(monkeypatch):
    calls=[]
    def request(method,url,**kw):
        calls.append((method,kw))
        class Response:
            def raise_for_status(self): pass
            def json(self): return []
        return Response()
    monkeypatch.setattr('core.observations.requests.request',request)
    repo=SharedObservations('https://test.supabase.co','fake-test-key')
    assert not repo.save_observation({'idempotency_key':'test'})
    assert calls[0][1]['params']['on_conflict']=='idempotency_key'
    repo.get_observations_by_participant('R07')
    assert calls[1][1]['params']['participant_id']=='eq.R07'


def test_shared_failures_are_not_success(monkeypatch):
    import requests
    def fail(*a,**kw): raise requests.Timeout('contains secret')
    monkeypatch.setattr('core.observations.requests.request',fail)
    repo=SharedObservations('https://test.supabase.co','fake-test-key')
    with pytest.raises(RuntimeError,match='서버 연결 실패') as err:
        repo.save_observation({})
    assert 'secret' not in str(err.value)
