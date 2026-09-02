"""Discovery — scan a servers directory for MCP server.json manifests.

Each MCP server lives in mcp_servers/<name>/server.json:

    {
      "name": "echo_demo",
      "enabled": true,
      "command": "python3",
      "args": ["server.py"],
      "cwd": "mcp_servers/echo_demo"
    }
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from tools.mcp.client import MCPClient, MCPError


def discover_servers(servers_dir: str | Path,
                     enabled_only: bool = True) -> list[dict]:
    root = Path(servers_dir)
    if not root.is_dir():
        return []
    manifests = []
    for entry in sorted(os.listdir(root)):
        manifest = root / entry / "server.json"
        if not manifest.is_file():
            continue
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(data, dict) or "name" not in data:
            continue
        if enabled_only and not data.get("enabled", True):
            continue
        data["cwd"] = str(root / entry)
        manifests.append(data)
    return manifests


def connect(registry, config: dict | None = None) -> list[str]:
    """Instantiate and attach all discovered servers.

    Returns the names of successfully connected servers.
    """
    cfg = config or {}
    servers_dir = cfg.get("mcp", {}).get("servers_dir", "mcp_servers")
    ok, failed = [], []
    for manifest in discover_servers(servers_dir):
        data = {k: v for k, v in manifest.items() if k != "cwd"}
        try:
            client = MCPClient(
                name=manifest["name"],
                command=manifest["command"],
                args=manifest.get("args", []),
                cwd=manifest.get("cwd"),
            )
            registry.attach(client)
            ok.append(manifest["name"])
        except MCPError as e:
            failed.append(f"{manifest['name']}: {e}")
    if failed:
        print("[mcp] failed to connect: " + "; ".join(failed))
    return ok