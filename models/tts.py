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
import threading
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
        self._playback_lock = threading.Lock()
        self._playback: subprocess.Popen | None = None
        self._playback_path: Path | None = None

    def synthesize(self, text, out_path=None):
        if out_path is None:
            fd, out_path = tempfile.mkstemp(prefix="ev-tts-", suffix=".wav")
            import os
            os.close(fd)
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

    @staticmethod
    def _player_command(path: Path) -> list[str]:
        for binary, flags in (
                ("aplay", ["-q"]),
                ("ffplay", ["-nodisp", "-autoexit", "-loglevel", "error"]),
                ("mpv", ["--no-video", "--quiet"]),
                ("paplay", [])):
            executable = shutil.which(binary)
            if executable:
                return [executable, *flags, str(path)]
        raise RuntimeError("no audio player found (aplay, ffplay, mpv, paplay)")

    def speak(self, text, block=False):
        self.stop()
        audio_path = Path(self.synthesize(text))
        try:
            command = self._player_command(audio_path)
        except Exception:
            audio_path.unlink(missing_ok=True)
            raise
        if block:
            try:
                subprocess.run(command, check=True)
            finally:
                audio_path.unlink(missing_ok=True)
            return
        try:
            proc = subprocess.Popen(command, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL)
        except OSError:
            audio_path.unlink(missing_ok=True)
            raise
        with self._playback_lock:
            self._playback = proc
            self._playback_path = audio_path
        threading.Thread(target=self._reap_playback,
                         args=(proc, audio_path), daemon=True,
                         name="ev-tts-playback").start()

    def _reap_playback(self, proc: subprocess.Popen, audio_path: Path) -> None:
        try:
            proc.wait()
        finally:
            audio_path.unlink(missing_ok=True)
            with self._playback_lock:
                if self._playback is proc:
                    self._playback = None
                    self._playback_path = None

    def stop(self) -> None:
        with self._playback_lock:
            proc, path = self._playback, self._playback_path
            self._playback = None
            self._playback_path = None
        if proc is None or proc.poll() is not None:
            if path:
                path.unlink(missing_ok=True)
            return
        try:
            proc.terminate()
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)
        except OSError:
            pass
        if path:
            path.unlink(missing_ok=True)


def test_tts(text="سلام، من در دسترس هستم"):
    tts = TTSModel(backend="piper")
    tts.speak(text, block=False)
    print(f"TTS play queued: {text!r}")
