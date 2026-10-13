"""Idempotent, opt-in installer for optional local voice components."""
from __future__ import annotations

import hashlib
import importlib.metadata
import importlib.util
import json
import os
import platform
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath


class VoiceInstallError(RuntimeError):
    pass


class InstallationCancelled(VoiceInstallError):
    pass


PACKAGE_CATALOG = {
    "faster_whisper": {
        "requirements": ["faster-whisper>=1.2.1,<2.0"],
        "modules": ["faster_whisper"],
        "minimum_free_bytes": 2 * 1024**3,
        "description": "Optional multilingual local speech recognition",
    },
    "gemini_live": {
        "requirements": ["google-genai>=2.29.0,<3.0",
                          "keyring>=25.7.0,<26.0", "cryptography>=44.0"],
        "modules": ["google.genai", "keyring", "cryptography"],
        "minimum_free_bytes": 512 * 1024**2,
        "description": "Gemini Live SDK and secure credential support",
    },
    "piper": {
        "requirements": ["piper-tts>=1.8.0,<2.0"],
        "modules": ["piper"],
        "minimum_free_bytes": 512 * 1024**2,
        "description": "Optional local neural text-to-speech runtime",
    },
}

MODEL_CATALOG = {
    "vosk_en_small": {
        "id": "vosk-model-small-en-us-0.15",
        "language": "en",
        "url": "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip",
        "license": "Apache-2.0",
        "expected_download_bytes": 40 * 1024**2,
        "minimum_free_bytes": 180 * 1024**2,
        "max_unpacked_bytes": 160 * 1024**2,
    },
}


