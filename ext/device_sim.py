from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class DeviceResponse:
    ok: bool
    message: str
    raw: str


class SimulatedDevice:
    mode = "simulation"

    def __init__(self) -> None:
        self.last_command = "FAN:OFF"

    def send(self, command: str) -> DeviceResponse:
        self.last_command = command
        return DeviceResponse(True, "가상 기기가 명령을 확인했습니다.", f"ACK:{command}")

    def read_gas(self) -> float | None:
        return None


def device_command(
    probability: float,
    fan_on: bool,
    manual_stop: bool,
    quiet_hours: bool,
    max_duration_reached: bool,
    start_threshold: float = 0.65,
    stop_threshold: float = 0.45,
) -> tuple[str | None, bool, str]:
    if manual_stop:
        return ("FAN:OFF" if fan_on else None), False, "수동 중지"
    if quiet_hours:
        return ("FAN:OFF" if fan_on else None), False, "야간 소음 제한"
    if max_duration_reached:
        return ("FAN:OFF" if fan_on else None), False, "최대 지속시간 도달"
    if fan_on and probability <= stop_threshold:
        return "FAN:OFF", False, "해제 임계값 도달"
    if not fan_on and probability >= start_threshold:
        return "FAN:ON", True, "시작 임계값 도달"
    return None, fan_on, "히스테리시스 유지"

