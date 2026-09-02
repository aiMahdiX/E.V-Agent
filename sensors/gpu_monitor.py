"""GPU monitor (Phase 5 placeholder)."""
from __future__ import annotations

from sensors.event_bus import EventBus


class GPUMonitor:
    def __init__(self, bus: EventBus, threshold: int = 90):
        self.bus = bus
        self.threshold = threshold

    def start(self) -> None:
        raise NotImplementedError("GPU monitor not implemented (Phase 5)")
