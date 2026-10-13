"""Offline smoke checks for voice hardware detection and recommendations."""
from __future__ import annotations

import io
import hashlib
import json
import tempfile
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from voice.hardware import detect_hardware, recommend_configuration
from voice.config import normalize_voice_config
from voice.installer import (InstallationCancelled, VoiceInstallManager,
                             VoiceInstallError)
from voice.secrets import SecretStoreError, VoiceSecretStore
from voice.router import (SpeechRouter, VoiceBackendError,
                          detect_text_language)
from voice.setup import run_setup_wizard
from voice.vad import EnergyVAD
from models.llm import select_provider_instances


def test_hardware_report() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        sysfs = root / "sys"
        proc = root / "proc"
        data = root / "data" / "models"
        (proc / "asound").mkdir(parents=True)
        (proc / "asound" / "cards").write_text(
            " 0 [PCH ]: HDA-Intel - Intel Audio\n", encoding="utf-8")
        (proc / "meminfo").write_text(
            "MemTotal:  16777216 kB\nMemAvailable: 8388608 kB\n",
            encoding="utf-8")
        (proc / "cpuinfo").write_text(
            "model name : Test CPU\n", encoding="utf-8")
        drm_device = sysfs / "class" / "drm" / "card0" / "device"
        drm_device.mkdir(parents=True)
        (drm_device / "vendor").write_text("0x10de", encoding="ascii")
        (drm_device / "device").write_text("0x25a2", encoding="ascii")
        model_dir = data / "vosk-model-small-fa-0.5"
        model_dir.mkdir(parents=True)
        (data / "piper").mkdir()
        (data / "piper" / "fa_IR-amir-medium.onnx").write_bytes(b"model")

        def fake_run(command, **_kwargs):
            if command[0] == "nvidia-smi":
                return SimpleNamespace(
                    returncode=0,
                    stdout="RTX 3050, 4096, 3800, 595.91\n")
            return SimpleNamespace(returncode=1, stdout="")

        report = detect_hardware(data, sysfs, proc, runner=fake_run)
        assert report["cpu"]["name"] == "Test CPU"
        assert report["memory"]["available_gib"] == 8.0
        assert report["nvidia"]["vram_total_mib"] == 4096
        assert report["gpus"][0]["vendor"] == "nvidia"
        assert report["audio"]["alsa_cards"] == [
            "0 [PCH ]: HDA-Intel - Intel Audio"]


def test_recommendation_is_conservative() -> None:
    report = {
        "nvidia": {"vram_total_mib": 4096, "vram_free_mib": 4096},
        "memory": {"available_gib": 7.5},
        "components": {
            "modules": {"vosk": True, "faster_whisper": False,
                        "piper": True},
            "vosk_models": ["vosk-model-small-fa-0.5"],
            "piper_models": ["data/models/piper/fa_IR-amir-medium.onnx"],
            "piper_voices": [{"path": "fa_IR-amir-medium.onnx",
                              "language": "fa", "license": None}],
        },
        "local_runtime": {"ollama_binary": True},
    }
    result = recommend_configuration(report, languages=("Persian", "English"))
    assert result["recommended_mode"] == "local"
    assert result["asr"]["state"] == "partial_language_coverage"
    assert result["asr"]["missing_languages"] == ["en"]
    assert result["tts"]["state"] == "missing_language_voice"
    assert result["tts"]["missing_languages"] == ["en"]
    assert result["asr_device"] == "cpu"
    assert result["live"]["requires_cloud_consent"] is True
    assert result["tool_execution"]["uses_existing_permissions"] is True
    assert result["llm"]["model"] == "qwen3:4b"
    assert result["llm"]["recommended_mode"] == "local"
    assert result["llm"]["cloud_policy"].startswith("only_after_provider_configuration")

    high_resource_report = {
        **report,
        "memory": {"available_gib": 14},
        "disk": {"free_gib": 10},
        "nvidia": {"vram_total_mib": 8192},
    }
    assert recommend_configuration(high_resource_report)["llm"]["model"] == "qwen3:8b"

    low_disk_report = {**report, "disk": {"free_gib": 0}}
    low_disk_recommendation = recommend_configuration(low_disk_report)["llm"]
    assert low_disk_recommendation["model"] is None
    assert low_disk_recommendation["state"] == "insufficient_disk"
    assert low_disk_recommendation["recommended_mode"] == "cloud_candidate"

    low_memory_report = {
        **report,
        "memory": {"available_gib": 1.5},
        "disk": {"free_gib": 10},
    }
    low_memory_recommendation = recommend_configuration(low_memory_report)["llm"]
    assert low_memory_recommendation["model"] is None
    assert low_memory_recommendation["recommended_mode"] == "cloud_candidate"


