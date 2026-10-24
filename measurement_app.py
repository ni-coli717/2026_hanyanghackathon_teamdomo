"""냄새 기록 앱(주민 제보 수집). 로그인(참여자 코드 + PIN) → GPS 위치 → 서버 교차검증 → 관측 입력 → 저장.

- 구역은 주민이 고르지 않고 GPS 로 서버가 정한다(core/geo_check). 구역 밖·정확도 불량이면 'rejected'로 저장되어 분석에서 제외된다.
- REQUIRE_GPS=0 (테스트·시연)일 때만 구역 수동 선택을 허용하고 location_check='unverified'로 남긴다.
- PIN 은 secrets [participants] 에 해시로 둔다(python -m core.auth participant). 비어 있으면 코드만으로 들어가되 화면에 '로그인 미설정'을 표시한다.
"""
import re
from uuid import uuid4
import pandas as pd
import streamlit as st
from core.auth import participant_pins, verify_participant
from core.config import ZONE_PUBLIC_NAMES, classify_collection_mode, now_kst, setting
from core.geo_check import ZONE_COLORS, ZONE_POINTS, check_location, zone_polygons
from core.observations import build_observation, observation_repository
from core.public_ui import header


def reset():
    for k in ['environment', 'judgment', 'intensity', 'odor_type', 'draft', 'submission_key']:
        st.session_state.pop(k, None)
    st.session_state.step = 1
    st.session_state.answers = {}


def require_gps() -> bool:
    return setting('REQUIRE_GPS', '1') != '0'


def login(repo_ok: bool):
    pins = participant_pins()
    st.subheader('로그인')
    with st.form('identity'):
        code = st.text_input('참여자 코드', placeholder='예: P01')
        pin = st.text_input('PIN', type='password') if pins else None
        zone = None
        if not require_gps():
            zone = st.selectbox('관측 구역(GPS 미사용 모드)', list(ZONE_PUBLIC_NAMES), index=None, format_func=lambda x: ZONE_PUBLIC_NAMES[x])
        if not pins:
            st.caption('PIN 로그인이 아직 설정되지 않아 코드만 확인합니다(운영자가 secrets [participants] 를 채우면 PIN 이 필요해집니다).')
        if st.form_submit_button('시작', use_container_width=True):
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
            reset(); st.rerun()


def zone_map(loc):
    """구역 3개를 반투명 면으로, 내 위치를 점으로. 판정된 구역은 진하게·테두리 굵게."""
    import pydeck as pdk
    polys = zone_polygons()
    picked = loc.get('zone_id') if loc else None
    rows = []
    for z, ring in polys.items():
        r, g, b = ZONE_COLORS[z]
        rows.append(dict(zone=z, name=ZONE_PUBLIC_NAMES.get(z, z), polygon=[list(p) for p in ring],
                         fill=[r, g, b, 150 if z == picked else 55], line=[r, g, b, 255 if z == picked else 140],
                         width=5 if z == picked else 2))
    layers = [
        pdk.Layer('PolygonLayer', rows, get_polygon='polygon', get_fill_color='fill', get_line_color='line',
                  get_line_width='width', line_width_units='pixels', stroked=True, filled=True, pickable=True),
        pdk.Layer('TextLayer', [dict(name=ZONE_PUBLIC_NAMES.get(z, z).split('·')[0], lon=v[1], lat=v[0]) for z, v in ZONE_POINTS.items()],
                  get_position='[lon, lat]', get_text='name', get_size=13, get_color=[30, 41, 59, 230],
                  get_text_anchor='"middle"', get_alignment_baseline='"center"', font_family='sans-serif'),
    ]
    if loc and loc.get('lat') is not None:
        me = [dict(lon=loc['lon'], lat=loc['lat'], name='내 위치')]
        acc = max(40, min(float(loc.get('accuracy_m') or 40), 400))
        layers += [
            pdk.Layer('ScatterplotLayer', me, get_position='[lon, lat]', get_radius=acc, get_fill_color=[220, 38, 38, 45], stroked=True,
                      get_line_color=[220, 38, 38, 160], line_width_min_pixels=1),
            pdk.Layer('ScatterplotLayer', me, get_position='[lon, lat]', get_radius=28, radius_min_pixels=7, get_fill_color=[220, 38, 38, 255],
                      stroked=True, get_line_color=[255, 255, 255, 255], line_width_min_pixels=2, pickable=True),
        ]
        view = pdk.ViewState(latitude=loc['lat'], longitude=loc['lon'], zoom=13.2)
    else:
        view = pdk.ViewState(latitude=37.654, longitude=126.681, zoom=12.6)
    st.pydeck_chart(pdk.Deck(layers=layers, map_style=None, initial_view_state=view, tooltip={'text': '{name}'}), height=320)
    chips = ' '.join(f'<span style="display:inline-block;width:11px;height:11px;border-radius:3px;background:rgb{ZONE_COLORS[z]};margin:0 4px 0 10px"></span>{ZONE_PUBLIC_NAMES[z]}' for z in ZONE_POINTS)
    st.markdown(f'<div style="font-size:12px;color:#57606a;margin-top:-6px">{chips} <span style="display:inline-block;width:11px;height:11px;border-radius:50%;background:rgb(220,38,38);margin:0 4px 0 10px"></span>내 위치</div>', unsafe_allow_html=True)


