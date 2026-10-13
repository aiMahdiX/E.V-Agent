"""Human approval interaction for Level 3/4 actions.

Prompt resolution order in :meth:`Approval.ask`:
1. ``ask_hook`` — a pluggable bridge (the web HUD asks the user in the
   browser and answers asynchronously);
2. interactive CLI ``input()`` prompt when ``confirm=True`` (REPL mode);
3. deny — headless default (``confirm=False``).
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Callable

_approval_override: ContextVar[Callable[..., Any] | None] = ContextVar(
    "approval_override", default=None)


@contextmanager
def approval_context(hook: Callable[..., Any]):
    """Override approval handling only within the current execution context."""
    token = _approval_override.set(hook)
    try:
        yield
    finally:
        _approval_override.reset(token)


class Approval:
    def __init__(self, confirm: bool = True,
                 ask_hook: Callable[..., Any] | None = None):
        self.confirm = confirm
        # web bridge: callable(level=..., action=..., args=...,
        # auto_approve_until=...) -> bool | None
        # True/False decides; None (or a raised error) falls through to the
        # default CLI/headless behaviour below.
        self.ask_hook = ask_hook

    def ask(self, level: int, action: str, args: dict,
            auto_approve_until: int) -> bool:
        hook = _approval_override.get() or self.ask_hook
        if hook is not None:
            try:
                decision = hook(
                    level=level, action=action, args=args,
                    auto_approve_until=auto_approve_until)
            except Exception:  # noqa: BLE001 — the gate must never crash
                decision = None
            if decision is not None:
                return bool(decision)
        if not self.confirm:
            # headless default: deny anything requiring approval
            return False
        from security import policy
        print("\n[⚠ Permission required]")
        print(f"  Action : {action}")
        print(f"  Level  : {level} — {policy.describe_level(level)}")
        if args:
            print(f"  Args   : {args}")
        resp = input("  Approve? [y/N] ").strip().lower()
        return resp in ("y", "yes")