def test_energy_vad_returns_to_silence() -> None:
    vad = EnergyVAD(frame_ms=20, threshold=180, hangover_ms=100)
    speech = b"".join(int(value).to_bytes(2, "little", signed=True)
                     for value in ([5000, -5000] * 160))
    silence = bytes(640)
    assert vad.feed(speech)
    assert vad.feed(silence)
    assert vad.feed(silence)
    assert vad.feed(silence)
    assert vad.feed(silence)
    assert not vad.feed(silence)
    assert not vad.active
    vad.reset()
    assert not vad.active


def test_config_language_and_privacy() -> None:
    config = normalize_voice_config({
        "voice": {"stt_backend": "vosk", "tts_backend": "edge",
                  "stt_model": "data/models/vosk-model-small-fa-0.5",
                  "mode": "local"},
    })
    assert config["voice"]["stt_model"].endswith("vosk-model-small-fa-0.5")
    assert config["voice"]["tts_backend"] == "edge"
    assert config["live"]["enabled"] is False
    assert config["live"]["allow_audio_upload"] is False
    assert detect_text_language("درود") == "fa"
    assert detect_text_language("Hello E.V.") == "en"

    router = SpeechRouter(config["voice"])
    try:
        router.synthesize("Hello", language="en")
    except VoiceBackendError as exc:
        assert "Cloud TTS is disabled" in str(exc)
    else:
        raise AssertionError("local mode allowed a cloud TTS request")

    piper_config = {"mode": "local", "tts_backend": "piper",
                    "tts_voices": {"fa": "not-installed.onnx", "en": None}}
    try:
        SpeechRouter(piper_config).synthesize("Hello", language="en")
    except VoiceBackendError as exc:
        assert "No installed local Piper voice" in str(exc)
    else:
        raise AssertionError("missing English voice was accepted")

    providers = {
        "ollama": {"type": "ollama"},
        "gemini": {"type": "google-genai"},
        "ashna": {"type": "openai-compatible"},
    }
    local = select_provider_instances(providers, "local")
    assert list(local) == ["ollama"]
    assert len(select_provider_instances(providers, "hybrid")) == 3


