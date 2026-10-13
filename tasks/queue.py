"""Safe local task queue for proactive reminders and event-driven tasks."""
from __future__ import annotations

from collections import deque


class TaskQueue:
    def __init__(self, maxlen: int = 100):
        self.maxlen = max(1, int(maxlen))
        self._items: deque[str] = deque(maxlen=self.maxlen)

    def push(self, task: str) -> str:
        value = (task or "").strip()
        if not value:
            raise ValueError("task cannot be empty")
        self._items.append(value)
        return value

    def pop(self) -> str | None:
        return self._items.popleft() if self._items else None

    def drain(self) -> list[str]:
        items = list(self._items)
        self._items.clear()
        return items

    def __len__(self) -> int:
        return len(self._items)

    def __iter__(self):
        return iter(self._items)


class EventDrivenTaskQueue(TaskQueue):
    """Converts sensor events into reminder tasks without auto-running them."""

    def __init__(self, task_manager=None, scheduler=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.task_manager = task_manager
        self.scheduler = scheduler

    @staticmethod
    def _message_for(event: str, payload: dict | None) -> str:
        payload = payload or {}
        if event == "CPU_HIGH":
            value = payload.get("value")
            return f"Check high CPU load alert ({value} loadavg)."
        if event == "GPU_HIGH":
            value = payload.get("value")
            return f"Check GPU utilization alert ({value}% usage)."
        if event == "DISK_LOW":
            value = payload.get("value")
            return f"Disk space is low ({value}% free remaining)."
        if event == "SERVICE_FAILED":
            return "Review failed service alert and verify local system health."
        if event == "NETWORK_CHANGED":
            return "Review network change and confirm connectivity."
        return f"Review local system event: {event}."

    def subscribe(self, bus) -> None:
        for event in ["CPU_HIGH", "GPU_HIGH", "DISK_LOW", "SERVICE_FAILED",
                      "NETWORK_CHANGED"]:
            bus.subscribe(event, self.on_event)

    def on_event(self, payload: dict | None) -> None:
        event = payload.get("event") if isinstance(payload, dict) else None
        if not event:
            return
        message = self._message_for(event, payload)
        self.push(message)
        if self.task_manager is not None:
            task = self.task_manager.new(message)
            if self.scheduler is not None:
                self.scheduler.schedule(task.id, delay_seconds=30)

    def process_event(self, event: str, payload: dict | None = None) -> str | None:
        message = self._message_for(event, payload or {})
        self.push(message)
        if self.task_manager is not None:
            task = self.task_manager.new(message)
            if self.scheduler is not None:
                self.scheduler.schedule(task.id, delay_seconds=30)
            return task.id
        return message
