"""Task Manager — track long-running tasks (architecture §18)."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Task:
    id: str
    description: str
    status: str = "pending"          # pending|running|done|failed
    steps: list[dict] = field(default_factory=list)
    retries: int = 0
    result: dict = field(default_factory=dict)
    created: float = field(default_factory=time.time)


class TaskManager:
    def __init__(self, store: str = "data/tasks.json"):
        self.store = Path(store)
        self.store.parent.mkdir(parents=True, exist_ok=True)
        self._tasks: dict[str, Task] = {}
        self._load()
        self._counter = max((int(t.id.split("-")[1]) for t in
                             self._tasks.values()
                             if t.id.startswith("TASK-")), default=0)

    def _load(self) -> None:
        if not self.store.exists():
            return
        try:
            data = json.loads(self.store.read_text())
            for k, v in data.items():
                self._tasks[k] = Task(**v)
        except (json.JSONDecodeError, TypeError):
            pass

    def _save(self) -> None:
        payload = {k: v.__dict__ for k, v in self._tasks.items()}
        self.store.write_text(json.dumps(payload, ensure_ascii=False,
                                         indent=2))

    def new(self, description: str) -> Task:
        self._counter += 1
        t = Task(id=f"TASK-{self._counter:04d}", description=description)
        self._tasks[t.id] = t
        self._save()
        return t

    def get(self, tid: str) -> Task | None:
        return self._tasks.get(tid)

    def update(self, tid: str, **kw) -> Task | None:
        t = self.get(tid)
        if not t:
            return None
        for k, v in kw.items():
            setattr(t, k, v)
        self._save()
        return t

    def add_step(self, tid: str, name: str, status: str) -> None:
        t = self.get(tid)
        if t:
            t.steps.append({"name": name, "status": status, "ts": time.time()})
            self._save()

    def all(self) -> list[Task]:
        return list(self._tasks.values())
