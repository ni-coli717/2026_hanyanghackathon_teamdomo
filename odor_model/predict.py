"""운양동 악취 예측: 현재 기상(nowcast) 또는 기상청 단기예보(forecast)로 구역별 감지 가능성·유입 방향 추정.

CLI 예시
  # 현재 기상 1건
  python predict.py now --time "2026-09-19 22:00" --wind-dir 67.5 --wind-speed 0.8 --humidity 82 --temp 21 --rain 0
  # 예보 CSV(열: datetime, wind_from_deg, wind_speed, humidity_pct, temperature_c, rain_1h_mm)
  python predict.py forecast --csv sample_forecast.csv --out forecast_result.csv
  # 기상청 단기예보 API(서비스키 필요, 인터넷 필요)
  python predict.py kma --key <SERVICE_KEY> --nx 55 --ny 128 --out forecast_result.csv

출력 항목은 모두 '예비 실험·미보정' 상태이며 운영용 위험 등급이나 확률로 해석하지 않는다.
"""
from __future__ import annotations
import argparse, json, os, sys, datetime as dt
import numpy as np, pandas as pd, joblib
try:
    from .features import make_features, candidate_table, alignment, deg_to_sector, ZONES, sector_to_deg
except ImportError:  # python predict.py 직접 실행
    from features import make_features, candidate_table, alignment, deg_to_sector, ZONES, sector_to_deg

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(HERE, "artifacts", "odor_model.joblib")
CALM_MS = 0.5          # 운영 설정: 이 미만이면 방향 표시 보류(공인 기준 아님)
ALIGN_MIN = 0.5        # 정렬도 0.5(45도) 이상인 후보만 '정렬'로 표시
ALIGN_TIE = 0.15       # 상위 두 후보 정렬도 차이가 이보다 작으면 '여러 방향 가능'


def load_model(path=MODEL_PATH):
    return joblib.load(path)


def level(p: float, thr_valid: float, thr_mid: float = 0.5) -> str:
    if p >= thr_valid: return "높음"
    if p >= thr_mid: return "보통"
    return "낮음"