def test_installer_confirmation_and_safe_extract() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        opened = []

        def forbidden_open(*_args, **_kwargs):
            opened.append(True)
            raise AssertionError("network must not open before confirmation")

        manager = VoiceInstallManager(root, opener=forbidden_open)
        try:
            manager.install_model("vosk_en_small",
                                  confirm=lambda *_: False)
        except InstallationCancelled:
            pass
        else:
            raise AssertionError("declined install was not cancelled")
        assert not opened
        assert not (root / "data" / "models" /
                    "vosk-model-small-en-us-0.15").exists()

        def archive_bytes(entries):
            content = io.BytesIO()
            with zipfile.ZipFile(content, "w") as archive:
                for name, data in entries:
                    archive.writestr(name, data)
            content.seek(0)
            content.status = 200
            return content

        valid = archive_bytes([
            ("vosk-model-small-en-us-0.15/am/final.mdl", b"tiny-test-model"),
            ("vosk-model-small-en-us-0.15/conf/model.conf", b"test"),
        ])
        archive_payload = valid.getvalue()
        manager = VoiceInstallManager(
            root, opener=lambda *_a, **_k: io.BytesIO(archive_payload))
        with patch("voice.installer._module_available", return_value=True):
            installed = manager.install_model(
                "vosk_en_small", confirm=lambda *_: True)
            repeated = manager.install_model(
                "vosk_en_small", confirm=lambda *_: False)
        assert installed["status"] == "installed"
        assert len(installed["archive_sha256"]) == 64
        assert repeated["status"] == "already_installed"
        manifest = json.loads((root / "data" / "voice" /
                               "installation.json").read_text())
        assert manifest["models"]["vosk_en_small"][
            "upstream_checksum_verified"] is False

        resumed_root = root / "resumed"
        resumed_manager = VoiceInstallManager(resumed_root)
        resumed_manager.models_dir.mkdir(parents=True)
        partial = (resumed_manager.models_dir /
                   ".vosk-model-small-en-us-0.15.zip.part")
        prefix = archive_payload[:32]
        partial.write_bytes(prefix)

        def range_open(request, **_kwargs):
            assert request.get_header("Range") == f"bytes={len(prefix)}-"
            response = io.BytesIO(archive_payload[len(prefix):])
            response.status = 206
            return response

        resumed_manager = VoiceInstallManager(resumed_root, opener=range_open)
        with patch("voice.installer._module_available", return_value=True):
            resumed = resumed_manager.install_model(
                "vosk_en_small", confirm=lambda *_: True)
        assert resumed["archive_sha256"] == hashlib.sha256(
            archive_payload).hexdigest()

        unsafe = archive_bytes([
            ("../outside", b"no"),
            ("vosk-model-small-en-us-0.15/am/final.mdl", b"tiny-test-model"),
        ])
        bad_root = root / "bad"
        bad_manager = VoiceInstallManager(
            bad_root, opener=lambda *_a, **_k: unsafe)
        with patch("voice.installer._module_available", return_value=True):
            try:
                bad_manager.install_model(
                    "vosk_en_small", confirm=lambda *_: True)
            except VoiceInstallError:
                pass
            else:
                raise AssertionError("unsafe archive path was accepted")
        assert not (bad_root / "data" / "outside").exists()


def test_secret_store_never_writes_plaintext() -> None:
    class FakeKeyring:
        values = {}

        def set_password(self, service, name, value):
            self.values[(service, name)] = value

        def get_password(self, service, name):
            return self.values.get((service, name))

        def delete_password(self, service, name):
            del self.values[(service, name)]

    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "voice-secrets.json"
        store = VoiceSecretStore(path)
        try:
            store.set("GEMINI_API_KEY", "never-write-this")
        except SecretStoreError:
            pass
        else:
            raise AssertionError("secret stored without a secure backend")
        assert not path.exists()
        backend = FakeKeyring()
        with patch.object(VoiceSecretStore, "_secure_keyring",
                          return_value=backend):
            store.set("GEMINI_API_KEY", "keyring-only")
            assert store.get("GEMINI_API_KEY") == "keyring-only"
            assert store.delete("GEMINI_API_KEY")
            assert store.get("GEMINI_API_KEY") is None
        assert not path.exists()


def test_local_wizard_needs_no_cloud_credentials() -> None:
    answers = iter(["en", "1", "fa", "any", "all", "n", "y", "y",
                    "n", "0", "free", "y"])
    config = normalize_voice_config({
        "agent": {"language": "auto"},
        "voice": {"mode": "local", "languages": ["fa"]},
    })
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        updates = {}
        result = run_setup_wizard(
            config, VoiceInstallManager(root),
            VoiceSecretStore(root / "secrets.json"),
            input_fn=lambda _prompt: next(answers),
            secret_input_fn=lambda _prompt: (_ for _ in ()).throw(
                AssertionError("local setup must not ask for credentials")),
            output_fn=lambda _line: None,
            update_config=updates.update)
        assert result["saved"] and result["mode"] == "local"
        assert updates["operating_mode"] == "local"
        assert updates["cloud.allow_text"] is False
        assert updates["live.enabled"] is False
        assert updates["live.allow_audio_upload"] is False


if __name__ == "__main__":
    test_hardware_report()
    test_recommendation_is_conservative()
    test_energy_vad_returns_to_silence()
    test_config_language_and_privacy()
    test_installer_confirmation_and_safe_extract()
    test_secret_store_never_writes_plaintext()
    test_local_wizard_needs_no_cloud_credentials()
    print("Adaptive voice hardware smoke checks passed")