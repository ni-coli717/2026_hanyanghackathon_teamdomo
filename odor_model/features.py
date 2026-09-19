"""운양동 악취 예측 모델 공통 모듈: 관측 데이터 → 구역·시간창 학습표, 특징 생성, 후보 방향 정렬도.

방향 규칙
- 기상청 풍향(wind_from_deg)은 바람이 '불어오는' 방향이다.
- 냄새가 이동하는 방향 = (wind_from_deg + 180) % 360
- 후보 발생원이 구역에서 볼 때 bearing_deg 방위에 있으면, 풍향이 bearing_deg와 가까울수록 정렬도가 높다.
"""
from __future__ import annotations
import math, json, os
import numpy as np
import pandas as pd

ZONES = ["U01", "U02", "U03"]
SECTORS = ["북","북북동","북동","동북동","동","동남동","남동","남남동","남","남남서","남서","서남서","서","서북서","북서","북북서"]
SEC_DEG = {s: i * 22.5 for i, s in enumerate(SECTORS)}
TYPE_CLASSES = ["축산계 추정", "하수계 추정", "기타/미확인"]

# 임시 좌표: 구역 대표점과 후보 지역 좌표는 운영자가 검증해야 한다(기획서 §5).
# 후보는 '지역·시설 유형' 수준이며 특정 시설을 원인으로 판정하지 않는다.
DEFAULT_GEO = {
    "zones": {
        "U01": {"name": "운양동 북측", "lat": 37.6720, "lon": 126.6790},
        "U02": {"name": "운양동 중앙", "lat": 37.6660, "lon": 126.6825},
        "U03": {"name": "운양동 동측", "lat": 37.6690, "lon": 126.6900},
    },
    "candidates": {
        "C1": {"name": "고양 구산동 축산지역", "type": "축산계", "lat": 37.6960, "lon": 126.7120},
        "C2": {"name": "김포 하성·월곶 축산지역", "type": "축산계", "lat": 37.7250, "lon": 126.6050},
        "C3": {"name": "김포 하수처리계통(걸포동)", "type": "하수계", "lat": 37.6380, "lon": 126.7020},
        "C4": {"name": "고양 하수처리시설 주변", "type": "하수계", "lat": 37.6480, "lon": 126.7480},
    },
}


def load_geo(path: str | None = None) -> dict:
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return DEFAULT_GEO


