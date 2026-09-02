"""Service tools — systemd service status/control."""
from __future__ import annotations

import subprocess

from tools.base import Tool


def _svc(unit: str, action: str = "status") -> dict:
    proc = subprocess.run(
        ["systemctl", action, unit], capture_output=True, text=True)
    return {"unit": unit, "action": action,
            "exit_code": proc.returncode,
            "output": (proc.stdout or proc.stderr).strip()[:2000]}


def service_status(unit: str, **kwargs) -> dict:
    return _svc(unit, "status")


def service_start(unit: str, **kwargs) -> dict:
    return _svc(unit, "start")


def service_stop(unit: str, **kwargs) -> dict:
    return _svc(unit, "stop")


def service_restart(unit: str, **kwargs) -> dict:
    return _svc(unit, "restart")


SERVICE_TOOLS = [
    Tool("service_status", "Show systemd status of a service unit.",
         {"type": "object", "properties": {"unit": {"type": "string"}}},
         required=["unit"], fn=service_status),
    Tool("service_start", "Start a systemd service.",
         {"type": "object", "properties": {"unit": {"type": "string"}}},
         required=["unit"], fn=service_start),
    Tool("service_stop", "Stop a systemd service.",
         {"type": "object", "properties": {"unit": {"type": "string"}}},
         required=["unit"], fn=service_stop),
    Tool("service_restart", "Restart a systemd service.",
         {"type": "object", "properties": {"unit": {"type": "string"}}},
         required=["unit"], fn=service_restart),
]
