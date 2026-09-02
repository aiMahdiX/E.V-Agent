"""Camera sensor (Phase 4)."""
from __future__ import annotations

from sensors.event_bus import EventBus


class CameraMonitor:
    def __init__(self, bus: EventBus):
        self.bus = bus

    def start(self) -> None:
        raise NotImplementedError("Camera monitor not implemented (Phase 4)")
