from pathlib import Path

import pandas as pd

from core.features import alignment, make_windows
from core.geo import haversine_km, initial_bearing, source_geometry
from core.model import train_models, training_status
from core.repo import SQLiteRepository
from core.sample_data import generate_sample_data
from ext.device_sim import device_command


def test_sample_is_reproducible_and_has_signal(tmp_path: Path):
    first = generate_sample_data(tmp_path / "a")
    second = generate_sample_data(tmp_path / "b")
    pd.testing.assert_frame_equal(first["reports"], second["reports"])
    windows = make_windows(first["reports"], first["weather"], first["zones"], first["sources"])
    assert len(first["reports"]) > 800
    assert windows.label.sum() >= 10
    assert windows.label.nunique(dropna=True) == 2
    assert windows.label.isna().any()  # 관측 부족과 감지 없음을 구분할 표본


def test_runtime_geometry_is_calculated_per_zone(tmp_path: Path):
    frames = generate_sample_data(tmp_path)
    geometry = source_geometry(frames["zones"], frames["sources"])
    assert len(geometry) == 9
    assert geometry.groupby("source_id").bearing_deg.nunique().min() > 1
    z2_d1 = geometry.query("zone_id == 'Z2' and source_id == 'D1'").iloc[0]
    assert 15 < z2_d1.bearing_deg < 50
    assert 2 < z2_d1.dist_km < 4


def test_ai_beats_direction_rule_on_seeded_demo(tmp_path: Path):
    frames = generate_sample_data(tmp_path)
    windows = make_windows(frames["reports"], frames["weather"], frames["zones"], frames["sources"])
    assert training_status(windows)[0]
    result = train_models(windows)
    metrics = result.metrics.set_index("모델")
    baseline = metrics.loc["기준선 2 · 방향 규칙", "F1"]
    best_ai = metrics.loc[["로지스틱 회귀", "랜덤포레스트"], "F1"].max()
    assert best_ai > baseline


def test_repository_separates_sample_and_real(tmp_path: Path):
    repo = SQLiteRepository(tmp_path / "odor.db")
    frame = pd.DataFrame([{"zone_id": "Z1", "name": "테스트", "rep_lat": 37.6, "rep_lon": 126.6, "boundary_note": ""}])
    repo.replace("zones", frame, sample=True)
    assert len(repo.read("zones", sample=True)) == 1
    assert repo.read("zones", sample=False).empty


def test_calm_wind_and_hysteresis():
    assert pd.isna(alignment(30, 30, ws=0.4))
    command, on, _ = device_command(.70, False, False, False, False)
    assert (command, on) == ("FAN:ON", True)
    command, on, _ = device_command(.55, True, False, False, False)
    assert (command, on) == (None, True)
    command, on, _ = device_command(.40, True, False, False, False)
    assert (command, on) == ("FAN:OFF", False)

