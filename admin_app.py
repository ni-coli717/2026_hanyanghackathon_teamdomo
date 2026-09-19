from __future__ import annotations

from datetime import datetime, time
from pathlib import Path
import math

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import pydeck as pdk
import streamlit as st

from core.analysis import alignment_summary, chi_square, sector_rates
from core.features import make_windows, normalize_weather, response_summary
from core.geo import source_geometry
from core.model import CATEGORICAL_FEATURES, NUMERIC_FEATURES, load_bundle, save_bundle, train_models, training_status
from core.repo import SQLiteRepository, new_id
from core.risk import LEVEL_COLORS, direction_hint, risk_level, rule_probability, wind_name
from core.sample_data import generate_sample_data
from core.ui import CSS, badge, card, compass_svg, logo_wordmark, section
from ext.arduino import ArduinoDevice, available_ports
from ext.device_sim import SimulatedDevice, device_command


st.set_page_config(page_title="냄새 나침반", page_icon="assets/logo.svg", layout="wide", initial_sidebar_state="collapsed")
from core.auth import require_admin
require_admin()
st.markdown(CSS, unsafe_allow_html=True)

DATA_DIR = Path("data")
DB_PATH = DATA_DIR / "odor.db"
MODEL_PATH = DATA_DIR / "models" / "admin.joblib"
SOURCE_LABELS = {"D1": "고양 일산서구 구산동·법곳동 일대", "D2": "김포 하성면·월곶면 일대", "D3": "김포 레코파크·계양천 방면"}


@st.cache_resource
def get_repo() -> SQLiteRepository:
    from core.config import setting
    return SQLiteRepository(setting('ADMIN_DB_PATH',str(DB_PATH)))


def bootstrap(repo: SQLiteRepository) -> None:
    if repo.read("reports", sample=True).empty:
        provided = DATA_DIR / "provided"
        if (provided / "reports.csv").exists() and (provided / "weather.csv").exists():
            frames = {
                "reports": pd.read_csv(provided / "reports.csv"),
                "weather": pd.read_csv(provided / "weather.csv"),
                "sources": pd.read_csv(DATA_DIR / "sample" / "sources.csv"),
                "zones": pd.read_csv(DATA_DIR / "sample" / "zones.csv"),
            }
        else:
            frames = generate_sample_data(DATA_DIR / "sample")
        for name in ["reports", "weather", "sources", "zones"]:
            repo.replace(name, frames[name], sample=True)


def load_data(repo: SQLiteRepository, sample: bool):
    if not sample:
        from core.public_data import dashboard
        reports, weather, zones, sources, windows, geometry = dashboard('live')
        uploaded_weather = repo.read('weather',sample=False)
        if not uploaded_weather.empty:
            weather = normalize_weather(uploaded_weather)
            windows = make_windows(reports,weather,zones,sources)
        return reports,weather,zones,sources,windows,geometry
    reports = repo.read("reports", sample=sample)
    weather = normalize_weather(repo.read("weather", sample=sample))
    zones = repo.read("zones", sample=sample)
    sources = repo.read("sources", sample=sample)
    windows = make_windows(reports, weather, zones, sources) if not any(x.empty for x in [weather, zones, sources]) else pd.DataFrame()
    geometry = source_geometry(zones, sources) if not zones.empty and not sources.empty else pd.DataFrame()
    return reports, weather, zones, sources, windows, geometry


def current_features(weather: pd.DataFrame, geometry: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series | None]:
    if weather.empty or geometry.empty:
        return pd.DataFrame(), None
    row = weather.sort_values("weather_at").iloc[-1].copy()
    ts = pd.Timestamp(row.weather_at)
    hour = ts.hour + ts.minute / 60
    record = {
        "zone_id": "Z2", "wd_sin": np.sin(np.deg2rad(row.wd)) if pd.notna(row.wd) else np.nan,
        "wd_cos": np.cos(np.deg2rad(row.wd)) if pd.notna(row.wd) else np.nan, "ws": row.ws,
        "temp": row.temp, "humidity": row.humidity, "rain": row.rain, "pressure": row.pressure,
        "dp_3h": np.nan, "hour_sin": np.sin(2 * np.pi * hour / 24), "hour_cos": np.cos(2 * np.pi * hour / 24),
        "is_night": int(ts.hour >= 21 or ts.hour <= 6),
    }
    for _, g in geometry.query("zone_id == 'Z2'").iterrows():
        record[f"align_{g.source_id}"] = np.cos(np.deg2rad(float(row.wd) - g.bearing_deg)) if pd.notna(row.wd) and row.ws >= 0.5 else np.nan
    return pd.DataFrame([record]), row


def probability_for_now(features: pd.DataFrame, row: pd.Series | None, bundle) -> tuple[float | None, str]:
    if row is None or features.empty or pd.isna(row.ws) or pd.isna(row.wd):
        return None, "기상 자료 없음"
    if bundle is not None and "로지스틱 회귀" in bundle.models:
        try:
            needed = [c for c in NUMERIC_FEATURES + CATEGORICAL_FEATURES if c in features]
            return float(bundle.models["로지스틱 회귀"].predict_proba(features[needed])[0, 1]), "AI 모델"
        except Exception:
            pass
    return rule_probability(row, features.iloc[0].get("align_D1")), "규칙 기반 추정"


def render_header(sample_mode: bool) -> None:
    left, right = st.columns([3, 1])
    with left:
        st.markdown(logo_wordmark(), unsafe_allow_html=True)
    with right:
        st.caption("운양동 · KST · 운영자 전용")
    if sample_mode:
        st.markdown('<div class="sample-banner">제공 시나리오(가상) 데이터 — 실제 주민 관측 결과가 아닙니다</div>', unsafe_allow_html=True)


