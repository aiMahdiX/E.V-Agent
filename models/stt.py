"""Speech-to-Text wrapper (Phase 2 — Whisper / Qwen ASR)."""
from __future__ import annotations


class STTModel:
    def transcribe(self, audio_path: str) -> str:
        raise NotImplementedError("STT not implemented (Phase 2)")
