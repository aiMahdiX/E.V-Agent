"""Offline checks for the opt-in Laya MCP integration."""
from __future__ import annotations

import json
from pathlib import Path

from core.capability_manager import CapabilityManager
from tools.mcp.discovery import discover_servers


def main() -> int:
    root = Path(__file__).resolve().parent
    manifest_path = root / "mcp_servers" / "laya" / "server.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["name"] == "laya"
    assert manifest["enabled"] is False
    assert manifest["command"] == "../../.venv/bin/python3"
    assert manifest["args"] == ["launch.py"]
    assert "laya" not in {
        server["name"] for server in discover_servers(root / "mcp_servers")
    }

    manager = CapabilityManager()
    tools = ["laya_predict", "laya_decide", "laya_preset"]
    manager.register_mcp_server("laya", tools)
    capability = manager.by_tool("laya_predict", "mcp")
    assert capability is not None
    assert capability.provider == "laya"
    assert capability.needs_approval is True
    assert set(capability.tools) == set(tools)
    print("Laya MCP stays disabled by default and requires approval when enabled: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())