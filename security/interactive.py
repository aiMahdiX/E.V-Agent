"""Session interaction context — distinguishes a web-HUD request from a
plain terminal (REPL) request.

tools/shell.py uses this to decide **how** to ask for a sudo password:
- web HUD request  -> ``pkexec`` so the desktop polkit agent pops the
  graphical password dialog;
- terminal (REPL) request -> ``sudo -S`` with an in-terminal ``getpass``
  prompt right there on the TTY.

The user asked for frictionless operation: only commands that genuinely need
a root password (sudo) may ask for it, and always in the same channel the
request came from — never a generic "y/N approve?" gate.
"""
from __future__ import annotations

_sudo_web_active = False
_sudo_announcer = None     # callable(command) -> None, invoked before asking


def set_sudo_web_active(active: bool) -> None:
    """Mark the current agent run as coming from the web HUD."""
    global _sudo_web_active
    _sudo_web_active = bool(active)


def sudo_should_ask_gui() -> bool:
    """True when the current request is being served through the web HUD."""
    return _sudo_web_active


def set_sudo_announcer(fn) -> None:
    """Register a callback called right before a sudo password request.

    ``fn(command: str) -> None``.  The web layer uses this to push a
    ``sudo_request`` SSE event to the HUD (so the user sees *why* a
    password is being asked and for *which* command) before the graphical
    polkit dialog (pkexec) or the terminal getpass prompt appears.
    """
    global _sudo_announcer
    _sudo_announcer = fn


def announce_sudo(command: str) -> None:
    """Tell the active user-facing layer a sudo password is needed."""
    fn = _sudo_announcer
    if fn is not None:
        try:
            fn(command)
            return
        except Exception:  # noqa: BLE001 — a broken announcer must not block the OS gate
            pass
    # No hook registered (headless / plain terminal) — print a clear line
    # so the user knows *why* a password is being asked and for which command.
    import sys
    print(f"🔐 رمز sudo برای دستور زیر لازم است: {command}", file=sys.stderr, flush=True)