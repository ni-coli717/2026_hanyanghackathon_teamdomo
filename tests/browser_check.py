"""Run against local viewer :8511 and measurement :8512; writes only test observations."""
from pathlib import Path
import json
import re
from playwright.sync_api import sync_playwright, expect


def check():
    out=Path('artifacts'); out.mkdir(exist_ok=True)
    results=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,args=['--enable-unsafe-swiftshader'])
        for width,height in [(1440,1000),(390,844)]:
            page=browser.new_page(viewport={'width':width,'height':height})
            page.goto('http://localhost:8511',wait_until='domcontentloaded')
            expect(page.get_by_text('최근 관측 상태',exact=True)).to_be_visible(timeout=60000)
            page.wait_for_function("document.querySelector('.compass-svg')?.naturalWidth > 0")
            page.wait_for_selector('.js-plotly-plot canvas')
            page.wait_for_timeout(1500)
            page.screenshot(path=str(out/f'viewer-{width}.png'),full_page=True)
            overflow=page.evaluate('document.documentElement.scrollWidth > window.innerWidth')
            assert not overflow, f'viewer overflow {width}'
            assert page.locator('.compass-svg').count()==1
            box=page.locator('.compass-svg').bounding_box()
            assert box['y']+box['height'] < height
            assert page.get_by_text('AI 실험',exact=True).count()==0
            point=page.locator('.js-plotly-plot').evaluate('''gd => {
                const map=gd._fullLayout.map._subplot.map;
                const p=map.project([126.680,37.654]);
                const r=map.getCanvas().getBoundingClientRect();
                return {x:r.x+p.x,y:r.y+p.y};
            }''')
            page.mouse.click(point['x'],point['y'])
            expect(page.get_by_role('combobox')).to_have_attribute('aria-label', re.compile('운양역 인근'),timeout=15000)
            results.append({'app':'viewer','width':width,'overflow':overflow,'compass':True})
            page.goto('http://localhost:8512',wait_until='domcontentloaded')
            expect(page.get_by_text('처음 한 번만 알려주세요',exact=True)).to_be_visible(timeout=30000)
            page.get_by_label('참여자 코드',exact=True).fill('BROWSER_TEST')
            page.get_by_role('combobox').click()
            page.get_by_role('option',name='운양역 인근').click()
            page.get_by_role('button',name='관측 시작',exact=True).click()
            expect(page.get_by_text('1 · 지금 어디에서 확인하고 있나요?',exact=True)).to_be_visible()
            expect(page.get_by_role('button',name='다음',exact=True)).to_be_visible()
            assert page.get_by_role('radio',name='실외',exact=True).is_checked() is False
            page.screenshot(path=str(out/f'measurement-{width}.png'),full_page=True)
            assert not page.evaluate('document.documentElement.scrollWidth > window.innerWidth')
            page.get_by_text('실외',exact=True).click()
            page.get_by_role('button',name='다음',exact=True).click()
            expect(page.get_by_text('2 · 지금 냄새가 느껴지나요?',exact=True)).to_be_visible()
            assert not page.get_by_role('radio',name='느껴짐',exact=True).is_checked()
            page.get_by_text('느껴지지 않음',exact=True).click()
            page.get_by_role('button',name='다음',exact=True).click()
            expect(page.get_by_text('마지막 · 내용 확인',exact=True)).to_be_visible()
            page.get_by_role('button',name='기록 저장',exact=True).click()
            expect(page.get_by_text('기록되었습니다.',exact=True)).to_be_visible()
            results.append({'app':'measurement','width':width,'no_defaults':True,'no_odor_saved':True})
            page.close()
        browser.close()
    print(json.dumps(results,ensure_ascii=True))


if __name__=='__main__': check()