def render_home(weather, windows, geometry, probability, method, wx_row, hint):
    st.session_state.saw_forecast = True
    level = risk_level(probability)
    geom = geometry.query("zone_id == 'Z2'") if not geometry.empty else geometry
    active = hint["source_id"] if hint else None
    direction_copy = "무풍 — 방향 표시 보류" if hint is None else ("후보 간 구분 어려움" if hint["ambiguous"] else f'{hint["name"]}')
    prob_copy = "추정 보류" if probability is None or pd.isna(probability) else f"{probability:.0%} · {level}"
    st.markdown(f'''<div class="hero"><div><div class="eyebrow">ODOR COMPASS · 현재 상태</div><h1>바람은 어디서<br/>냄새를 데려올까?</h1><div class="subtitle">Odor Compass — a resident-participatory odor diagnosis app</div><p class="hero-copy">주민 체감 기록과 기상 조건을 함께 읽어, 지금의 악취 감지 가능성과 가장 관련 높은 유입 방향을 조심스럽게 추정합니다.</p><div>{badge("예비 실험 · 미보정", "#667985")} {badge(method, LEVEL_COLORS[level])}</div></div>{compass_svg(wx_row.wd if wx_row is not None else None, wx_row.ws if wx_row is not None else None, geom, active)}</div>''', unsafe_allow_html=True)
    latest_note = "관측 없음 — 위험 낮음으로 해석하지 않습니다"
    latest_value = "관측 없음"
    if not windows.empty:
        latest_at = windows.window_at.max()
        latest = windows[windows.window_at == latest_at]
        latest_value = f"{int(latest.n_detected.sum())} / {int(latest.n_observers.sum())}명"
        latest_note = f"{latest_at:%m월 %d일 %H:%M} · 구역 합계"
    weather_value = "자료 없음"
    weather_note = "추정 보류"
    if wx_row is not None:
        weather_value = f"{wind_name(wx_row.wd)}풍 {wx_row.ws:.1f} m/s"
        weather_note = f"{pd.Timestamp(wx_row.weather_at):%m월 %d일 %H:%M} · {wx_row.temp:.1f}°C · 습도 {wx_row.humidity:.0f}%"
    st.markdown(f'<div class="card-grid">{card("현재 위험 추정", prob_copy, "예비 실험 · 미보정", f"risk-{level.lower()}")}{card("현재 바람", weather_value, weather_note)}{card("최근 주민 관측", latest_value, latest_note)}</div>', unsafe_allow_html=True)
    st.markdown(section("유입 방향 안내", "풍향과 후보 방향의 정렬도를 비교합니다. 발생원이나 개별 시설을 판정하지 않습니다."), unsafe_allow_html=True)
    st.markdown(f'<div class="card"><div class="card-label">가장 관련 높은 유입 방향</div><div class="card-value">{direction_copy}</div><div class="card-note">{("정렬도 " + format(hint["align"], ".2f")) if hint else "풍속 0.5 m/s 미만에서는 방향을 표시하지 않습니다."}</div></div>', unsafe_allow_html=True)
    now = pd.Timestamp.now(tz="Asia/Seoul")
    candidates = [now.normalize() + pd.Timedelta(hours=h, minutes=30) for h in [7, 12, 18, 21]] + [now.normalize() + pd.Timedelta(days=1, hours=7, minutes=30)]
    next_obs = min(x for x in candidates if x > now)
    st.info(f"다음 정시 관측: {next_obs:%H:%M} · 약 {int((next_obs-now).total_seconds()//60)}분 후")
    a, b = st.columns(2)
    if a.button("냄새 기록하기", use_container_width=True, type="primary"):
        st.session_state.page = "③ 냄새 기록"
        st.rerun()
    if b.button("동네 지도 보기", use_container_width=True):
        st.session_state.page = "② 동네 지도"
        st.rerun()


