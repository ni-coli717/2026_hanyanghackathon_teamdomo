import hashlib
import hmac
import secrets
import streamlit as st
from .config import nested_setting


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256',password.encode(),salt.encode(),600000).hex()
    return f'pbkdf2_sha256$600000${salt}${digest}'


def verify_password(password, stored):
    try:
        algorithm, iterations, salt, expected = stored.split('$')
        if algorithm != 'pbkdf2_sha256' or not 100000 <= int(iterations) <= 2000000: return False
        actual=hashlib.pbkdf2_hmac('sha256',password.encode(),salt.encode(),int(iterations)).hex()
        return hmac.compare_digest(actual,expected)
    except (ValueError,TypeError): return False


def require_admin():
    stored=nested_setting('admin','password_hash')
    if not stored:
        st.warning('관리자 인증이 설정되지 않아 운영자 기능이 잠겨 있습니다.')
        st.stop()
    if st.session_state.get('admin_authenticated') == hashlib.sha256(stored.encode()).hexdigest(): return
    st.title('운영자 로그인')
    with st.form('admin_login'):
        password=st.text_input('비밀번호',type='password')
        if st.form_submit_button('로그인'):
            if verify_password(password,stored):
                st.session_state.admin_authenticated=hashlib.sha256(stored.encode()).hexdigest()
                st.rerun()
            else: st.error('인증 정보를 확인하세요.')
    st.stop()


if __name__ == '__main__':
    import getpass
    print(password_hash(getpass.getpass('관리자 비밀번호: ')))
