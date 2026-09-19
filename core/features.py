from __future__ import annotations

import numpy as np
import pandas as pd

from .geo import source_geometry


def circular_mean_degrees(values: pd.Series) -> float:
    values = pd.to_numeric(values, errors="coerce").dropna()
    if values.empty:
        return np.nan
    radians = np.deg2rad(values)
    return float((np.rad2deg(np.arctan2(np.sin(radians).mean(), np.cos(radians).mean())) + 360) % 360)


def alignment(wd: float, bearing: float, ws: float | None = None) -> float:
    if pd.isna(wd) or pd.isna(bearing) or (ws is not None and (pd.isna(ws) or ws < 0.5)):
        return np.nan
    return float(np.cos(np.deg2rad(float(wd) - float(bearing))))


def normalize_weather(frame: pd.DataFrame) -> pd.DataFrame:
    aliases = {
        "지점": "station_id", "일시": "weather_at", "풍향(deg)": "wd", "풍속(m/s)": "ws",
        "기온(°C)": "temp", "습도(%)": "humidity", "현지기압(hPa)": "pressure", "강수량(mm)": "rain",
    }
    weather = frame.rename(columns=aliases).copy()
    for required, default in {"station_id": "(확인필요)", "quality_flag": "ok", "rain": 0}.items():
        if required not in weather:
            weather[required] = default
    if 'weather_at' not in weather:
        weather['weather_at'] = pd.Series(dtype='datetime64[ns]')
    weather["weather_at"] = pd.to_datetime(weather["weather_at"], errors="coerce")
    for col in ["wd", "ws", "temp", "humidity", "pressure", "rain"]:
        if col not in weather:
            weather[col] = np.nan
        weather[col] = pd.to_numeric(weather[col].replace("-", np.nan), errors="coerce")
    return weather.dropna(subset=["weather_at"]).sort_values("weather_at")


def window_id_time(values: pd.Series) -> pd.Series:
    """Workbook ids ('W-20260915-2200') or live ISO timestamps -> naive window time; else NaT."""
    text = values.astype(str).str.extract(r"^W-(\d{8}-\d{4})$")[0]
    coded = pd.to_datetime(text, format="%Y%m%d-%H%M", errors="coerce")
    def parse(value):
        try:
            moment = pd.Timestamp(value)
        except (TypeError, ValueError):
            return pd.NaT
        return moment.tz_convert("Asia/Seoul").tz_localize(None) if moment.tzinfo else moment
    other = pd.Series([parse(v) for v in values.where(text.isna(), None)], index=values.index, dtype="datetime64[ns]")
    return coded.astype("datetime64[ns]").fillna(other)


def make_windows(reports: pd.DataFrame, weather: pd.DataFrame, zones: pd.DataFrame, sources: pd.DataFrame) -> pd.DataFrame:
    if reports.empty:
        return pd.DataFrame()
    r = reports.copy()
    r["observed_at"] = pd.to_datetime(r["observed_at"], errors="coerce")
    r["submitted_at"] = pd.to_datetime(r["submitted_at"], errors="coerce")
    r = r[(r.report_mode == "scheduled") & (r.environment == "outdoor") & (r.observer_code != "GUEST")]
    # 정시 관측의 ±30분 허용창을 중앙 시각에 모은다. 21:29와 21:31이
    # 서로 다른 학습창으로 갈라지지 않도록 단순 내림이 아닌 반올림을 쓴다.
    r["window_at"] = r["observed_at"].dt.round("30min")
    if 'window_id' in r.columns:
        explicit=window_id_time(r['window_id'])
        r['window_at']=explicit.fillna(r['window_at'])
    r = r.sort_values("submitted_at").drop_duplicates(["observer_code", "zone_id", "window_at"], keep="last")
    r = r[r.odor.notna()]
    if r.empty:
        return pd.DataFrame()
    windows = r.groupby(["zone_id", "window_at"], as_index=False).agg(
        n_observers=("observer_code", "nunique"),
        n_detected=("odor", "sum"),
        median_intensity=("intensity", "median"),
    )
    windows["detected_ratio"] = windows.n_detected / windows.n_observers
    windows["label"] = np.where(windows.n_observers >= 3, (windows.detected_ratio >= 0.5).astype(float), np.nan)
    wx = normalize_weather(weather)
    wx = wx[wx.quality_flag.eq("ok")].copy()
    # AWS 정시자료와 제공된 30분 스냅샷을 모두 받을 수 있도록 관측창 기준
    # 직전 1시간 이내의 최신 기상을 연결한다.
    windows["weather_at"] = windows.window_at.astype("datetime64[ns]")
    wx = wx.drop_duplicates("weather_at", keep="last").copy()
    wx["weather_at"] = wx["weather_at"].astype("datetime64[ns]")
    wx["weather_source_at"] = wx["weather_at"]
    windows = pd.merge_asof(
        windows.sort_values("weather_at"),
        wx.sort_values("weather_at"),
        on="weather_at",
        direction="backward",
        tolerance=pd.Timedelta("1h"),
    )
    windows["wd"] = windows["wd"].where(windows.ws >= 0.5)
    windows["wd_sin"] = np.sin(np.deg2rad(windows.wd))
    windows["wd_cos"] = np.cos(np.deg2rad(windows.wd))
    hour = windows.window_at.dt.hour + windows.window_at.dt.minute / 60
    windows["hour_sin"] = np.sin(2 * np.pi * hour / 24)
    windows["hour_cos"] = np.cos(2 * np.pi * hour / 24)
    windows["is_night"] = ((windows.window_at.dt.hour >= 21) | (windows.window_at.dt.hour <= 6)).astype(int)
    windows["dow"] = windows.window_at.dt.dayofweek
    windows = windows.sort_values(["zone_id", "window_at"])
    windows["dp_3h"] = windows.groupby("zone_id")["pressure"].diff(6)
    geometry = source_geometry(zones, sources)
    for source_id in sources.source_id:
        bearings = geometry.query("source_id == @source_id").set_index("zone_id")["bearing_deg"]
        b = windows.zone_id.map(bearings)
        windows[f"bearing_{source_id}"] = b
        windows[f"align_{source_id}"] = np.where(windows.ws >= 0.5, np.cos(np.deg2rad(windows.wd - b)), np.nan)
    lag_cols = ["wd", "ws"] + [f"align_{x}" for x in sources.source_id]
    for col in lag_cols:
        windows[f"{col}_lag1"] = windows.groupby("zone_id")[col].shift(2)
    return windows.reset_index(drop=True)


def response_summary(reports: pd.DataFrame) -> pd.DataFrame:
    r = reports.copy()
    r["observed_at"] = pd.to_datetime(r.observed_at, errors="coerce")
    r = r[(r.report_mode == "scheduled") & (r.observer_code != "GUEST")]
    if r.empty:
        return pd.DataFrame(columns=["zone_id", "응답 수", "참여자", "응답률"])
    r["day"] = r.observed_at.dt.date
    actual = r.groupby("zone_id").agg(**{"응답 수": ("report_id", "count"), "참여자": ("observer_code", "nunique"), "일수": ("day", "nunique")})
    actual["응답률"] = actual["응답 수"] / (actual["참여자"] * actual["일수"] * 4)
    return actual.reset_index()
