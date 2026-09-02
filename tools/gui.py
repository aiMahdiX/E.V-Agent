"""GUI automation tool (Phase 3) — Wayland-aware.

Backend selection:
* Wayland session  -> ``ydotool`` (needs ``ydotoold`` running).
* X11 session      -> ``xdotool`` -> ``pyautogui``.

Honesty guarantees (the agent MUST NOT claim success without them):
* Every command's exit code is checked; ``ok=True`` is returned ONLY
  when the backend actually accepted the event.
* Errors carry the raw stderr plus a fix hint, so the agent relays
  facts instead of inventing cursor positions.

Only use when the user explicitly asks for a GUI action.
"""
from __future__ import annotations

import os
import shutil
import subprocess

from tools.base import Tool


def _available(exe: str) -> bool:
    return shutil.which(exe) is not None


def _is_wayland() -> bool:
    return os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"


def _yd_env() -> dict:
    """Environment with YDOTOOL_SOCKET pointing at the first live socket."""
    candidates = []
    if os.environ.get("YDOTOOL_SOCKET"):
        candidates.append(os.environ["YDOTOOL_SOCKET"])
    uid = os.getuid()
    candidates += [f"/run/user/{uid}/.ydotool_socket", "/tmp/.ydotool_socket"]
    env = dict(os.environ)
    for c in candidates:
        if os.path.exists(c):
            env["YDOTOOL_SOCKET"] = c
            break
    else:  # none exists — let client use default & report the failure
        env.setdefault("YDOTOOL_SOCKET", candidates[1])
    return env


_DAEMON_HINT = (
    "start daemon: sudo systemctl enable --now ydotool "
    "(or: sudo ydotoold &) then ensure YDOTOOL_SOCKET matches"
)


def _ydo(args: list) -> tuple:
    """Run ydotool; return (rc, combined_output)."""
    try:
        r = subprocess.run(["ydotool", *args], capture_output=True,
                           text=True, timeout=15, env=_yd_env())
        out = (r.stderr or r.stdout or "").strip()
        return r.returncode, out
    except Exception as e:  # noqa: BLE001
        return -1, f"{type(e).__name__}: {e}"


def _err(tool: str, msg: str, hint=None) -> dict:
    d = {"ok": False, "error": f"{tool}: {msg}"}
    if hint:
        d["hint"] = hint
    return d


# ----------------------------------------------------------------- backends
def _move_click(x, y, button) -> dict:
    """Absolute move (+optional click). Returns honest result."""
    if _is_wayland():
        if not _available("ydotool"):
            return _err("gui", "ydotool not installed",
                        "sudo apt install ydotool")
        rc, out = _ydo(["mousemove", "-a", str(int(x)), str(int(y))])
        if rc != 0:
            return _err("gui_move",
                        f"ydotool failed (rc={rc}): {out}", _DAEMON_HINT)
        if button is not None:
            rc2, out2 = _ydo(["click", str(button)])
            if rc2 != 0:
                return _err("gui_click",
                            f"ydotool failed (rc={rc2}): {out2}",
                            _DAEMON_HINT)
        return {"ok": True, "backend": "ydotool",
                "at": [int(x), int(y)],
                "clicked": button if button is not None else False}
    # X11
    if _available("xdotool"):
        cmd = ["xdotool"]
        if x is not None and y is not None:
            cmd += ["mousemove", str(int(x)), str(int(y))]
        if button is not None:
            cmd += ["click", str(button)]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if r.returncode != 0:
            return _err("gui", f"xdotool failed: {(r.stderr or '').strip()}")
        return {"ok": True, "backend": "xdotool",
                "at": [int(x), int(y)] if x is not None else None,
                "clicked": button if button is not None else False}
    try:
        import pyautogui  # lazy import
        if x is not None and y is not None:
            pyautogui.moveTo(x, y)
        if button is not None:
            pyautogui.click()
        return {"ok": True, "backend": "pyautogui",
                "at": [int(x), int(y)] if x is not None else None}
    except Exception as e:  # noqa: BLE001
        return _err("gui", f"no backend available ({e})")


def _scroll(steps) -> dict:
    """Scroll ``steps`` wheel ticks; positive = down, negative = up."""
    steps = int(steps)
    btn = 5 if steps >= 0 else 4          # ydotool/xdotool wheel buttons
    n = abs(steps)
    if _is_wayland():
        if not _available("ydotool"):
            return _err("gui_scroll", "ydotool not installed",
                        "sudo apt install ydotool")
        rc, out = _ydo(["click", "-r", str(n), str(btn)])
        if rc != 0:
            return _err("gui_scroll",
                        f"ydotool failed (rc={rc}): {out}", _DAEMON_HINT)
        return {"ok": True, "backend": "ydotool",
                "scrolled": ["down" if steps >= 0 else "up", n]}
    if _available("xdotool"):
        r = subprocess.run(["xdotool", "click", "--repeat", str(n), str(btn)],
                           capture_output=True, text=True, timeout=15)
        if r.returncode != 0:
            return _err("gui_scroll",
                        f"xdotool failed: {(r.stderr or '').strip()}")
        return {"ok": True, "backend": "xdotool",
                "scrolled": ["down" if steps >= 0 else "up", n]}
    return _err("gui_scroll", "no backend available (wayland="
                f"{_is_wayland()}, xdotool={_available('xdotool')})")


