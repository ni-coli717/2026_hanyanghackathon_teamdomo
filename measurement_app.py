"""냄새 기록 앱(주민 제보 수집). 전체 화면 지도 + 아래에서 올라오는 제보 창.

- 로그인(참여자 코드 + PIN) → 지도에서 [내 위치] → 서버가 구역 판정(core/geo_check) → [제보하기] 창에서 실내/실외·냄새·강도(1·2·3) → 저장.
- 구역은 GPS 로만 정한다. 구역 밖·정확도 불량이면 'rejected'로 저장되어 분석에서 제외된다.
- 냄새 종류는 묻지 않는다(odor_type='미구분'). 강도는 1 약함 / 2 보통 / 3 심함.
- REQUIRE_GPS=0 (테스트·시연)일 때만 구역 수동 선택을 허용하고 location_check='unverified'로 남긴다.
"""
import re
from uuid import uuid4
import pandas as pd
import streamlit as st
from core.auth import participant_pins, verify_participant
from core.config import ZONE_PUBLIC_NAMES, classify_collection_mode, now_kst, setting
from core.geo_check import ZONE_COLORS, ZONE_POINTS, check_location, zone_polygons
from core.observations import build_observation, observation_repository
from core.ui import CSS

INTENSITY = {1: '1 · 약함', 2: '2 · 보통', 3: '3 · 심함'}
APP_CSS = '''<style>
.block-container{max-width:100%!important;padding:0 0 0 0!important}
header[data-testid="stHeader"]{background:transparent}
.st-key-topbar{position:fixed;top:0;left:0;right:0;z-index:50;background:rgba(255,255,255,.94);backdrop-filter:blur(6px);
  padding:10px 14px 6px;border-bottom:1px solid #e3e8ee}
.st-key-topbar p{margin:0}
.st-key-mapwrap{margin-top:0;padding-bottom:120px}
.st-key-actionbar{position:fixed;left:0;right:0;bottom:0;z-index:55;background:rgba(255,255,255,.96);backdrop-filter:blur(6px);
  border-top:1px solid #e3e8ee;padding:8px 12px 10px;box-shadow:0 -4px 16px rgba(0,0,0,.08)}
.st-key-actionbar p{margin:0}
.st-key-sheet{position:fixed;left:0;right:0;bottom:0;z-index:60;background:#fff;border-radius:18px 18px 0 0;
  box-shadow:0 -6px 24px rgba(0,0,0,.18);padding:10px 16px 18px;max-height:88vh;overflow-y:auto;
  animation:slideup .28s ease-out}
.st-key-sheet::before{content:"";display:block;width:44px;height:5px;border-radius:3px;background:#cfd6de;margin:0 auto 8px}
@keyframes slideup{from{transform:translateY(100%)}to{transform:translateY(0)}}
.st-key-sheet div[role="radiogroup"]{flex-direction:row;gap:8px}
.st-key-sheet div[role="radiogroup"] label{border:1px solid #DCE4E9;border-radius:10px;padding:10px 12px;min-height:46px;flex:1;justify-content:center}
.st-key-sheet div[role="radiogroup"] label>div:first-child{display:none}
.zone-card{padding:10px 14px;border-radius:12px;margin:4px 0 8px}
.zone-card .k{font-size:12px;color:#57606a}.zone-card .v{font-size:20px;font-weight:700;line-height:1.25}.zone-card .s{font-size:12px;color:#57606a;margin-top:2px}
.legend{font-size:12px;color:#57606a}.legend i{display:inline-block;width:11px;height:11px;border-radius:3px;margin:0 4px 0 10px;vertical-align:-1px}
@media(max-width:600px){.st-key-sheet{padding:8px 12px 14px}}
</style>'''


def require_gps() -> bool:
    return setting('REQUIRE_GPS', '1') != '0'


def reset_form():
    for k in ('environment', 'judgment', 'intensity', 'draft', 'submission_key'):
        st.session_state.pop(k, None)


# ------------------------------------------------------------------ 로그인
def login():
    pins = participant_pins()
    st.markdown(CSS, unsafe_allow_html=True)
    st.title('냄새 기록')
    st.caption('제보할 자리에서 위치를 켜고 기록합니다. 위치는 구역 판정에만 쓰고 약 100 m 단위로만 저장됩니다.')
    with st.form('identity'):
        code = st.text_input('참여자 코드', placeholder='예: P01')
        pin = st.text_input('PIN', type='password') if pins else None
        zone = None
        if not require_gps():
            zone = st.selectbox('관측 구역(GPS 미사용 모드)', list(ZONE_PUBLIC_NAMES), index=None, format_func=lambda x: ZONE_PUBLIC_NAMES[x])
        if not pins:
            st.caption('PIN 로그인이 아직 설정되지 않아 코드만 확인합니다.')
        if st.form_submit_button('시작', use_container_width=True, type='primary'):
            code = code.strip().upper()
            if not re.fullmatch(r'[A-Za-z0-9_-]{2,24}', code):
                st.error('참여자 코드를 입력하세요.'); return
            if pins and not verify_participant(code, pin or ''):
                st.error('코드 또는 PIN 이 맞지 않습니다.'); return
            if not require_gps() and zone is None:
                st.error('관측 구역을 선택하세요.'); return
            st.session_state.participant = code
            st.session_state.manual_zone = zone
            st.session_state.pop('location', None)
            st.session_state.sheet = False
            reset_form(); st.rerun()


