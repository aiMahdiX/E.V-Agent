"""Event Bus (Phase 5 — proactive system)."""
from __future__ import annotations

from collections import defaultdict
from typing import Callable

EVENTS = ["CPU_HIGH", "GPU_HIGH", "DISK_LOW", "SERVICE_FAILED",
          "USB_CONNECTED", "CAMERA_EVENT", "NETWORK_CHANGED",
          "DOWNLOAD_FINISHED", "TIMER_FIRED"]


class EventBus:
    def __init__(self):
        self._subs: dict[str, list[Callable]] = defaultdict(list)

    def subscribe(self, event: str, handler: Callable) -> None:
        self._subs[event].append(handler)

    def publish(self, event: str, payload: dict | None = None) -> None:
        for handler in self._subs.get(event, []):
            handler(payload or {})

    def start(self) -> None:
        raise NotImplementedError("Event bus loop not started (Phase 5)")
