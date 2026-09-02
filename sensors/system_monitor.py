"""System monitor (Phase 5 placeholder)."""
from __future__ import annotations

from sensors.event_bus import EventBus


class SystemMonitor:
    def __init__(self, bus: EventBus):
        self.bus = bus

    def start(self) -> None:
        raise NotImplementedError("System monitor not implemented (Phase 5)")
