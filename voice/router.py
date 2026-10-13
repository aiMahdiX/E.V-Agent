"""Local-first language-aware speech backend routing."""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

from voice.interfaces import AudioChunk, Transcription


class VoiceBackendError(RuntimeError):
    pass


_LANGUAGE_ALIASES = {
    "fa": "fa", "fa-ir": "fa", "farsi": "fa", "persian": "fa",
    "en": "en", "en-us": "en", "english": "en",
}


def normalize_language(language: str | None) -> str | None:
    if language is None:
        return None
    normalized = _LANGUAGE_ALIASES.get(language.strip().casefold())
    if normalized is None:
        raise VoiceBackendError(
            f"Unsupported voice language {language!r}; supported codes: fa, en")
    return normalized


def detect_text_language(text: str, fallback: str | None = None) -> str | None:
    """Detect Persian script or English Latin text without translating content."""
    persian = len(re.findall(r"[\u0600-\u06ff\u0750-\u077f]", text or ""))
    latin = len(re.findall(r"[A-Za-z]", text or ""))
    if persian and persian >= latin:
        return "fa"
    if latin:
        return "en"
    return normalize_language(fallback) if fallback else None


def _vosk_model_language(path: Path) -> str | None:
    name = path.name.casefold()
    if "-fa-" in name or "_fa_" in name:
        return "fa"
    if "-en-" in name or "_en_" in name:
        return "en"
    return None


