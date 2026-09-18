from __future__ import annotations

from pathlib import Path
import argparse
import math

import numpy as np
import pandas as pd

from .geo import source_geometry


SEED = 20212
SCHEDULE_HOURS = [(7, 30), (12, 30), (18, 30), (21, 30)]


def _sigmoid(value: float) -> float:
    return 1 / (1 + math.exp(-value))


def generate_sample_data(output_dir: str | Path = "data/sample", seed: int = SEED) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    zones = pd.DataFrame([
        {"zone_id": "Z1", "name": "운양동 북부(한강변·라베니체 일대)", "rep_lat": 37.6620, "rep_lon": 126.6790, "boundary_note": "대표점 — 추후 실측 교체"},
        {"zone_id": "Z2", "name": "운양역 중심부", "rep_lat": 37.6540, "rep_lon": 126.6800, "boundary_note": "대표점 — 추후 실측 교체"},
        {"zone_id": "Z3", "name": "운양동 남부(모담산·학교 일대)", "rep_lat": 37.6470, "rep_lon": 126.6850, "boundary_note": "대표점 — 추후 실측 교체"},
    ])
    sources = pd.DataFrame([
        {"source_id": "D1", "name": "고양 일산서구 구산동·법곳동 일대", "source_type": "축산", "lat": 37.6790, "lon": 126.6980},
        {"source_id": "D2", "name": "김포 하성면·월곶면 일대", "source_type": "축산", "lat": 37.7200, "lon": 126.6300},
        {"source_id": "D3", "name": "김포 레코파크·계양천 방면", "source_type": "하수·분뇨처리", "lat": 37.6330, "lon": 126.7000},
    ])
    geometry = source_geometry(zones, sources)

    end = pd.Timestamp('2026-09-16 14:00', tz='Asia/Seoul')
    start = (end - pd.Timedelta(days=14)).normalize()
    weather_times = pd.date_range(start, end, freq="h", tz="Asia/Seoul")
    weather_rows = []
    for i, ts in enumerate(weather_times):
        hour = ts.hour
        night = hour >= 21 or hour <= 6
        # 매일 정오에는 D1 방향 바람이 불어도 건조한 조건에서는 대체로
        # 감지되지 않는 반례를 둔다. 그래서 '풍향만 보는 규칙'보다 시간·습도까지
        # 학습한 모델이 샘플 평가에서 실제로 나아질 여지가 생긴다.
        d1_event = True if hour in (12, 21) else rng.random() < (0.28 if night else 0.14)
        wd = (rng.normal(30, 10 if hour == 12 else 22) if d1_event else rng.uniform(0, 360)) % 360
        ws = float(rng.uniform(1.0, 2.5)) if hour == 12 else float(np.clip(rng.gamma(2.2, 0.85), 0.1, 7.5))
        humidity = float(np.clip((52 if hour == 12 else 61 + (14 if night else 0)) + rng.normal(0, 7 if hour == 12 else 9), 30, 98))
        rain = float(np.round(rng.gamma(1.4, 1.2), 1)) if rng.random() < 0.08 else 0.0
        temp = 23 + 4 * math.sin((hour - 7) / 24 * 2 * math.pi) + rng.normal(0, 1.2)
        pressure = 1008 + 4 * math.sin(i / 42) + rng.normal(0, 1.2)
        weather_rows.append({
            "지점": "(확인필요)", "지점명": "김포(예시)", "일시": ts.strftime("%Y-%m-%d %H:%M"),
            "풍향(deg)": round(wd, 1), "풍속(m/s)": round(ws, 1), "기온(°C)": round(temp, 1),
            "습도(%)": round(humidity, 1), "현지기압(hPa)": round(pressure, 1), "강수량(mm)": rain if rain else "-",
        })
    aws_weather = pd.DataFrame(weather_rows)
    weather = aws_weather.rename(columns={
        "지점": "station_id", "일시": "weather_at", "풍향(deg)": "wd", "풍속(m/s)": "ws",
        "기온(°C)": "temp", "습도(%)": "humidity", "현지기압(hPa)": "pressure", "강수량(mm)": "rain",
    }).drop(columns=["지점명"])
    weather["rain"] = pd.to_numeric(weather["rain"], errors="coerce").fillna(0)
    weather["quality_flag"] = "ok"

    scheduled_times = []
    for day in pd.date_range(start, periods=14, freq="D", tz="Asia/Seoul"):
        scheduled_times.extend(day + pd.Timedelta(hours=h, minutes=m) for h, m in SCHEDULE_HOURS)
    response_rate = {"Z1": 0.84, "Z2": 0.79, "Z3": 0.76}
    observers = [f"R{i:02d}" for i in range(1, 21)]
    assignments = {code: ["Z1", "Z2", "Z3"][i % 3] for i, code in enumerate(observers)}
    d1_bearings = geometry.query("source_id == 'D1'").set_index("zone_id")["bearing_deg"].to_dict()
    report_rows = []

    def make_report(code: str, zone: str, ts: pd.Timestamp, mode: str) -> None:
        wx_time = ts.floor("h")
        wx = weather.loc[pd.to_datetime(weather.weather_at).eq(wx_time.tz_localize(None))]
        if wx.empty:
            return
        w = wx.iloc[0]
        align = math.cos(math.radians(float(w.wd) - d1_bearings[zone]))
        night = ts.hour >= 21 or ts.hour <= 6
        midday = 11 <= ts.hour <= 13
        logit = -2.35 + 1.7 * align + 0.75 * (1 <= w.ws <= 3) + 1.20 * night + 0.035 * (w.humidity - 65) - 0.55 * (w.ws > 4) - 1.05 * (w.rain > 0) - 1.25 * midday
        zone_effect = {"Z1": 0.15, "Z2": 0.05, "Z3": -0.15}[zone]
        detected = int(rng.random() < _sigmoid(logit + zone_effect + rng.normal(0, 0.45)))
        intensity = int(np.clip(round(1 + 3.2 * _sigmoid(logit) + rng.normal(0, 0.8)), 1, 5)) if detected else 0
        odor_type = rng.choice(["축산분뇨", "하수", "기타", "모름"], p=[0.69, 0.12, 0.08, 0.11]) if detected else "없음"
        report_rows.append({
            "report_id": f"S{len(report_rows)+1:05d}", "observer_code": code, "zone_id": zone,
            "observed_at": ts.tz_localize(None).strftime("%Y-%m-%d %H:%M:%S"),
            "submitted_at": (ts + pd.Timedelta(minutes=int(rng.integers(0, 15)))).tz_localize(None).strftime("%Y-%m-%d %H:%M:%S"),
            "report_mode": mode, "odor": detected, "intensity": intensity, "odor_type": odor_type,
            "environment": "outdoor" if rng.random() > 0.06 else "indoor",
            "confidence": rng.choice(["low", "mid", "high"], p=[0.12, 0.53, 0.35]),
            "saw_forecast": int(rng.random() < 0.38), "memo": "",
        })

    for ts in scheduled_times:
        for code in observers:
            zone = assignments[code]
            if rng.random() < response_rate[zone]:
                make_report(code, zone, ts + pd.Timedelta(minutes=int(rng.integers(-12, 13))), "scheduled")
    n_extra = round(len(report_rows) * 0.08)
    for _ in range(n_extra):
        code = rng.choice(observers)
        ts = start + pd.Timedelta(minutes=int(rng.integers(0, 14 * 24 * 60)))
        make_report(str(code), assignments[str(code)], ts, "extra")
    reports = pd.DataFrame(report_rows)

    reports.to_csv(out / "reports.csv", index=False, encoding="utf-8-sig")
    aws_weather.to_csv(out / "weather_kimpo_aws.csv", index=False, encoding="utf-8-sig")
    sources.to_csv(out / "sources.csv", index=False, encoding="utf-8-sig")
    zones.to_csv(out / "zones.csv", index=False, encoding="utf-8-sig")
    geometry.to_csv(out / "source_geometry_by_zone.csv", index=False, encoding="utf-8-sig")
    return {"reports": reports, "weather": weather, "sources": sources, "zones": zones, "geometry": geometry}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="data/sample")
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args()
    generated = generate_sample_data(args.output, args.seed)
    print(" / ".join(f"{name}: {len(frame):,}" for name, frame in generated.items()))