def render_map(zones, sources, windows, wx_row, geometry, hint):
    st.markdown(section("동네 지도", "감지 없음과 관측 부족을 분리하고, 바람이 가는 방향과 후보 방위를 함께 표시합니다."), unsafe_allow_html=True)
    if zones.empty:
        st.warning("지도에 표시할 구역 데이터가 없습니다.")
        return
    latest = pd.DataFrame()
    if not windows.empty:
        selected = st.select_slider("관측창 되돌려 보기", options=sorted(windows.window_at.unique()), value=windows.window_at.max(), format_func=lambda x: pd.Timestamp(x).strftime("%m/%d %H:%M"))
        latest = windows[windows.window_at == selected][["zone_id", "n_observers", "n_detected", "detected_ratio", "median_intensity"]]
    z = zones.merge(latest, on="zone_id", how="left")
    z["enough"] = z.n_observers.fillna(0) >= 3
    def color(row):
        if not row.enough: return [154, 165, 174, 210]
        if row.detected_ratio >= .5: return [192, 86, 59, 220]
        if row.detected_ratio >= .2: return [217, 154, 60, 220]
        return [61, 139, 95, 220]
    z["color"] = z.apply(color, axis=1)
    z["radius"] = 120 + z.n_observers.fillna(0) * 24
    z["tooltip"] = z.apply(lambda r: f'{r.zone_id} · {r["name"]}\n관측 부족' if not r.enough else f'{r.zone_id} · {int(r.n_observers)}명 중 {int(r.n_detected)}명 감지\n강도 중앙값 {r.median_intensity:.1f}', axis=1)
    layers = [pdk.Layer("ScatterplotLayer", z, get_position="[rep_lon, rep_lat]", get_radius="radius", get_fill_color="color", get_line_color=[255,255,255], line_width_min_pixels=2, pickable=True)]
    hatch = z[~z.enough].copy(); hatch["pattern"] = "╱╱╱"
    if not hatch.empty:
        layers.append(pdk.Layer("TextLayer", hatch, get_position="[rep_lon, rep_lat]", get_text="pattern", get_color=[85,100,110], get_size=12))
    center = zones[zones.zone_id == "Z2"].iloc[0]
    line_rows = []
    for _, s in sources.iterrows():
        line_rows.append({"start": [center.rep_lon, center.rep_lat], "end": [s.lon, s.lat], "source_id": s.source_id, "color": [46,139,116,230] if hint and s.source_id == hint["source_id"] else [125,140,150,135]})
    if line_rows:
        layers.append(pdk.Layer("LineLayer", pd.DataFrame(line_rows), get_source_position="start", get_target_position="end", get_color="color", get_width=3, pickable=True))
    if wx_row is not None and pd.notna(wx_row.wd) and wx_row.ws >= .5:
        angle = math.radians((float(wx_row.wd) + 180) % 360)
        scale = .004 + min(float(wx_row.ws), 6) * .0015
        wind = pd.DataFrame([{"start": [center.rep_lon, center.rep_lat], "end": [center.rep_lon + math.sin(angle)*scale, center.rep_lat + math.cos(angle)*scale]}])
        layers.append(pdk.Layer("LineLayer", wind, get_source_position="start", get_target_position="end", get_color=[31,92,139,255], get_width=7))
    st.pydeck_chart(pdk.Deck(map_style=None, initial_view_state=pdk.ViewState(latitude=zones.rep_lat.mean(), longitude=zones.rep_lon.mean(), zoom=11.8, pitch=0), layers=layers, tooltip={"text": "{tooltip}"}), use_container_width=True)
    st.markdown('<div class="mini-note"><b>범례</b> · <span style="color:#3D8B5F">● 감지 낮음</span> · <span style="color:#D99A3C">● 일부 감지</span> · <span style="color:#C0563B">● 집단 감지</span> · <span class="hatched" style="padding:.1rem .4rem">관측 부족 ╱╱</span></div>', unsafe_allow_html=True)


def render_record(repo, sample_mode, zones):
    st.markdown('<div class="record-shell">', unsafe_allow_html=True)
    st.markdown(section("냄새 기록", "밖에서 20초 안에 끝내는 주민 관측입니다. 판단 어려움은 감지율 집계에서 제외됩니다."), unsafe_allow_html=True)
    query = st.query_params
    initial_code = str(query.get("r", st.session_state.get("observer_code", ""))).upper()
    zone_options = zones.zone_id.tolist() if not zones.empty else ["Z1", "Z2", "Z3"]
    initial_zone = str(query.get("z", st.session_state.get("zone_id", zone_options[0])))
    with st.form("report_form", clear_on_submit=False):
        a, b = st.columns(2)
        code = a.text_input("참여자 코드", value=initial_code, placeholder="예: R07 · 비워두면 GUEST")
        zone = b.selectbox("관측 구역", zone_options, index=zone_options.index(initial_zone) if initial_zone in zone_options else 0)
        now = pd.Timestamp.now(tz="Asia/Seoul")
        minutes = min(abs(now.minute - 30), abs(now.minute + 30))
        default_mode = "정시 관측" if minutes <= 30 and now.hour in [7, 12, 18, 21] else "추가 신고"
        mode = st.radio("관측 유형", ["정시 관측", "추가 신고"], index=0 if default_mode == "정시 관측" else 1, horizontal=True)
        judgment = st.radio("지금 냄새가 느껴지나요?", ["냄새 있음", "냄새 없음", "판단 어려움"], horizontal=True)
        intensity = st.slider("체감 강도", 1, 5, 3, disabled=judgment != "냄새 있음")
        odor_type = st.radio("냄새 유형", ["축산분뇨", "하수", "기타", "모름"], horizontal=True, disabled=judgment != "냄새 있음")
        c, d = st.columns(2)
        environment = c.radio("관측 환경", ["실외", "실내"], horizontal=True)
        confidence = d.radio("확신도", ["낮음", "보통", "높음"], index=1, horizontal=True)
        memo = st.text_input("메모 (선택)", max_chars=120, placeholder="특이사항만 짧게")
        submitted = st.form_submit_button("기록 저장", type="primary", use_container_width=True)
    if submitted:
        observer = code.strip().upper() or "GUEST"
        if observer != "GUEST" and not (len(observer) == 3 and observer[0] == "R" and observer[1:].isdigit()):
            st.error("참여자 코드는 R01처럼 입력하거나 비워주세요.")
        else:
            odor = 1 if judgment == "냄새 있음" else (0 if judgment == "냄새 없음" else None)
            now_naive = pd.Timestamp.now(tz="Asia/Seoul").tz_localize(None)
            row = {"report_id": new_id("R"), "observer_code": observer, "zone_id": zone, "observed_at": now_naive.isoformat(timespec="seconds"), "submitted_at": now_naive.isoformat(timespec="seconds"), "report_mode": "scheduled" if mode == "정시 관측" else "extra", "odor": odor, "intensity": intensity if odor == 1 else 0, "odor_type": odor_type if odor == 1 else ("없음" if odor == 0 else "모름"), "environment": "outdoor" if environment == "실외" else "indoor", "confidence": {"낮음":"low","보통":"mid","높음":"high"}[confidence], "saw_forecast": int(st.session_state.get("saw_forecast", False)), "memo": memo, "is_sample": int(sample_mode)}
            repo.insert("reports", row)
            st.session_state.observer_code, st.session_state.zone_id = observer if observer != "GUEST" else "", zone
            st.query_params.update({"r": observer if observer != "GUEST" else "", "z": zone})
            st.toast(f"저장됨 · {now_naive:%H:%M} · {zone}", icon="✅")
            st.success("기록이 저장되었습니다. 지도와 분석에 반영됩니다.")
    st.markdown('</div>', unsafe_allow_html=True)


