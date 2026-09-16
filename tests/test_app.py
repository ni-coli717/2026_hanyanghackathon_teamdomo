from streamlit.testing.v1 import AppTest


def test_all_pages_render_without_exception():
    app = AppTest.from_file("app.py", default_timeout=40).run()
    assert not app.exception
    pages = ["② 동네 지도", "③ 냄새 기록", "④ 분석·방향", "⑤ AI 실험", "⑥ 우리 집 대응", "⚙ 설정"]
    for page in pages:
        app.radio[0].set_value(page).run()
        assert not app.exception, f"{page}: {[x.value for x in app.exception]}"

