"""Screen capture tool (Phase 3).

Captures the desktop using whatever is available:
    scrot -> gnome-screenshot -> import (ImageMagick) -> PIL/Xlib -> browser fallback
All captures are lazy so E.V. works even without GUI tooling.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from tools.base import Tool


def _available(exe: str) -> bool:
    return shutil.which(exe) is not None


def capture_screen(path: str = "data/screenshots/screen.png", workspace=None) -> dict:
    """Capture the whole desktop to ``path``. Returns path/size or error."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        if _available("scrot"):
            subprocess.run(["scrot", "-q", "90", str(out)],
                           check=True, capture_output=True)
        elif _available("gnome-screenshot"):
            subprocess.run(["gnome-screenshot", "-f", str(out)],
                           check=True, capture_output=True)
        elif _available("import"):
            subprocess.run(["import", "-window", "root", str(out)],
                           check=True, capture_output=True)
        else:
            # last-resort: capture via the headless browser (a data URL)
            from tools.browser import screenshot as _browser_shot
            return _browser_shot(str(out))
        if not out.exists():
            return {"error": "capture_screen: no file produced"}
        return {"ok": True, "path": str(out),
                "size": out.stat().st_size}
    except Exception as e:  # noqa: BLE001
        return {"error": f"capture_screen: {type(e).__name__}: {e}"}


SCREEN_TOOLS = [
    Tool(name="capture_screen",
         description="Capture the desktop screen to a PNG file.",
         parameters={"type": "object",
                     "properties": {"path": {"type": "string"}}},
         required=[],
         fn=capture_screen,
         level=1),
]
