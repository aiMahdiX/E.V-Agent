"""Permission engine — the gate between the model and the OS.

Every tool call passes through here. Based on the classified level and the
configured auto-approve threshold it either allows, or requests human
approval.
"""
from __future__ import annotations

import json
import time

from security import policy
from security.approval import Approval


class PermissionDenied(Exception):
    pass


class PermissionEngine:
    def __init__(self, auto_approve_until: int = 2,
                 approval: Approval | None = None,
                 config: dict | None = None):
        self._auto_approve_until = auto_approve_until
        self.config = config
        self.approval = approval or Approval(confirm=True)
        self.reviewed: list[dict] = []
        # session memory: actions the user approved once stay approved
        # for the rest of the session (keyed by base action name).
        self.approved_actions: dict[str, float] = {}

    @property
    def auto_approve_until(self) -> int:
        if self.config is not None:
            configured = self.config.get("security", {}).get(
                "auto_approve_until_level", self._auto_approve_until)
            if isinstance(configured, int) and not isinstance(configured, bool):
                return configured
        return self._auto_approve_until

    @auto_approve_until.setter
    def auto_approve_until(self, value: int) -> None:
        self._auto_approve_until = int(value)

    def _log(self, entry: dict) -> None:
        self.reviewed.append(entry)
        try:
            with open("data/logs/permissions.jsonl", "a",
                      encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            pass

    @staticmethod
    def _base(action: str) -> str:
        return action.split("::", 1)[-1] if "::" in action else action

    def authorize(self, action: str, args: dict | None = None, *,
                  force_approval: bool = False,
                  level_override: int | None = None) -> int:
        args = args or {}
        level = (level_override if level_override is not None
                 else policy.action_level(action))
        base = self._base(action)
        requires_approval = force_approval or level >= 3
        auto_ok = not requires_approval and level <= self.auto_approve_until
        session_ok = (not requires_approval and not auto_ok
                      and base in self.approved_actions)
        decision = None

        if not auto_ok and not session_ok:
            decision = self.approval.ask(
                level=level, action=action, args=args,
                auto_approve_until=self.auto_approve_until)
            if decision and not requires_approval:
                self.approved_actions[base] = time.time()

        outcome = ("allowed" if (auto_ok or session_ok or decision)
                   else "blocked")
        self._log({
            "ts": time.time(),
            "action": action,
            "args": args,
            "level": level,
            "auto_approved": auto_ok,
            "session_approved": session_ok or bool(decision),
            "decision": ("auto" if auto_ok
                         else "session" if session_ok
                         else decision and "approved" or "denied"),
            "outcome": outcome,
        })

        if not (auto_ok or session_ok or decision):
            raise PermissionDenied(
                f"{action} blocked (Level {level}).")
        return level


class ShellPermissionEngine:
    def __init__(self, delegate: PermissionEngine):
        self.delegate = delegate
        # exact-command memory: an identical command is only asked once
        self.approved_commands: dict[str, float] = {}

    def authorize_command(self, command: str) -> int:
        level, reason = policy.classify_shell_command(command)
        self.delegate.authorize(
            "shell", {"command": command, "reason": reason},
            force_approval=level >= 3, level_override=level)
        return level
