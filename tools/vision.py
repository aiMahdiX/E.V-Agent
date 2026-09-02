"""Vision tools (Phase 4) — describe an image with the local multimodal model.

Thin wrapper that lets the Agent ask "what is in this image?" for a camera
frame or a screenshot.
"""
from __future__ import annotations

from tools.base import Tool

_vision_model = None  # lazily set by main.py via set_vision_model()


def set_vision_model(vm):
    global _vision_model
    _vision_model = vm


def describe_image(path: str, prompt: str = "describe the image",
                   workspace=None) -> dict:
    """Describe an image file with the local vision model."""
    if _vision_model is None:
        return {"error": "vision model not initialized"}
    text = _vision_model.describe(path, prompt)
    return {"ok": bool(text and not text.startswith("[vision error]")),
            "description": text, "path": path}


def describe_screen(prompt: str = "describe this screen",
                    workspace=None) -> dict:
    """Capture the screen and describe it with the vision model."""
    from tools.screen import capture_screen
    shot = capture_screen(path="data/screenshots/vision_screen.png")
    if not shot.get("ok"):
        return shot
    return describe_image(shot["path"], prompt)


def camera_look(index: int = 0,
                prompt: str = "به فارسی و در حد دو جمله بگو در این تصویر چه می‌بینی",
                workspace=None) -> dict:
    """Capture a webcam frame AND describe it in one step.

    This is the tool for 'دوربین رو باز کن' / 'چی می‌بینی؟' requests.
    """
    from tools.camera import capture_frame
    shot = capture_frame(path="data/camera/frame.png", index=index,
                         workspace=workspace)
    if not shot.get("ok"):
        return shot
    result = describe_image(shot["path"], prompt)
    result["camera"] = shot.get("camera", f"/dev/video{index}")
    return result


VISION_TOOLS = [
    Tool(name="camera_look",
         description="Take a photo with the WEBCAM and describe what the "
                     "camera sees. USE THIS when the user says «دوربین رو "
                     "باز کن», «دوربین چی می‌بینی؟», «با دوربین نگاه کن», "
                     "«چی می‌بینی؟». This is about the CAMERA (webcam), "
                     "NOT the browser — never open websites for this.",
         parameters={"type": "object",
                     "properties": {"index": {"type": "integer"},
                                    "prompt": {"type": "string"}}},
         required=[],
         fn=camera_look,
         level=1),
    Tool(name="vision_describe",
         description="Describe the contents of an IMAGE FILE (e.g. a saved "
                     "camera frame or screenshot) with the local vision "
                     "model. Use for «این عکس چیه» / describing an existing "
                     "image path.",
         parameters={"type": "object",
                     "properties": {"path": {"type": "string"},
                                    "prompt": {"type": "string"}}},
         required=["path"],
         fn=describe_image,
         level=1),
    Tool(name="vision_screen",
         description="Capture the SCREEN (monitor) and describe what is "
                     "visible. Use when the user says «صفحه رو نگاه کن», "
                     "«روی صفحه چی هست؟».",
         parameters={"type": "object",
                     "properties": {"prompt": {"type": "string"}}},
         required=[],
         fn=describe_screen,
         level=1),
]