def _type_text(text: str) -> dict:
    if _is_wayland():
        if not _available("ydotool"):
            return _err("gui_type", "ydotool not installed")
        rc, out = _ydo(["type", "-d", "15", text])
        if rc != 0:
            return _err("gui_type",
                        f"ydotool failed (rc={rc}): {out}", _DAEMON_HINT)
        return {"ok": True, "backend": "ydotool", "typed": len(text)}
    if _available("xdotool"):
        r = subprocess.run(["xdotool", "type", "--clearmodifiers", text],
                           capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            return _err("gui_type",
                        f"xdotool failed: {(r.stderr or '').strip()}")
        return {"ok": True, "backend": "xdotool", "typed": len(text)}
    try:
        import pyautogui
        pyautogui.typewrite(text, interval=0.01)
        return {"ok": True, "backend": "pyautogui", "typed": len(text)}
    except Exception as e:  # noqa: BLE001
        return _err("gui_type", f"no backend available ({e})")


# ------------------------------------------------------------------- tools
def gui_move(x: int, y: int, workspace=None) -> dict:
    """Move the mouse pointer to absolute coordinates (no click)."""
    return _move_click(x, y, None)


def gui_click(x: int, y: int, workspace=None) -> dict:
    """Move the pointer to (x, y) and left-click there."""
    return _move_click(x, y, 1)


def gui_scroll(steps: int = 3, workspace=None) -> dict:
    """Scroll the window under the pointer. steps>0 down, <0 up."""
    return _scroll(int(steps))


def gui_type(text: str, workspace=None) -> dict:
    """Type text into the currently focused window."""
    return _type_text(text)


def gui_screenshot(path: str = "data/screenshots/gui.png",
                   workspace=None) -> dict:
    """Capture a screenshot of the whole screen."""
    from tools.screen import capture_screen
    res = capture_screen(path=path, workspace=workspace)
    if res.get("ok") and not res.get("path"):
        res["path"] = path
    return res


GUI_TOOLS = [
    Tool(name="gui_move",
         description="Move the mouse pointer to absolute screen "
                     "coordinates WITHOUT clicking.",
         parameters={"type": "object",
                     "properties": {"x": {"type": "integer"},
                                    "y": {"type": "integer"}}},
         required=["x", "y"],
         fn=gui_move,
         level=2),
    Tool(name="gui_click",
         description="Move the pointer to absolute coordinates and "
                     "left-click there.",
         parameters={"type": "object",
                     "properties": {"x": {"type": "integer"},
                                    "y": {"type": "integer"}}},
         required=["x", "y"],
         fn=gui_click,
         level=2),
    Tool(name="gui_scroll",
         description="Scroll the focused window: steps>0 scrolls down, "
                     "steps<0 scrolls up (each step = one wheel tick).",
         parameters={"type": "object",
                     "properties": {"steps": {"type": "integer"}}},
         required=[],
         fn=gui_scroll,
         level=2),
    Tool(name="gui_type",
         description="Type text into the currently focused window.",
         parameters={"type": "object",
                     "properties": {"text": {"type": "string"}}},
         required=["text"],
         fn=gui_type,
         level=2),
    Tool(name="gui_screenshot",
         description="Capture a screenshot of the whole screen.",
         parameters={"type": "object",
                     "properties": {"path": {"type": "string"}}},
         required=[],
         fn=gui_screenshot,
         level=2),
]


def gui_screenshot(path: str = "data/screenshots/gui.png", workspace=None) -> dict:
    """Screenshot the whole screen (via xdotool/import or pyautogui)."""
    from pathlib import Path
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        if _available("import"):
            subprocess.run(["import", "-window", "root", str(out)],
                           check=True, capture_output=True)
        else:
            import pyautogui
            pyautogui.screenshot(str(out))
        return {"ok": True, "path": str(out),
                "size": out.stat().st_size}
    except Exception as e:  # noqa: BLE001
        return {"error": f"gui_screenshot: {type(e).__name__}: {e}"}


GUI_TOOLS = [
    Tool(name="gui_click",
         description="Click the mouse at absolute screen coordinates.",
         parameters={"type": "object",
                     "properties": {"x": {"type": "integer"},
                                    "y": {"type": "integer"}}},
         required=["x", "y"],
         fn=gui_click,
         level=2),
    Tool(name="gui_type",
         description="Type text on the active window.",
         parameters={"type": "object",
                     "properties": {"text": {"type": "string"}}},
         required=["text"],
         fn=gui_type,
         level=2),
    Tool(name="gui_screenshot",
         description="Capture a GUI screenshot.",
         parameters={"type": "object",
                     "properties": {"path": {"type": "string"}}},
         required=[],
         fn=gui_screenshot,
         level=2),
]