"""Manual browser regression for the viewer first screen: viewer running on port 8511. No production writes.

python -m streamlit run viewer_app.py --server.port 8511 --server.headless true   (DATA_MODE=demo)
python tests/browser_map_check.py            # full check
python tests/browser_map_check.py missing    # with odor_model.joblib moved away
"""
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

URL = 'http://localhost:8511'
FRAME = 'iframe[title="core.map_component.odor_map"]'


def open_map(browser, width, height):
    page = browser.new_page(viewport={'width': width, 'height': height})
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(URL)
    page.wait_for_selector(FRAME, timeout=90000)
    frame = page.frame_locator(FRAME)
    actual = next(f for f in page.frames if 'odor_map' in f.url)
    actual.wait_for_function('window.odorMap?.map && window.odorMap.data.frames.length > 0', timeout=90000)
    page.wait_for_timeout(1500)
    return page, frame, actual, errors


def go(frame, actual, prefix):
    """Scrub the 예보 tab slider to the frame starting with prefix."""
    i = actual.evaluate('p=>odorMap.data.frames.findIndex(f=>f.at.startsWith(p))', prefix)
    assert i >= 0, prefix
    actual.evaluate('odorMap.setTab("forecast")')
    frame.locator('#time-slider').evaluate('(el,i)=>{el.value=i;el.dispatchEvent(new Event("input",{bubbles:true}))}', i)
    return i