def predict_rows(rows: pd.DataFrame, m: dict, settings: dict | None = None) -> pd.DataFrame:
    """rows: window_start, wind_from_deg, wind_speed, humidity_pct, temperature_c, rain_1h_mm (+ optional source, basis).
    각 행을 3개 구역으로 확장해 예측. settings: 운영 설정(thr_mid, thr_high, calm_ms, align_min, align_tie) — 공인 기준 아님."""
    s = settings or {}
    thr_mid = float(s.get("thr_mid", 0.5)); thr_high = float(s.get("thr_high", m["thr_valid"]))
    calm_ms = float(s.get("calm_ms", CALM_MS)); align_min = float(s.get("align_min", ALIGN_MIN))
    align_tie = float(s.get("align_tie", ALIGN_TIE))
    geo = m["geo"]; ct = candidate_table(geo)
    out, inputs, slots = [], [], []
    for _, r in rows.iterrows():
        missing = [k for k in ("wind_from_deg", "wind_speed", "humidity_pct", "temperature_c") if pd.isna(r.get(k))]
        for z in ZONES:
            base = dict(window_start=pd.to_datetime(r.window_start), zone_id=z, zone_name=geo["zones"][z]["name"],
                        basis=r.get("basis", "input"), source=r.get("source", ""))
            if missing:
                out.append(dict(**base, status="추정 보류", reason="핵심 기상 결측: " + ",".join(missing))); continue
            inputs.append(dict(window_start=r.window_start, zone_id=z, wind_from_deg=float(r.wind_from_deg),
                               wind_speed=float(r.wind_speed), humidity_pct=float(r.humidity_pct),
                               temperature_c=float(r.temperature_c), rain_1h_mm=float(r.get("rain_1h_mm", 0) or 0)))
            slots.append((len(out), base)); out.append(None)
    if not inputs:
        return pd.DataFrame(out)
    # 모든 행×구역을 한 번에 예측한다(행마다 예측할 때와 결과 동일).
    X = make_features(pd.DataFrame(inputs), geo)[m["feature_columns"]]
    P = m["detect_model"].predict_proba(X)[:, 1]
    TP = m["type_model"].predict_proba(X)
    for (pos, base), inp, p, tp in zip(slots, inputs, P, TP):
        z = base["zone_id"]; p = float(p)
        types = dict(zip(m["type_classes"], [round(float(v), 3) for v in tp]))
        wd = inp["wind_from_deg"]; ws = inp["wind_speed"]
        rec = dict(**base, status="예비 추정", p_detect=round(p, 3), level=level(p, thr_high, thr_mid),
                   wind_from_deg=wd, wind_from_sector=deg_to_sector(wd), move_to_deg=(wd + 180) % 360,
                   move_to_sector=deg_to_sector((wd + 180) % 360), wind_speed=ws,
                   type_top=max(types, key=types.get), type_probs=json.dumps(types, ensure_ascii=False))
        if ws < calm_ms:
            rec.update(direction_status="방향 보류(약풍)", aligned_candidates="", direction_note=f"풍속 {calm_ms:g} m/s 미만")
        else:
            sub = ct[ct.zone_id == z].copy()
            sub["align_score"] = [alignment(wd, b) for b in sub.bearing_deg]
            sub = sub.sort_values("align_score", ascending=False)
            top = sub[sub.align_score >= align_min]
            if len(top) == 0:
                rec.update(direction_status="정렬 후보 없음", aligned_candidates="", direction_note="후보 방위와 45도 이상 차이")
            elif len(top) >= 2 and (top.align_score.iloc[0] - top.align_score.iloc[1]) < align_tie:
                rec.update(direction_status="여러 방향 가능",
                           aligned_candidates="; ".join(f"{n}({t},{al:.2f})" for n, t, al in zip(top.cand_name, top.cand_type, top.align_score)),
                           direction_note="상위 후보 정렬도 차이 작음")
            else:
                rec.update(direction_status="정렬",
                           aligned_candidates="; ".join(f"{n}({t},{al:.2f})" for n, t, al in zip(top.cand_name, top.cand_type, top.align_score)),
                           direction_note=f"{deg_to_sector(wd)}쪽에서 유입 추정")
        out[pos] = rec
    return pd.DataFrame(out)


def summarize(res: pd.DataFrame) -> str:
    lines = []
    for _, r in res.iterrows():
        t = pd.to_datetime(r.window_start).strftime("%m.%d %H:%M")
        if r.status != "예비 추정":
            lines.append(f"[{t}] {r.zone_name}: {r.status} — {r.reason}"); continue
        d = f"{r.wind_from_sector}쪽에서 들어와 {r.move_to_sector}쪽으로 이동" if r.direction_status != "방향 보류(약풍)" else "방향 보류(약풍)"
        s = f"[{t}] {r.zone_name}: 유입 가능성 {r.level} (p={r.p_detect:.2f}) · {d} · 유형 {r.type_top}"
        if r.direction_status not in ("방향 보류(약풍)",): s += f" · {r.direction_status}"
        if r.aligned_candidates: s += f" · {r.aligned_candidates}"
        lines.append(s)
    return "\n".join(lines)