def location_panel():
    """GPS 받기 → 서버 판정 → 지도. 반환: check 결과 dict 또는 None."""
    from core.geo_component import geo_locate
    st.subheader('지금 있는 자리')
    raw = geo_locate(key='geo')
    if raw and raw.get('ok'):
        st.session_state.location = check_location(raw.get('lat'), raw.get('lon'), raw.get('accuracy'))
    elif raw and raw.get('message'):
        st.warning(raw['message'])
    loc = st.session_state.get('location')
    try:
        zone_map(loc)
    except Exception:
        st.caption('지도를 그릴 수 없어 판정 결과만 표시합니다.')
    if loc is None:
        st.info('위치를 가져오면 어느 구역에 있는지 지도에 표시되고, 그 구역으로 제보가 기록됩니다. 세 구역 밖이면 분석에서 제외됩니다.')
        return None
    if loc['status'] == 'verified':
        r, g, b = ZONE_COLORS[loc['zone_id']]
        st.markdown(f'<div style="padding:14px 16px;border-radius:10px;background:rgba({r},{g},{b},0.14);border-left:6px solid rgb({r},{g},{b})">'
                    f'<div style="font-size:12px;color:#57606a">지금 있는 구역</div>'
                    f'<div style="font-size:22px;font-weight:700;line-height:1.3">{ZONE_PUBLIC_NAMES[loc["zone_id"]]}</div>'
                    f'<div style="font-size:13px;color:#57606a;margin-top:2px">구역 대표점에서 {loc["distance_m"]} m · 위치 정확도 약 {loc["accuracy_m"]} m · 이 구역으로 기록됩니다</div></div>',
                    unsafe_allow_html=True)
    else:
        st.error(f"세 구역 밖이거나 위치가 부정확합니다 — {loc['reason']}")
        st.caption('제보는 저장되지만 "위치 미확인"으로 표시되어 통계에 들어가지 않습니다. 색칠된 구역 안으로 이동해 다시 위치를 가져오세요.')
    return loc


