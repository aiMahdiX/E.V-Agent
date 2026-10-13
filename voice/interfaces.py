"""Backend contracts shared by the adaptive voice pipeline."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Transcription:
    text: str
    language: str | None = None
    language_probability: float | None = None
    provider: str = ""


@dataclass(frozen=True)
class AudioChunk:
    data: bytes
    sample_rate: int
    channels: int = 1
    sample_format: str = "s16le"


class SpeechRecognizer(Protocol):
    provider: str

    def transcribe(self, audio: AudioChunk,
                   language: str | None = None) -> Transcription: ...


class SpeechSynthesizer(Protocol):
    provider: str

    def synthesize(self, text: str, language: str,
                   voice: str | None = None) -> AudioChunk: ...


class LiveConversation(Protocol):
    provider: str

    async def send_audio(self, audio: AudioChunk) -> None: ...

    async def receive(self): ...

    async def interrupt(self) -> None: ...

    async def close(self) -> None: ...