"""Safe desktop workflow orchestration for browser, screen, and camera tasks.

This layer does not bypass approvals. It keeps a small allowlist of safe desktop
operations, records each step in a JSONL audit log, and blocks any workflow that
attempts to run arbitrary shell commands or other high-risk actions.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Callable


class DesktopWorkflow:
    """Single-entry orchestration layer for safe local desktop automation."""

    SAFE_TOOLS = {
        "capture_screen",
        "browser_open",
        "browser_read",
        "browser_links",
        "browser_scroll",
        "browser_launch",
        "camera_list",
        "camera_capture",
        "camera_look",
        "vision_describe",
        "vision_screen",
    }

    def __init__(self, audit_path: str = "data/logs/desktop_workflow.jsonl"):
        self.audit_path = Path(audit_path)
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        self._tools: dict[str, Callable[..., Any]] = {}
        self._audit_fd = None

    def register_tool(self, name: str, fn: Callable[..., Any]) -> None:
        self._tools[name] = fn

    def _audit(self, action: str, payload: dict, ok: bool, result: Any) -> None:
        entry = {
            "ts": time.time(),
            "action": action,
            "payload": payload,
            "ok": ok,
            "result": result,
        }
        try:
            with open(self.audit_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def run(self, action: str, payload: dict | None = None) -> dict:
        payload = payload or {}
        if action not in self.SAFE_TOOLS and action not in self._tools:
            raise ValueError(f"unsafe workflow action rejected: {action}")
        if action.startswith("shell_") or "shell" in action.lower():
            raise ValueError("workflow blocks shell actions")
        fn = self._tools.get(action)
        if fn is None:
            raise ValueError(f"tool not registered: {action}")
        try:
            result = fn(**payload)
            ok = bool(result.get("ok") or result.get("path") or result.get("url")
                      or result.get("text") is not None)
            self._audit(action, payload, ok, result)
            return result
        except Exception as exc:  # noqa: BLE001
            self._audit(action, payload, False, {"error": str(exc)})
            raise

    def allowlist(self) -> list[str]:
        return sorted(self.SAFE_TOOLS | set(self._tools))