def render_analysis(reports, windows, sources):
    st.markdown(section("분석 · 방향", "진단(H1)과 유입 방향 추정(H2)을 분리해 보여줍니다."), unsafe_allow_html=True)
    if windows.empty:
        st.warning("분석할 유효 관측창이 없습니다. 관측 부족은 감지 없음이 아닙니다.")
        return
    valid = windows.dropna(subset=["label"])
    if valid.empty:
        st.info('관측 부족 — 구역별 응답 3명 이상인 관측창이 없습니다.')
        return
    summary = response_summary(reports)
    period=f'{pd.Timestamp(reports.observed_at.min()):%Y-%m-%d} ~ {pd.Timestamp(reports.observed_at.max()):%Y-%m-%d}'
    st.markdown(f'<div class="card-grid">{card("관측 기간", period)}{card("전체 기록", f"{len(reports):,}건", f"유효 관측창 {len(valid):,}개")}{card("집단 감지 창", f"{int(valid.label.sum()):,}개", f"미정 {int(windows.label.isna().sum()):,}개")}</div>', unsafe_allow_html=True)
    if not summary.empty:
        formatted = summary.copy(); formatted["응답률"] = formatted["응답률"].map(lambda x: f"{x:.1%}")
        st.dataframe(formatted[["zone_id", "응답 수", "참여자", "응답률"]], hide_index=True, use_container_width=True)
    st.markdown(section("H1 · 언제 감지되는가", "시간대와 기상 조건을 비교합니다."), unsafe_allow_html=True)
    valid = valid.copy(); valid["시각"] = valid.window_at.dt.strftime("%H:%M")
    hourly = valid.groupby("시각").agg(감지율=("label", "mean"), 표본=("label", "size")).reset_index()
    fig = px.bar(hourly, x="시각", y="감지율", text=hourly.감지율.map(lambda x:f"{x:.0%}"), color_discrete_sequence=["#1F5C8B"])
    fig.add_trace(go.Scatter(x=hourly.시각, y=hourly.표본 / max(hourly.표본.max(),1), name="표본(상대)", line=dict(color="#2E8B74")))
    fig.update_layout(yaxis_tickformat=".0%", height=330, margin=dict(l=10,r=10,t=20,b=10), plot_bgcolor="white")
    st.plotly_chart(fig, use_container_width=True)
    weather_long = valid.melt(id_vars="label", value_vars=[c for c in ["ws","humidity","pressure","temp"] if c in valid], var_name="기상 변수", value_name="값")
    st.plotly_chart(px.box(weather_long, x="기상 변수", y="값", color=weather_long.label.map({0:"미감지",1:"감지"}), color_discrete_map={"미감지":"#9AA5AE","감지":"#C0563B"}, height=340), use_container_width=True)
    st.markdown(section("H2 · 어떤 방향에서 유입되는가", "방위별 감지율과 후보 방향 정렬도를 비교합니다."), unsafe_allow_html=True)
    rates = sector_rates(valid)
    st.plotly_chart(px.bar_polar(rates, r="감지율", theta="sector", color="감지율", color_continuous_scale=[[0,"#DCE7EC"],[1,"#1F5C8B"]], range_r=[0,max(.01,rates.감지율.max()*1.15)], height=430), use_container_width=True)
    align = alignment_summary(valid, sources.source_id.tolist())
    display = align.copy()
    for col in ["정렬 시 감지율","기타 감지율"]: display[col] = display[col].map(lambda x: "—" if pd.isna(x) else f"{x:.1%}")
    display["감지율 배수"] = display["감지율 배수"].map(lambda x: "—" if pd.isna(x) else f"{x:.2f}배")
    st.dataframe(display, hide_index=True, use_container_width=True)
    p = chi_square(valid)
    best_sector = rates.sort_values("감지율", ascending=False).iloc[0]
    best_candidate = align.sort_values("감지율 배수", ascending=False).iloc[0] if not align.empty else None
    conclusion = f'감지율이 가장 높은 방위는 {best_sector.sector}(n={int(best_sector.표본)})입니다.'
    if best_candidate is not None and pd.notna(best_candidate["감지율 배수"]): conclusion += f' 후보 {best_candidate["후보"]} 정렬도가 높을 때 감지율은 {best_candidate["감지율 배수"]:.2f}배입니다.'
    conclusion += " 이는 유입 가능성을 시사하지만 원인 시설을 확정하지 않습니다."
    st.markdown(f'<div class="mini-note"><b>자동 결론</b><br>{conclusion}<br><small>8방위 카이제곱 p={p:.4f}</small></div>' if p is not None else f'<div class="mini-note"><b>자동 결론</b><br>{conclusion}<br><small>표본 부족으로 카이제곱 검정 보류</small></div>', unsafe_allow_html=True)
    st.download_button("집계 CSV 내려받기", valid.to_csv(index=False).encode("utf-8-sig"), "odor_windows.csv", "text/csv")