def check():
    Path('artifacts').mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for width, height in [(1440, 900), (390, 844)]:
            page, frame, actual, errors = open_map(browser, width, height)
            assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
            assert not actual.evaluate('document.documentElement.scrollWidth>innerWidth')
            # First screen: map + collapsed sheet only; header, fabs and sheet inside the viewport.
            assert actual.evaluate('odorMap.state.collapsed') is True
            for name in ['#header', '#wind-btn', '#locate', '#sheet', '#tabs']:
                box = frame.locator(name).bounding_box()
                assert 0 <= box['y'] and box['y'] + box['height'] <= height + 2, (width, name, box)
            assert frame.locator('#bars').is_hidden()
            assert actual.evaluate('odorMap.data.frames.filter(f=>f.kind==="observed").length') == 364
            assert actual.evaluate('odorMap.data.zones.length') == 3
            assert actual.evaluate('odorMap.data.zones.every(z=>z.ring.length>=30)')
            assert actual.locator('path.leaflet-interactive').count() == 3            # three zone polygons, no arrows
            expect(frame.locator('#head-label')).to_contain_text('오늘 냄새 날 가능성')
            expect(frame.locator('#head-label')).to_contain_text('운양역')
            assert frame.locator('#level-word').inner_text() in ('낮음', '보통', '높음', '보류')
            text = actual.evaluate('document.body.innerText')
            for word in ('Z1', 'Z2', 'Z3', '실시간', '%', '188건'):
                assert word not in text, word
            page.screenshot(path=f'artifacts/first-{width}.png', full_page=True)

            # Expand: six-hour bars, footnote with version and refresh time only.
            frame.locator('#head').click()
            assert actual.evaluate('odorMap.state.collapsed') is False
            expect(frame.locator('#bars')).to_be_visible()
            expect(frame.locator('#foot')).to_contain_text('냄새 나침반 v1')
            expect(frame.locator('#foot')).to_contain_text('갱신')
            assert '학습' not in frame.locator('#foot').inner_text()
            page.screenshot(path=f'artifacts/expanded-{width}.png', full_page=True)

            # 09-15 22:00: ENE 0.5 m/s -> wind button points WSW 247.5°, head shows that time, zone levels drawn.
            go(frame, actual, '2026-09-15T22:00')
            expect(frame.locator('#time-mode')).to_have_text('지난 기록')
            expect(frame.locator('#head-label')).to_contain_text('09.15 22:00 기록')
            assert actual.evaluate('((odorMap.arrowAngle%360)+360)%360') == 247.5
            expect(frame.locator('#wind-name')).to_have_text('동풍')
            fills = actual.evaluate('[...document.querySelectorAll("path.leaflet-interactive")].map(p=>p.getAttribute("fill"))')
            assert set(fills) <= {'#2E8B57', '#E0A100', '#D64533', '#9AA5AE'}, fills
            page.screenshot(path=f'artifacts/history-{width}.png', full_page=True)

            # 09-11 22:00: calm -> button dimmed, text says 방향 보류.
            go(frame, actual, '2026-09-11T22:00')
            assert actual.evaluate('document.querySelector("#wind-btn").classList.contains("calm")')
            frame.locator('#wind-btn').click()
            expect(frame.locator('#panel-title')).to_have_text('바람과 냄새')
            expect(frame.locator('#panel-content')).to_contain_text('방향 보류')
            frame.locator('#back').click()

            # Forecast region: labelled as forecast, never 실시간.
            latest = actual.evaluate('odorMap.data.latest_index')
            actual.evaluate('odorMap.setTab("forecast")')
            frame.locator('#time-slider').evaluate('(el,i)=>{el.value=i;el.dispatchEvent(new Event("input",{bubbles:true}))}', latest + 2)
            expect(frame.locator('#time-mode')).to_have_text('시연 예보')
            expect(frame.locator('#head-label')).to_contain_text('예보')
            assert '실시간' not in actual.evaluate('document.body.innerText')
            page.screenshot(path=f'artifacts/forecast-{width}.png', full_page=True)
            frame.locator('#latest').click()
            expect(frame.locator('#time-mode')).to_have_text('갱신 지연')
            expect(frame.locator('#head-label')).to_contain_text('오늘')

            # Zone list in 예보 picks the zone for map and 지금.
            frame.locator('[data-zone="Z1"]').click()
            expect(frame.locator('#head-label')).to_contain_text('한강변')
            page.wait_for_timeout(1200)
            assert actual.evaluate('odorMap.state.position[0]') == 37.662

            # 안내 > 공기질 관리 기기: honest status, toggle works, model status shown once in 안내.
            frame.locator('[data-tab="help"]').click()
            expect(frame.locator('#model-status')).to_have_text('실제 제보 학습 · 센서 보정 전')
            frame.locator('[data-open="air"]').click()
            expect(frame.locator('#device-state')).to_have_text('연결된 기기 없음')
            frame.locator('#auto-toggle').click()
            expect(frame.locator('#auto-toggle')).to_have_text('사용 안 함')
            frame.locator('#auto-toggle').click()
            expect(frame.locator('#auto-toggle')).to_have_text('사용 중')
            page.screenshot(path=f'artifacts/air-{width}.png', full_page=True)
            frame.locator('#back').click()
            expect(frame.locator('#panel-title')).to_have_text('안내')

            # 기록 tab links out; position/time untouched.
            frame.locator('[data-tab="record"]').click()
            expect(frame.locator('#panel-content')).to_contain_text('냄새 기록')
            assert actual.evaluate('odorMap.state.position[0]') == 37.662

            # Position picking, outside-Gimpo rejection, geolocation denial.
            frame.locator('[data-tab="now"]').click()
            frame.locator('#pick').click()
            actual.evaluate('odorMap.map.fire("click",{latlng:L.latLng(37.647,126.685)})')
            expect(frame.locator('#head-label')).to_contain_text('모담산')
            frame.locator('#pick').click()
            actual.evaluate('odorMap.map.fire("click",{latlng:L.latLng(37.5,127.1)})')
            expect(frame.locator('#notice')).to_contain_text('김포 밖')
            assert actual.evaluate('odorMap.state.position[0]') == 37.647
            actual.evaluate('()=>{navigator.geolocation.getCurrentPosition=(ok,fail)=>fail({code:1});}')
            frame.locator('#locate').click()
            expect(frame.locator('#notice')).to_contain_text('위치 권한')
            assert actual.evaluate('odorMap.deltaAngle(359,1)') == 2
            assert actual.evaluate('odorMap.direction8(67.5)') == '동'

            # Tile failure surfaces and recovers.
            page.route('**/basemaps.cartocdn.com/**', lambda route: route.abort())
            actual.evaluate('odorMap.map.eachLayer(l=>{if(l instanceof L.TileLayer)l.redraw()})')
            expect(frame.locator('#tile-error')).to_be_visible(timeout=15000)
            page.unroute('**/basemaps.cartocdn.com/**')
            frame.locator('#retry').click()
            expect(frame.locator('#tile-error')).to_be_hidden()

            # Missing data never reads as "no odor".
            actual.evaluate('''() => {
                const f=odorMap.data.frames.find(f=>f.at===odorMap.state.at);
                f.wind=null; f.zones={}; odorMap.data.frames.forEach(g=>{if(g.kind==='forecast')g.zones={};}); render();
            }''')
            expect(frame.locator('#level-word')).to_have_text('보류')
            expect(frame.locator('#head-sub')).to_contain_text('바람 자료 없음')
            assert not errors, errors
            page.close()
        browser.close()
    print('Map browser checks passed: first screen, sheet, history, forecast, zones, air care, position, tiles.')


def check_model_missing():
    """Run while odor_model.joblib is moved away: the viewer must stay up and show 보류."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for width, height in [(1440, 900), (390, 844)]:
            page, frame, actual, errors = open_map(browser, width, height)
            expect(frame.locator('#level-word')).to_have_text('보류')
            frame.locator('[data-tab="help"]').click()
            expect(frame.locator('#model-status')).to_contain_text('추정 보류')
            fills = actual.evaluate('[...document.querySelectorAll("path.leaflet-interactive")].map(p=>p.getAttribute("fill"))')
            assert set(fills) == {'#9AA5AE'}, fills
            page.screenshot(path=f'artifacts/model-missing-{width}.png', full_page=True)
            assert not errors, errors
            page.close()
        browser.close()
    print('Model-missing check passed: 보류 everywhere, grey zones, no crash.')


if __name__ == '__main__':
    import sys
    check_model_missing() if 'missing' in sys.argv else check()
