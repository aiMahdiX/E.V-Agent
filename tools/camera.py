"""Camera tool (Phase 4).

Captures frames from a webcam using OpenCV (preferred) or ffmpeg.
Lazy imports so E.V. works even without a camera present.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from tools.base import Tool


def _camera_indices() -> list[int]:
    """Detect /dev/videoN indexes (even ones are usually real cams)."""
    idx = []
    for n in range(0, 6):
        if os.path.exists(f"/dev/video{n}"):
            idx.append(n)
    return idx


def camera_list(workspace=None, **kwargs) -> dict:
    """List available local video devices."""
    try:
        idx = _camera_indices()
        if not idx:
            return {"error": "no /dev/video* devices found"}
        return {"ok": True, "devices": [f"/dev/video{n}" for n in idx]}
    except Exception as e:  # noqa: BLE001
        return {"error": f"camera_list: {type(e).__name__}: {e}"}


def capture_frame(path: str = "data/camera/frame.png", index: int = 0,
                  workspace=None, **kwargs) -> dict:
    """Capture a single frame from camera ``index`` to ``path``."""
    out = Path(path)
    if not out.is_absolute() and workspace:
        out = Path(workspace) / out
    out.parent.mkdir(parents=True, exist_ok=True)
    # prefer OpenCV
    try:
        import cv2
        cap = cv2.VideoCapture(index)
        if not cap.isOpened():
            return {"error": f"cannot open /dev/video{index}"}
        ok, frame = cap.read()
        cap.release()
        if not ok:
            return {"error": "failed to read a frame"}
        cv2.imwrite(str(out), frame)
    except ImportError:
        # fallback: ffmpeg grab single frame
        r = subprocess.run(
            ["ffmpeg", "-y", "-f", "v4l2", "-i", f"/dev/video{index}",
             "-frames:v", "1", str(out)],
            capture_output=True, text=True, timeout=15)
        if r.returncode != 0:
            return {"error": "ffmpeg capture failed: " +
                             (r.stderr or "")[-200:]}
    if not out.exists():
        return {"error": "capture produced no file"}
    return {"ok": True, "path": str(out),
            "size": out.stat().st_size, "camera": f"/dev/video{index}"}


CAMERA_TOOLS = [
    Tool(name="camera_list",
         description="List available webcam / video devices.",
         parameters={"type": "object", "properties": {}},
         required=[],
         fn=camera_list,
         level=1),
    Tool(name="camera_capture",
         description="Capture a single frame from a webcam to a PNG file.",
         parameters={"type": "object",
                     "properties": {"path": {"type": "string"},
                                    "index": {"type": "integer"}}},
         required=[],
         fn=capture_frame,
         level=1),
]