# ------------------------------------------------------------------ 지도
def zone_map(loc, height):
    import pydeck as pdk
    picked = loc.get('zone_id') if loc else None
    rows = []
    for z, ring in zone_polygons().items():
        r, g, b = ZONE_COLORS[z]
        rows.append(dict(name=ZONE_PUBLIC_NAMES.get(z, z), polygon=[list(p) for p in ring],
                         fill=[r, g, b, 150 if z == picked else 55], line=[r, g, b, 255 if z == picked else 140], width=5 if z == picked else 2))
    layers = [pdk.Layer('PolygonLayer', rows, get_polygon='polygon', get_fill_color='fill', get_line_color='line',
                        get_line_width='width', line_width_units='pixels', stroked=True, filled=True, pickable=True)]
    if loc and loc.get('lat') is not None:
        me = [dict(lon=loc['lon'], lat=loc['lat'], name='내 위치')]
        acc = max(40, min(float(loc.get('accuracy_m') or 40), 400))
        layers += [pdk.Layer('ScatterplotLayer', me, get_position='[lon, lat]', get_radius=acc, get_fill_color=[220, 38, 38, 45], stroked=True, get_line_color=[220, 38, 38, 160], line_width_min_pixels=1),
                   pdk.Layer('ScatterplotLayer', me, get_position='[lon, lat]', get_radius=28, radius_min_pixels=7, get_fill_color=[220, 38, 38, 255], stroked=True, get_line_color=[255, 255, 255, 255], line_width_min_pixels=2, pickable=True)]
        view = pdk.ViewState(latitude=loc['lat'], longitude=loc['lon'], zoom=13.4)
    else:
        view = pdk.ViewState(latitude=37.654, longitude=126.681, zoom=12.7)
    st.pydeck_chart(pdk.Deck(layers=layers, map_style=None, initial_view_state=view, tooltip={'text': '{name}'}), height=height)


def zone_card(loc):
    if loc is None:
        st.info('지도 아래 [내 위치]를 누르면 어느 구역에 있는지 표시됩니다.'); return
    if loc['status'] == 'verified':
        r, g, b = ZONE_COLORS[loc['zone_id']]
        st.markdown(f'<div class="zone-card" style="background:rgba({r},{g},{b},.14);border-left:6px solid rgb({r},{g},{b})"><div class="k">지금 있는 구역</div>'
                    f'<div class="v">{ZONE_PUBLIC_NAMES[loc["zone_id"]]}</div><div class="s">대표점에서 {loc["distance_m"]} m · 위치 정확도 약 {loc["accuracy_m"]} m · 이 구역으로 기록됩니다</div></div>', unsafe_allow_html=True)
    else:
        st.error(f"세 구역 밖이거나 위치가 부정확합니다 — {loc['reason']}")
        st.caption('이 상태로 제보하면 "위치 미확인"으로 저장되어 통계에 들어가지 않습니다. 색칠된 구역 안에서 다시 위치를 받아 주세요.')


# ------------------------------------------------------------------ 제보 창(아래에서 올라옴)
def report_sheet(repo, zone, loc, participant):
    with st.container(key='sheet'):
        head = st.columns([5, 1])
        head[0].markdown('**제보하기**')
        if head[1].button('✕', key='close_sheet', help='닫기'):
            st.session_state.sheet = False; reset_form(); st.rerun()
        if st.session_state.get('saved'):
            st.success('기록되었습니다. 고맙습니다.')
            st.caption(f'기록 번호 {st.session_state.saved[:8]} · 저장 후에는 수정할 수 없습니다.')
            if st.button('닫기', use_container_width=True):
                st.session_state.saved = None; st.session_state.sheet = False; reset_form(); st.rerun()
            return
        zone_card(loc)
        if zone is None:
            return
        env = st.radio('어디에서 확인했나요?', ['실외', '실내'], index=None, key='environment', horizontal=True)
        odor = st.radio('지금 냄새가 나나요?', ['나요', '안 나요', '모르겠어요'], index=None, key='judgment', horizontal=True)
        level = None
        if odor == '나요':
            level = st.radio('얼마나 심한가요?', [1, 2, 3], index=None, key='intensity', horizontal=True, format_func=lambda x: INTENSITY[x])
        ready = env is not None and odor is not None and (odor != '나요' or level is not None)
        st.caption(classify_collection_mode()[1] + f' · {now_kst():%m/%d %H:%M} KST 기준으로 기록')
        if st.button('기록 저장', type='primary', disabled=not ready or repo is None, use_container_width=True):
            key = st.session_state.setdefault('submission_key', str(uuid4()))
            odor_v = {'나요': True, '안 나요': False, '모르겠어요': None}[odor]
            draft = build_observation(participant, zone, 'outdoor' if env == '실외' else 'indoor', odor_v, level, None, key, location=loc)
            draft['received_at'] = now_kst().isoformat(); draft['collection_mode'] = classify_collection_mode()[0]
            try:
                repo.save_observation(draft)
            except Exception:
                st.error('서버 연결 실패 — 저장을 확인하지 못했습니다. 잠시 후 같은 내용으로 다시 눌러 주세요.')
            else:
                st.session_state.setdefault('own_ids', []).append(draft['observation_id'])
                st.session_state.saved = draft['observation_id']; reset_form(); st.rerun()


