import re
from uuid import uuid4
import pandas as pd
import streamlit as st
from core.config import ZONE_PUBLIC_NAMES, classify_collection_mode, now_kst
from core.observations import build_observation, observation_repository
from core.public_ui import header


def reset():
    for k in ['environment','judgment','intensity','odor_type','draft','submission_key']:
        st.session_state.pop(k,None)
    st.session_state.step = 1
    st.session_state.answers = {}


def main():
    st.set_page_config(page_title='냄새 기록',page_icon='assets/logo.svg',layout='centered')
    header('냄새 기록',False)
    page = st.radio('메뉴',['새 관측','내 최근 기록','참여 안내'],horizontal=True)
    try:
        repo, notice = observation_repository()
    except Exception:
        repo,notice = None,'서버 연결 실패 — 저장소 설정을 확인 중입니다.'
    st.caption(notice)
    if page == '참여 안내':
        st.write('정기 관측은 07:30 · 12:30 · 18:30 · 22:00 전후 15분입니다. 다른 시간에는 추가 제보로 자동 기록됩니다.')
        st.write('냄새가 없는 기록도 중요합니다. 기억으로 채우지 말고 지금 확인한 상태를 선택해 주세요.')
        st.caption('서버 연결이 필요하며 오프라인 저장·재전송은 제공하지 않습니다. 코드와 구역은 이 세션에서만 기억합니다.')
        return
    if 'participant' not in st.session_state:
        st.subheader('처음 한 번만 알려주세요')
        with st.form('identity'):
            code = st.text_input('참여자 코드',placeholder='예: R07')
            zone = st.selectbox('관측 구역',list(ZONE_PUBLIC_NAMES),index=None,format_func=lambda x:ZONE_PUBLIC_NAMES[x])
            if st.form_submit_button('관측 시작',use_container_width=True):
                if not re.fullmatch(r'[A-Za-z0-9_-]{2,24}',code.strip()) or zone is None:
                    st.error('참여자 코드와 관측 구역을 입력하세요.')
                else:
                    st.session_state.participant = code.strip().upper()
                    st.session_state.zone = zone
                    reset()
                    st.rerun()
        return
    participant, zone = st.session_state.participant,st.session_state.zone
    st.caption(f'{ZONE_PUBLIC_NAMES[zone]}에서 관측합니다 · {participant}')
    if page == '내 최근 기록':
        if repo is None: st.info('저장 연결이 준비되지 않았습니다.'); return
        try:
            records = repo.get_observations_by_participant(participant)
            # Codes are not passwords: only show records submitted by this session.
            own = set(st.session_state.get('own_ids',[]))
            records = [r for r in records if r['observation_id'] in own]
            for row in records:
                label = '판단 어려움' if row['odor_detected'] is None else ('느껴짐' if row['odor_detected'] else '느껴지지 않음')
                st.write(f'{pd.Timestamp(row["observed_at"]).tz_convert("Asia/Seoul"):%m/%d %H:%M} · {label}')
            if not records: st.info('이 세션에서 제출한 기록이 없습니다.')
            st.caption('참여자 코드는 인증 수단이 아니므로 다른 세션의 개별 기록은 공개하지 않습니다.')
        except Exception: st.error('서버 연결 실패 — 기록을 불러오지 못했습니다.')
        return
    if st.session_state.get('saved'):
        st.success('기록되었습니다.')
        st.write('냄새가 느껴지지 않은 기록도 중요한 자료입니다.')
        if st.button('새 관측 시작',use_container_width=True):
            st.session_state.saved = False
            reset(); st.rerun()
        return
    step = st.session_state.get('step',1)
    answers = st.session_state.setdefault('answers',{})
    st.progress(min(step,4)/4)
    st.caption(classify_collection_mode()[1])
    with st.container(key='survey'):
        if step == 1:
            st.subheader('1 · 지금 어디에서 확인하고 있나요?')
            env = st.radio('관측 환경',['실외','실내'],index=None,key='environment')
            if st.button('다음',disabled=env is None,use_container_width=True):
                answers['environment']=env
                st.session_state.step=2; st.rerun()
        elif step == 2:
            st.subheader('2 · 지금 냄새가 느껴지나요?')
            odor = st.radio('냄새 확인',['느껴짐','느껴지지 않음','판단하기 어려움'],index=None,key='judgment')
            if st.button('다음',disabled=odor is None,use_container_width=True):
                answers['judgment']=odor
                st.session_state.step=3 if odor=='느껴짐' else 4
                st.rerun()
        elif step == 3:
            st.subheader('3 · 냄새의 느낌을 알려주세요')
            intensity = st.radio('강도',[1,2,3,4,5],index=None,key='intensity',format_func=lambda x:f'{x} · '+['거의 느끼기 어려움','약함','분명함','강함','매우 강함'][x-1])
            kind = st.radio('냄새 느낌',['분뇨와 비슷함','하수구와 비슷함','탄내','화학물질과 비슷함','기타','구분하기 어려움'],index=None,key='odor_type')
            if st.button('내용 확인',disabled=intensity is None or kind is None,use_container_width=True):
                answers['intensity'],answers['odor_type']=intensity,kind
                st.session_state.step=4; st.rerun()
        else:
            st.subheader('마지막 · 내용 확인')
            odor = {'느껴짐':True,'느껴지지 않음':False,'판단하기 어려움':None}[answers['judgment']]
            if 'draft' not in st.session_state:
                key = st.session_state.setdefault('submission_key',str(uuid4()))
                st.session_state.draft=build_observation(participant,zone,'outdoor' if answers['environment']=='실외' else 'indoor',odor,answers.get('intensity'),answers.get('odor_type'),key)
            draft = st.session_state.draft
            st.write(f'관측 구역: {ZONE_PUBLIC_NAMES[zone]}')
            st.write(f'관측 환경: {answers["environment"]}')
            st.write(f'냄새: {answers["judgment"]}')
            if odor is True: st.write(f'강도: {draft["intensity"]} · 냄새 느낌: {draft["odor_type"]}')
            st.caption(f'관측 시각: {pd.Timestamp(draft["observed_at"]):%m/%d %H:%M} KST')
            if st.button('기록 저장',type='primary',disabled=repo is None,use_container_width=True):
                try:
                    if not draft.get('_attempted'):
                        draft['received_at']=now_kst().isoformat()
                        draft['collection_mode']=classify_collection_mode()[0]
                    payload={k:v for k,v in draft.items() if not k.startswith('_')}
                    draft['_attempted']=True
                    repo.save_observation(payload)
                except Exception:
                    st.error('서버 연결 실패 — 저장을 확인하지 못했습니다. 같은 기록으로 다시 시도해 주세요.')
                else:
                    st.session_state.setdefault('own_ids',[]).append(draft['observation_id'])
                    reset(); st.session_state.saved=True; st.rerun()
        if step>1 and st.button('이전 단계',use_container_width=True):
            st.session_state.step=2 if step==4 and answers['judgment']!='느껴짐' else step-1
            st.session_state.pop('draft',None)
            st.rerun()


if __name__ == '__main__': main()
