"""Auto-response judgment. The rule itself is odor_model.device_service.AutoRule (hysteresis state machine);
this module only builds it from data/model_settings.json and replays level histories.

Roles: the model estimates level only; AutoRule turns level history into ON/OFF/HOLD; the board just
executes the ACTION it receives.
"""
from __future__ import annotations

import pandas as pd

from odor_model.device_service import AutoRule

from . import analysis_service as service


def make_rule(enabled: bool = True, settings: dict | None = None) -> AutoRule:
    auto = (settings or service.load_settings())['auto']
    return AutoRule(on_streak=int(auto['start_count']), off_streak=int(auto['stop_count']), enabled=enabled)


def decide(levels, rule: dict | None = None, enabled: bool = True) -> tuple[str, str]:
    """Replay chronological levels ('낮음'/'보통'/'높음', None = 추정 보류) through a fresh AutoRule."""
    settings = {'auto': rule} if rule else None
    machine = make_rule(enabled, settings)
    if not enabled:
        return 'HOLD', '사용 안 함'
    action = 'OFF'
    for level in levels:
        action = machine.decide(level)
    if action == 'HOLD':
        return 'HOLD', '판단 보류'
    return action, '가동' if action == 'ON' else '대기'


def zone_levels(predictions: pd.DataFrame, zone_id: str) -> list:
    """Chronological levels for one zone. Accepts app ids (Z1) or model ids (U01)."""
    if predictions is None or predictions.empty:
        return []
    rows = predictions[(predictions.app_zone_id == zone_id) | (predictions.zone_id == zone_id)].sort_values('window_start')
    return [r.level if r.status == '예비 추정' else None for r in rows.itertuples()]


def get_auto_action(zone_id: str, predictions: pd.DataFrame | None = None, enabled: bool = True) -> str:
    """Interface for device modules: 'ON' | 'OFF' | 'HOLD' after replaying the observed-time estimates."""
    if predictions is None:
        from .public_data import dashboard, window_slots
        from .config import data_mode
        mode = data_mode()
        _, weather, _, _, _, _ = dashboard(mode)
        slots = window_slots(mode)
        predictions = service.predict_windows(service.weather_inputs(weather, slots.window_start))
    return decide(zone_levels(predictions, zone_id), enabled=enabled)[0]
