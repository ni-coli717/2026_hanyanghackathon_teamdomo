"""Supabase 연결 점검(운영자용). 키는 secrets.toml 에서만 읽고 출력하지 않는다."""
import requests
from core.config import nested_setting


def run_checks():
    url, key, anon = nested_setting('database', 'url').rstrip('/'), nested_setting('database', 'key'), nested_setting('database', 'anon_key')
    out = []
    for name, k in [('secret', key), ('anon', anon)]:
        for mode in ('apikey', 'bearer'):
            h = {'apikey': k}
            if mode == 'bearer': h['Authorization'] = f'Bearer {k}'
            for table in ('observations', 'profiles'):
                try:
                    r = requests.get(f'{url}/rest/v1/{table}', headers=h, params={'select': '*', 'limit': 1}, timeout=15)
                    out.append(f'{name:6} {mode:6} {table:12} {r.status_code} {r.text[:200]!r}')
                except Exception as e:
                    out.append(f'{name:6} {mode:6} {table:12} EXC {type(e).__name__}: {str(e)[:120]}')
    return out


if __name__ == '__main__':
    print('\n'.join(run_checks()))
