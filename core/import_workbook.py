from __future__ import annotations

from pathlib import Path
import argparse

import numpy as np
import pandas as pd


ZONE_MAP = {"U01": "Z1", "U02": "Z2", "U03": "Z3"}
ODOR_TYPE_MAP = {
    "없음": "없음",
    "판단 어려움": "모름",
    "구분 어려움": "모름",
    "축산계 추정": "축산분뇨",
    "하수계 추정": "하수",
    "기타": "기타",
}


def convert_workbook(path: str | Path, output_dir: str | Path = "data/provided") -> dict[str, pd.DataFrame]:
    path, out = Path(path), Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    observations = pd.read_excel(path, sheet_name="관측데이터")
    origins = set(observations["record_origin"].dropna().astype(str).str.lower())
    if origins != {"simulated"}:
        raise ValueError(f"예상하지 못한 record_origin: {sorted(origins)}")

    odor = observations["odor_detected"].map({True: 1, False: 0})
    reports = pd.DataFrame({
        "report_id": observations["observation_id"].astype(str),
        "observer_code": observations["participant_id"].astype(str).str.extract(r"(\d+)")[0].astype(int).map(lambda x: f"R{x:02d}"),
        "zone_id": observations["zone_id"].map(ZONE_MAP),
        "observed_at": pd.to_datetime(observations["observed_at"]).dt.strftime("%Y-%m-%d %H:%M:%S"),
        "submitted_at": pd.to_datetime(observations["received_at"]).dt.strftime("%Y-%m-%d %H:%M:%S"),
        "report_mode": observations["collection_mode"].map({"scheduled": "scheduled", "spontaneous": "extra"}),
        "odor": odor,
        "intensity": observations["intensity"].fillna(0).astype(int),
        "odor_type": observations["odor_type"].map(ODOR_TYPE_MAP).fillna("모름"),
        "environment": observations["context"].map({"outdoor": "outdoor", "indoor": "indoor"}).fillna("outdoor"),
        "confidence": np.where(odor.isna(), "low", "mid"),
        "saw_forecast": observations["prediction_seen"].fillna(False).astype(int),
        "memo": "제공 시나리오 · 실제 관측 아님",
        "record_origin": "simulated",
        "idempotency_key": observations["observation_id"].astype(str).map(lambda x: f"scenario:{x}"),
    })
    if reports[["zone_id", "report_mode"]].isna().any().any():
        raise ValueError("매핑되지 않은 구역 또는 수집 모드가 있습니다.")

    snapshots = pd.read_excel(path, sheet_name="기상스냅샷")
    referenced_station = int(observations["weather_station_id"].mode().iloc[0])
    snapshots = snapshots[snapshots["station_id"].eq(referenced_station)].copy()
    weather = pd.DataFrame({
        "station_id": snapshots["station_id"].astype(str),
        "weather_at": pd.to_datetime(snapshots["observed_at"]).dt.strftime("%Y-%m-%d %H:%M:%S"),
        "wd": snapshots["wind_from_sector_center_deg"],
        "ws": snapshots["wind_speed_10min_ms"],
        "temp": snapshots["temperature_c"],
        "humidity": snapshots["humidity_pct"],
        "pressure": np.nan,
        "rain": snapshots["rain_rolling_1h_mm"],
        "quality_flag": "ok",
    })
    reports.to_csv(out / "reports.csv", index=False, encoding="utf-8-sig")
    weather.to_csv(out / "weather.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame([{
        "source_file": path.name,
        "record_origin": "simulated",
        "scenario_seed": int(observations["scenario_seed"].iloc[0]),
        "report_rows": len(reports),
        "weather_rows": len(weather),
        "station_id": referenced_station,
        "notice": "제공 파일 자체가 simulated로 표시되어 실제 주민 관측으로 사용하지 않음",
    }]).to_csv(out / "provenance.csv", index=False, encoding="utf-8-sig")
    return {"reports": reports, "weather": weather}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="제공 관측 워크북을 앱 스키마로 변환")
    parser.add_argument("workbook")
    parser.add_argument("--output", default="data/provided")
    args = parser.parse_args()
    result = convert_workbook(args.workbook, args.output)
    print(f"reports={len(result['reports'])}, weather={len(result['weather'])}")
