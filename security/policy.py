"""Security policy — classifies actions into permission Levels 0..4.

Level 0  Safe            : read-only inspection
Level 1  Write           : file edits / moves within workspace
Level 2  System          : package install, service restart, network
Level 3  Privileged      : sudo, /etc, /boot, users, firewall
Level 4  Destructive     : rm -rf, format, wipe, partitions, credentials

The classifier is deliberately conservative: unknown input is *escalated*
rather than assumed safe.
"""
from __future__ import annotations

import re

ACTION_LEVELS = {
    # Level 0 — read-only
    "read_file": 0, "search_files": 0, "list_processes": 0,
    "gpu_status": 0, "service_status": 0, "list_directory": 0,
    "run_command": 0,
    # actual tool names (Phase 1 registry)
    "fs_read_file": 0, "fs_search_files": 0, "fs_list_directory": 0,
    "fs_create_file": 0,
    "process_list": 0, "service_status_t": 0,
    "gpu_temperature": 0,
    # Level 1 — write within workspace
    "write_file": 1, "edit_file": 1, "move_file": 1, "copy_file": 1,
    "mkdir": 1, "create_file": 1,
    "fs_write_file": 1, "fs_edit_file": 1,
    # Level 2 — system level
    "kill_process": 2, "service_start": 2, "service_stop": 2,
    "service_restart": 2, "pip_install": 2, "apt_install": 2,
    "network_change": 2,
    "process_kill": 2, "process_start": 2,
    "service_start_t": 2, "service_stop_t": 2, "service_restart_t": 2,
    # Level 3 — privileged
    "user_management": 3, "firewall_change": 3, "edit_system_conf": 3,
    # Level 4 — destructive
    "delete_file": 4, "format_disk": 4, "wipe": 4, "credential_delete": 4,
    # Phase 3 — browser/screen (navigation & inspection are safe)
    "browser_open": 0, "browser_read": 0, "browser_screenshot": 0,
    "capture_screen": 0,
    "browser_links": 0, "browser_scroll": 0,
    "browser_click": 1, "browser_type": 1, "browser_launch": 1,
    # GUI control is invasive but not privileged
    "gui_click": 2, "gui_type": 2, "gui_screenshot": 2,
    "gui_move": 2, "gui_scroll": 2,
    # Phase 4 — camera/vision (read-only sensing; capture writes a frame
    # into the workspace data dir, hence Level 1)
    "camera_list": 0, "camera_capture": 1, "camera_look": 0,
    "vision_describe": 0, "vision_screen": 0,
    # The shell tool itself is Level 0 here — every concrete command is
    # classified separately by ShellPermissionEngine/classify_shell_command.
    "shell_run_command": 0,
}

_SHELL_RULES = [
    (re.compile(r"\brm\s+(-[a-z]*r[a-z]*\s+)?(-[a-z]*f[a-z]*\s*)?", re.I),
     4, "recursive/force remove"),
    (re.compile(r"\b(mkfs|format|wipe|fdisk|parted|gdisk|shred)\b", re.I),
     4, "disk format/partition"),
    (re.compile(r"\bdd\b", re.I), 4, "low-level disk write"),
    (re.compile(r"\b(passwd|userdel|deluser)\b", re.I),
     4, "credential/user delete"),
    (re.compile(r"\bsudo\b", re.I), 3, "elevated privileges"),
    (re.compile(r"\bchown\b|\bchmod\s+[0-7]{3,4}\b", re.I),
     3, "ownership/permission change"),
    (re.compile(r"\b/etc/\b|\b/boot\b|\b/usr/\b", re.I),
     3, "system directory touch"),
    (re.compile(r"\b(iptables|ufw|firewall-cmd)\b", re.I),
     3, "firewall change"),
    (re.compile(r"\b(useradd|adduser|usermod|passwd)\b", re.I),
     3, "user management"),
    (re.compile(r"\bapt(-get)?\s+(install|remove|purge|dist-upgrade)\b", re.I),
     2, "package change"),
    (re.compile(r"\bpip\s+install\b", re.I), 2, "python package install"),
    (re.compile(r"\bsystemctl\s+(start|stop|restart|enable|disable)\b", re.I),
     2, "service control"),
    (re.compile(r"\bservice\s+(start|stop|restart)\b", re.I),
     2, "service control"),
    (re.compile(r"\bip\s+(link|addr|route)\s+(add|del|set)\b", re.I),
     2, "network config"),
    (re.compile(r"\b(sysctl|modprobe|rmmod|dpkg|rpm)\b", re.I),
     2, "kernel/module"),
    (re.compile(r"\b(mkdir|touch|mv|cp|ln)\b", re.I), 1, "file write"),
    (re.compile(r"\b(echo|cat|printf)\s*>", re.I), 1, "redirect write"),
    (re.compile(r"\bsed\s+-i\b|\btee\b", re.I), 1, "in-place write"),
    (re.compile(r"\b(killall|setxkbmap)\b", re.I), 2, "process/input change"),
    (re.compile(r"\b(pwd|ls|df|free|du|stat|file|which|type)\b", re.I),
     0, "inspection"),
    (re.compile(r"\b(echo|printf|true|false)\b(?!\s*[>|])", re.I),
     0, "harmless output"),
    (re.compile(r"\b(nvidia-smi|sensors|top|htop)\b", re.I), 0, "monitor"),
    (re.compile(r"\b(cat|less|more|head|tail|grep|rg|find|locate)\b", re.I),
     0, "read/search"),
    (re.compile(r"\b(ps|ss|netstat|lsof|uptime|w|who)\b", re.I),
     0, "process/network status"),
    (re.compile(r"\b(journalctl|dmesg)\b", re.I), 0, "log inspect"),
    (re.compile(r"\b(uname|hostname|id|groups|env|printenv)\b", re.I),
     0, "environment inspect"),
    (re.compile(r"\bgit\s+(status|log|diff)\b", re.I), 0, "git inspect"),
    (re.compile(r"\b(lsblk|mount|blkid)\b", re.I), 0, "block device inspect"),
]


def classify_shell_command(command: str) -> tuple[int, str]:
    cmd = command.strip()
    if not cmd:
        return 0, "empty command"
    for pattern, level, reason in _SHELL_RULES:
        if pattern.search(cmd):
            return level, reason
    return 3, "unrecognized command (escalated)"


def action_level(action: str) -> int:
    if action in ACTION_LEVELS:
        return ACTION_LEVELS[action]
    if action.startswith("mcp::"):
        # MCP actions are keyed by their bare tool name; local MCP
        # extensions are trusted, so unknown ones default to Level 1.
        base = action.split("::", 1)[1]
        if base in ACTION_LEVELS:
            return ACTION_LEVELS[base]
        return 1
    return ACTION_LEVELS.get(action, 3)


def describe_level(level: int) -> str:
    return {0: "Safe (read-only)", 1: "Write (workspace)", 2: "System",
            3: "Privileged", 4: "Destructive"}.get(level, "Unknown")


def needs_approval(level: int, auto_approve_until: int = 2) -> bool:
    return level > auto_approve_until
