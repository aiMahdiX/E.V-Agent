"""Microphone sensor (Phase 2) — thin wrapper for the voice session."""
from __future__ import annotations

from voice import mic
from voice.session import capture_utterance


class MicrophoneMonitor:
    """Managed access to the arecord-based microphone."""

    def __init__(self, device: str | None = None):
        self.device = device
        self._stream: mic.MicStream | None = None

    def open_stream(self, frame_ms: int = 20) -> mic.MicStream:
        self._stream = mic.MicStream(frame_ms=frame_ms, device=self.device)
        self._stream.start()
        return self._stream

    def close(self) -> None:
        if self._stream:
            self._stream.stop()
            self._stream = None

    def stop(self) -> None:
        self.close()

    def available(self) -> bool:
        return mic.arecord_available()
