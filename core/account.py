"""계정. 로그인 두 갈래, 프로필 한 곳.

- 카카오·구글: Streamlit st.login (OIDC). secrets [auth] / [auth.google] / [auth.kakao].
- 이메일: Supabase Auth (signup / password / refresh_token) 를 서버가 대신 부른다. 브라우저에는 refresh 토큰만 남긴다.
- 프로필(닉네임·동의·참여 코드·사용법 완료)은 서버가 Supabase `profiles` 에 service 키로 쓴다(브라우저는 접근 못 함).
  Supabase 설정이 없고 APP_ENV=local 이면 data/accounts.db(sqlite).

계정 키: '<provider>:<sub>'. 기록(observations.participant_id)에는 이 키를 쓰지 않고 짧은 참여자 코드(P로 시작, 자동 발급)를 쓴다.
"""
from __future__ import annotations

import json
import re
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import requests
import streamlit as st

from .config import nested_setting, now_kst, setting

NICK_RE = re.compile(r'^[\w가-힣 ·._-]{2,20}$')
CODE_RE = re.compile(r'^[A-Z0-9_-]{2,24}$')
ISSUERS = {'https://accounts.google.com': 'google', 'accounts.google.com': 'google', 'https://kauth.kakao.com': 'kakao'}
PROVIDER_NAMES = {'google': '구글', 'kakao': '카카오', 'email': '이메일'}


# ------------------------------------------------------------------ 설정
def _auth_section():
    try:
        return dict(st.secrets.get('auth', {}))
    except Exception:
        return {}


def providers() -> dict:
    """어떤 로그인 버튼을 켤지. 비밀값은 돌려주지 않는다."""
    auth = _auth_section()
    oidc_ready = bool(auth.get('redirect_uri') and auth.get('cookie_secret'))
    def ready(p):
        sec = auth.get(p) or {}
        return oidc_ready and bool(dict(sec).get('client_id') and dict(sec).get('client_secret'))
    return {'kakao': ready('kakao'), 'google': ready('google'), 'email': bool(_supabase())}


def _supabase():
    url, anon = nested_setting('database', 'url').rstrip('/'), nested_setting('database', 'anon_key')
    return (url, anon) if url.startswith('https://') and anon else None


def operators() -> set:
    try:
        return {str(x).strip().lower() for x in _auth_section().get('operators', [])}
    except Exception:
        return set()


# ------------------------------------------------------------------ 로그인 상태
def oidc_user():
    """st.login 으로 들어온 사용자. 없으면 None."""
    try:
        u = st.user
        if not getattr(u, 'is_logged_in', False):
            return None
        d = u.to_dict() if hasattr(u, 'to_dict') else dict(u)
    except Exception:
        return None
    provider = ISSUERS.get(str(d.get('iss', '')), 'oidc')
    sub = d.get('sub') or d.get('email')
    if not sub:
        return None
    return {'key': f'{provider}:{sub}', 'provider': provider, 'email': d.get('email') or '',
            'name': d.get('nickname') or d.get('name') or ''}


class EmailAuthError(Exception):
    pass


def _auth_post(path, body, params=None):
    sb = _supabase()
    if not sb:
        raise EmailAuthError('이메일 로그인 준비 중')
    url, anon = sb
    try:
        r = requests.post(f'{url}/auth/v1/{path}', params=params, json=body, timeout=15,
                          headers={'apikey': anon, 'Content-Type': 'application/json'})
    except requests.RequestException:
        raise EmailAuthError('서버 연결 실패') from None
    try:
        j = r.json()
    except ValueError:
        j = {}
    if r.status_code >= 400:
        m = str(j.get('msg') or j.get('error_description') or j.get('message') or j.get('error_code') or '')
        low = m.lower()
        if 'invalid login' in low or 'invalid_credentials' in low: raise EmailAuthError('이메일 또는 비밀번호가 맞지 않음')
        if 'already' in low or 'registered' in low: raise EmailAuthError('이미 가입된 이메일 · 로그인하세요')
        if 'password' in low and ('short' in low or 'least' in low or 'weak' in low): raise EmailAuthError('비밀번호 8자 이상')
        if 'email' in low and ('invalid' in low or 'valid' in low): raise EmailAuthError('이메일 주소 확인')
        if 'not confirmed' in low: raise EmailAuthError('메일함의 확인 링크를 먼저 눌러 주세요')
        if 'rate' in low: raise EmailAuthError('잠시 후 다시 시도')
        if 'refresh' in low or 'invalid_grant' in low: raise EmailAuthError('다시 로그인해 주세요')
        raise EmailAuthError(m[:60] or f'오류 {r.status_code}')
    return j


def _session_from(j):
    user = j.get('user') or {}
    if not j.get('access_token') or not user.get('id'):
        return None
    return {'key': f"email:{user['id']}", 'provider': 'email', 'email': user.get('email', ''), 'name': '',
            'refresh': j.get('refresh_token', '')}


def email_signup(email, password):
    email, password = email.strip().lower(), password or ''
    if not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email): raise EmailAuthError('이메일 주소 확인')
    if len(password) < 8: raise EmailAuthError('비밀번호 8자 이상')
    j = _auth_post('signup', {'email': email, 'password': password})
    s = _session_from(j)
    if s is None:   # 메일 확인이 켜져 있으면 세션 없이 user 만 온다
        raise EmailAuthError('가입 메일을 보냈어요 · 확인 링크를 누른 뒤 로그인')
    return s


def email_login(email, password):
    j = _auth_post('token', {'email': email.strip().lower(), 'password': password or ''}, params={'grant_type': 'password'})
    s = _session_from(j)
    if s is None: raise EmailAuthError('로그인 실패')
    return s


