from __future__ import annotations

import math
import pandas as pd


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def initial_bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def source_geometry(zones: pd.DataFrame, sources: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, z in zones.iterrows():
        for _, s in sources.iterrows():
            rows.append({
                "zone_id": z.zone_id,
                "source_id": s.source_id,
                "source_name": s["name"],
                "source_type": s.source_type,
                "bearing_deg": initial_bearing(z.rep_lat, z.rep_lon, s.lat, s.lon),
                "dist_km": haversine_km(z.rep_lat, z.rep_lon, s.lat, s.lon),
            })
    return pd.DataFrame(rows)

