from __future__ import annotations

import math
import pandas as pd


LEVEL_COLORS = {"LOW": "#3D8B5F", "MEDIUM": "#D99A3C", "HIGH": "#C0563B", "HOLD": "#9AA5AE"}
WIND_NAMES = ["북", "북북동", "북동", "동북동", "동", "동남동", "남동", "남남동", "남", "남남서", "남서", "서남서", "서", "서북서", "북서", "북북서"]


def risk_level(probability: float | None) -> str:
    if probability is None or pd.isna(probability):
        return "HOLD"
    if probability < 0.35:
        return "LOW"
    if probability < 0.65:
        return "MEDIUM"
    return "HIGH"


def wind_name(degrees: float | None) -> str:
    if degrees is None or pd.isna(degrees):
        return "방향 미상"
    return WIND_NAMES[int((float(degrees) + 11.25) // 22.5) % 16]


def rule_probability(row: pd.Series, align_d1: float | None) -> float:
    if pd.isna(row.get("ws")) or pd.isna(row.get("wd")) or align_d1 is None or pd.isna(align_d1):
        return math.nan
    if align_d1 > 0.7 and row.ws < 3:
        return 0.72
    if align_d1 > 0.3:
        return 0.50
    return 0.22


def direction_hint(weather_row: pd.Series, geometry: pd.DataFrame) -> dict | None:
    if weather_row is None or pd.isna(weather_row.get("ws")) or weather_row.ws < 0.5 or pd.isna(weather_row.get("wd")):
        return None
    g = geometry.copy()
    g["align"] = g.bearing_deg.map(lambda b: math.cos(math.radians(float(weather_row.wd) - b)))
    g = g.sort_values("align", ascending=False)
    first = g.iloc[0]
    ambiguous = len(g) > 1 and first["align"] - g.iloc[1]["align"] < 0.15
    return {"source_id": first.source_id, "name": first.source_name, "bearing": first.bearing_deg, "align": first["align"], "ambiguous": ambiguous}