def render_ai(repo, windows, sample_mode):
    st.markdown(section("AI 실험", "규칙 기준선과 분류 모델을 같은 마지막 날짜 자료에서 비교합니다."), unsafe_allow_html=True)
    ok, message = training_status(windows)
    positives = int(windows.label.fillna(0).sum()) if not windows.empty else 0
    st.markdown(f'<div class="card-grid">{card("양성 관측창", f"{positives}개", "최소 10개")}{card("학습 조건", "충족" if ok else "자료 부족", message, "risk-low" if ok else "risk-hold")}{card("평가 원칙", "시간 기준 분할", "마지막 날짜 · 예비 평가")}</div>', unsafe_allow_html=True)
    st.markdown('<div class="mini-note"><b>모델 구조</b> · 기준선 1(다수 클래스) · 기준선 2(D1 정렬 규칙) · 로지스틱 회귀(L2, balanced) · 랜덤포레스트(200개, depth 4)<br>입력: 풍향 sin/cos, 풍속, 기온, 습도, 강수, 시간, 구역, 기압, 정렬도. 같은 창의 감지 정보는 입력하지 않습니다.</div>', unsafe_allow_html=True)
    col1, col2 = st.columns(2)
    train_clicked = col1.button("모델 학습", disabled=not ok, type="primary", use_container_width=True)
    retrain_clicked = col2.button("새 기록으로 재학습", disabled=not ok, use_container_width=True)
    if train_clicked or retrain_clicked:
        try:
            previous = st.session_state.get("bundle") or load_bundle(MODEL_PATH)
            bundle = train_models(windows)
            model_path = save_bundle(bundle, MODEL_PATH)
            st.session_state.bundle = bundle
            st.session_state.previous_metrics = previous.metrics if previous else None
            for _, m in bundle.metrics[bundle.metrics.모델.isin(["로지스틱 회귀","랜덤포레스트"])].iterrows():
                repo.insert("model_runs", {"run_id": new_id("M"), "run_at": bundle.trained_at, "model_name": m["모델"], "n_train": int(m["학습 창"]), "n_test": int(m["평가 창"]), "n_pos": int(m["평가 양성"]), "accuracy": float(m["정확도"]), "precision": float(m["정밀도"]), "recall": float(m["재현율"]), "f1": float(m["F1"]), "model_path": model_path, "is_sample": int(sample_mode)})
            st.success("재학습 완료 — 새 모델은 기존 실행과 별도 이력으로 저장했습니다.")
        except Exception as exc:
            st.error(f"학습을 완료하지 못했습니다: {exc}")
    if not ok:
        st.info('자료 부족 — 이전 데이터에서 학습한 모델의 결과는 표시하지 않습니다.')
        return
    bundle = st.session_state.get("bundle") or load_bundle(MODEL_PATH)
    if bundle:
        m = bundle.metrics.copy()
        st.dataframe(m.style.format({"정확도":"{:.2f}","정밀도":"{:.2f}","재현율":"{:.2f}","F1":"{:.2f}"}), hide_index=True, use_container_width=True)
        choice = st.selectbox("혼동행렬 모델", list(bundle.confusion))
        cm = bundle.confusion[choice]
        st.plotly_chart(px.imshow(cm, text_auto=True, x=["예측 미감지","예측 감지"], y=["실제 미감지","실제 감지"], color_continuous_scale=[[0,"#F3F6F8"],[1,"#1F5C8B"]], aspect="auto", height=310), use_container_width=True)
        imp = bundle.feature_importance.sort_values("절대 영향도", ascending=False).groupby("모델").head(10)
        st.plotly_chart(px.bar(imp, x="절대 영향도", y="변수", color="모델", orientation="h", barmode="group", color_discrete_sequence=["#1F5C8B","#2E8B74"], height=430), use_container_width=True)
        st.caption("정렬도 변수의 순위는 같은 풍향에서 파생된 연관 신호이며 독립적인 발생원 증거가 아닙니다. 모든 점수는 예비 실험 · 미보정입니다.")