def bearing_deg(lat1, lon1, lat2, lon2) -> float:
    """점1에서 점2를 바라보는 방위(도, 북=0, 시계방향)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def distance_m(lat1, lon1, lat2, lon2) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def ang_diff(a, b) -> float:
    d = abs((a - b + 180) % 360 - 180)
    return d


def alignment(wind_from_deg: float, cand_bearing_deg: float) -> float:
    """정렬도 0~1: 풍향(불어오는 방향)이 후보 방위와 일치할수록 1. 45도 차이면 0.5, 90도 이상이면 0."""
    d = ang_diff(wind_from_deg, cand_bearing_deg)
    return max(0.0, 1.0 - d / 90.0)


def candidate_table(geo: dict) -> pd.DataFrame:
    rows = []
    for z, zi in geo["zones"].items():
        for c, ci in geo["candidates"].items():
            rows.append(dict(zone_id=z, cand_id=c, cand_name=ci["name"], cand_type=ci["type"],
                             bearing_deg=round(bearing_deg(zi["lat"], zi["lon"], ci["lat"], ci["lon"]), 1),
                             distance_m=round(distance_m(zi["lat"], zi["lon"], ci["lat"], ci["lon"]))))
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- 학습표
def build_zone_windows(obs: pd.DataFrame, min_valid: int = 3) -> pd.DataFrame:
    """관측데이터(개인 기록) → 구역×시간창 집계표. 정기 실외 관측만 사용."""
    s = obs[(obs.collection_mode == "scheduled") & (obs.context == "outdoor")].copy()
    s["det"] = s.odor_detected.map(lambda v: None if pd.isna(v) or v == "" else (1 if str(v).lower() == "true" else 0))
    v = s[s.det.notna()].copy()
    v["det"] = v.det.astype(int)

    def agg(g):
        n = len(g); k = int(g.det.sum())
        rate = k / n if n else np.nan
        label = (1 if rate >= 0.5 else 0) if n >= min_valid else np.nan
        types = g.loc[g.det == 1, "odor_type"].value_counts()
        top = types.index[0] if len(types) else None
        return pd.Series(dict(n_valid=n, n_detected=k, detection_rate=rate, label=label,
                              top_type=top,
                              temperature_c=g.temperature_c.iloc[0], humidity_pct=g.humidity_pct.iloc[0],
                              wind_speed=g.wind_speed_10min_ms.iloc[0], wind_from_deg=g.wind_from_sector_center_deg.iloc[0],
                              rain_1h_mm=g.rain_rolling_1h_mm.iloc[0], weather_basis=g.weather_basis.iloc[0]))

    zw = v.groupby(["window_id", "zone_id"]).apply(agg).reset_index()
    zw["window_start"] = pd.to_datetime(zw.window_id.str[2:15], format="%Y%m%d-%H%M")
    zw = zw.sort_values(["window_start", "zone_id"]).reset_index(drop=True)
    return zw


def add_lag_features(zw: pd.DataFrame) -> pd.DataFrame:
    """직전 시간창(같은 구역) 감지율. 예보 모드에서는 알 수 없으므로 선택 특징."""
    zw = zw.sort_values(["zone_id", "window_start"]).copy()
    zw["prev_rate"] = zw.groupby("zone_id").detection_rate.shift(1)
    zw["prev_label"] = zw.groupby("zone_id").label.shift(1)
    return zw.sort_values(["window_start", "zone_id"]).reset_index(drop=True)


# ---------------------------------------------------------------- 특징
def make_features(df: pd.DataFrame, geo: dict, use_lag: bool = False) -> pd.DataFrame:
    """공통 특징 행렬. df에는 window_start, zone_id, wind_from_deg, wind_speed, humidity_pct, temperature_c, rain_1h_mm 필요."""
    X = pd.DataFrame(index=df.index)
    wd = np.radians(df.wind_from_deg.astype(float))
    X["wind_sin"] = np.sin(wd); X["wind_cos"] = np.cos(wd)
    spd = df.wind_speed.astype(float)
    X["wind_speed"] = spd
    X["calm"] = (spd < 0.5).astype(int)
    X["wind_u"] = -spd * np.sin(wd)   # 이동 방향 벡터(동쪽 +)
    X["wind_v"] = -spd * np.cos(wd)   # 이동 방향 벡터(북쪽 +)
    X["humidity"] = df.humidity_pct.astype(float)
    X["temperature"] = df.temperature_c.astype(float)
    X["rain"] = (df.rain_1h_mm.astype(float) >= 1.0).astype(int)
    ts = pd.to_datetime(df.window_start)
    h = ts.dt.hour + ts.dt.minute / 60
    X["hour_sin"] = np.sin(2 * np.pi * h / 24); X["hour_cos"] = np.cos(2 * np.pi * h / 24)
    doy = ts.dt.dayofyear
    X["doy_sin"] = np.sin(2 * np.pi * doy / 365); X["doy_cos"] = np.cos(2 * np.pi * doy / 365)
    for z in ZONES:
        X[f"zone_{z}"] = (df.zone_id == z).astype(int)
    ct = candidate_table(geo).set_index(["zone_id", "cand_id"]).bearing_deg
    for c in geo["candidates"]:
        b = df.zone_id.map(lambda z: ct.get((z, c), np.nan))
        X[f"align_{c}"] = [alignment(w, bb) if not (np.isnan(w) or np.isnan(bb)) else 0.0
                           for w, bb in zip(df.wind_from_deg.astype(float), b)]
    if use_lag:
        X["prev_rate"] = df.get("prev_rate", pd.Series(np.nan, index=df.index)).fillna(0.0)
    return X


def sector_to_deg(v) -> float:
    if isinstance(v, str) and v in SEC_DEG:
        return SEC_DEG[v]
    return float(v)


def deg_to_sector(deg: float) -> str:
    return SECTORS[int(((deg + 11.25) % 360) // 22.5)]


def type_target(t: str) -> str:
    if t in ("축산계 추정", "하수계 추정"):
        return t
    return "기타/미확인"
