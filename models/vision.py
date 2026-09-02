"""Vision model wrapper (Phase 4 — image understanding via a multimodal
Ollama model, e.g. qwen3.5:4b which supports vision).

Local-first: the image is sent as base64 to the Ollama /api/generate
``images`` field. No cloud dependency.
"""
from __future__ import annotations

import base64
from pathlib import Path

from models.llm import OllamaClient


def _encode_image(path: str) -> str:
    data = Path(path).read_bytes()
    return base64.b64encode(data).decode("ascii")


class VisionModel:
    def __init__(self, client: OllamaClient, model: str | None = None):
        self.client = client
        self.model = model  # falls back to client's vision model

    def describe(self, image_path: str, prompt: str = "describe the image") -> str:
        """Send an image + prompt to the multimodal model; return text."""
        if not Path(image_path).exists():
            return f"image not found: {image_path}"
        b64 = _encode_image(image_path)
        payload = {
            "model": self.model or self.client.model,
            "prompt": prompt,
            "images": [b64],
            "stream": False,
            # thinking-capable vision models can dump the answer into the
            # `thinking` channel leaving `response` empty; disable it.
            "think": False,
            "options": {"num_predict": 400},
        }
        try:
            data = self.client._post("/api/generate", payload)
        except Exception as e:  # noqa: BLE001
            return f"[vision error] {type(e).__name__}: {e}"
        text = (data.get("response") or "").strip()
        if not text and data.get("thinking"):
            text = str(data["thinking"]).strip()
        return text