# ------------------------------------------------------------------ 메인
def main():
    st.set_page_config(page_title='냄새 기록', page_icon='assets/logo.svg', layout='wide', initial_sidebar_state='collapsed')
    try:
        repo, notice = observation_repository()
    except Exception:
        repo, notice = None, '서버 연결 실패 — 저장소 설정을 확인 중입니다.'
    if 'participant' not in st.session_state:
        st.caption(notice); login(); return
    participant = st.session_state.participant
    st.markdown(CSS + APP_CSS, unsafe_allow_html=True)

    # 위치 → 구역
    loc = st.session_state.get('location')
    if require_gps():
        zone = loc['zone_id'] if loc and loc['status'] == 'verified' else (loc['nearest_zone'] if loc else None)
    else:
        zone = st.session_state.manual_zone

    with st.container(key='topbar'):
        c = st.columns([4, 2, 2])
        c[0].markdown(f'**냄새 기록** · 참여자 {participant}')
        if c[1].button('내 기록', use_container_width=True):
            st.session_state.sheet = 'mine'
        if c[2].button('로그아웃', use_container_width=True):
            for k in ('participant', 'manual_zone', 'location', 'own_ids', 'sheet', 'saved'): st.session_state.pop(k, None)
            reset_form(); st.rerun()

    with st.container(key='mapwrap'):
        try:
            zone_map(loc, height=700)
        except Exception:
            st.caption('지도를 그릴 수 없습니다.')
        legend = ''.join(f'<i style="background:rgb{ZONE_COLORS[z]}"></i>{ZONE_PUBLIC_NAMES[z]}' for z in ZONE_POINTS)
        st.markdown(f'<div class="legend">{legend}<i style="background:rgb(220,38,38);border-radius:50%"></i>내 위치</div>', unsafe_allow_html=True)
        if not require_gps():
            st.caption(f'{ZONE_PUBLIC_NAMES[zone]}에서 관측합니다 (GPS 미사용 모드 · 위치 미검증)')
    with st.container(key='actionbar'):
        bar = st.columns([1, 1])
        with bar[0]:
            if require_gps():
                from core.geo_component import geo_locate
                raw = geo_locate(key='geo')
                if raw and raw.get('ok'):
                    st.session_state.location = check_location(raw.get('lat'), raw.get('lon'), raw.get('accuracy'))
                    if (st.session_state.location != loc):
                        st.rerun()
                elif raw and raw.get('message'):
                    st.warning(raw['message'])
        with bar[1]:
            if st.button('제보하기', type='primary', use_container_width=True, disabled=zone is None):
                st.session_state.sheet = True; st.session_state.saved = None; st.rerun()
        if zone is None and require_gps():
            st.caption('먼저 [내 위치 가져오기]를 눌러 주세요. 세 구역 중 어디에 있는지 확인된 뒤 제보할 수 있습니다.')

    if st.session_state.get('sheet') == 'mine':
        with st.container(key='sheet'):
            head = st.columns([5, 1]); head[0].markdown('**내 기록 (이 세션)**')
            if head[1].button('✕', key='close_mine'):
                st.session_state.sheet = False; st.rerun()
            if repo is None: st.info('저장 연결이 준비되지 않았습니다.')
            else:
                try:
                    own = set(st.session_state.get('own_ids', []))
                    rows = [r for r in repo.get_observations_by_participant(participant) if r['observation_id'] in own]
                    for r in rows:
                        label = '모르겠어요' if r['odor_detected'] is None else ('냄새 남' + (f" · 강도 {r['intensity']}" if r.get('intensity') else '') if r['odor_detected'] else '냄새 없음')
                        chk = {'verified': '위치 확인', 'rejected': '위치 미확인 · 제외', 'unverified': 'GPS 없음'}.get(r.get('location_check'), '')
                        st.write(f'{pd.Timestamp(r["observed_at"]).tz_convert("Asia/Seoul"):%m/%d %H:%M} · {ZONE_PUBLIC_NAMES.get(r["zone_id"], r["zone_id"])} · {label} · {chk}')
                    if not rows: st.info('이 세션에서 제출한 기록이 없습니다.')
                except Exception: st.error('서버 연결 실패 — 기록을 불러오지 못했습니다.')
    elif st.session_state.get('sheet'):
        report_sheet(repo, zone, loc, participant)


if __name__ == '__main__': main()
