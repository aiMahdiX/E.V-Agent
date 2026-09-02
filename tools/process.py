"""Process tools — list and manage processes."""
from __future__ import annotations

import os
import signal
import subprocess

from tools.base import Tool


def list_processes(pattern: str | None = None, **kwargs) -> dict:
    cmd = "ps -eo pid,pcpu,pmem,etime,cmd --sort=-pcpu"
    if pattern:
        cmd += f" | grep -i {pattern!r} | grep -v grep | head -40"
    else:
        cmd += " | head -40"
    proc = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return {"processes": proc.stdout.strip() or "(none)"}


def kill_process(pid: int, signal_num: int = 15, **kwargs) -> dict:
    try:
        os.kill(pid, signal_num)
        return {"pid": pid, "signalled": signal_num}
    except ProcessLookupError:
        return {"pid": pid, "error": "no such process"}
    except PermissionError:
        return {"pid": pid, "error": "permission denied"}


def start_process(command: str, background: bool = True, **kwargs) -> dict:
    try:
        if background:
            subprocess.Popen(command, shell=True,
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
            return {"started": command, "background": True}
        return {"started": command, "background": False}
    except OSError as e:
        return {"error": str(e)}


PROCESS_TOOLS = [
    Tool("process_list",
         "List running processes (optionally filtered by pattern).",
         {"type": "object", "properties": {
             "pattern": {"type": "string",
                         "description": "optional filter substring"}}},
         fn=list_processes),
    Tool("process_kill",
         "Send a signal to a process by PID.",
         {"type": "object", "properties": {
             "pid": {"type": "integer"},
             "signal": {"type": "integer",
                        "description": "signal number (default 15=SIGTERM)"}}},
         required=["pid"], fn=kill_process),
    Tool("process_start",
         "Start a process/command, optionally in background.",
         {"type": "object", "properties": {
             "command": {"type": "string"},
             "background": {"type": "boolean"}}},
         required=["command"], fn=start_process),
]