def render_device(repo, probability, level):
    st.markdown(section("우리 집 대응 · 확장", "위험 신호를 기기 명령으로 연결하되, 명령 확인과 공기 개선 효과를 구분합니다."), unsafe_allow_html=True)
    ports = available_ports()
    mode = st.radio("기기 연결", ["가상 기기", "아두이노"], horizontal=True, index=0, disabled=not ports)
    if not ports:
        st.markdown(badge("실기기 미연결 — 시뮬레이션", "#667985"), unsafe_allow_html=True)
        mode = "가상 기기"
    selected_port = st.selectbox("시리얼 포트", ports, disabled=mode != "아두이노") if ports else None
    settings_col, state_col = st.columns([1,1])
    with settings_col:
        st.markdown("#### 자동 대응 설정")
        quiet = st.toggle("야간 소음 제한", value=True)
        max_minutes = st.slider("최대 지속시간", 5, 120, 30, 5)
        manual_stop = st.toggle("수동 중지", value=False)
        start_threshold=st.slider('시작 임계값',0.50,0.95,0.65,0.05)
        stop_threshold=st.slider('해제 임계값',0.10,start_threshold-0.05,min(0.45,start_threshold-0.05),0.05)
        st.caption('명령 평가 버튼을 누를 때만 설정을 평가합니다. 백그라운드 자동 제어나 연속 감시는 제공하지 않습니다.')
    if "fan_on" not in st.session_state: st.session_state.fan_on = False
    if "fan_started_at" not in st.session_state: st.session_state.fan_started_at = None
    now = pd.Timestamp.now(tz="Asia/Seoul")
    is_quiet = quiet and (now.hour >= 22 or now.hour < 7)
    duration_reached = bool(st.session_state.fan_started_at and (now.tz_localize(None) - st.session_state.fan_started_at).total_seconds() > max_minutes*60)
    p = float(probability) if probability is not None and not pd.isna(probability) else 0.0
    command, next_state, reason = device_command(p, st.session_state.fan_on, manual_stop or level=='HOLD', is_quiet, duration_reached,start_threshold,stop_threshold)
    with state_col:
        st.markdown("#### 기기 상태")
        st.markdown(card("현재 대응", "작동 중" if st.session_state.fan_on else "대기", reason, "risk-high" if st.session_state.fan_on else ""), unsafe_allow_html=True)
        if st.button("현재 위험도로 명령 평가", use_container_width=True, type="primary"):
            device = SimulatedDevice()
            if mode == "아두이노" and selected_port:
                try: device = ArduinoDevice(selected_port)
                except Exception as exc:
                    st.warning(f"아두이노 연결 실패 — 가상 기기로 전환했습니다: {exc}")
            send_command = command or ('FAN:ON' if next_state else 'FAN:OFF')
            response = device.send(send_command)
            if response.ok and command:
                st.session_state.fan_on = next_state
                st.session_state.fan_started_at = now.tz_localize(None) if next_state else None
            if not response.ok:
                st.session_state.fan_on=False
                st.warning('기기 응답 미확인 — 실제 정지 여부를 직접 확인하세요.')
            repo.insert("device_log", {"log_id":new_id("D"), "logged_at":now.tz_localize(None).isoformat(timespec="seconds"), "mode":device.mode, "command":send_command, "acknowledged":int(response.ok), "risk_level":level, "gas_value":device.read_gas(), "outcome":None, "note":reason})
            st.success("명령 전송 완료 · 기기 응답 확인" if response.ok else "작동 확인 중 — 응답 미확인")
            st.caption("이 상태는 공기 개선 완료를 뜻하지 않습니다.")
            if hasattr(device,'close'): device.close()
    st.markdown(section("대응 후 평가", "기기 작동 기록은 실외 악취 학습 데이터와 분리됩니다."), unsafe_allow_html=True)
    outcome = st.radio("10분 후 실내 냄새가 줄었나요?", ["평가 전", "줄었다", "비슷하다", "심해졌다"], horizontal=True)
    if st.button("평가 저장", disabled=outcome == "평가 전"):
        repo.insert("device_log", {"log_id":new_id("D"), "logged_at":now.tz_localize(None).isoformat(timespec="seconds"), "mode":"assessment", "command":None, "acknowledged":0, "risk_level":level, "gas_value":None, "outcome":outcome, "note":"실내 대응 후 평가"})
        st.toast("대응 후 평가가 별도 기록으로 저장되었습니다.", icon="✅")


def evaluation_markdown(path):
    """Date ranges use '~'; Streamlit markdown would turn '~a~b' into strikethrough."""
    return path.read_text(encoding="utf-8").replace("~", r"\~") if path.exists() else "평가 파일 없음"