def main():
    st.set_page_config(page_title='냄새 기록', page_icon='assets/logo.svg', layout='centered')
    header('냄새 기록', False)
    page = st.radio('메뉴', ['새 관측', '내 최근 기록', '참여 안내'], horizontal=True)
    try:
        repo, notice = observation_repository()
    except Exception:
        repo, notice = None, '서버 연결 실패 — 저장소 설정을 확인 중입니다.'
    st.caption(notice)
    if page == '참여 안내':
        st.write('정기 관측은 07:30 · 12:30 · 18:30 · 22:00 전후 15분입니다. 다른 시간에는 추가 제보로 자동 기록됩니다.')
        st.write('냄새가 없는 기록도 중요합니다. 기억으로 채우지 말고 지금 확인한 상태를 선택해 주세요.')
        st.write('제보할 때 휴대폰 위치(GPS)를 받아 어느 구역인지 서버가 정합니다. 관측 구역 밖이거나 위치가 부정확하면 그 제보는 분석에서 제외됩니다. 좌표는 약 100 m 단위로만 저장합니다.')
        st.caption('서버 연결이 필요하며 오프라인 저장·재전송은 제공하지 않습니다.')
        return
    if 'participant' not in st.session_state:
        login(repo is not None); return
    participant = st.session_state.participant
    top = st.columns([3, 1])
    top[0].caption(f'참여자 {participant}')
    if top[1].button('로그아웃', use_container_width=True):
        for k in ('participant', 'manual_zone', 'location', 'own_ids'): st.session_state.pop(k, None)
        reset(); st.rerun()
    if page == '내 최근 기록':
        if repo is None: st.info('저장 연결이 준비되지 않았습니다.'); return
        try:
            records = repo.get_observations_by_participant(participant)
            own = set(st.session_state.get('own_ids', []))
            records = [r for r in records if r['observation_id'] in own]
            for row in records:
                label = '판단 어려움' if row['odor_detected'] is None else ('느껴짐' if row['odor_detected'] else '느껴지지 않음')
                chk = {'verified': '위치 확인', 'rejected': '위치 미확인 · 제외', 'unverified': 'GPS 없음'}.get(row.get('location_check'), '')
                st.write(f'{pd.Timestamp(row["observed_at"]).tz_convert("Asia/Seoul"):%m/%d %H:%M} · {ZONE_PUBLIC_NAMES.get(row["zone_id"], row["zone_id"])} · {label} · {chk}')
            if not records: st.info('이 세션에서 제출한 기록이 없습니다.')
            st.caption('다른 세션의 기록은 표시하지 않습니다.')
        except Exception: st.error('서버 연결 실패 — 기록을 불러오지 못했습니다.')
        return
    if st.session_state.get('saved'):
        st.success('기록되었습니다.')
        st.write('냄새가 느껴지지 않은 기록도 중요한 자료입니다.')
        if st.button('새 관측 시작', use_container_width=True):
            st.session_state.saved = False
            reset(); st.rerun()
        return

    # 위치 → 구역
    if require_gps():
        loc = location_panel()
        zone = loc['zone_id'] if loc and loc['status'] == 'verified' else (loc['nearest_zone'] if loc else None)
    else:
        loc, zone = None, st.session_state.manual_zone
        st.caption(f'{ZONE_PUBLIC_NAMES[zone]}에서 관측합니다 (GPS 미사용 모드 · 위치 미검증)')
    if zone is None:
        return

    step = st.session_state.get('step', 1)
    answers = st.session_state.setdefault('answers', {})
    st.progress(min(step, 4) / 4)
    st.caption(classify_collection_mode()[1])
    with st.container(key='survey'):
        if step == 1:
            st.subheader('1 · 지금 어디에서 확인하고 있나요?')
            env = st.radio('관측 환경', ['실외', '실내'], index=None, key='environment')
            if st.button('다음', disabled=env is None, use_container_width=True):
                answers['environment'] = env
                st.session_state.step = 2; st.rerun()
        elif step == 2:
            st.subheader('2 · 지금 냄새가 느껴지나요?')
            odor = st.radio('냄새 확인', ['느껴짐', '느껴지지 않음', '판단하기 어려움'], index=None, key='judgment')
            if st.button('다음', disabled=odor is None, use_container_width=True):
                answers['judgment'] = odor
                st.session_state.step = 3 if odor == '느껴짐' else 4
                st.rerun()
        elif step == 3:
            st.subheader('3 · 냄새의 느낌을 알려주세요')
            intensity = st.radio('강도', [1, 2, 3, 4, 5], index=None, key='intensity', format_func=lambda x: f'{x} · ' + ['거의 느끼기 어려움', '약함', '분명함', '강함', '매우 강함'][x - 1])
            kind = st.radio('냄새 느낌', ['분뇨와 비슷함', '하수구와 비슷함', '탄내', '화학물질과 비슷함', '기타', '구분하기 어려움'], index=None, key='odor_type')
            if st.button('내용 확인', disabled=intensity is None or kind is None, use_container_width=True):
                answers['intensity'], answers['odor_type'] = intensity, kind
                st.session_state.step = 4; st.rerun()
        else:
            st.subheader('마지막 · 내용 확인')
            odor = {'느껴짐': True, '느껴지지 않음': False, '판단하기 어려움': None}[answers['judgment']]
            if 'draft' not in st.session_state:
                key = st.session_state.setdefault('submission_key', str(uuid4()))
                st.session_state.draft = build_observation(participant, zone, 'outdoor' if answers['environment'] == '실외' else 'indoor',
                                                           odor, answers.get('intensity'), answers.get('odor_type'), key, location=loc)
            draft = st.session_state.draft
            st.write(f'관측 구역: {ZONE_PUBLIC_NAMES[zone]}' + ('' if draft['location_check'] == 'verified' else ' · 위치 미확인(분석 제외)' if draft['location_check'] == 'rejected' else ' · GPS 없음'))
            st.write(f'관측 환경: {answers["environment"]}')
            st.write(f'냄새: {answers["judgment"]}')
            if odor is True: st.write(f'강도: {draft["intensity"]} · 냄새 느낌: {draft["odor_type"]}')
            st.caption(f'관측 시각: {pd.Timestamp(draft["observed_at"]):%m/%d %H:%M} KST')
            if st.button('기록 저장', type='primary', disabled=repo is None, use_container_width=True):
                try:
                    if not draft.get('_attempted'):
                        draft['received_at'] = now_kst().isoformat()
                        draft['collection_mode'] = classify_collection_mode()[0]
                    payload = {k: v for k, v in draft.items() if not k.startswith('_')}
                    draft['_attempted'] = True
                    repo.save_observation(payload)
                except Exception:
                    st.error('서버 연결 실패 — 저장을 확인하지 못했습니다. 같은 기록으로 다시 시도해 주세요.')
                else:
                    st.session_state.setdefault('own_ids', []).append(draft['observation_id'])
                    reset(); st.session_state.saved = True; st.rerun()
        if step > 1 and st.button('이전 단계', use_container_width=True):
            st.session_state.step = 2 if step == 4 and answers['judgment'] != '느껴짐' else step - 1
            st.session_state.pop('draft', None)
            st.rerun()


if __name__ == '__main__': main()
