import json
import pandas as pd
import streamlit as st
from core.config import data_mode, nested_setting, now_kst, setting
from core.public_data import dashboard, window_slots
from core.map_data import prepare_payload, resolve_selection
from core.map_component import odor_map
from core import analysis_service as service
from core.automation import make_rule
from core.device import AppDeviceLink, basis_key
from core.observations import observation_repository
from core import account as acc
from core.participation import summary as participation_summary, save_record
from odor_model.device_service import push_prediction

RECENT_HOURS = 3


def model_key():
    """Cache key: active model file, its mtime, operator settings and coordinates."""
    settings = service.load_settings()
    path = service.model_path(settings['active_model'])
    mtime = path.stat().st_mtime if path.exists() else 0
    return json.dumps([str(path), mtime, settings, service.load_geo(), service.demo_forecast_mtime()], ensure_ascii=False, sort_keys=True)


@st.cache_data(show_spinner=False, max_entries=8)
def observed_predictions(inputs, key):
    return service.predict_windows(inputs)


@st.cache_data(ttl=3600, show_spinner=False)
def forecast(key):
    rows, meta = service.forecast_inputs()
    return service.predict_windows(rows), meta


@st.cache_data(ttl=15, show_spinner=False)
def map_payload(mode, key):
    reports, weather, zones, _, windows, _ = dashboard(mode)
    slots = window_slots(mode)
    times = slots.window_start if not slots.empty else sorted(set(windows.window_at)) if not windows.empty else []
    predictions = observed_predictions(service.weather_inputs(weather, times), key)
    ahead, meta = forecast(key)
    _, info = service.load_model()
    payload = prepare_payload(reports, weather, zones, windows, mode == 'demo', slots=slots, predictions=predictions,
                              forecast=meta, forecast_predictions=ahead, model_info=info)
    return payload, pd.concat([predictions, ahead], ignore_index=True)


@st.cache_resource(show_spinner=False)
def device_link():
    """One serial link per server process; reopening on every rerun would lock the port."""
    try:
        repo, _ = observation_repository()
    except Exception:
        repo = None
    return AppDeviceLink(repo=repo)


@st.cache_data(ttl=20, show_spinner=False)
def recent_reports(saved_count=0, hours=RECENT_HOURS):
    """Spontaneous reports (resident or board button) in the last few hours. Shown apart from rates.
    saved_count is part of the cache key so a new board report appears immediately."""
    try:
        repo, _ = observation_repository()
        rows = repo.get_recent_observations() if repo else []
    except Exception:
        return {}
    cutoff = pd.Timestamp(now_kst()) - pd.Timedelta(hours=hours)
    counts = {}
    for row in rows:
        if row.get('collection_mode') != 'spontaneous' or row.get('odor_detected') is not True:
            continue
        if pd.Timestamp(row['observed_at']) < cutoff:
            continue
        item = counts.setdefault(row['zone_id'], {'count': 0, 'device': 0})
        item['count'] += 1
        item['device'] += row.get('record_origin') == 'device_button'
    return counts


def prediction_row(predictions, at, zone_id):
    if not zone_id or predictions is None or predictions.empty:
        return {'status': '자료 없음'}
    rows = predictions[(predictions.app_zone_id == zone_id) & (predictions.window_start == pd.Timestamp(at).tz_localize(None))]
    return rows.iloc[0].to_dict() if not rows.empty else {'status': '자료 없음'}


def device_api():
    """Browser-side access to the home air-purifier card (Supabase RPC with the publishable key only).
    The publishable key is meant to be public; every device function still checks a per-browser token."""
    url = nested_setting('database', 'url').rstrip('/')
    key = nested_setting('database', 'anon_key')
    if not url.startswith('https://') or not key:
        return None
    zone_map = {app: model for model, app in service.app_zone_ids().items()}
    return {'url': url, 'key': key, 'zone_map': zone_map}


# ------------------------------------------------------------------ 계정
def _profile(store, user):
    """프로필은 세션에 한 번만 읽어 둔다(바뀌면 _profile_set 으로 갱신)."""
    if user is None or store is None:
        return None
    cache = st.session_state.get('profile_cache')
    if cache and cache[0] == user['key']:
        return cache[1]
    try:
        profile = store.get(user['key'])
    except RuntimeError:
        st.session_state.auth_notice = '서버 연결 실패 · 새로고침'
        return None
    st.session_state.profile_cache = (user['key'], profile)
    return profile


def _profile_set(user, profile):
    st.session_state.profile_cache = (user['key'], profile)


def account_state():
    user, store = acc.current_user(), acc.profile_store()
    profile = _profile(store, user)
    pub = acc.public_account(user, profile, store_ok=store is not None)
    pub['providers'] = acc.providers()
    pub['notice'] = st.session_state.pop('auth_notice', '')
    pub['cmd_done'] = st.session_state.get('auth_cmd_done', 0)
    if 'email_refresh' in st.session_state:
        pub['refresh'] = st.session_state.pop('email_refresh')
    return pub, user, profile, store


