"""사전 작동(pre-run) 판단 — 예보를 보고 냄새가 오기 '전에' 공기청정기를 켠다.

입력: predict_windows() 결과(구역×1시간 예보 행). 한 행의 window_start 는 그 시각부터 1시간 구간이다.
규칙:
  1. 집 구역의 '예비 추정' 행 중 단계가 trigger(기본 높음) 이상인 시간을 찾는다.
  2. 이어지는 시간은 한 '냄새 구간'으로 묶는다 (start ~ 마지막 시각+1h).
  3. 구간마다 켜는 시각 = start − lead_min, 끄는 시각 = end + tail_min.
  4. 지금이 어느 구간의 [켜는 시각, 끄는 시각) 안이면 ON, 아니면 OFF.
  5. 예보가 전부 '추정 보류'면 HOLD (자료 없음을 냄새 없음으로 바꾸지 않는다).
모델은 단계만 추정하고, 켜고 끄는 결정은 이 규칙이 한다. 보드는 받은 결과만 수행한다.
순수 함수: 네트워크·파일·Streamlit 의존 없음.
"""
from __future__ import annotations

import dataclasses
import pandas as pd

RANK = {"낮음": 0, "보통": 1, "높음": 2}
HOUR = pd.Timedelta(hours=1)


@dataclasses.dataclass
class Episode:
    odor_start: pd.Timestamp      # 냄새 예상 시작
    odor_end: pd.Timestamp        # 냄새 예상 끝
    on_at: pd.Timestamp           # 미리 켜는 시각
    off_at: pd.Timestamp          # 끄는 시각
    peak_level: str
    wind_sector: str              # 첫 시각의 '불어오는' 방향(예: 북동)

    def as_dict(self):
        return {k: (v.isoformat() if isinstance(v, pd.Timestamp) else v) for k, v in dataclasses.asdict(self).items()}


def _hhmm(t: pd.Timestamp) -> str:
    return t.strftime("%H:%M")


def plan(predictions: pd.DataFrame, zone_id: str, now, lead_min: int = 40, tail_min: int = 30,
         trigger: str = "높음") -> dict:
    """반환: action(ON/OFF/HOLD), state(pre_run/running/standby/hold), next(다음 구간), episodes, reason."""
    now = pd.Timestamp(now)
    if now.tzinfo is not None:
        now = now.tz_convert("Asia/Seoul").tz_localize(None)
    if predictions is None or predictions.empty:
        return _result("HOLD", "hold", [], None, "예보 자료 없음 · 판단 보류")
    zcol = predictions["zone_id"].eq(zone_id)
    if "app_zone_id" in predictions:
        zcol |= predictions["app_zone_id"].eq(zone_id)
    rows = predictions[zcol].copy()
    rows["window_start"] = pd.to_datetime(rows["window_start"])
    rows = rows[rows["window_start"] + HOUR + pd.Timedelta(minutes=tail_min) > now].sort_values("window_start")  # 끝난 구간의 꼬리 시간까지 유지
    valid = rows[rows["status"] == "예비 추정"]
    if valid.empty:
        return _result("HOLD", "hold", [], None, "예보 추정 보류 · 직전 상태 유지")

    need = RANK[trigger]
    hot = valid[valid["level"].map(RANK).fillna(-1) >= need]
    episodes, cur = [], None
    for r in hot.itertuples():
        t = r.window_start
        if cur and t <= cur["end"]:
            cur["end"] = t + HOUR
            if RANK[r.level] > RANK[cur["peak"]]:
                cur["peak"] = r.level
        else:
            if cur:
                episodes.append(cur)
            cur = dict(start=t, end=t + HOUR, peak=r.level, sector=getattr(r, "wind_from_sector", "") or "")
    if cur:
        episodes.append(cur)
    lead, tail = pd.Timedelta(minutes=lead_min), pd.Timedelta(minutes=tail_min)
    eps = [Episode(e["start"], e["end"], e["start"] - lead, e["end"] + tail, e["peak"], e["sector"]) for e in episodes]
    # 켜는 구간이 겹치면 합친다(끄자마자 다시 켜는 깜빡임 방지)
    merged: list[Episode] = []
    for e in eps:
        if merged and e.on_at <= merged[-1].off_at:
            m = merged[-1]
            m.odor_end, m.off_at = e.odor_end, e.off_at
            if RANK[e.peak_level] > RANK[m.peak_level]:
                m.peak_level = e.peak_level
        else:
            merged.append(e)

    active = next((e for e in merged if e.on_at <= now < e.off_at), None)
    upcoming = next((e for e in merged if e.on_at > now), None)
    if active:
        wind = f"{active.wind_sector}풍 · " if active.wind_sector else ""
        if now < active.odor_start:
            reason = f"{_hhmm(active.odor_start)} {wind}{active.peak_level} 예상 → {_hhmm(active.on_at)}부터 가동"
            return _result("ON", "pre_run", merged, active, reason)
        reason = f"{wind}{active.peak_level} 예상 구간 · {_hhmm(active.off_at)}까지 가동"
        return _result("ON", "running", merged, active, reason)
    if upcoming:
        wind = f"{upcoming.wind_sector}풍 · " if upcoming.wind_sector else ""
        reason = f"{_hhmm(upcoming.on_at)} 가동 예정 ({_hhmm(upcoming.odor_start)} {wind}{upcoming.peak_level} 예상)"
        return _result("OFF", "standby", merged, upcoming, reason)
    horizon = valid["window_start"].max() + HOUR
    return _result("OFF", "standby", merged, None, f"{_hhmm(horizon)}까지 {trigger} 예상 없음 · 대기")


def _result(action, state, episodes, nxt, reason):
    return dict(action=action, state=state, reason=reason,
                next=nxt.as_dict() if nxt else None,
                episodes=[e.as_dict() for e in episodes])
