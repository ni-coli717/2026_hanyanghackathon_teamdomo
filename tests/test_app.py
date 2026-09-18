from streamlit.testing.v1 import AppTest
from core.observations import LocalObservations


def click(app, label):
    next(b for b in app.button if b.label == label).click().run()
    assert not app.exception


def test_viewer_public_pages():
    app=AppTest.from_file('app.py',default_timeout=40).run()
    assert not app.exception
    assert app.radio[0].options == ['현재 상황','지난 기록','생활 대응','서비스 정보']
    for page in app.radio[0].options:
        app.radio[0].set_value(page).run()
        assert not app.exception


def test_admin_locked_without_secret(monkeypatch):
    monkeypatch.delenv('ADMIN_PASSWORD_HASH',raising=False)
    app=AppTest.from_file('admin_app.py',default_timeout=40).run()
    assert not app.exception
    assert not app.radio
    assert any('잠겨' in w.value for w in app.warning)


def test_admin_authenticated_pages(monkeypatch,tmp_path):
    from core.auth import password_hash
    monkeypatch.setenv('ADMIN_PASSWORD_HASH',password_hash('test-password'))
    monkeypatch.setenv('ADMIN_DB_PATH',str(tmp_path/'admin.db'))
    app=AppTest.from_file('admin_app.py',default_timeout=40).run()
    app.text_input[0].set_value('test-password')
    click(app,'로그인')
    for page in ['④ 분석·방향','⑤ AI 실험','⑥ 우리 집 대응','⚙ 설정']:
        app.radio[0].set_value(page).run()
        assert not app.exception


def start_measurement(monkeypatch,tmp_path):
    monkeypatch.setenv('APP_ENV','local')
    monkeypatch.setenv('OBSERVATION_DB_PATH',str(tmp_path/'resident.db'))
    app=AppTest.from_file('measurement_app.py',default_timeout=30).run()
    app.text_input[0].set_value('R07')
    app.selectbox[0].set_value('Z2')
    click(app,'관측 시작')
    assert app.radio[1].value is None
    app.radio[1].set_value('실외').run()
    click(app,'다음')
    assert app.radio[1].value is None
    return app


def test_no_odor_fast_path_and_reset(monkeypatch,tmp_path):
    app=start_measurement(monkeypatch,tmp_path)
    app.radio[1].set_value('느껴지지 않음').run()
    click(app,'다음'); click(app,'기록 저장')
    assert app.success
    rows=LocalObservations(tmp_path/'resident.db').get_recent_observations()
    assert len(rows)==1 and rows[0]['odor_detected'] is False
    assert rows[0]['intensity']==0 and rows[0]['odor_type']=='없음'
    click(app,'새 관측 시작')
    assert app.radio[1].value is None


def test_unknown_and_indoor(monkeypatch,tmp_path):
    app=start_measurement(monkeypatch,tmp_path)
    click(app,'이전 단계')
    app.radio[1].set_value('실내').run(); click(app,'다음')
    app.radio[1].set_value('판단하기 어려움').run()
    click(app,'다음'); click(app,'기록 저장')
    row=LocalObservations(tmp_path/'resident.db').get_recent_observations()[0]
    assert row['odor_detected'] is None and row['context']=='indoor'


def test_yes_requires_explicit_details(monkeypatch,tmp_path):
    app=start_measurement(monkeypatch,tmp_path)
    app.radio[1].set_value('느껴짐').run(); click(app,'다음')
    assert app.radio[1].value is None and app.radio[2].value is None
    assert next(b for b in app.button if b.label=='내용 확인').disabled
    app.radio[1].set_value(4).run(); app.radio[2].set_value('탄내').run()
    click(app,'내용 확인'); click(app,'기록 저장')
    row=LocalObservations(tmp_path/'resident.db').get_recent_observations()[0]
    assert row['odor_detected'] is True and row['intensity']==4


def test_save_failure_keeps_draft(monkeypatch,tmp_path):
    app=start_measurement(monkeypatch,tmp_path)
    app.radio[1].set_value('느껴지지 않음').run(); click(app,'다음')
    def fail(*args): raise RuntimeError('offline')
    with monkeypatch.context() as m:
        m.setattr(LocalObservations,'save_observation',fail)
        click(app,'기록 저장')
        assert app.error and not app.success
    click(app,'기록 저장')
    assert app.success


def test_live_viewer_reads_shared_local_store(monkeypatch,tmp_path):
    from core.observations import build_observation
    from datetime import datetime
    from uuid import uuid4
    monkeypatch.setenv('APP_ENV','local')
    monkeypatch.setenv('DATA_MODE','live')
    monkeypatch.setenv('OBSERVATION_DB_PATH',str(tmp_path/'shared.db'))
    repo=LocalObservations(tmp_path/'shared.db')
    for i in range(3):
        repo.save_observation(build_observation(f'R{i:02}','Z2','outdoor',False,0,'없음',str(uuid4()),datetime(2026,9,18,7,30)))
    app=AppTest.from_file('viewer_app.py',default_timeout=40).run()
    assert not app.exception
    assert any('3명 중 0명 감지' in m.value for m in app.markdown)
    assert any('기상자료 없음' in i.value for i in app.info)
