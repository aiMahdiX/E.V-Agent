"""Durable local scheduler for task reminders and explicit execution."""
from __future__ import annotations

import threading
import time


class Scheduler:
    def __init__(self, tasks, on_due=None, poll_seconds: float = 1.0,
                 clock=time.time):
        self.tasks = tasks
        self.on_due = on_due or (lambda task: None)
        self.poll_seconds = max(0.1, poll_seconds)
        self.clock = clock
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def schedule(self, task_id: str, delay_seconds: int,
                 interval_seconds: int | None = None) -> None:
        if delay_seconds < 1:
            raise ValueError("delay_seconds must be positive")
        if interval_seconds is not None and interval_seconds < 1:
            raise ValueError("interval_seconds must be positive")
        task = self.tasks.get(task_id)
        if task is None:
            raise KeyError(f"unknown task: {task_id}")
        self.tasks.update(task_id, next_run_at=self.clock() + delay_seconds,
                          interval_seconds=interval_seconds, due_count=0,
                          status="pending")

    def cancel(self, task_id: str) -> bool:
        task = self.tasks.get(task_id)
        if task is None or task.next_run_at is None:
            return False
        self.tasks.update(task_id, next_run_at=None, interval_seconds=None,
                          due_count=0, status="pending")
        return True

    def run_due(self, now: float | None = None) -> list:
        """Mark due tasks and notify once per polling pass."""
        current = self.clock() if now is None else now
        due = []
        for task in self.tasks.all():
            if task.next_run_at is None or task.next_run_at > current:
                continue
            missed = 1
            next_run = None
            if task.interval_seconds:
                missed += int((current - task.next_run_at)
                              // task.interval_seconds)
                next_run = task.next_run_at + missed * task.interval_seconds
            total_due = task.due_count + missed
            self.tasks.update(task.id, next_run_at=next_run,
                              due_count=total_due, status="due")
            updated = self.tasks.get(task.id)
            due.append(updated)
            self.on_due(updated)
        return due

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()

        def loop() -> None:
            while not self._stop.wait(self.poll_seconds):
                try:
                    self.run_due()
                except Exception as exc:  # keep one malformed task from killing the loop
                    print(f"[scheduler] error: {exc}")

        self._thread = threading.Thread(target=loop, name="ev-scheduler",
                                        daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=max(1.0, self.poll_seconds + 0.5))