def handle_auth_command(state):
    cmd = state.get('auth_cmd') or {}
    if not cmd or cmd.get('id', 0) <= st.session_state.get('auth_cmd_done', 0):
        return
    st.session_state.auth_cmd_done = cmd['id']
    op = cmd.get('op')
    try:
        if op == 'login':
            if acc.providers().get(cmd.get('provider')):
                st.login(cmd['provider'])
            else:
                st.session_state.auth_notice = '이 로그인은 아직 준비 중'
        elif op in ('email_login', 'email_signup', 'resume'):
            fn = {'email_login': lambda: acc.email_login(cmd.get('email', ''), cmd.get('password', '')),
                  'email_signup': lambda: acc.email_signup(cmd.get('email', ''), cmd.get('password', '')),
                  'resume': lambda: acc.email_resume(cmd.get('refresh', ''))}[op]
            session = fn()
            if session:
                st.session_state.email_user = {k: v for k, v in session.items() if k != 'refresh'}
                st.session_state.email_refresh = session.get('refresh', '')
                st.session_state.pop('profile_cache', None)
            elif op == 'resume':
                st.session_state.email_refresh = ''
        elif op == 'logout':
            if acc.oidc_user():
                st.logout()
            st.session_state.pop('email_user', None); st.session_state.pop('profile_cache', None); st.session_state.email_refresh = ''
        else:
            user, store = acc.current_user(), acc.profile_store()
            if user is None or store is None:
                st.session_state.auth_notice = '로그인 또는 저장소 확인'; return
            profile = _profile(store, user)
            if op == 'signup':
                _profile_set(user, acc.create_profile(store, user, cmd.get('nickname'), cmd.get('consents') or [], cmd.get('code'),
                                                      notify='notify' in (cmd.get('consents') or [])))
            elif profile is None:
                st.session_state.auth_notice = '가입 먼저'
            elif op == 'tutorial_done':
                _profile_set(user, acc.update_profile(store, profile, tutorial_done=True))
            elif op == 'nickname':
                _profile_set(user, acc.update_profile(store, profile, nickname=(cmd.get('value') or '').strip())); st.session_state.auth_notice = '닉네임 저장됨'
            elif op == 'notify':
                _profile_set(user, acc.update_profile(store, profile, notify=bool(cmd.get('value'))))
            elif op == 'link_code':
                code = (cmd.get('code') or '').strip().upper()
                if not acc.CODE_RE.match(code): raise ValueError('참여 코드 확인')
                if code != profile['participant_code'] and store.code_taken(code): raise ValueError('이미 다른 계정에 연결된 코드')
                _profile_set(user, acc.update_profile(store, profile, legacy_code=code)); st.session_state.auth_notice = f'{code} 연결됨'
            elif op == 'withdraw':
                acc.update_profile(store, profile, nickname='탈퇴 계정', email='', consents=[], withdrawn=True)
                if acc.oidc_user(): st.logout()
                st.session_state.pop('email_user', None); st.session_state.pop('profile_cache', None); st.session_state.email_refresh = ''
    except (acc.EmailAuthError, ValueError) as e:
        st.session_state.auth_notice = str(e)
    except RuntimeError:
        st.session_state.auth_notice = '서버 연결 실패'


@st.cache_data(ttl=30, show_spinner=False)
def participation(code, legacy, version):
    try:
        repo, _ = observation_repository()
    except Exception:
        repo = None
    return participation_summary(repo, code, legacy)


def handle_record_command(state, code):
    cmd = state.get('record_cmd') or {}
    if not cmd or cmd.get('id', 0) <= st.session_state.get('record_cmd_done', 0):
        return
    st.session_state.record_cmd_done = cmd['id']
    try:
        repo, _ = observation_repository()
    except Exception:
        repo = None
    st.session_state.record_result = save_record(repo, code, cmd)
    if st.session_state.record_result.get('ok'):
        st.session_state.record_version = st.session_state.get('record_version', 0) + 1


def handle_device_command(link, state):
    cmd = state.get('device_cmd') or {}
    if not cmd or cmd.get('id', 0) <= st.session_state.get('device_cmd_done', 0):
        return
    st.session_state.device_cmd_done = cmd['id']
    op = cmd.get('op')
    if op == 'connect':
        link.connect(cmd.get('port') or None)
        st.session_state.device_resend = True          # send the current state to the new link
    elif op == 'disconnect':
        link.disconnect()
    elif op == 'auto':
        link.set_auto()
        st.session_state.device_resend = True          # board is back on AUTO: apply the rule's current state
    elif link.board and op in ('sim_short', 'sim_long', 'sim_unplug'):
        {'sim_short': link.board.press_short, 'sim_long': link.board.press_long, 'sim_unplug': link.board.unplug}[op]()


