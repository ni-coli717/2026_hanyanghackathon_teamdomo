import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import pandas as pd
from odor_model.prerun import plan


def preds(levels, start="2026-10-27 18:00", zone="U01", sector="북동"):
    t0 = pd.Timestamp(start)
    return pd.DataFrame([dict(window_start=t0 + pd.Timedelta(hours=i), zone_id=zone, app_zone_id="Z1",
                              status="예비 추정" if lv else "추정 보류", level=lv, wind_from_sector=sector)
                         for i, lv in enumerate(levels)])


P = preds(["낮음", "낮음", "낮음", "높음", "높음", "보통"])   # 높음 21:00~23:00


def test_standby_before_lead():
    r = plan(P, "U01", "2026-10-27 19:00")
    assert r["action"] == "OFF" and r["state"] == "standby"
    assert r["next"]["on_at"].startswith("2026-10-27T20:20")
    assert "20:20" in r["reason"] and "21:00" in r["reason"] and "북동풍" in r["reason"]


def test_prerun_starts_lead_minutes_before():
    assert plan(P, "U01", "2026-10-27 20:19")["action"] == "OFF"
    r = plan(P, "U01", "2026-10-27 20:20")
    assert r["action"] == "ON" and r["state"] == "pre_run"


def test_running_and_off_after_tail():
    assert plan(P, "U01", "2026-10-27 22:10")["state"] == "running"
    assert plan(P, "U01", "2026-10-27 23:29")["action"] == "ON"
    assert plan(P, "U01", "2026-10-27 23:30")["action"] == "OFF"


def test_app_zone_id_and_lead_setting():
    r = plan(P, "Z1", "2026-10-27 20:00", lead_min=60)
    assert r["action"] == "ON"


def test_hold_when_no_estimate():
    r = plan(preds([None, None, None]), "U01", "2026-10-27 18:30")
    assert r["action"] == "HOLD"


def test_gap_merge():
    p = preds(["높음", "낮음", "높음"])                       # 18시, 20시 높음 → 켜는 구간이 겹쳐 하나로
    r = plan(p, "U01", "2026-10-27 17:00")
    assert len(r["episodes"]) == 1


def test_trigger_mid():
    r = plan(P, "U01", "2026-10-27 18:00", trigger="보통")
    assert r["next"]["odor_start"].startswith("2026-10-27T21:00")
