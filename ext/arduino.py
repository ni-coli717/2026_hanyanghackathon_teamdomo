from __future__ import annotations

import time

from .device_sim import DeviceResponse


def available_ports() -> list[str]:
    try:
        from serial.tools import list_ports
        return [port.device for port in list_ports.comports()]
    except Exception:
        return []


class ArduinoDevice:
    mode = "arduino"

    def __init__(self, port: str, baud: int = 9600) -> None:
        import serial
        self.serial = serial.Serial(port, baud, timeout=1)
        time.sleep(2)

    def send(self, command: str) -> DeviceResponse:
        try:
            self.serial.write((command + "\n").encode())
            line = self.serial.readline().decode(errors="replace").strip()
            ok = line == f"ACK:{command}"
            return DeviceResponse(ok, "기기 응답 확인" if ok else "응답을 확인하지 못했습니다.", line)
        except Exception as exc:
            return DeviceResponse(False, "연결 끊김 — 자동 제어 중단", str(exc))

    def read_gas(self) -> float | None:
        try:
            line = self.serial.readline().decode(errors="replace").strip()
            return float(line[4:]) if line.startswith("GAS:") else None
        except Exception:
            return None

