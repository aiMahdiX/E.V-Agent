"""Audio/voice tool (Phase 2)."""
from __future__ import annotations

from tools.base import Tool


def record(duration_s: float) -> dict:
    raise NotImplementedError("Audio not implemented (Phase 2)")


def play(path: str) -> dict:
    raise NotImplementedError("Audio not implemented (Phase 2)")


AUDIO_TOOLS = []
