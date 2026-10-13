"""Durable, resumable local workflows built on TaskManager checkpoints."""
from __future__ import annotations

from typing import Callable


class WorkflowEngine:
    def __init__(self, tasks, max_retries: int = 2):
        self.tasks = tasks
        self.max_retries = max(0, int(max_retries))

    def run(self, task_id: str, steps: list[dict], execute: Callable):
        task = self.tasks.get(task_id)
        if task is None:
            return {"ok": False, "error": f"unknown task: {task_id}"}
        if not steps:
            self.tasks.update(task_id, status="done", result={"completed": 0})
            return {"ok": True, "completed": 0}

        completed_names = {
            item.get("name") for item in task.steps
            if item.get("status") == "done"
        }
        self.tasks.update(task_id, status="running")
        completed = 0
        for step in steps:
            name = str(step.get("name") or "step")
            if name in completed_names:
                completed += 1
                continue
            retries = 0
            while True:
                self.tasks.add_step(task_id, name, "running")
                try:
                    result = execute(step, self.tasks.get(task_id))
                except Exception as exc:  # noqa: BLE001 - checkpoint failure
                    retries += 1
                    self.tasks.update(task_id, retries=task.retries + 1,
                                      result={"error": str(exc), "step": name})
                    self.tasks.add_step(task_id, name, f"retry:{retries}")
                    if retries > self.max_retries:
                        self.tasks.update(task_id, status="failed")
                        return {"ok": False, "completed": completed,
                                "error": str(exc), "failed_step": name}
                    continue
                self.tasks.add_step(task_id, name, "done")
                current = self.tasks.get(task_id)
                self.tasks.update(task_id, result={
                    "last_step": name, "last_result": result,
                    "completed": completed + 1,
                }, retries=current.retries if current else 0)
                completed += 1
                break
        self.tasks.update(task_id, status="done", result={"completed": completed})
        return {"ok": True, "completed": completed}

    def resume(self, task_id: str, steps: list[dict], execute: Callable):
        """Resume using completed step checkpoints already persisted."""
        return self.run(task_id, steps, execute)
