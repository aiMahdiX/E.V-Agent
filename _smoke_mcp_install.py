"""Smoke-check GitHub MCP installation staging and discovery behavior."""
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tools.mcp.discovery import discover_servers
from tools.mcp.installer import install_github_server, set_server_enabled


def main():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir) / "mcp_servers"

        def fake_clone(command, **_kwargs):
            destination = Path(command[-1])
            destination.mkdir(parents=True)
            (destination / "server.json").write_text(json.dumps({
                "name": "sample", "command": "python3",
                "args": ["server.py"], "enabled": True,
            }), encoding="utf-8")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with patch("tools.mcp.installer.subprocess.run", side_effect=fake_clone):
            installed = install_github_server(
                "https://github.com/example/sample", root)

        assert installed["enabled"] is False
        assert discover_servers(root) == []
        set_server_enabled(root, "sample", True)
        discovered = discover_servers(root)
        assert len(discovered) == 1
        assert discovered[0]["name"] == "sample"
        assert discovered[0]["command"] == "python3"
        set_server_enabled(root, "sample", False)
        assert discover_servers(root) == []
        print("GitHub MCP install staging smoke check passed")


if __name__ == "__main__":
    main()