def render_odor_model():
    """odor_model: evaluation, retraining, operating settings and provisional coordinates."""
    import subprocess, sys
    from core import analysis_service as service
    st.markdown(section("예측 모델", "주민 화면의 화살표·나침반·공기질 관리가 모두 이 모델 결과를 사용합니다."), unsafe_allow_html=True)
    settings = service.load_settings()
    model, info = service.load_model()
    active = settings["active_model"]
    state_note = "정상" if info["ok"] else f"추정 보류 · {info['reason']}"
    high = f"{settings.get('thr_high') or info.get('thr_valid', 0.75):.2f}"
    cards = (card("주민 화면 모델", "번들" if active == "bundled" else active, "예비 실험·미보정")
             + card("로딩 상태", state_note, info["path"], "risk-low" if info["ok"] else "risk-hold")
             + card("높음 임계값", high, "운영 설정 · 공인 기준 아님"))
    st.markdown(f'<div class="card-grid">{cards}</div>', unsafe_allow_html=True)
    evaluation, retrain, config, coords, device_tab = st.tabs(["평가", "재학습", "운영 설정", "좌표", "기기"])

    with evaluation:
        st.markdown(badge("번들 평가 · odor_model/artifacts", "#667985"), unsafe_allow_html=True)
        st.markdown(evaluation_markdown(service.BUNDLED_EVALUATION))
        for run in service.retrained_runs():
            with st.expander(f"재학습 평가 · {run}" + (" · 주민 화면 적용 중" if run == active else "")):
                path = service.RETRAINED_DIR / run / "evaluation.md"
                st.markdown(evaluation_markdown(path))

    with retrain:
        workbooks = sorted((DATA_DIR / "provided").glob("*.xlsx"))
        if not workbooks:
            st.warning("data/provided에 관측 워크북(xlsx)이 없습니다.")
        else:
            source = st.selectbox("학습 자료", workbooks, format_func=lambda p: p.name)
            st.caption("새 모델은 data/models/odor/<시각>에 따로 저장됩니다. 아래에서 선택해 적용하기 전까지 주민 화면은 바뀌지 않습니다.")
            if st.button("모델 재학습", type="primary"):
                out = service.RETRAINED_DIR / datetime.now().strftime("%Y%m%d-%H%M%S")
                with st.spinner("학습 중"):
                    done = subprocess.run([sys.executable, "-m", "odor_model.train", "--data", str(source), "--out", str(out),
                                           "--geo", str(service.GEO_PATH)], cwd=str(service.ROOT), capture_output=True,
                                          text=True, encoding="utf-8", errors="replace", timeout=900)
                if done.returncode == 0:
                    st.success(f"재학습 완료 · {out.name} · 기존 평가와 별도로 저장했습니다.")
                else:
                    st.error("재학습 실패")
                    st.code(done.stderr[-3000:])
        options = ["bundled"] + service.retrained_runs()
        choice = st.selectbox("주민 화면에 쓸 모델", options, index=options.index(active) if active in options else 0,
                              format_func=lambda v: "번들 모델(odor_model/artifacts)" if v == "bundled" else f"재학습 · {v}")
        if st.button("주민 화면에 적용", disabled=choice == active):
            candidate, check = service.load_model(choice)
            if candidate is None:
                st.error(f"적용하지 않았습니다 · {check['reason']}")
            else:
                service.save_settings({**settings, "active_model": choice})
                st.success("적용했습니다. 조회 앱은 다음 새로고침부터 이 모델을 씁니다.")
                st.rerun()

    with config:
        st.markdown(badge("운영 설정 · 공인 기준 아님", "#9A6B1F"), unsafe_allow_html=True)
        a, b = st.columns(2)
        thr_mid = a.number_input("보통 임계값", 0.05, 0.95, float(settings["thr_mid"]), 0.05)
        thr_high = b.number_input("높음 임계값", 0.05, 0.99, float(settings.get("thr_high") or info.get("thr_valid", 0.75)), 0.05)
        calm = a.number_input("약풍 기준 (m/s)", 0.0, 3.0, float(settings["calm_ms"]), 0.1)
        align = b.number_input("정렬도 최소", 0.0, 1.0, float(settings["align_min"]), 0.05)
        obs = a.number_input("바람 레이어 전환 감지율", 0.0, 1.0, float(settings["obs_rate_min"]), 0.05)
        start_n = b.number_input("on_streak · 켜기: 높음 연속 횟수", 1, 6, int(settings["auto"]["start_count"]))
        stop_n = a.number_input("off_streak · 끄기: 낮음 연속 횟수", 1, 6, int(settings["auto"]["stop_count"]))
        new = {**settings, "thr_mid": thr_mid, "thr_high": thr_high, "calm_ms": calm, "align_min": align, "obs_rate_min": obs,
               "auto": {**settings["auto"], "start_count": int(start_n), "stop_count": int(stop_n)}}
        changed = new != settings
        if changed:
            st.warning("운영 설정·공인 기준 아님 · 저장하면 주민 화면의 표시 기준이 바뀝니다.")
        if thr_mid >= thr_high:
            st.error("보통 임계값은 높음 임계값보다 작아야 합니다.")
        if st.button("설정 저장", disabled=not changed or thr_mid >= thr_high):
            service.save_settings(new)
            st.success("저장했습니다 · 운영 설정·공인 기준 아님")
            st.rerun()

    with coords:
        geo = service.load_geo()
        st.markdown(badge("임시 좌표", "#9A6B1F"), unsafe_allow_html=True)
        st.caption("구역 대표점과 후보 지역은 운영자가 검증해야 합니다. 후보는 지역·시설 유형 수준으로만 적습니다. 후보 ID는 모델 특징과 연결되어 바꿀 수 없습니다.")
        zones_df = pd.DataFrame([{"id": k, **v} for k, v in geo["zones"].items()])
        cands_df = pd.DataFrame([{"id": k, **v} for k, v in geo["candidates"].items()])
        zones_edit = st.data_editor(zones_df, disabled=["id", "app_zone_id"], hide_index=True, key="geo_zones", use_container_width=True)
        cands_edit = st.data_editor(cands_df, disabled=["id", "app_source_id"], hide_index=True, key="geo_cands", use_container_width=True)
        if st.button("좌표 저장"):
            clean = lambda row: {k: (float(v) if k in ("lat", "lon") else v) for k, v in row.items() if k != "id" and pd.notna(v)}
            updated = {**geo, "provisional": True,
                       "zones": {r["id"]: clean(r) for r in zones_edit.to_dict("records")},
                       "candidates": {r["id"]: clean(r) for r in cands_edit.to_dict("records")}}
            service.save_geo(updated)
            st.success("저장했습니다 · 임시 좌표")
            st.rerun()

    with device_tab:
        from core.device import read_status
        st.markdown(badge("운영 설정 · 공인 기준 아님", "#9A6B1F"), unsafe_allow_html=True)
        st.caption("공기질 관리 기기는 주민 조회 앱 프로세스가 USB로 연결합니다. 이 화면은 그 앱이 남긴 상태 파일(data/device_status.json)을 읽기만 합니다. "
                   f"켜기·끄기 규칙: 높음 {settings['auto']['start_count']}회 연속 켜기, 낮음 {settings['auto']['stop_count']}회 연속 끄기, 자료 없음은 판단 보류.")
        status = read_status()
        if not status:
            st.info("연결된 기기 없음 · 조회 앱에서 아직 기기를 연결한 적이 없습니다.")
        else:
            fan = {True: "가동 중", False: "대기 중"}.get(status.get("device_fan"), "기기 상태 알 수 없음") if status.get("connected") else "기기 상태 알 수 없음"
            port = (status.get("port") or "없음") + (" · 시뮬레이터" if status.get("simulator") else "")
            cards = (card("기기 상태", status.get("status", "—"), f"{fan} · {status.get('mode', '—')}")
                     + card("포트", port, f"기록 시각 {status.get('updated', '—')}")
                     + card("마지막 ACK", status.get("last_ack") or "없음", status.get("last_ack_at") or ""))
            st.markdown(f'<div class="card-grid">{cards}</div>', unsafe_allow_html=True)
            st.markdown(f"**마지막 오류** · {status.get('last_error') or '없음'} · 기기 버튼 제보 저장 {status.get('reports_saved', 0)}건")
            log = pd.DataFrame(status.get("log") or [], columns=["at", "dir", "line"])
            st.dataframe(log.iloc[::-1].rename(columns={"at": "시각", "dir": "방향", "line": "내용"}), hide_index=True, use_container_width=True)
            if st.button("새로 고침"):
                st.rerun()


