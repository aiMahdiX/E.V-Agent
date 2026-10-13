"""Install MCP server repositories from GitHub without executing them."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlsplit


class MCPInstallError(RuntimeError):
    pass


def _github_repo(url: str) -> tuple[str, str, str]:
    try:
        parsed = urlsplit((url or "").strip())
        path = [unquote(part) for part in parsed.path.strip("/").split("/")]
        port = parsed.port
    except ValueError as exc:
        raise MCPInstallError("Invalid GitHub URL.") from exc
    if (parsed.scheme != "https"
            or parsed.hostname not in {"github.com", "www.github.com"}
            or parsed.username or parsed.password or port
            or parsed.query or parsed.fragment or len(path) != 2):
        raise MCPInstallError(
            "Use a GitHub URL in the form https://github.com/owner/repository.")
    owner, repository = path
    repository = repository.removesuffix(".git")
    if (not re.fullmatch(r"[A-Za-z0-9-]+", owner)
            or not re.fullmatch(r"[A-Za-z0-9._-]+", repository)
            or repository in {".", ".."}):
        raise MCPInstallError("The owner or repository name in the URL is invalid.")
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", repository).strip("-_").lower()
    if not slug:
        raise MCPInstallError("The repository name cannot be used as an install ID.")
    return owner, repository, slug


def _read_manifest(path: Path) -> dict:
    if path.is_symlink():
        raise MCPInstallError("server.json cannot be a symlink.")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MCPInstallError("Repository must contain a valid root-level server.json.") from exc
    if (not isinstance(manifest, dict)
            or not isinstance(manifest.get("name"), str)
            or not manifest["name"].strip()
            or not isinstance(manifest.get("command"), str)
            or not manifest["command"].strip()
            or ("enabled" in manifest
                and not isinstance(manifest["enabled"], bool))
            or not isinstance(manifest.get("args", []), list)
            or not all(isinstance(arg, str)
                       for arg in manifest.get("args", []))):
        raise MCPInstallError(
            "server.json must include string name and command fields, and an "
            "optional list of string args.")
    return manifest


def install_github_server(url: str, servers_dir: str | Path) -> dict:
    """Clone a GitHub MCP repo and stage its manifest in the disabled state."""
    owner, repository, slug = _github_repo(url)
    root = Path(servers_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    destination = root / slug
    if destination.exists():
        raise MCPInstallError(f"Install path already exists: {slug}")

    clone_url = f"https://github.com/{owner}/{repository}.git"
    try:
        result = subprocess.run(
            ["git", "clone", "--depth", "1", "--", clone_url,
             str(destination)], capture_output=True, text=True, timeout=180,
            check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        shutil.rmtree(destination, ignore_errors=True)
        raise MCPInstallError(f"Could not download repository: {exc}") from exc
    if result.returncode:
        shutil.rmtree(destination, ignore_errors=True)
        detail = (result.stderr or result.stdout or "git clone failed").strip()
        raise MCPInstallError(f"Could not download repository: {detail[-500:]}")

    try:
        manifest_path = destination / "server.json"
        manifest = _read_manifest(manifest_path)
        for existing in root.glob("*/server.json"):
            if existing == manifest_path:
                continue
            try:
                other = json.loads(existing.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(other, dict) and other.get("name") == manifest["name"]:
                raise MCPInstallError(
                    f"An MCP server with this name is already installed: {manifest['name']}")
        manifest["enabled"] = False
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise

    return {"id": slug, "name": manifest["name"],
            "command": manifest["command"], "enabled": False}


def list_installed_servers(servers_dir: str | Path) -> list[dict]:
    root = Path(servers_dir)
    if not root.is_dir():
        return []
    servers = []
    for manifest_path in sorted(root.glob("*/server.json")):
        try:
            manifest = _read_manifest(manifest_path)
        except MCPInstallError:
            continue
        servers.append({
            "id": manifest_path.parent.name,
            "name": manifest["name"],
            "command": manifest["command"],
            "enabled": bool(manifest.get("enabled", True)),
        })
    return servers


def set_server_enabled(servers_dir: str | Path, server_id: str,
                       enabled: bool) -> dict:
    root = Path(servers_dir).resolve()
    matches = [root / server["id"] / "server.json"
               for server in list_installed_servers(root)
               if server["id"] == server_id or server["name"] == server_id]
    if not matches:
        raise MCPInstallError(f"MCP server not found: {server_id}")
    if len(matches) > 1:
        raise MCPInstallError(f"Ambiguous name; use the directory ID: {server_id}")

    manifest_path = matches[0]
    manifest = _read_manifest(manifest_path)
    manifest["enabled"] = bool(enabled)
    temporary = manifest_path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    temporary.replace(manifest_path)
    return {"id": manifest_path.parent.name, "name": manifest["name"],
            "enabled": bool(enabled)}