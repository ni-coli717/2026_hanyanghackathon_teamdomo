"""Manual browser regression: viewer running on port 8511. No production writes."""
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
    expect(frame.locator('#time-label')).not_to_have_text('자료 없음', timeout=90000)
    actual = next(f for f in page.frames if 'odor_map' in f.url)
    actual.wait_for_function('window.odorMap?.map && window.odorMap.data.frames.length > 0')
    page.wait_for_timeout(1500)
    return page, frame, actual, errors


def go(frame, actual, prefix):
    i = actual.evaluate('p=>odorMap.data.frames.findIndex(f=>f.at.startsWith(p))', prefix)
    assert i >= 0, prefix
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
            for name in ['#timeline', '#compass', '#location-name']:
                box = frame.locator(name).bounding_box()
                assert 0 <= box['y'] and box['y']+box['height'] <= height+2, (width, name, box)
            assert actual.evaluate('odorMap.data.frames.filter(f=>f.kind==="observed").length') == 364
            expect(frame.locator('#time-mode')).to_have_text('업데이트 지연')
            expect(frame.locator('#model-badge')).to_have_text('예비 실험·미보정')
            page.screenshot(path=f'artifacts/map-{width}.png', full_page=True)

            # 09-11 22:00: group detection, calm -> arrows hidden, needle off, zone badge.
            go(frame, actual, '2026-09-11T22:00')
            expect(frame.locator('#summary')).to_contain_text('집단 감지')
            expect(frame.locator('#direction')).to_have_text('방향 보류')
            assert actual.locator('.flow-head').count() == 0
            assert actual.evaluate('document.querySelector("#needle").classList.contains("off")')
            assert actual.evaluate('[...document.querySelectorAll(".leaflet-tooltip")].some(t=>t.textContent.includes("운양역 인근 · 집단 감지 · 방향 보류"))')
            page.screenshot(path=f'artifacts/model-calm-{width}.png', full_page=True)

            # 09-15 22:00: ENE 0.5 m/s -> map arrows WSW 247.5°, compass ENE, livestock orange.
            go(frame, actual, '2026-09-15T22:00')
            expect(frame.locator('#direction')).to_have_text('동북동쪽에서 유입 추정')
            expect(frame.locator('#type-label')).to_have_text('축산계 · 추정')
            expect(frame.locator('#compass-status')).to_contain_text('유입 가능성')
            assert 8 <= actual.locator('.flow-head').count() <= 16  # 2-4 lines x 4 heads
            assert actual.evaluate('document.querySelector(".flow-head svg").style.transform') == 'rotate(247.5deg)'
            assert actual.evaluate('((odorMap.needleAngle%360)+360)%360') == 67.5
            assert actual.evaluate('[...document.querySelectorAll("path.leaflet-interactive")].some(p=>p.getAttribute("stroke")==="#D97706")')
            page.wait_for_timeout(700)
            page.screenshot(path=f'artifacts/model-ene-{width}.png', full_page=True)
            frame.locator('.leaflet-marker-icon.flow-head').first.click(force=True)
            expect(frame.locator('#panel-content')).to_contain_text('정렬 후보')
            expect(frame.locator('#panel-content')).to_contain_text('예비 실험·미보정')
            assert '%' not in frame.locator('#panel-content').inner_text()
            page.screenshot(path=f'artifacts/model-detail-{width}.png', full_page=True)
            frame.locator('#close-panel').click()

            # 09-14 12:30: low estimate, zero detections -> grey wind layer only.
            go(frame, actual, '2026-09-14T12:30')
            expect(frame.locator('#type-label')).to_have_text('바람')
            strokes = actual.evaluate('[...document.querySelectorAll("path.leaflet-interactive")].map(p=>p.getAttribute("stroke")).filter(s=>s&&s!=="white")')
            assert strokes and set(strokes) == {'#64748B'}, strokes

            # Forecast region: labelled, dotted, never '실시간'.
            latest = actual.evaluate('odorMap.data.latest_index')
            frame.locator('#time-slider').evaluate('(el,i)=>{el.value=i;el.dispatchEvent(new Event("input",{bubbles:true}))}', latest+2)
            expect(frame.locator('#time-mode')).to_have_text('시연 예보')
            expect(frame.locator('#basis')).to_have_text('예보 기준')
            expect(frame.locator('#timing-label')).to_have_text('예보 기준')
            assert actual.evaluate('[...document.querySelectorAll("path.leaflet-interactive")].some(p=>p.getAttribute("stroke-dasharray")==="1 9")') or actual.locator('.flow-head').count() == 0
            assert '실시간' not in actual.evaluate('document.body.innerText')
            page.wait_for_timeout(700)
            page.screenshot(path=f'artifacts/model-forecast-{width}.png', full_page=True)

            # Air care: honest status + judgment only.
            frame.locator('[data-panel="air"]').click()
            expect(frame.locator('#panel-content')).to_contain_text('연결된 기기 없음')
            expect(frame.locator('#panel-content')).to_contain_text('(예보)')
            expect(frame.locator('#device-state')).to_have_text('연결된 기기 없음')
            page.screenshot(path=f'artifacts/air-{width}.png', full_page=True)
            frame.locator('#auto-toggle').click()
            expect(frame.locator('#auto-toggle')).to_have_text('사용 안 함')
            frame.locator('#auto-toggle').click()
            expect(frame.locator('#auto-toggle')).to_have_text('사용 중')
            frame.locator('#close-panel').click()

            # Time/position independence and existing controls.
            initial = actual.evaluate('({position:odorMap.state.position,center:odorMap.map.getCenter(),zoom:odorMap.map.getZoom()})')
            frame.locator('#latest').click()
            frame.locator('#previous').click()
            expect(frame.locator('#time-mode')).to_have_text('지난 기록')
            after = actual.evaluate('({position:odorMap.state.position,center:odorMap.map.getCenter(),zoom:odorMap.map.getZoom()})')
            assert initial == after
            frame.locator('#latest').click()
            expect(frame.locator('#time-mode')).to_have_text('업데이트 지연')
            frame.locator('#pick').click()
            actual.evaluate('odorMap.map.fire("click",{latlng:L.latLng(37.662,126.679)})')
            expect(frame.locator('#location-name')).to_have_text('한강변·라베니체 인근')
            page.wait_for_timeout(1200)
            assert actual.evaluate('odorMap.state.position[0]') == 37.662
            frame.locator('[data-filter="sewage"]').click()
            assert actual.evaluate('odorMap.state.filter') == 'sewage'
            frame.locator('[data-filter="all"]').click()
            assert actual.evaluate('odorMap.deltaAngle(359,1)') == 2
            # 359° -> 1° turns 2° along the short arc.
            turn = actual.evaluate('''() => {
                const f=odorMap.data.frames.find(f=>f.at===odorMap.state.at);
                f.wind={from:359,to:179,speed:2,at:f.at}; render(); const a=odorMap.needleAngle;
                f.wind={from:1,to:181,speed:2,at:f.at}; render(); return odorMap.needleAngle-a;
            }''')
            assert turn == 2, turn
            frame.locator('#pick').click()
            actual.evaluate('odorMap.map.fire("click",{latlng:L.latLng(37.5,127.1)})')
            expect(frame.locator('#notice')).to_contain_text('김포 밖')
            assert actual.evaluate('odorMap.state.position[0]') == 37.662
            frame.locator('#play').click()
            expect(frame.locator('#play')).to_have_attribute('aria-label', '정지')
            page.wait_for_timeout(1900)
            frame.locator('#play').click()
            assert actual.evaluate('odorMap.state.position[0]') == 37.662
            actual.evaluate('()=>{navigator.geolocation.getCurrentPosition=(ok,fail)=>fail({code:1});}')
            frame.locator('#locate').click()
            expect(frame.locator('#notice')).to_contain_text('위치 권한')
            frame.locator('#overview').click()
            assert actual.evaluate('odorMap.map.getZoom()') >= 10
            frame.locator('#recenter').click()
            actual.wait_for_function('Math.abs(odorMap.map.getCenter().lat-37.662)<0.0001')
            page.route('**://tile.openstreetmap.org/**', lambda route: route.abort())
            actual.evaluate('odorMap.map.eachLayer(l=>{if(l instanceof L.TileLayer)l.redraw()})')
            expect(frame.locator('#tile-error')).to_be_visible(timeout=15000)
            page.unroute('**://tile.openstreetmap.org/**')
            frame.locator('#retry').click()
            expect(frame.locator('#tile-error')).to_be_hidden()
            # Missing data clears old arrows and never reads as "no odor".
            actual.evaluate('''() => {
                const f=odorMap.data.frames.find(f=>f.at===odorMap.state.at);
                f.wind=null; f.zones={}; render();
            }''')
            assert actual.locator('.flow-head').count() == 0
            expect(frame.locator('#direction')).to_have_text('방향 미확인')
            expect(frame.locator('#compass-status')).to_have_text('자료 없음')
            assert not errors, errors
            page.close()
        browser.close()
    print('Map browser checks passed: desktop/mobile, model windows, forecast, air care, time, position, compass.')


def check_model_missing():
    """Run while odor_model.joblib is moved away: the viewer must stay up and show 추정 보류."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for width, height in [(1440, 900), (390, 844)]:
            page, frame, actual, errors = open_map(browser, width, height)
            expect(frame.locator('#model-badge')).to_have_text('추정 보류')
            go(frame, actual, '2026-09-15T22:00')
            expect(frame.locator('#compass-status')).to_have_text('추정 보류')
            expect(frame.locator('#type-label')).to_have_text('바람')
            assert not {'#D97706', '#7C3AED'} & set(actual.evaluate('[...document.querySelectorAll("path.leaflet-interactive")].map(p=>p.getAttribute("stroke"))'))
            page.screenshot(path=f'artifacts/model-missing-{width}.png', full_page=True)
            assert not errors, errors
            page.close()
        browser.close()
    print('Model-missing check passed: 추정 보류, wind layer only, no crash.')


if __name__ == '__main__':
    import sys
    check_model_missing() if 'missing' in sys.argv else check()