def device_state(payload, predictions, selection, state):
    link = device_link()
    handle_device_command(link, state)
    link.report_zone = selection['zone_id']
    enabled = state.get('auto_enabled', True)
    rule = st.session_state.get('auto_rule')
    settings_auto = service.load_settings()['auto']
    if rule is None or (rule.on_streak, rule.off_streak) != (int(settings_auto['start_count']), int(settings_auto['stop_count'])):
        rule = st.session_state.auto_rule = make_rule(enabled)
    rule.enabled = enabled
    frame = payload['frames'][selection['index']] if payload['frames'] else {}
    basis = basis_key(frame, payload)
    row = prediction_row(predictions, selection['at'], selection['zone_id'])
    key = (selection['at'], selection['zone_id'])
    result = st.session_state.get('device_push')
    if result is None or st.session_state.get('device_push_key') != key:
        # Only a new time/zone is a new observation for the rule; each counts once.
        result = push_prediction(link, rule, row, basis)
        st.session_state.device_push_key = key
    elif st.session_state.pop('device_resend', False) or st.session_state.get('device_enabled') != enabled:
        # Reconnect or toggle: re-send the rule's current state without advancing its streak.
        level = row.get('level') if row.get('status') == '예비 추정' else None
        action = 'HOLD' if not enabled else ('ON' if rule._state else 'OFF')
        sent = link.send_state(row.get('wind_from_sector'), level, action, basis,
                               row.get('direction_status') == '방향 보류(약풍)') if link.connected else None
        result = {**result, 'action': action, 'sent': sent}
    st.session_state.device_push, st.session_state.device_enabled = result, enabled
    snap = link.snapshot()
    return {**snap, 'action': result['action'], 'sent': result['sent'], 'rule_enabled': rule.enabled,
            'ports': link.ports(), 'streak': [rule.on_streak, rule.off_streak]}, link


@st.fragment(run_every=2)
def watch_device(link):
    """Board events arrive on a background thread; redraw when the link's state changes."""
    if st.session_state.get('device_sig') != link.signature():
        st.session_state.device_sig = link.signature()
        st.rerun()


def main():
    st.set_page_config(page_title='냄새 나침반',page_icon='assets/logo.svg',layout='wide',initial_sidebar_state='collapsed')
    st.markdown('''<style>
    [data-testid="stHeader"], [data-testid="stToolbar"], #MainMenu, footer{display:none!important}
    .stMainBlockContainer,.block-container{padding:0!important;max-width:none!important}
    [data-testid="stVerticalBlock"]{gap:0!important}
    [data-stale="true"]{opacity:1!important}
    iframe[title="core.map_component.odor_map"]{display:block;width:100%;height:100dvh;border:0}
    html,body,.stApp,[data-testid="stAppViewContainer"]{overflow:hidden}
    </style>''',unsafe_allow_html=True)
    if st.query_params.get('diag') == 'db' and setting('APP_ENV', 'cloud') == 'local':
        # 로컬 전용 연결 점검(키는 출력하지 않는다): http://localhost:8501/?diag=db
        from scripts.db_check import run_checks
        st.code('\n'.join(run_checks())); return
    state = st.session_state.get('map_state', {})
    handle_auth_command(state)
    account, user, profile, _ = account_state()
    if account['status'] != 'ok':
        # 로그인·가입·사용법 전에는 지도 자료를 보내지 않는다.
        result = odor_map(payload=None, selection=None, initial_state=state, account=account, key='resident_map', default=None)
        if result and result.get('sequence',0)>state.get('sequence',0):
            st.session_state.map_state=result
            st.rerun()
        return
    code = profile['participant_code']
    handle_record_command(state, code)
    try:
        payload, predictions = map_payload(data_mode(), model_key())
    except Exception:
        st.error('서버 연결 실패')
        if st.button('다시 시도'): st.rerun()
        return
    selection = resolve_selection(payload,state)
    device, link = device_state(payload, predictions, selection, state)
    st.session_state.device_sig = link.signature()
    part = participation(code, profile.get('legacy_code'), st.session_state.get('record_version', 0)) if state.get('tab') in ('part',) or state.get('panel') == 'account' or st.session_state.get('record_result') else None
    result = odor_map(payload=payload, selection=selection, initial_state=state, device=device, account=account,
                      participation=part, record=st.session_state.get('record_result'),
                      recent=recent_reports(link.reports_saved + st.session_state.get('record_version', 0)), device_api=device_api(),
                      key='resident_map', default=None)
    if link.port:
        watch_device(link)
    if result and result.get('sequence',0)>state.get('sequence',0):
        st.session_state.map_state=result
        st.rerun()


if __name__ == '__main__': main()