def email_resume(refresh_token):
    if not refresh_token: return None
    try:
        j = _auth_post('token', {'refresh_token': refresh_token}, params={'grant_type': 'refresh_token'})
    except EmailAuthError:
        return None
    return _session_from(j)


def current_user():
    """로그인된 사용자(OIDC 우선, 아니면 이 세션의 이메일 세션). 없으면 None."""
    return oidc_user() or st.session_state.get('email_user')


# ------------------------------------------------------------------ 프로필
PROFILE_FIELDS = ('account_key', 'provider', 'email', 'nickname', 'participant_code', 'consents', 'tutorial_done',
                  'home_zone', 'notify', 'legacy_code', 'withdrawn', 'created_at', 'updated_at')


def new_participant_code():
    return 'P' + secrets.token_hex(3).upper()


class ProfileStore:
    def get(self, key): raise NotImplementedError
    def upsert(self, profile): raise NotImplementedError
    def code_taken(self, code): raise NotImplementedError


class SharedProfiles(ProfileStore):
    def __init__(self, url, key):
        self.url = url.rstrip('/') + '/rest/v1/profiles'
        self.headers = {'apikey': key, 'Content-Type': 'application/json', **({'Authorization': f'Bearer {key}'} if key.startswith('eyJ') else {})}

    def _req(self, method, **kw):
        try:
            r = requests.request(method, self.url, headers={**self.headers, **kw.pop('headers', {})}, timeout=15, **kw)
            r.raise_for_status()
            return r.json() if r.text else []
        except (requests.RequestException, ValueError):
            raise RuntimeError('서버 연결 실패') from None

    def get(self, key):
        rows = self._req('GET', params={'account_key': f'eq.{key}', 'select': '*', 'limit': 1})
        return rows[0] if rows else None

    def upsert(self, profile):
        self._req('POST', json=profile, params={'on_conflict': 'account_key'}, headers={'Prefer': 'resolution=merge-duplicates,return=minimal'})

    def code_taken(self, code):
        return bool(self._req('GET', params={'participant_code': f'eq.{code}', 'select': 'account_key', 'limit': 1}))


class LocalProfiles(ProfileStore):
    def __init__(self, path):
        self.path = Path(path); self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as c:
            c.execute('CREATE TABLE IF NOT EXISTS profiles(account_key TEXT PRIMARY KEY, payload TEXT NOT NULL)')

    def get(self, key):
        with sqlite3.connect(self.path) as c:
            row = c.execute('SELECT payload FROM profiles WHERE account_key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def upsert(self, profile):
        with sqlite3.connect(self.path) as c:
            c.execute('INSERT OR REPLACE INTO profiles(account_key,payload) VALUES(?,?)', (profile['account_key'], json.dumps(profile, ensure_ascii=False)))

    def code_taken(self, code):
        with sqlite3.connect(self.path) as c:
            return any(json.loads(r[0]).get('participant_code') == code for r in c.execute('SELECT payload FROM profiles'))


def profile_store():
    url, key = nested_setting('database', 'url'), nested_setting('database', 'key')
    if url.startswith('https://') and key:
        return SharedProfiles(url, key)
    if setting('APP_ENV', 'cloud') == 'local':
        return LocalProfiles(setting('ACCOUNT_DB_PATH', 'data/accounts.db'))
    return None


def mask_email(email):
    if not email or '@' not in email: return ''
    name, dom = email.split('@', 1)
    return f'{name[:2]}{"*" * max(1, len(name) - 2)}@{dom}'


def public_account(user, profile, store_ok=True):
    """브라우저로 보내는 계정 상태. 이메일은 가려서, 키·토큰은 빼고."""
    if user is None:
        return {'status': 'anon'}
    if profile is None or profile.get('withdrawn'):
        return {'status': 'signup', 'provider': user['provider'], 'provider_name': PROVIDER_NAMES.get(user['provider'], ''),
                'name': user.get('name', ''), 'store_ok': store_ok}
    return {'status': 'ok' if profile.get('tutorial_done') else 'tutorial', 'provider': profile['provider'],
            'provider_name': PROVIDER_NAMES.get(profile['provider'], ''), 'nickname': profile['nickname'],
            'code': profile['participant_code'], 'email': mask_email(profile.get('email', '')),
            'joined': str(profile.get('created_at', ''))[:10], 'notify': bool(profile.get('notify')),
            'operator': (user.get('email') or '').lower() in operators()}


def create_profile(store, user, nickname, consents, code=None, notify=False):
    nickname = (nickname or '').strip()
    if not NICK_RE.match(nickname): raise ValueError('닉네임 2–20자')
    required = {'terms', 'privacy', 'location'}
    if not required <= set(consents or []): raise ValueError('필수 동의 확인')
    code = (code or '').strip().upper()
    if code:
        if not CODE_RE.match(code): raise ValueError('참여 코드 확인')
        if store.code_taken(code): raise ValueError('이미 다른 계정에 연결된 코드')
    else:
        code = new_participant_code()
        while store.code_taken(code): code = new_participant_code()
    now = now_kst().isoformat()
    profile = {'account_key': user['key'], 'provider': user['provider'], 'email': user.get('email', ''), 'nickname': nickname,
               'participant_code': code, 'consents': sorted(set(consents)), 'tutorial_done': False, 'home_zone': None, 'withdrawn': False, 'legacy_code': None,
               'notify': bool(notify), 'created_at': now, 'updated_at': now}
    store.upsert(profile)
    return profile


def update_profile(store, profile, **changes):
    if 'nickname' in changes and not NICK_RE.match((changes['nickname'] or '').strip()): raise ValueError('닉네임 2–20자')
    profile = {**profile, **changes, 'updated_at': now_kst().isoformat()}
    store.upsert(profile)
    return profile
