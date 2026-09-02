"""E.V. Voice package (Phase 2) — hands-free audio pipeline.

Public API
----------
- :class:`VAD`            voice-activity detection (energy / webrtc)
- :class:`MicStream`      streaming 16 kHz mono s16le microphone capture
- :class:`VoskSTT`        offline Persian speech-to-text (Vosk)
- :class:`VoiceTTS`       text-to-speech (piper / edge / espeak)
- :class:`WakeWord`       continuous wake-word listener ("ای وی" / "e.v")
- :class:`VoiceLoop`      end-to-end hands-free loop (wake -> STT -> agent -> TTS)
- :func:`capture_utterance` record one utterance and transcribe it
- :func:`find_model`      locate the Vosk model under data/models
- :func:`has_speech`      one-shot energy check on raw s16le PCM

Everything is lazily heavy on purpose: importing this package does NOT load
Vosk, piper, or touch the microphone. Those are pulled in on first use.
"""
from __future__ import annotations

from voice.mic import (RATE, CHANNELS, WIDTH, MicStream, arecord_available,
                       record_wav)
from voice.vad import VAD, EnergyVAD, WebRTCVAD, has_speech
from voice.stt import VoskSTT, STTBackend, find_model
from voice.tts import VoiceTTS
from voice.wakeword import WakeWord
from voice.session import VoiceLoop, capture_utterance

__version__ = "2.0.0"

__all__ = [
    # constants
    "RATE", "CHANNELS", "WIDTH",
    # mic
    "MicStream", "arecord_available", "record_wav",
    # vad
    "VAD", "EnergyVAD", "WebRTCVAD", "has_speech",
    # stt
    "VoskSTT", "STTBackend", "find_model",
    # tts
    "VoiceTTS",
    # wake word
    "WakeWord",
    # session
    "VoiceLoop", "capture_utterance",
]