# ------------------------------------------------------------------ 기상청 단기예보
def fetch_kma_forecast(service_key: str, nx: int = 55, ny: int = 128, base: dt.datetime | None = None) -> pd.DataFrame:
    """기상청 단기예보 조회(getVilageFcst). 김포 운양동 격자는 nx=55, ny=128 근처(운영자가 확인).
    VEC 풍향(도), WSD 풍속(m/s), REH 습도(%), TMP 기온(℃), PCP 1시간 강수량(문자열)."""
    import requests
    base = base or dt.datetime.now()
    # 단기예보 발표 시각: 02,05,08,11,14,17,20,23시(+10분 이후 제공)
    hours = [2, 5, 8, 11, 14, 17, 20, 23]
    bt = max([h for h in hours if h <= base.hour - (1 if base.minute < 10 else 0)] or [23])
    bd = base if bt <= base.hour else base - dt.timedelta(days=1)
    url = "http://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst"
    params = dict(serviceKey=service_key, pageNo=1, numOfRows=1000, dataType="JSON",
                  base_date=bd.strftime("%Y%m%d"), base_time=f"{bt:02d}00", nx=nx, ny=ny)
    js = requests.get(url, params=params, timeout=20).json()
    items = js["response"]["body"]["items"]["item"]
    df = pd.DataFrame(items)
    piv = df.pivot_table(index=["fcstDate", "fcstTime"], columns="category", values="fcstValue", aggfunc="first").reset_index()
    def pcp(v):
        if pd.isna(v) or str(v).startswith("강수없음"): return 0.0
        try: return float(str(v).replace("mm", "").replace("미만", "").strip())
        except Exception: return 0.0
    out = pd.DataFrame(dict(window_start=pd.to_datetime(piv.fcstDate + piv.fcstTime, format="%Y%m%d%H%M"),
                            wind_from_deg=pd.to_numeric(piv.get("VEC"), errors="coerce"),
                            wind_speed=pd.to_numeric(piv.get("WSD"), errors="coerce"),
                            humidity_pct=pd.to_numeric(piv.get("REH"), errors="coerce"),
                            temperature_c=pd.to_numeric(piv.get("TMP"), errors="coerce"),
                            rain_1h_mm=piv.get("PCP", pd.Series([None] * len(piv))).map(pcp)))
    out["basis"] = "kma_forecast"; out["source"] = f"단기예보 {bd:%Y-%m-%d} {bt:02d}00 발표"
    return out


def read_forecast_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    col = {c.lower(): c for c in df.columns}
    ren = {}
    for k, alts in dict(window_start=["datetime", "time", "window_start", "fcst_time"], wind_from_deg=["wind_from_deg", "vec", "wind_dir"],
                        wind_speed=["wind_speed", "wsd", "wind_speed_ms"], humidity_pct=["humidity_pct", "reh", "humidity"],
                        temperature_c=["temperature_c", "tmp", "temp"], rain_1h_mm=["rain_1h_mm", "pcp", "rain"]).items():
        for a in alts:
            if a in col: ren[col[a]] = k; break
    df = df.rename(columns=ren)
    df["window_start"] = pd.to_datetime(df.window_start)
    df["wind_from_deg"] = df.wind_from_deg.map(sector_to_deg)
    if "rain_1h_mm" not in df: df["rain_1h_mm"] = 0.0
    if "basis" not in df: df["basis"] = "forecast_csv"
    return df


def main():
    ap = argparse.ArgumentParser(); sp = ap.add_subparsers(dest="cmd", required=True)
    n = sp.add_parser("now"); n.add_argument("--time", required=True); n.add_argument("--wind-dir", required=True)
    n.add_argument("--wind-speed", type=float, required=True); n.add_argument("--humidity", type=float, required=True)
    n.add_argument("--temp", type=float, required=True); n.add_argument("--rain", type=float, default=0.0); n.add_argument("--out")
    f = sp.add_parser("forecast"); f.add_argument("--csv", required=True); f.add_argument("--out")
    k = sp.add_parser("kma"); k.add_argument("--key", required=True); k.add_argument("--nx", type=int, default=55)
    k.add_argument("--ny", type=int, default=128); k.add_argument("--out")
    a = ap.parse_args()
    m = load_model()
    if a.cmd == "now":
        rows = pd.DataFrame([dict(window_start=pd.to_datetime(a.time), wind_from_deg=sector_to_deg(a.wind_dir), wind_speed=a.wind_speed,
                                  humidity_pct=a.humidity, temperature_c=a.temp, rain_1h_mm=a.rain, basis="observed_input")])
    elif a.cmd == "forecast":
        rows = read_forecast_csv(a.csv)
    else:
        rows = fetch_kma_forecast(a.key, a.nx, a.ny)
    res = predict_rows(rows, m)
    res.insert(0, "model_status", m["status"])
    print(summarize(res))
    if a.out:
        res.to_csv(a.out, index=False, encoding="utf-8-sig"); print("saved", a.out)


if __name__ == "__main__":
    main()
