"""Shell tool — run system commands through the permission engine."""
from __future__ import annotations

import re
import shutil
import subprocess
import time

from tools.base import Tool
from security.permissions import ShellPermissionEngine, PermissionDenied
from security.interactive import (sudo_should_ask_gui, announce_sudo)

# When enabled, an approved ``sudo ...`` command is executed via
# ``pkexec ...`` so the desktop polkit agent asks for the root password in
# a GUI dialog — no TTY needed.  If pkexec is missing or no polkit agent
# can be reached, the original command is run and its real error surfaces.
# Configured by main.py from ``security.sudo_via_pkexec`` (default true).
_sudo_via_pkexec: bool | dict = True
_SUDO_RE = re.compile(r"(?<![\w-])sudo(?![\w-])")


def set_sudo_via_pkexec(enabled: bool | dict) -> None:
    global _sudo_via_pkexec
    _sudo_via_pkexec = enabled


def _use_pkexec() -> bool:
    if isinstance(_sudo_via_pkexec, dict):
        return bool(_sudo_via_pkexec.get("security", {}).get(
            "sudo_via_pkexec", True))
    return bool(_sudo_via_pkexec)


def _execute(command: str, timeout: int, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(
        command, shell=True, capture_output=True, text=True,
        timeout=timeout, executable="/bin/bash", **kw)


def _sudo_password_from_terminal() -> str:
    """Ask for the sudo password right here on the TTY (REPL channel).)"""
    import getpass
    return getpass.getpass("Enter sudo password: ")


def run_command(command: str, timeout: int = 60,
                perm: ShellPermissionEngine | None = None,
                workspace=None, **kwargs) -> dict:
    """Execute a shell command, gated by the permission engine."""
    if perm is not None:
        perm.authorize_command(command)   # raises PermissionDenied if blocked
    try:
        timeout = max(1, int(timeout))
    except (TypeError, ValueError):
        timeout = 60
    start = time.time()

    is_sudo = bool(_SUDO_RE.search(command))
    # Web HUD requests -> pkexec (the desktop polkit agent pops a graphical
    # password dialog); terminal (REPL) requests -> sudo -S with an
    # in-terminal getpass prompt — the password is asked in the same
    # channel the request came from, never a generic "y/N" gate.
    use_pkexec = bool(is_sudo and _use_pkexec() and sudo_should_ask_gui()
                      and shutil.which("pkexec"))
    executed = command
    run_kw = {}
    if is_sudo and sudo_should_ask_gui() and not use_pkexec:
        # Web request but no polkit/pkexec available: the classic sudo -S
        # trick would block on a TTY nobody is looking at — instead surface a
        # clear error telling the user exactly what to run in the terminal.
        announce_sudo(command)
        return {
            "command": command,
            "error": (
                "🔐 This command requires a sudo password, but the graphical "
                "polkit (pkexec) prompt is unavailable.\n"
                "Run this command in a terminal instead:\n"
                f"    {command}"),
            "exit_code": None,
            "executor": "blocked-web-no-polkit",
        }
    if use_pkexec:
        executed = _SUDO_RE.sub("pkexec", command)
        # Before the graphical polkit password dialog appears, tell the
        # user-facing layer (HUD event / terminal line) WHY a password is
        # needed and for WHICH command — the GUI dialog alone gives no clue.
        announce_sudo(command)
        # the polkit dialog may wait for the user to type the password
        timeout = max(timeout, 180)
    elif is_sudo:
        # terminal (REPL) channel: announce + ask for the password right
        # here.  announce_sudo prints a clear line FIRST so the user knows
        # exactly which command needs root.
        announce_sudo(command)
        executed = _SUDO_RE.sub("sudo -S", command, count=1)
        run_kw["input"] = _sudo_password_from_terminal() + "\n"

    try:
        proc = _execute(executed, timeout, **run_kw)
        executor = ("pkexec" if use_pkexec
                     else "sudo -S" if is_sudo else "bash")
        if use_pkexec and proc.returncode in (126, 127):
            # pkexec could not exec (no polkit agent / not authorized):
            # retry the original command so the actual error surfaces.
            proc = _execute(command, timeout)
            executor = "bash (pkexec fallback)"
        return {
            "command": command,
            "exit_code": proc.returncode,
            "stdout": proc.stdout[:4000],
            "stderr": proc.stderr[:2000],
            "elapsed_s": round(time.time() - start, 2),
            "executor": executor,
        }
    except subprocess.TimeoutExpired:
        return {"command": command, "error": f"timed out after {timeout}s",
                "exit_code": None}
    except OSError as e:
        return {"command": command, "error": str(e), "exit_code": None}


SHELL_TOOL = Tool(
    name="shell_run_command",
    description=("Run a shell command on the host and return stdout, stderr "
                 "and exit code. Use for inspection (ls, ps, df, nvidia-smi, "
                 "systemctl status, journalctl) and for executing repairs."),
    parameters={
        "type": "object",
        "properties": {
            "command": {"type": "string",
                        "description": "The shell command to execute"},
            "timeout": {"type": "integer",
                        "description": "Seconds before timeout (default 60)"},
        },
    },
    required=["command"],
    fn=run_command,
)
