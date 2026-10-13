"""Lightweight in-process event bus for safe local monitoring."""
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
        data = {"event": event, **dict(payload or {})}
        for handler in list(self._subs.get(event, [])):
            try:
                handler(data)
            except Exception as exc:  # pragma: no cover - defensive logging
                print(f"[event-bus] {event} handler failed: {exc}")
