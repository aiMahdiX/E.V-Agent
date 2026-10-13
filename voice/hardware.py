"""Read-only host capability detection and conservative voice recommendations."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


_GPU_VENDORS = {
    "0x10de": "nvidia",
    "0x1002": "amd",
    "0x8086": "intel",
}
_LANGUAGE_ALIASES = {
    "fa": "fa", "farsi": "fa", "persian": "fa", "فارسی": "fa",
    "en": "en", "english": "en", "انگلیسی": "en",
}


def _run(command: list[str], runner=subprocess.run) -> str:
    try:
        result = runner(command, capture_output=True, text=True,
                        timeout=4, check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def _memory(proc_root: Path) -> dict:
    total = available = 0
    try:
        for line in (proc_root / "meminfo").read_text().splitlines():
            key, _, rest = line.partition(":")
            if key in {"MemTotal", "MemAvailable"}:
                value = int(rest.split()[0]) * 1024
                if key == "MemTotal":
                    total = value
                else:
                    available = value
    except (OSError, ValueError, IndexError):
        try:
            page_size = os.sysconf("SC_PAGE_SIZE")
            total = os.sysconf("SC_PHYS_PAGES") * page_size
            available = os.sysconf("SC_AVPHYS_PAGES") * page_size
        except (ValueError, OSError, AttributeError):
            pass
    return {"total_bytes": total, "available_bytes": available,
            "total_gib": round(total / 2**30, 2),
            "available_gib": round(available / 2**30, 2)}


def _cpu_name(proc_root: Path) -> str:
    try:
        for line in (proc_root / "cpuinfo").read_text().splitlines():
            key, _, value = line.partition(":")
            if key.strip().casefold() in {"model name", "hardware"}:
                return value.strip()
    except OSError:
        pass
    return platform.processor() or "Unknown CPU"


def _drm_devices(sysfs_root: Path) -> list[dict]:
    devices = []
    drm = sysfs_root / "class" / "drm"
    if not drm.is_dir():
        return devices
    for card in sorted(drm.glob("card[0-9]*")):
        device_path = card / "device"
        vendor_path = device_path / "vendor"
        if not vendor_path.is_file():
            continue
        try:
            vendor_id = vendor_path.read_text().strip().lower()
            product_id = (device_path / "device").read_text().strip().lower()
        except OSError:
            continue
        driver_link = device_path / "driver"
        try:
            driver = driver_link.resolve().name
        except OSError:
            driver = None
        devices.append({
            "id": card.name,
            "vendor": _GPU_VENDORS.get(vendor_id, "unknown"),
            "vendor_id": vendor_id,
            "device_id": product_id,
            "driver": driver,
        })
    return devices


def _nvidia_details(runner=subprocess.run) -> dict | None:
    output = _run([
        "nvidia-smi", "--query-gpu=name,memory.total,memory.free,driver_version",
        "--format=csv,noheader,nounits",
    ], runner=runner)
    if not output:
        return None
    name, total, free, driver = (output.splitlines()[0].split(",", 3)
                                 + ["", "", "", ""])[:4]
    try:
        total_mib, free_mib = int(total.strip()), int(free.strip())
    except ValueError:
        return None
    return {"vendor": "nvidia", "name": name.strip(),
            "vram_total_mib": total_mib, "vram_free_mib": free_mib,
            "driver": driver.strip()}


def _alsa_cards(proc_root: Path) -> list[str]:
    try:
        lines = (proc_root / "asound" / "cards").read_text().splitlines()
    except OSError:
        return []
    return [line.strip() for line in lines if line[:1].isspace()]


def _audio_report(proc_root: Path, runner=subprocess.run) -> dict:
    arecord = shutil.which("arecord")
    aplay = shutil.which("aplay")
    pactl = shutil.which("pactl")
    pulse = None
    if pactl:
        source = _run([pactl, "get-default-source"], runner=runner)
        sink = _run([pactl, "get-default-sink"], runner=runner)
        if source or sink:
            pulse = {"default_source": source or None,
                     "default_sink": sink or None}

    portaudio = {"available": False, "error": None, "devices": []}
    try:
        import sounddevice
        portaudio["devices"] = [
            {"name": device["name"],
             "inputs": int(device["max_input_channels"]),
             "outputs": int(device["max_output_channels"]),
             "default_rate": float(device["default_samplerate"])}
            for device in sounddevice.query_devices()
        ]
        portaudio["available"] = True
    except (ImportError, OSError, RuntimeError) as exc:
        portaudio["error"] = f"{type(exc).__name__}: {exc}"

    return {
        "capture_available": bool(arecord),
        "playback_available": bool(aplay),
        "capture_backend": "arecord" if arecord else None,
        "playback_backend": "aplay" if aplay else None,
        "alsa_cards": _alsa_cards(proc_root),
        "pulse": pulse,
        "portaudio": portaudio,
        "device_permissions": os.access("/dev/snd", os.R_OK | os.W_OK),
    }


def _component_report(data_root: Path) -> dict:
    modules = {}
    for name in ("vosk", "piper", "faster_whisper", "webrtcvad",
                 "google.genai", "keyring", "cryptography", "sounddevice"):
        try:
            modules[name] = importlib.util.find_spec(name) is not None
        except (ImportError, ModuleNotFoundError, ValueError):
            modules[name] = False
    vosk_models = sorted(path.name for path in data_root.glob("vosk-model*")
                         if path.is_dir())
    piper_models = sorted(str(path) for path in data_root.glob("piper/*.onnx")
                          if path.is_file())
    piper_voices = []
    for model_path in sorted((data_root / "piper").glob("*.onnx")):
        metadata_path = model_path.with_suffix(model_path.suffix + ".json")
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            metadata = {}
        language = metadata.get("language", {})
        piper_voices.append({
            "path": str(model_path),
            "language": str(language.get("code", "")).split("_")[0] or None,
            "name": language.get("name_english"),
            "license": metadata.get("license"),
        })
    return {"modules": modules, "vosk_models": vosk_models,
            "piper_models": piper_models, "piper_voices": piper_voices}


def detect_hardware(data_root: str | Path = "data/models",
                    sysfs_root: str | Path = "/sys",
                    proc_root: str | Path = "/proc",
                    runner=subprocess.run) -> dict:
    """Detect local capabilities only; never sends host data over the network."""
    data_root, sysfs_root, proc_root = map(Path,
                                           (data_root, sysfs_root, proc_root))
    try:
        disk_free = shutil.disk_usage(data_root if data_root.exists()
                                      else data_root.parent).free
    except OSError:
        disk_free = 0
    drm = _drm_devices(sysfs_root)
    nvidia = _nvidia_details(runner)
    gpus = list(drm)
    if nvidia:
        for gpu in gpus:
            if gpu["vendor"] == "nvidia":
                gpu.update(nvidia)
                break
        else:
            gpus.append(nvidia)
    audio = _audio_report(proc_root, runner)
    return {
        "platform": {"system": platform.system(),
                     "release": platform.release(),
                     "architecture": platform.machine(),
                     "python": platform.python_version()},
        "cpu": {"name": _cpu_name(proc_root),
                "logical_cores": os.cpu_count() or 1},
        "memory": _memory(proc_root),
        "disk": {"free_bytes": disk_free,
                 "free_gib": round(disk_free / 2**30, 2)},
        "gpus": gpus,
        "nvidia": nvidia,
        "audio": audio,
        "components": _component_report(data_root),
        "local_runtime": {"ollama_binary": shutil.which("ollama") is not None,
                          "ffmpeg_binary": shutil.which("ffmpeg") is not None},
    }


def _language_codes(languages) -> set[str]:
    out = set()
    for language in languages or ():
        code = _LANGUAGE_ALIASES.get(str(language).strip().casefold())
        if code:
            out.add(code)
    return out


def recommend_configuration(report: dict, languages=("fa", "en"),
                            purpose: str = "assistant",
                            budget: str = "minimum_cost") -> dict:
    """Recommend installed local components first; cloud remains opt-in."""
    wanted = _language_codes(languages)
    components = report.get("components", {})
    modules = components.get("modules", {})
    vosk_models = components.get("vosk_models", [])
    matching_vosk = []
    for model in vosk_models:
        normalized = model.casefold()
        if "-fa-" in normalized and "fa" in wanted:
            matching_vosk.append(model)
        if ("-en-" in normalized or "-en_" in normalized) and "en" in wanted:
            matching_vosk.append(model)

    nvidia = report.get("nvidia") or {}
    vram_mib = int(nvidia.get("vram_total_mib") or 0)
    memory_gib = float(report.get("memory", {}).get("available_gib") or 0)
    # Preserve VRAM for the main agent on small GPUs; do not infer that CUDA
    # is usable merely from an NVIDIA device being present.
    asr_device = "cpu" if vram_mib < 6144 or memory_gib < 4 else "auto"
    whisper_ready = modules.get("faster_whisper", False)
    vosk_languages = {
        "fa" if "-fa-" in model.casefold() else "en"
        for model in matching_vosk
    }
    if len(wanted) > 1 and whisper_ready:
        asr = {"provider": "faster_whisper", "state": "runtime_available",
               "language": "auto", "device": asr_device,
               "reason": "Multilingual transcription can detect language per utterance."}
    elif modules.get("vosk", False) and matching_vosk \
            and wanted.issubset(vosk_languages):
        asr = {"provider": "vosk", "state": "ready",
               "language": sorted(vosk_languages),
               "models": matching_vosk, "device": "cpu",
               "reason": "Installed Vosk models cover the selected languages; choose a language explicitly per session."}
    elif modules.get("vosk", False) and matching_vosk:
        asr = {"provider": "vosk", "state": "partial_language_coverage",
               "language": sorted(vosk_languages), "models": matching_vosk,
               "missing_languages": sorted(wanted - vosk_languages),
               "device": "cpu",
               "reason": "Vosk needs a separate installed model for each selected language; it does not auto-detect between models."}
    else:
        asr = {"provider": "vosk", "state": "needs_model_or_runtime",
               "language": sorted(wanted), "device": "cpu",
               "reason": "No installed recognizer/model covers all requested languages."}

    piper_ready = modules.get("piper", False)
    piper_models = components.get("piper_models", [])
    piper_voices = components.get("piper_voices", [])
    voice_languages = {voice["language"] for voice in piper_voices
                       if voice.get("language")}
    missing_voices = sorted(wanted - voice_languages)
    license_verified = bool(piper_voices) and all(
        voice.get("license") for voice in piper_voices)
    if not piper_ready or not piper_models:
        tts_state = "runtime_or_voice_missing"
    elif missing_voices:
        tts_state = "missing_language_voice"
    elif not license_verified:
        tts_state = "installed_license_unverified"
    else:
        tts_state = "ready"
    tts = {"provider": "piper" if piper_ready and piper_models else "unavailable",
           "state": tts_state, "installed_models": piper_models,
           "installed_voices": piper_voices,
           "missing_languages": missing_voices,
           "reason": "Only recommend voices whose model files and licenses are verified."}
    live = {"provider": "gemini_live", "model": "gemini-3.8-live",
            "state": "disabled_until_explicit_setup",
            "native_speech_to_speech": True,
            "requires_cloud_consent": True,
            "reason": "Official docs describe bidirectional audio Live API; no key or outbound call is made by default."}
    disk_report = report.get("disk", {})
    disk_gib = (float(disk_report["free_gib"])
                if "free_gib" in disk_report else None)
    if memory_gib >= 12 and vram_mib >= 8192:
        model, model_disk_gib = "qwen3:8b", 6
        model_reason = "Available memory and dedicated VRAM support the larger local model."
    elif memory_gib >= 6 or vram_mib >= 6144:
        model, model_disk_gib = "qwen3:4b", 4
        model_reason = "A small local model balances capability and resource use."
    else:
        model, model_disk_gib = "gemma3:1b-it-q4_K_M", 2
        model_reason = "Limited available memory favors the smallest configured local model."
    if memory_gib < 2:
        model = None
        model_reason = "Less than 2 GiB of available RAM; local inference is not recommended."
    if disk_gib is not None and disk_gib < model_disk_gib:
        model = None
        model_reason = (f"Only {disk_gib:.1f} GiB is free; at least "
                        f"{model_disk_gib} GiB is reserved for the suggested model.")
    return {
        "recommended_mode": "local",
        "requested_languages": sorted(wanted),
        "purpose": purpose,
        "budget": budget,
        "asr": asr,
        "tts": tts,
        "live": live,
        "vad": {"provider": "energy", "state": "ready",
                "reason": "Built-in dependency-free VAD is available."},
        "reasoning": {"provider": "ollama",
                      "state": "available" if report.get("local_runtime", {}).get("ollama_binary")
                      else "binary_missing",
                      "network": "local_only_by_default"},
        "llm": {"recommended_mode": "local" if model else "cloud_candidate",
            "provider": "ollama" if model else None,
            "model": model, "state": "ready_to_install" if model else "insufficient_disk",
            "reason": model_reason,
            "cloud_policy": "only_after_provider_configuration_and_explicit_consent"},
        "vision": {"optional": True,
                    "camera_available": any(Path("/dev").glob("video*"))},
        "tool_execution": {"provider": "existing_agent",
                            "uses_existing_permissions": True},
        "asr_device": asr_device,
        "notes": [
            "Cloud audio is never selected without explicit user consent.",
            "Model installation requires a separate disk-space check and confirmation.",
            "NVIDIA/AMD acceleration requires runtime-specific CUDA/ROCm checks; GPU presence alone is insufficient.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="E.V. hardware-based setup recommendation")
    parser.add_argument("--model", action="store_true",
                        help="print only the recommended Ollama model")
    args = parser.parse_args()
    report = detect_hardware()
    recommendation = recommend_configuration(report)
    if args.model:
        print(recommendation["llm"]["model"] or "")
        return 0
    print("Detected system:")
    print(f"  CPU: {report['cpu']['name']} ({report['cpu']['logical_cores']} threads)")
    print(f"  Available RAM: {report['memory']['available_gib']:.1f} GiB")
    print(f"  Free disk: {report['disk']['free_gib']:.1f} GiB")
    gpu = report.get("nvidia")
    print(f"  NVIDIA GPU: {gpu['name']} ({gpu['vram_total_mib']} MiB)" if gpu
          else "  NVIDIA GPU: not detected")
    llm = recommendation["llm"]
    mode = (f"local Ollama ({llm['model']})" if llm["model"] else
            "cloud candidate (not enabled; provider and consent required)")
    print(f"Recommended mode: {mode}")
    print(f"Reason: {llm['reason']}")
    print("Cloud inference stays off unless a provider is configured and you explicitly consent.")
    print("Tools: built-in tools use the existing permission system; review optional MCP servers before enabling.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())