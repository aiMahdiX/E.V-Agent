"""Speech-to-Text — local Vosk backend (offline, works on Python 3.14).

Model auto-detection order:
    1. ``data/models/vosk-model-small-fa-*`` (Persian small, ~40 MB)
    2. any ``vosk-model-*`` under data/models
    3. ``model_path`` override from config

Vosk supports *any* language model; set ``language``/``model_path`` in config
to switch (e.g. vosk-model-small-en-us for English).
"""
from __future__ import annotations

import json
import subprocess
import wave
from pathlib import Path

from voice import mic


def find_model(root: str | Path | None = None) -> str | None:
    root = Path(root) if root else Path("data/models")
    if not root.is_dir():
        return None
    # Persian small first
    for p in sorted(root.iterdir()):
        if p.is_dir() and p.name.startswith("vosk-model-small-fa"):
            return str(p)
    for p in sorted(root.iterdir()):
        if p.is_dir() and p.name.startswith("vosk-model"):
            return str(p)
    return None


class STTBackend:
    """Minimal backend interface."""

    def transcribe(self, audio_path: str) -> str:
        raise NotImplementedError


class VoskSTT(STTBackend):
    def __init__(self, model_path: str | None = None,
                 sample_rate: int = mic.RATE):
        if model_path is None:
            model_path = find_model()
        if model_path is None:
            raise RuntimeError(
                "No Vosk model found under data/models/. Run "
                "./setup_voice.sh to download the Persian model.")
        self.model_path = model_path
        self.sample_rate = sample_rate

    # ------------------------------------------------------------------ #
    def transcribe_bytes(self, data: bytes) -> str:
        """Transcribe raw s16le PCM as a single utterance."""
        return _transcribe_once(self.model_path, data, self.sample_rate)

    def transcribe(self, audio_path: str) -> str:
        """Transcribe a WAV file (16 kHz mono s16le)."""
        data = _read_wav(audio_path)
        if not data:
            return ""
        return self.transcribe_bytes(data)

    def transcribe_as(self, data: bytes) -> str:
        """Alias for transcribe_bytes — used by the voice session."""
        return self.transcribe_bytes(data)


def _read_wav(path: str) -> bytes:
    wav_path = Path(path)
    with wave.open(str(wav_path), "rb") as wf:
        if wf.getframerate() != mic.RATE or wf.getnchannels() != mic.CHANNELS \
                or wf.getsampwidth() != mic.WIDTH:
            # resample via ffmpeg if available
            wav_path2 = wav_path.with_suffix(".conv.wav")
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(wav_path),
                 "-ar", str(mic.RATE), "-ac", "1", "-acodec", "pcm_s16le",
                 str(wav_path2)],
                capture_output=True)
            wav_path = wav_path2
        return wf.readframes(wf.getnframes())


_vosk_model_cache = {}


def _load(model_path: str):
    if model_path not in _vosk_model_cache:
        from vosk import Model
        import vosk
        # Silence Vosk's C++ LOG messages on stderr so the CLI stays clean.
        try:
            vosk.SetLogLevel(-1)
        except Exception:
            pass
        _vosk_model_cache[model_path] = Model(model_path)
    return _vosk_model_cache[model_path]


def _transcribe_once(model_path: str, data: bytes, rate: int) -> str:
    import json
    from vosk import KaldiRecognizer
    model = _load(model_path)
    rec = KaldiRecognizer(model, rate)
    rec.AcceptWaveform(data)
    res = rec.FinalResult()
    try:
        return _persian_clean(json.loads(res).get("text", ""))
    except json.JSONDecodeError:
        return ""


def _persian_clean(text: str) -> str:
    """Normalize Persian/English transcript for matching & intent."""
    text = text.replace("\u200c", " ")       # ZWNJ -> space
    text = " ".join(text.split())
    return text.strip()
