"""Manual browser check of the air-care board flow.

Run a viewer with the board simulator on port 8521:
  ODOR_DEVICE_SIM=1 APP_ENV=local OBSERVATION_DB_PATH=<scratch db> streamlit run viewer_app.py --server.port 8521
Optional: operator app on 8523 (ADMIN_PASSWORD_HASH for password 'screenshot') to check the 기기 tab.
With a real board, use the same steps by hand and read the LCD instead of the simulator panel.
"""
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

VIEWER = 'http://localhost:8521'
FRAME = 'iframe[title="core.map_component.odor_map"]'
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else 'artifacts/device')


def open_viewer(browser, width, height):
    page = browser.new_page(viewport={'width': width, 'height': height})
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.goto(VIEWER)
    page.wait_for_selector(FRAME, timeout=120000)
    f = page.frame_locator(FRAME)
    expect(f.locator('#time-label')).not_to_have_text('자료 없음', timeout=120000)
    a = next(fr for fr in page.frames if 'odor_map' in fr.url)
    a.wait_for_function('window.odorMap?.map && odorMap.data.frames.length>0')
    page.wait_for_timeout(1500)
    return page, f, a, errors


def go(f, a, prefix):
    i = a.evaluate('p=>odorMap.data.frames.findIndex(f=>f.at.startsWith(p))', prefix)
    f.locator('#time-slider').evaluate('(el,i)=>{el.value=i;el.dispatchEvent(new Event("input",{bubbles:true}))}', i)


def panel_text(f):
    return f.locator('#panel-content').inner_text()


def shot(page, name):
    OUT.mkdir(parents=True, exist_ok=True)
    page.wait_for_timeout(600)
    page.screenshot(path=str(OUT / f'{name}.png'))


def check():
    with sync_playwright() as p:
        b = p.chromium.launch()
        page, f, a, errors = open_viewer(b, 1440, 900)
        f.locator('[data-panel="air"]').click()
        page.wait_for_timeout(800)
        if f.locator('[data-device="disconnect"]').is_enabled():      # link is per server process
            f.locator('[data-device="disconnect"]').click()
        expect(f.locator('#device-state')).to_have_text('연결된 기기 없음', timeout=20000)
        assert 'SIMULATOR' in f.locator('#device-port').inner_text()
        shot(page, '01_기기없음')

        f.locator('[data-device="connect"]').click()
        expect(f.locator('#device-state')).to_contain_text('연결됨', timeout=20000)
        expect(f.locator('#device-state')).to_contain_text('시뮬레이터')

        go(f, a, '2026-09-14T12:30')
        expect(f.locator('#panel-content')).to_contain_text('AIRFLOW: WNW', timeout=20000)
        expect(f.locator('#panel-content')).to_contain_text('SYSTEM: STANDBY')
        expect(f.locator('#device-state')).to_contain_text('대기 중')
        expect(f.locator('#panel-content')).to_contain_text('LED 빨강 · 팬 정지')
        shot(page, '02_0914-1230_OFF_대기')

        f.locator('#latest').click()                               # 09-16 22:00: 높음 (1회)
        page.wait_for_timeout(2500)
        go(f, a, '2026-09-15T22:00')                               # 높음 2회 연속 → ON
        expect(f.locator('#device-state')).to_contain_text('가동 중', timeout=20000)
        expect(f.locator('#panel-content')).to_contain_text('ODOR INFLOW EST')
        expect(f.locator('#panel-content')).to_contain_text('WIND FROM:ENE')
        expect(f.locator('#panel-content')).to_contain_text('LED 초록 · 팬 회전')
        shot(page, '03_0915-2200_ON_가동')

        f.locator('[data-device="sim_short"]').click()             # board button short press
        expect(f.locator('#panel-content')).to_contain_text('수동 조작 중 · 자동 대응 일시 중지', timeout=20000)
        expect(f.locator('#device-state')).to_contain_text('대기 중')
        shot(page, '04_수동조작')
        f.locator('#next').click()                                 # auto still wants ON; board must stay OFF
        page.wait_for_timeout(3000)
        expect(f.locator('#device-state')).to_contain_text('대기 중')
        f.locator('[data-device="auto"]').click()
        expect(f.locator('#panel-content')).not_to_contain_text('수동 조작 중', timeout=20000)
        expect(f.locator('#device-state')).to_contain_text('가동 중', timeout=20000)   # rule state re-applied

        go(f, a, '2026-09-15T22:00')
        page.wait_for_timeout(2500)
        before = f.locator('#summary').inner_text()
        f.locator('[data-device="sim_long"]').click()             # long press = 냄새 남 report
        expect(f.locator('#panel-content')).to_contain_text('REPORT SENT', timeout=20000)
        import re
        count = lambda text: int(m.group(1)) if (m := re.search(r'제보 (\d+)', text)) else 0
        expect(f.locator('#summary')).to_contain_text(f'제보 {count(before) + 1}', timeout=20000)
        after = f.locator('#summary').inner_text()
        assert before.split('제보')[0].strip() == after.split('제보')[0].strip(), (before, after)   # 감지 x/n unchanged
        shot(page, '05_버튼길게_제보')

        f.locator('[data-device="sim_unplug"]').click()
        expect(f.locator('#device-state')).to_have_text('연결 끊김', timeout=20000)
        page.wait_for_timeout(16500)
        f.locator('[data-panel="air"]').click()                    # re-render to read the board LCD after 15 s
        f.locator('[data-panel="air"]').click()
        expect(f.locator('#panel-content')).to_contain_text('NO SIGNAL', timeout=20000)
        expect(f.locator('#panel-content')).to_contain_text('팬 정지')
        shot(page, '06_USB분리_NO_SIGNAL')
        assert not errors, errors
        page.close()

        page, f, a, errors = open_viewer(b, 390, 844)
        f.locator('[data-panel="air"]').click()
        shot(page, '07_모바일_공기질관리')
        assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
        page.close()

        try:
            page = b.new_page(viewport={'width': 1440, 'height': 900})
            page.goto('http://localhost:8523', timeout=15000)
            page.get_by_label('비밀번호').fill('screenshot'); page.get_by_role('button', name='로그인').click()
            page.wait_for_timeout(4000)
            page.get_by_text('⑦ 예측 모델', exact=True).first.click(); page.wait_for_timeout(3500)
            page.get_by_role('tab', name='기기').click(); page.wait_for_timeout(1500)
            expect(page.get_by_text('마지막 ACK')).to_be_visible()
            shot(page, '08_운영자_기기탭')
            page.close()
        except Exception as exc:  # operator app optional
            print('operator check skipped:', exc)
        b.close()
    print('Device browser checks passed.')


if __name__ == '__main__':
    check()
