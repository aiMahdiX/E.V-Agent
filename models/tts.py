"""Text-to-Speech - local-friendly Persian voice.

Backends:
    1. piper : piper-tts - fully offline neural Persian (fa_IR-amir-medium).
    2. edge  : edge-tts - online, natural Persian voices.
    3. espeak: fully offline fallback (lower quality).
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

DEFAULT_VOICE = "fa-IR-FaridNeural"


class TTSError(RuntimeError):
    pass


class EdgeTTS:
    def __init__(self, voice: str = DEFAULT_VOICE, rate: str = "+0%",
                 volume: str = "+0%"):
        self.voice = voice
        self.rate = rate
        self.volume = volume

    def synthesize(self, text, out_path):
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        if out.suffix.lower() != ".mp3":
            out = out.with_suffix(".mp3")
        try:
            import edge_tts
        except ImportError as e:
            raise TTSError("edge-tts not installed: " + str(e)) from e
        import anyio

        async def _run():
            com = edge_tts.Communicate(text, self.voice, rate=self.rate,
                                       volume=self.volume)
            with out.open("wb") as f:
                async for chunk in com.stream():
                    if chunk["type"] == "audio":
                        f.write(chunk["data"])
        anyio.run(_run)
        return out


class EspeakTTS:
    def __init__(self, lang: str = "fa"):
        self.lang = lang

    def synthesize(self, text, out_path):
        exe = shutil.which("espeak-ng") or shutil.which("espeak")
        if not exe:
            raise TTSError("no espeak/espeak-ng binary found")
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        if out.suffix.lower() != ".wav":
            out = out.with_suffix(".wav")
        subprocess.run([exe, "-v", self.lang, "-w", str(out), text],
                       check=True, capture_output=True)
        return out


class PiperTTS:
    DEFAULT_MODEL = "data/models/piper/fa_IR-amir-medium.onnx"

    def __init__(self, model_path: str | None = None):
        self.model_path = model_path or self.DEFAULT_MODEL
        if not Path(self.model_path).exists():
            raise TTSError(
                f"piper voice model not found: {self.model_path}. "
                "Download fa_IR-amir-medium.onnx from huggingface.co/rhasspy/piper-voices "
                "into data/models/piper/")
        self._voice = None

    def _load(self):
        if self._voice is None:
            try:
                from piper import PiperVoice
            except ImportError as e:
                raise TTSError("piper-tts not installed: " + str(e)) from e
            self._voice = PiperVoice.load(self.model_path)
        return self._voice

    def warm(self):
        """Preload the voice model so the first reply is instant."""
        if self._voice is None:
            self._load()

    def synthesize(self, text, out_path):
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        if out.suffix.lower() != ".wav":
            out = out.with_suffix(".wav")
        import wave

        voice = self._load()
        with wave.open(str(out), "wb") as wf:
            # set format and synthesize in one call
            voice.synthesize_wav(text, wf, set_wav_format=True)
        return out


class TTSModel:
    def __init__(self, backend: str = "piper", voice: str = DEFAULT_VOICE,
                 model_path: str | None = None):
        self.backend = backend
        if backend == "edge":
            self._impl = EdgeTTS(voice=voice)
        elif backend == "piper":
            self._impl = PiperTTS(model_path=model_path)
        else:
            self._impl = EspeakTTS()

    def synthesize(self, text, out_path=None):
        if out_path is None:
            out_path = str(Path(tempfile.gettempdir()) / "ev_tts")
        impl = getattr(self, "_impl", None)
        if impl is None:
            try:
                impl = PiperTTS()
                self._impl = impl
            except TTSError:
                impl = EspeakTTS()
                self._impl = impl
        try:
            return impl.synthesize(text, out_path)
        except TTSError:
            for cls in (PiperTTS, EspeakTTS):
                if impl.__class__ is cls:
                    continue
                try:
                    return cls().synthesize(text, out_path)
                except TTSError:
                    continue
            raise

    def warm(self):
        """Preload the underlying TTS backend for a faster first reply."""
        impl = getattr(self, "_impl", None)
        if impl is not None and hasattr(impl, "warm"):
            impl.warm()

    def speak(self, text, block=False):
        wav = self.synthesize(text)
        player = (shutil.which("aplay") or shutil.which("ffplay")
                  or shutil.which("mpv") or shutil.which("paplay"))
        if not player:
            raise RuntimeError("no audio player found (aplay/ffplay/mpv)")
        cmd = [player, "-q", str(wav)]
        if block:
            subprocess.run(cmd, check=True)
        else:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)


def test_tts(text="سلام، من در دسترس هستم"):
    tts = TTSModel(backend="piper")
    tts.speak(text, block=False)
    print(f"TTS play queued: {text!r}")
