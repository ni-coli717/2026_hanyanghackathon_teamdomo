import html
import base64
import math
from urllib.parse import urlparse
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from .config import ZONE_PUBLIC_NAMES, measurement_url
from .ui import CSS, badge, compass_svg

PUBLIC_CSS = '''<style>
.block-container{max-width:1180px;padding-top:4rem;padding-bottom:100px}
div[role="radiogroup"]{position:static;overflow:visible;flex-wrap:wrap;}
div[role="radiogroup"] label{white-space:normal;min-height:44px;align-items:center}
.st-key-survey div[role="radiogroup"]{flex-direction:column;background:white}
.st-key-survey div[role="radiogroup"] label{min-height:56px;width:100%;border:1px solid #DCE4E9;margin:3px 0}
.compass-wrap{min-height:0}.compass-svg{width:190px}
.wind-panel{text-align:center}.wind-copy{text-align:left;line-height:1.6}.wind-copy small{color:#647684}
.js-plotly-plot .maplibregl-map{position:relative;overflow:hidden}
.js-plotly-plot .maplibregl-control-container{position:absolute;bottom:0;right:0;z-index:2;font-size:10px;line-height:16px;background:rgba(255,255,255,.9)}
.js-plotly-plot .maplibregl-ctrl-attrib{padding:0 4px}.js-plotly-plot .maplibregl-ctrl-attrib a{color:#405569}
.st-key-viewer_menu div[role="radiogroup"] label{padding:.35rem .45rem}
.st-key-viewer_menu div[role="radiogroup"] label>div:first-child{display:none}
.st-key-viewer_menu div[role="radiogroup"] label p{white-space:nowrap}
.participate{position:fixed;bottom:16px;right:24px;z-index:99;background:#1F5C8B;color:white!important;border-radius:12px;padding:14px 22px;box-shadow:0 4px 18px #1234;text-decoration:none;font-weight:700}
@media(max-width:600px){.block-container{padding:3.5rem .7rem 100px}h1{font-size:1.55rem!important}h2{font-size:1.2rem!important}.participate{bottom:10px;left:12px;right:12px;text-align:center}.compass-svg{width:95px;flex-shrink:0}.wind-panel{display:flex;align-items:center;gap:10px}.wind-copy{font-size:.88rem}.compass-wrap{min-height:0}div[role="radiogroup"]{gap:0;padding:.2rem}div[role="radiogroup"] label{padding:.25rem .35rem;font-size:.85rem;min-width:0}.st-key-viewer_menu div[role="radiogroup"]{flex-wrap:nowrap}.st-key-viewer_menu div[role="radiogroup"] label{padding:.15rem .2rem}.st-key-viewer_menu p{font-size:.77rem}.card-value{font-size:1.2rem}}</style>'''


def header(title, demo):
    st.markdown(CSS + PUBLIC_CSS, unsafe_allow_html=True)
    st.markdown(f'**{title}**　' + (badge('시연 데이터', '#667985') if demo else ''), unsafe_allow_html=True)


def participation():
    url = measurement_url()
    if url and urlparse(url).scheme in ('http','https'):
        st.markdown(f'<a class="participate" href="{html.escape(url, quote=True)}" target="_blank" rel="noopener">냄새 기록 참여 →</a>', unsafe_allow_html=True)
    else:
        st.button('냄새 기록 참여 · 연결 준비 중', disabled=True, use_container_width=True)
        st.caption('로컬 실행: python -m streamlit run measurement_app.py --server.port 8502')


def state(n, ratio):
    if pd.isna(n) or n < 3: return '관측 부족', '#9AA5AE'
    if ratio >= .5: return '집단 감지', '#C0563B'
    if ratio >= .2: return '일부 감지', '#D99A3C'
    return '감지 낮음', '#3D8B5F'


def map_view(zones, latest, wx, key):
    if latest.empty:
        latest = pd.DataFrame(columns=['zone_id','n_observers','n_detected','detected_ratio','median_intensity','window_at'])
    merged = zones.merge(latest, on='zone_id', how='left')
    colors, texts = [], []
    for _, r in merged.iterrows():
        status, color = state(r.n_observers, r.detected_ratio)
        colors.append(color)
        texts.append(f'{ZONE_PUBLIC_NAMES.get(r.zone_id,r["name"])} · {status}')
    fig = go.Figure(go.Scattermap(lat=merged.rep_lat.tolist(), lon=merged.rep_lon.tolist(),
        mode='markers+text', marker=dict(size=25,color=colors), text=texts,textfont=dict(color='#1B2A38',size=12),
        textposition='top center', customdata=merged.zone_id.tolist(), hovertemplate='%{text}<extra></extra>'))
    if wx is not None and pd.notna(wx.wd) and pd.notna(wx.ws) and wx.ws >= .5:
        lat, lon = 37.658, 126.690
        a = math.radians(float(wx.wd)+180)
        end = (lat+math.cos(a)*.004, lon+math.sin(a)*.005)
        fig.add_trace(go.Scattermap(lat=[lat,end[0]],lon=[lon,end[1]],mode='lines',line=dict(color='#1F5C8B',width=4),hoverinfo='skip'))
        for turn in (-145,145):
            b = a+math.radians(turn)
            fig.add_trace(go.Scattermap(lat=[end[0],end[0]+math.cos(b)*.001],lon=[end[1],end[1]+math.sin(b)*.0012],mode='lines',line=dict(color='#1F5C8B',width=3),hoverinfo='skip'))
    fig.update_layout(map=dict(style='open-street-map',center=dict(lat=37.654,lon=126.683),zoom=12.4),
        height=310,margin=dict(l=0,r=0,t=0,b=0),showlegend=False,clickmode='event+select')
    selected = None
    try:
        event = st.plotly_chart(fig, key=key, use_container_width=True, on_select='rerun', selection_mode='points')
        points = event.selection.points
        if points: selected = points[0].get('customdata')
    except Exception:
        st.warning('지도 로딩 실패 — 아래 구역 선택에서 관측을 확인할 수 있습니다.')
    st.caption('회색: 관측 부족 · 초록: 감지 낮음 · 주황: 일부 감지 · 빨강: 집단 감지 | 화살표: 바람 이동')
    ids = merged.zone_id.tolist()
    if selected in ids:
        st.session_state[key+'_zone'] = selected
    return merged


def public_compass(wx):
    if wx is None or pd.isna(wx.ws) or pd.isna(wx.wd):
        st.info('기상자료 없음 · 방향 표시 보류')
        return
    from .risk import wind_name
    raw=compass_svg(wx.wd,wx.ws,pd.DataFrame(),None,compact=True)
    svg=raw[raw.index('<svg'):raw.index('</svg>')+6]
    encoded=base64.b64encode(svg.encode()).decode()
    description = '무풍 — 방향 표시 보류' if wx.ws < .5 else f'바람은 <b>{wind_name(wx.wd)}</b>에서 불어 <b>{wind_name((wx.wd+180)%360)}</b>으로 이동합니다.'
    st.markdown(f'<div class="wind-panel"><img class="compass-svg" alt="바람이 불어오는 방향 나침반" src="data:image/svg+xml;base64,{encoded}"/><div class="wind-copy">{description}<br><small>기상 기준: {pd.Timestamp(wx.weather_at):%m/%d %H:%M} KST</small></div></div>',unsafe_allow_html=True)