def _module_available(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


class VoiceInstallManager:
    def __init__(self, project_root: str | Path,
                 runner=subprocess.Popen, opener=urllib.request.urlopen):
        self.project_root = Path(project_root).resolve()
        self.venv_python = Path(sys.executable).resolve()
        self.models_dir = self.project_root / "data" / "models"
        self.voice_dir = self.project_root / "data" / "voice"
        self.manifest_path = self.voice_dir / "installation.json"
        self._popen = runner
        self._open = opener
        self._lock = threading.RLock()

    def _manifest(self) -> dict:
        try:
            value = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {"schema": 1, "packages": {}, "models": {}}

    def _save_manifest(self, manifest: dict) -> None:
        self.voice_dir.mkdir(parents=True, exist_ok=True)
        temporary = self.manifest_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(manifest, indent=2) + "\n",
                             encoding="utf-8")
        os.chmod(temporary, 0o600)
        os.replace(temporary, self.manifest_path)

    def _check_environment(self) -> None:
        if sys.prefix == sys.base_prefix:
            raise VoiceInstallError(
                "Refusing to install packages outside a virtual environment. "
                "Run E.V. with its .venv interpreter.")
        if platform.machine().casefold() not in {
                "x86_64", "amd64", "aarch64", "arm64"}:
            raise VoiceInstallError(
                f"Unsupported package architecture: {platform.machine()}")
        if sys.version_info < (3, 9):
            raise VoiceInstallError("Optional voice packages require Python 3.9 or newer.")

    def inventory(self) -> dict:
        hardware = self._hardware()
        manifest = self._manifest()
        packages = {}
        for name, item in PACKAGE_CATALOG.items():
            versions = {}
            for requirement, module in zip(item["requirements"], item["modules"]):
                package_name = requirement.split("[", 1)[0].split(">", 1)[0]
                try:
                    version = importlib.metadata.version(package_name)
                except importlib.metadata.PackageNotFoundError:
                    version = None
                versions[module] = {"available": _module_available(module),
                                    "version": version}
            packages[name] = {
                "description": item["description"],
                "installed": all(value["available"]
                                  for value in versions.values()),
                "modules": versions,
                "manifest": manifest.get("packages", {}).get(name),
            }
        models = {}
        for name, item in MODEL_CATALOG.items():
            path = self.models_dir / item["id"]
            models[name] = {
                "id": item["id"], "language": item["language"],
                "installed": (path / "am" / "final.mdl").is_file(),
                "license": item["license"],
                "manifest": manifest.get("models", {}).get(name),
            }
        return {"python": sys.version.split()[0],
                "venv": sys.prefix != sys.base_prefix,
                "architecture": platform.machine(),
                "disk_free_bytes": hardware["disk"]["free_bytes"],
                "packages": packages, "models": models}

    def _hardware(self) -> dict:
        from voice.hardware import detect_hardware
        return detect_hardware(self.models_dir)

    @staticmethod
    def _confirm(confirm, component: str, details: dict) -> bool:
        if confirm is None or not bool(confirm(component, details)):
            raise InstallationCancelled(f"Installation cancelled: {component}")
        return True

    def install_package(self, component: str, *, confirm,
                        progress=None,
                        cancel_event: threading.Event | None = None) -> dict:
        if component not in PACKAGE_CATALOG:
            raise VoiceInstallError(f"Unknown optional voice component: {component}")
        self._check_environment()
        item = PACKAGE_CATALOG[component]
        inventory = self.inventory()
        state = inventory["packages"][component]
        if state["installed"]:
            return {"status": "already_installed", "component": component,
                    "modules": state["modules"]}
        required = item["minimum_free_bytes"]
        if inventory["disk_free_bytes"] < required:
            raise VoiceInstallError(
                f"Insufficient disk space for {component}: need "
                f"{required // 1024**2} MiB free.")
        self._confirm(confirm, component, {
            "description": item["description"],
            "requirements": item["requirements"],
            "estimated_bytes": required,
            "python": sys.version.split()[0],
        })
        if cancel_event and cancel_event.is_set():
            raise InstallationCancelled(f"Installation cancelled: {component}")

        command = [str(self.venv_python), "-m", "pip", "install",
                   *item["requirements"]]
        output: queue.Queue[str | None] = queue.Queue()
        try:
            process = self._popen(command, cwd=self.project_root,
                                  stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, text=True,
                                  bufsize=1)
        except OSError as exc:
            raise VoiceInstallError(f"Could not start pip: {exc}") from exc

        def read_output() -> None:
            assert process.stdout
            for line in process.stdout:
                output.put(line.rstrip())
            output.put(None)

        reader = threading.Thread(target=read_output, daemon=True,
                                  name="ev-voice-install-output")
        reader.start()
        eof = False
        try:
            while process.poll() is None or not eof:
                if cancel_event and cancel_event.is_set():
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=3)
                    raise InstallationCancelled(
                        f"Installation cancelled: {component}")
                try:
                    line = output.get(timeout=0.1)
                except queue.Empty:
                    continue
                if line is None:
                    eof = True
                elif progress:
                    progress(component, line)
            reader.join(timeout=2)
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)

        if process.returncode != 0:
            raise VoiceInstallError(
                f"pip failed installing {component} (exit {process.returncode}). "
                "Retry from /voice setup; application configuration was not changed.")
        state = self.inventory()["packages"][component]
        if not state["installed"]:
            raise VoiceInstallError(
                f"pip completed but {component} did not pass its import check.")
        manifest = self._manifest()
        manifest.setdefault("schema", 1)
        manifest.setdefault("packages", {})[component] = {
            "requirements": item["requirements"],
            "versions": {module: details["version"]
                         for module, details in state["modules"].items()},
            "installed_at": time.time(),
            "status": "verified",
        }
        self._save_manifest(manifest)
        return {"status": "installed", "component": component,
                "modules": state["modules"]}

    def install_model(self, component: str, *, confirm,
                      progress=None,
                      cancel_event: threading.Event | None = None) -> dict:
        if component not in MODEL_CATALOG:
            raise VoiceInstallError(f"Unknown voice model: {component}")
        item = MODEL_CATALOG[component]
        destination = self.models_dir / item["id"]
        if (destination / "am" / "final.mdl").is_file():
            return {"status": "already_installed", "path": str(destination)}
        self._confirm(confirm, component, {
            "id": item["id"], "language": item["language"],
            "license": item["license"], "source": item["url"],
            "estimated_download_bytes": item["expected_download_bytes"],
            "minimum_free_bytes": item["minimum_free_bytes"],
            "upstream_checksum": None,
        })
        if not _module_available("vosk"):
            raise VoiceInstallError(
                "Vosk runtime is not installed. Install the Vosk voice component first.")
        disk_path = self.models_dir
        while not disk_path.exists() and disk_path != disk_path.parent:
            disk_path = disk_path.parent
        free = shutil.disk_usage(disk_path).free
        if free < item["minimum_free_bytes"]:
            raise VoiceInstallError(
                f"Insufficient disk space for {item['id']}: need at least "
                f"{item['minimum_free_bytes'] // 1024**2} MiB free.")
        self.models_dir.mkdir(parents=True, exist_ok=True)
        partial = self.models_dir / f".{item['id']}.zip.part"
        digest = hashlib.sha256()
        downloaded = partial.stat().st_size if partial.exists() else 0
        if downloaded:
            with partial.open("rb") as existing:
                for previous_chunk in iter(
                        lambda: existing.read(1024 * 1024), b""):
                    digest.update(previous_chunk)
        headers = {"User-Agent": "E.V-Voice-Installer/1"}
        if downloaded:
            headers["Range"] = f"bytes={downloaded}-"
        request = urllib.request.Request(item["url"], headers=headers)
        try:
            with self._open(request, timeout=30) as response:
                status = getattr(response, "status", 200)
                append = downloaded > 0 and status == 206
                if not append:
                    downloaded = 0
                    partial.unlink(missing_ok=True)
                mode = "ab" if append else "wb"
                with partial.open(mode) as output:
                    while True:
                        if cancel_event and cancel_event.is_set():
                            raise InstallationCancelled(
                                f"Download paused and can be resumed: {component}")
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        output.write(chunk)
                        digest.update(chunk)
                        downloaded += len(chunk)
                        if progress:
                            progress(component, downloaded,
                                     item["expected_download_bytes"])
        except InstallationCancelled:
            raise
        except (OSError, urllib.error.URLError, TimeoutError) as exc:
            raise VoiceInstallError(
                f"Model download failed; partial data is retained for retry: {exc}") from exc

        try:
            with zipfile.ZipFile(partial) as archive:
                bad_member = archive.testzip()
                if bad_member:
                    raise VoiceInstallError(
                        f"Downloaded archive is corrupt at {bad_member}")
                files = archive.infolist()
                expanded_size = sum(entry.file_size for entry in files)
                if expanded_size > item["max_unpacked_bytes"]:
                    raise VoiceInstallError("Archive exceeds its extraction size limit.")
                staging = Path(tempfile.mkdtemp(prefix=".ev-voice-",
                                                dir=self.models_dir))
                try:
                    for entry in files:
                        if cancel_event and cancel_event.is_set():
                            raise InstallationCancelled(
                                f"Extraction cancelled: {component}")
                        relative = PurePosixPath(entry.filename)
                        if relative.is_absolute() or ".." in relative.parts:
                            raise VoiceInstallError(
                                "Archive contains an unsafe path; extraction blocked.")
                        target = (staging / Path(*relative.parts)).resolve()
                        if not target.is_relative_to(staging.resolve()):
                            raise VoiceInstallError(
                                "Archive path escapes its staging directory.")
                        if entry.is_dir():
                            target.mkdir(parents=True, exist_ok=True)
                            continue
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with archive.open(entry) as source, target.open("wb") as sink:
                            shutil.copyfileobj(source, sink, length=1024 * 1024)
                    source_dir = staging / item["id"]
                    if not (source_dir / "am" / "final.mdl").is_file():
                        raise VoiceInstallError(
                            "Archive does not contain a valid Vosk acoustic model.")
                    if destination.exists():
                        raise VoiceInstallError(
                            f"Install destination already exists: {destination}")
                    os.replace(source_dir, destination)
                finally:
                    shutil.rmtree(staging, ignore_errors=True)
        except (zipfile.BadZipFile, OSError) as exc:
            raise VoiceInstallError(f"Could not verify/extract model archive: {exc}") from exc
        finally:
            partial.unlink(missing_ok=True)

        manifest = self._manifest()
        manifest.setdefault("schema", 1)
        manifest.setdefault("models", {})[component] = {
            "id": item["id"], "language": item["language"],
            "source": item["url"], "license": item["license"],
            "archive_sha256": digest.hexdigest(),
            "upstream_checksum_verified": False,
            "integrity": "zip CRC checked; SHA-256 recorded locally; upstream checksum unavailable",
            "downloaded_bytes": downloaded,
            "installed_at": time.time(), "status": "verified",
        }
        self._save_manifest(manifest)
        return {"status": "installed", "path": str(destination),
                "archive_sha256": digest.hexdigest(),
                "upstream_checksum_verified": False}

    def remove_model(self, component: str, *, confirm) -> dict:
        item = MODEL_CATALOG.get(component)
        if not item:
            raise VoiceInstallError("Only manager-installed optional models can be removed.")
        manifest = self._manifest()
        if component not in manifest.get("models", {}):
            raise VoiceInstallError(
                "Model is not recorded as installed by the voice manager; it was left untouched.")
        path = self.models_dir / item["id"]
        if not path.is_dir():
            raise VoiceInstallError("Recorded model directory is missing.")
        self._confirm(confirm, f"remove:{component}", {
            "path": str(path), "language": item["language"]})
        shutil.rmtree(path)
        del manifest["models"][component]
        self._save_manifest(manifest)
        return {"status": "removed", "component": component}