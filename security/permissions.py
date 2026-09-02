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
                 approval: Approval | None = None):
        self.auto_approve_until = auto_approve_until
        self.approval = approval or Approval(confirm=True)
        self.reviewed: list[dict] = []
        # session memory: actions the user approved once stay approved
        # for the rest of the session (keyed by base action name).
        self.approved_actions: dict[str, float] = {}

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

    def authorize(self, action: str, args: dict | None = None) -> int:
        args = args or {}
        level = policy.action_level(action)
        base = self._base(action)
        auto_ok = level <= self.auto_approve_until
        session_ok = (not auto_ok) and base in self.approved_actions
        decision = None

        if not auto_ok and not session_ok:
            # Frictionless-operation policy: only destructive (Level 4)
            # actions still ask for human approval — everything else runs
            # automatically.  sudo is *not* gated here: the shell gate lets
            # Level-3 commands through (see ShellPermissionEngine) and the
            # password itself is requested at run time by tools/shell.py
            # (pkexec dialog for web-HUD requests, terminal getpass for REPL).
            if level >= 4:
                decision = self.approval.ask(
                    level=level, action=action, args=args,
                    auto_approve_until=self.auto_approve_until)
                if decision:
                    # remember for the rest of the session — asked once
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
        if level <= self.delegate.auto_approve_until:
            return level
        if level == 3:
            # Frictionless-operation policy: Level 3 (sudo / elevated /
            # unrecognized) runs without a "y/N" gate.  If the command uses
            # sudo, tools/shell.py requests only the password at execution time
            # (pkexec dialog via the web bridge, terminal getpass otherwise)).
            # Truly unrecognized commands run as-is, audited by policy/his log.

            return level
        key = command.strip()
        if key in self.approved_commands:
            return level          # already approved this session
        decision = self.delegate.approval.ask(
            level=level, action="shell",
            args={"command": command, "reason": reason},
            auto_approve_until=self.delegate.auto_approve_until)
        if not decision:
            raise PermissionDenied(
                f"Shell command blocked: {command!r}\n"
                f"Reason: {reason} (Level {level}).")
        self.approved_commands[key] = time.time()
        return level
