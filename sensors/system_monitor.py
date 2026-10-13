"""Low-noise local system monitor for safe proactive alerts."""
from __future__ import annotations

import os
import shutil
import threading

from sensors.event_bus import EventBus


class SystemMonitor:
    def __init__(self, bus: EventBus, poll_seconds: float = 5.0,
                 cpu_high_threshold: float = 2.0,
                 disk_low_threshold: float = 15.0):
        self.bus = bus
        self.poll_seconds = max(0.5, float(poll_seconds))
        self.cpu_high_threshold = float(cpu_high_threshold)
        self.disk_low_threshold = float(disk_low_threshold)
        self._cpu_high_active = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run_loop,
                                        name="ev-system-monitor",
                                        daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=max(1.0, self.poll_seconds + 0.5))

    def _cpu_load(self) -> float:
        try:
            return float(os.getloadavg()[0])
        except (AttributeError, OSError, ValueError):
            return 0.0

    def _disk_free_pct(self) -> float:
        try:
            usage = shutil.disk_usage('/')
            return 100.0 * (usage.free / usage.total)
        except OSError:
            return 100.0

    def _publish_cpu_alert(self, cpu: float) -> None:
        if cpu >= self.cpu_high_threshold:
            if self._cpu_high_active:
                return
            self._cpu_high_active = True
            self.bus.publish('CPU_HIGH', {'value': cpu, 'unit': 'loadavg'})
        elif cpu < self.cpu_high_threshold * 0.8:
            self._cpu_high_active = False

    def _run_loop(self) -> None:
        while not self._stop.wait(self.poll_seconds):
            cpu = self._cpu_load()
            self._publish_cpu_alert(cpu)

            disk_free = self._disk_free_pct()
            if disk_free <= self.disk_low_threshold:
                self.bus.publish('DISK_LOW', {
                    'value': round(disk_free, 2),
                    'unit': 'percent_free',
                    'source': 'system_monitor',
                })