class SpeechRouter:
    """Routes PCM input to configured local ASR/TTS backends.

    Cloud TTS is refused unless the configuration explicitly allows audio
    upload. ASR model names are never downloaded implicitly.
    """

    def __init__(self, voice_config: dict, data_root: str | Path = "data/models"):
        self.config = voice_config
        self.data_root = Path(data_root).resolve()
        self._whisper_models: dict[tuple[str, str, str], object] = {}
        self._tts_models: dict[tuple[str, str], object] = {}
        self.last_transcription: Transcription | None = None

    def _resolve_path(self, value: str | Path) -> Path:
        path = Path(value)
        if path.is_absolute():
            return path
        project_path = self.data_root.parent.parent / path
        if project_path.exists() or path.parts[:1] == ("data",):
            return project_path
        return self.data_root / path

    def available_vosk_models(self) -> dict[str, str]:
        result = {}
        configured = self.config.get("stt_model")
        if configured:
            path = self._resolve_path(configured)
            language = _vosk_model_language(path)
            if path.is_dir() and language:
                result.setdefault(language, str(path))
        for path in sorted(self.data_root.glob("vosk-model*")):
            language = _vosk_model_language(path)
            if path.is_dir() and language:
                result.setdefault(language, str(path))
        return result

    def _language_for_asr(self, language: str | None) -> str:
        requested = normalize_language(language)
        if requested:
            return requested
        configured = self.config.get("language", "fa")
        if configured != "auto":
            return normalize_language(configured) or "fa"
        selected = [normalize_language(item)
                    for item in self.config.get("languages", [])]
        selected = [item for item in selected if item]
        if len(set(selected)) == 1:
            return selected[0]
        return "auto"

    def transcribe(self, audio: AudioChunk,
                   language: str | None = None) -> Transcription:
        if audio.sample_format != "s16le" or audio.channels != 1:
            raise VoiceBackendError("ASR requires mono signed 16-bit PCM audio")
        if audio.sample_rate != 16000:
            raise VoiceBackendError("ASR input must be sampled at 16000 Hz")

        selected = self._language_for_asr(language)
        provider = str(self.config.get("asr_provider") or
                       self.config.get("stt_backend", "vosk")).casefold()
        if provider in {"auto", "vosk"}:
            models = self.available_vosk_models()
            if selected == "auto":
                if len(models) != 1:
                    if provider == "auto" and self._whisper_is_ready():
                        return self._transcribe_whisper(audio, None)
                    raise VoiceBackendError(
                        "Automatic language detection needs a local multilingual "
                        "Whisper model. Choose fa or en in Voice settings, or "
                        "install a Whisper model explicitly.")
                selected = next(iter(models))
            path = models.get(selected)
            if path:
                return self._transcribe_vosk(audio, selected, path)
            if provider == "auto" and self._whisper_is_ready():
                return self._transcribe_whisper(audio, selected)
            raise VoiceBackendError(
                f"No installed Vosk model covers {selected}. Install a matching "
                "model from Voice setup or select an installed language.")
        if provider in {"faster-whisper", "whisper"}:
            return self._transcribe_whisper(
                audio, None if selected == "auto" else selected)
        raise VoiceBackendError(f"Unknown ASR provider: {provider}")

    def transcribe_bytes(self, data: bytes, sample_rate: int = 16000,
                         language: str | None = None) -> str:
        """Compatibility method for the existing wake/utterance pipeline."""
        result = self.transcribe(
            AudioChunk(data=data, sample_rate=sample_rate), language=language)
        self.last_transcription = result
        return result.text

    @staticmethod
    def _transcribe_vosk(audio: AudioChunk, language: str,
                         model_path: str) -> Transcription:
        try:
            from voice.stt import VoskSTT
            text = VoskSTT(model_path=model_path,
                           sample_rate=audio.sample_rate).transcribe_bytes(
                               audio.data)
        except (ImportError, RuntimeError, OSError) as exc:
            raise VoiceBackendError(f"Vosk is unavailable: {exc}") from exc
        return Transcription(text=text, language=language, provider="vosk")

    def _whisper_is_ready(self) -> bool:
        model_path = self.config.get("faster_whisper_model_path")
        return (importlib.util.find_spec("faster_whisper") is not None
                and bool(model_path) and Path(model_path).is_dir())

    def _transcribe_whisper(self, audio: AudioChunk,
                            language: str | None) -> Transcription:
        model_path = self.config.get("faster_whisper_model_path")
        if not model_path or not self._resolve_path(model_path).is_dir():
            raise VoiceBackendError(
                "Faster-Whisper needs a model installed locally. Use "
                "`/voice setup` to review installation options; models are "
                "never downloaded automatically.")
        try:
            import numpy as np
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise VoiceBackendError(
                "Faster-Whisper is not installed. Use `/voice setup` to add it.") from exc

        device = str(self.config.get("asr_device", "auto")).casefold()
        if device == "auto":
            device = "cpu"
        compute_type = "int8" if device == "cpu" else "int8_float16"
        model_path = self._resolve_path(model_path)
        key = (str(model_path), device, compute_type)
        model = self._whisper_models.get(key)
        if model is None:
            try:
                model = WhisperModel(str(model_path), device=device,
                                     compute_type=compute_type)
            except Exception as exc:
                raise VoiceBackendError(
                    f"Could not load the local Whisper model: {exc}") from exc
            self._whisper_models[key] = model
        samples = np.frombuffer(audio.data, dtype="<i2").astype(np.float32)
        samples /= 32768.0
        segments, info = model.transcribe(
            samples, language=language, vad_filter=True,
            condition_on_previous_text=False)
        text = " ".join(segment.text.strip() for segment in segments).strip()
        detected = normalize_language(getattr(info, "language", None))
        probability = getattr(info, "language_probability", None)
        return Transcription(text=text, language=detected,
                             language_probability=probability,
                             provider="faster-whisper")

    def _tts_model(self, text: str, language: str | None = None):
        selected = normalize_language(language) or detect_text_language(
            text, fallback=self.config.get("language", "fa"))
        selected = selected or "fa"
        provider = str(self.config.get("tts_provider") or
                       self.config.get("tts_backend", "piper")).casefold()
        mode = str(self.config.get("mode", "local")).casefold()
        if provider in {"edge", "edge-tts", "cloud"} and not (
                mode in {"cloud", "hybrid"}
                and self.config.get("allow_cloud_audio") is True):
            raise VoiceBackendError(
                "Cloud TTS is disabled. Explicitly allow audio upload in Voice settings first.")

        if provider in {"piper", "auto"}:
            voice_map = self.config.get("tts_voices", {})
            model_path = voice_map.get(selected)
            if selected == "fa" and not model_path:
                model_path = self.config.get("tts_piper_model")
            if not model_path or not self._resolve_path(model_path).is_file():
                raise VoiceBackendError(
                    f"No installed local Piper voice for {selected}. Install a "
                    "verified voice or explicitly configure an online provider.")
            cache_key = ("piper", str(model_path))
            model = self._tts_models.get(cache_key)
            if model is None:
                from models.tts import TTSModel
                model = TTSModel(
                    backend="piper", model_path=str(self._resolve_path(model_path)))
                self._tts_models[cache_key] = model
        elif provider in {"edge", "edge-tts", "cloud"}:
            from models.tts import TTSModel
            voices = self.config.get("edge_tts_voices", {})
            voice = voices.get(selected)
            if not voice:
                raise VoiceBackendError(
                    f"No explicitly configured Edge TTS voice for {selected}.")
            cache_key = ("edge", voice)
            model = self._tts_models.get(cache_key)
            if model is None:
                model = TTSModel(backend="edge", voice=voice)
                self._tts_models[cache_key] = model
        else:
            raise VoiceBackendError(f"Unknown TTS provider: {provider}")
        return model

    def synthesize(self, text: str, language: str | None = None,
                   out_path: str | Path | None = None) -> Path:
        model = self._tts_model(text, language)
        output = str(out_path) if out_path else None
        try:
            result = model.synthesize(text, output)
        except Exception as exc:  # noqa: BLE001 - voice errors must not crash E.V.
            backend = self.config.get("tts_provider") or self.config.get(
                "tts_backend", "piper")
            raise VoiceBackendError(
                f"{backend} synthesis failed: {exc}") from exc
        return Path(result)

    def speak(self, text: str, language: str | None = None,
              block: bool = False) -> None:
        self._tts_model(text, language).speak(text, block=block)

    def stop(self) -> None:
        for model in tuple(self._tts_models.values()):
            stop = getattr(model, "stop", None)
            if callable(stop):
                stop()

    def warm(self) -> None:
        language = self.config.get("language", "fa")
        if language == "auto":
            languages = self.config.get("languages", [])
            language = languages[0] if languages else "fa"
        try:
            self._tts_model("", language).warm()
        except VoiceBackendError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise VoiceBackendError(f"Could not warm the selected voice: {exc}") from exc