def render_settings(repo, sample_mode):
    st.markdown(section("설정 · 데이터", "샘플과 실데이터는 SQLite 안에서도 분리 저장됩니다."), unsafe_allow_html=True)
    st.warning("공개 클라우드의 로컬 SQLite는 임시 저장소입니다. 앱 재시작·재배포 시 주민 기록이 사라질 수 있으므로, 실제 주민 수집 전에는 repo.py에 Supabase 또는 Google Sheets 구현체를 연결해야 합니다.")
    mode = st.radio("데이터 소스", ["샘플", "실데이터"], index=0 if sample_mode else 1, horizontal=True)
    if (mode == "샘플") != sample_mode:
        st.session_state.sample_mode = mode == "샘플"
        st.rerun()
    if sample_mode:
        st.caption("제공 워크북 2026-06-18~2026-09-16 시나리오 · 참여자 20명 · 원본 record_origin=simulated")
        if st.button("샘플 데이터 재생성"):
            provided = DATA_DIR / "provided"
            if (provided / "reports.csv").exists():
                frames = {"reports":pd.read_csv(provided / "reports.csv"), "weather":pd.read_csv(provided / "weather.csv"), "sources":pd.read_csv(DATA_DIR / "sample" / "sources.csv"), "zones":pd.read_csv(DATA_DIR / "sample" / "zones.csv")}
            else:
                frames = generate_sample_data(DATA_DIR / "sample")
            for name in ["reports", "weather", "sources", "zones"]: repo.replace(name, frames[name], sample=True)
            st.success("제공 시나리오 CSV에서 DB를 다시 구성했습니다.")
            st.rerun()
    st.markdown("#### 실데이터 CSV 가져오기")
    table = st.selectbox("대상", ["reports", "weather", "sources", "zones"])
    upload = st.file_uploader("UTF-8 또는 CP949 CSV", type="csv")
    if upload and st.button("실데이터로 가져오기", type="primary"):
        try:
            try: frame = pd.read_csv(upload, encoding="utf-8-sig")
            except UnicodeDecodeError:
                upload.seek(0); frame = pd.read_csv(upload, encoding="cp949")
            if table == "weather": frame = normalize_weather(frame)
            repo.replace(table, frame, sample=False)
            st.success(f"{table} {len(frame):,}행을 실데이터 영역에 저장했습니다.")
        except Exception as exc:
            st.error(f"가져오기 실패: {exc}")
    st.markdown("#### 개인정보 원칙")
    st.info("실명·주소·연락처 컬럼은 스키마에 없습니다. 외부 공유에는 구역·관측창 집계만 사용하세요.")


repo = get_repo()
bootstrap(repo)
if "sample_mode" not in st.session_state: st.session_state.sample_mode = True
if "page" not in st.session_state: st.session_state.page = str(st.query_params.get("page", "① 홈"))
sample_mode = bool(st.session_state.sample_mode)
try:
    reports, weather, zones, sources, windows, geometry = load_data(repo, sample_mode)
except Exception:
    st.error('서버 연결 실패 — 공유 저장소 설정을 확인하세요.')
    st.stop()
features, wx_row = current_features(weather, geometry)
bundle = st.session_state.get("bundle") or load_bundle(MODEL_PATH)
probability, method = probability_for_now(features, wx_row, bundle)
hint = direction_hint(wx_row, geometry.query("zone_id == 'Z2'")) if wx_row is not None and not geometry.empty else None
level = risk_level(probability)

render_header(sample_mode)
pages = ["④ 분석·방향", "⑤ AI 실험", "⑥ 우리 집 대응", "⑦ 예측 모델", "⚙ 설정"]
if st.session_state.page not in pages: st.session_state.page = pages[0]
page = st.radio("화면", pages, index=pages.index(st.session_state.page), horizontal=True, label_visibility="collapsed", key="top_navigation")
st.session_state.page = page

if page == "① 홈": render_home(weather, windows, geometry, probability, method, wx_row, hint)
elif page == "② 동네 지도": render_map(zones, sources, windows, wx_row, geometry, hint)
elif page == "③ 냄새 기록": render_record(repo, sample_mode, zones)
elif page == "④ 분석·방향": render_analysis(reports, windows, sources)
elif page == "⑤ AI 실험": render_ai(repo, windows, sample_mode)
elif page == "⑥ 우리 집 대응": render_device(repo, probability, level)
elif page == "⑦ 예측 모델": render_odor_model()
else: render_settings(repo, sample_mode)

st.divider()
st.caption("냄새 나침반 · 유입 방향 추정은 원인 시설 판정이 아닙니다 · 관측 부족은 감지 없음이 아닙니다")
