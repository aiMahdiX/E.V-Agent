"""Launch Laya's optional MCP server conservatively for E.V."""
from __future__ import annotations

import os


def main() -> int:
    os.environ.setdefault("LAYA_DEVICE", "cpu")
    os.environ.setdefault("LAYA_PRELOAD", "0")
    os.environ.setdefault("LAYA_THREADS", "4")
    try:
        from laya.mcp.server import main as run_server
    except ImportError as exc:
        raise SystemExit(
            "Laya MCP is not installed. Run: "
            ".venv/bin/python3 -m pip install -r requirements-laya.txt"
        ) from exc
    run_server()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())