"""GPU monitor for local proactive alerts without unsafe automation."""
from __future__ import annotations

import subprocess
import threading

from sensors.event_bus import EventBus


class GPUMonitor:
    def __init__(self, bus: EventBus, threshold: int = 90,
                 poll_seconds: float = 5.0):
        self.bus = bus
        self.threshold = max(0, int(threshold))
        self.poll_seconds = max(0.5, float(poll_seconds))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run_loop,
                                        name="ev-gpu-monitor",
                                        daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=max(1.0, self.poll_seconds + 0.5))

    def _gpu_utilization(self) -> int | None:
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=utilization.gpu",
                 "--format=csv,noheader,nounits"],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            return None
        if result.returncode != 0 or not result.stdout.strip():
            return None
        try:
            return int(float(result.stdout.strip().splitlines()[0].strip()))
        except ValueError:
            return None

    def _run_loop(self) -> None:
        while not self._stop.wait(self.poll_seconds):
            usage = self._gpu_utilization()
            if usage is not None and usage >= self.threshold:
                self.bus.publish('GPU_HIGH', {
                    'value': usage,
                    'unit': 'percent',
                    'source': 'gpu_monitor',
                })
