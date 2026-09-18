import pandas as pd
import streamlit as st
from core.config import data_mode, now_kst, ZONE_PUBLIC_NAMES
from core.public_data import dashboard
from core.public_ui import header, participation, map_view, public_compass, state


def main():
    st.set_page_config(page_title='냄새 나침반',page_icon='assets/logo.svg',layout='wide')
    demo = data_mode() == 'demo'
    header('냄새 나침반', demo)
    page = st.radio('메뉴',['현재 상황','지난 기록','생활 대응','서비스 정보'],horizontal=True,key='viewer_menu',label_visibility='collapsed')
    if page == '서비스 정보':
        st.subheader('주민의 기록으로 동네 상황을 함께 살펴봅니다')
        st.write('풍향과 주민 관측의 관계를 보여주며 발생원을 판정하지 않습니다. 개인 위치는 표시하지 않습니다.')
        st.write('시연 자료: 2026년 9월 9~16일 제공 시나리오 655건. 원본에 simulated로 표시된 가상 주민 기록이며 기상도 제공 파일의 참고값입니다.')
        st.write('구역 대표점은 임시 설정입니다. 실제 구역 경계와 후보 방향은 운영자가 검증해야 합니다.')
        st.write('정기 관측 07:30 · 12:30 · 18:30 · 22:00, 각 ±15분. 판단 어려움·실내 기록·추가 제보는 실외 정기 감지율에서 제외됩니다.')
    elif page == '생활 대응':
        st.subheader('주변 관측과 내 주변 상황을 함께 확인하세요')
        st.write('냄새가 느껴지면 창문 상태와 실내 냄새 원인도 함께 확인해 주세요. 잠시 후 동네 관측을 다시 살펴볼 수 있습니다.')
        st.info('관측이 없거나 오래되었다면 현재 상황을 알기 어렵습니다. 냄새가 없는 경우도 기록해 주세요.')
        st.caption('공기청정기 연결과 알림은 확장 기능 준비 중입니다. 현재 앱은 자동 제어 또는 개선 효과를 보장하지 않습니다.')
    else:
        st.title('운양동 현재 상황' if page == '현재 상황' else '지난 기록')
        try:
            reports, weather, zones, sources, windows, geometry = dashboard('demo' if demo else 'live')
        except Exception:
            st.error('서버 연결 실패 — 관측 자료를 불러오지 못했습니다. 잠시 후 다시 확인해 주세요.')
            participation()
            return
        latest = pd.DataFrame()
        reference = None
        if not windows.empty:
            reference = windows.window_at.max()
            if page == '지난 기록':
                reference = st.select_slider('관측 시각',options=sorted(windows.window_at.unique()),value=reference,
                    format_func=lambda x:pd.Timestamp(x).strftime('%m/%d %H:%M KST'))
            latest = windows[windows.window_at == reference]
        stale = reference is None or (pd.Timestamp(now_kst()).tz_localize(None)-pd.Timestamp(reference)).total_seconds()>3600
        st.caption(('과거 시연 자료 · ' if demo else '마지막 관측: ') + (f'{pd.Timestamp(reference):%Y-%m-%d %H:%M} KST' if reference is not None else '관측 없음'))
        if not demo and stale: st.warning('관측 부족 · 최근 1시간 관측이 없습니다. 아래는 마지막 기록입니다.')
        wx = None
        if not weather.empty:
            candidates = weather[weather.weather_at <= reference] if reference is not None else weather
            if not candidates.empty: wx = candidates.iloc[-1]
        left,right = st.columns([.65,.35])
        with left:
            mapped = map_view(zones,latest,wx,'public_map')
        with right:
            public_compass(wx)
            if wx is not None and (pd.Timestamp(now_kst()).tz_localize(None)-pd.Timestamp(wx.weather_at)).total_seconds()>3600:
                st.caption('기상자료 지연 · 과거 기준 시각의 바람입니다.')
        n = int(latest.n_observers.sum()) if not latest.empty else 0
        detected = int(latest.n_detected.sum()) if not latest.empty else 0
        enough = not latest.empty and bool((latest.n_observers>=3).all())
        st.subheader('최근 관측 상태')
        if n: st.write(f'**{n}명 중 {detected}명 감지** · 표시된 시각의 정기 실외 관측')
        else: st.info('관측 부족 — 현재 상태를 판단할 자료가 없습니다.')
        st.caption('자료 충분' if enough else '일부 또는 전체 구역의 관측 부족')
        zone=st.selectbox('관측 구역 선택',mapped.zone_id.tolist(),format_func=lambda x:ZONE_PUBLIC_NAMES.get(x,x),key='public_map_zone')
        detail=mapped[mapped.zone_id==zone].iloc[0]
        with st.container(border=True):
            st.write(f'**{ZONE_PUBLIC_NAMES.get(detail.zone_id,detail["name"])}**')
            status,_ = state(detail.n_observers,detail.detected_ratio)
            st.write(status)
            if pd.notna(detail.n_observers):
                st.write(f'{int(detail.n_observers)}명 중 {int(detail.n_detected)}명 감지')
                if detail.n_observers>=3:
                    st.write(f'감지 비율 {detail.detected_ratio:.0%} · 중앙 강도 {detail.median_intensity:g}')
                st.caption(f'관측 시각 {pd.Timestamp(detail.window_at):%m/%d %H:%M} KST')
            st.caption('발생원 판정 결과가 아닙니다.')
        st.info('주변 관측을 확인하고, 냄새가 느껴지면 창문 상태와 실내 원인도 함께 살펴보세요.')
        with st.expander('지도가 보이지 않나요?'):
            st.write('배경 지도에는 인터넷 연결이 필요합니다. 위 구역 선택과 관측 요약은 배경 지도를 불러오지 못해도 이용할 수 있습니다.')
    participation()


if __name__ == '__main__':
    main()
