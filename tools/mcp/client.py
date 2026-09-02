"""MCPClient — a minimal Model Context Protocol client over stdio.

Speaks JSON-RPC 2.0 to an MCP server subprocess (the standard local transport).
Used by the registry to let E.V. call external tools (game, browser, home,
vision servers) without binding them into the core.

Protocol (2024-11-05):
  initialize  ->  (server capabilities, serverInfo)
  notifications/initialized notification
  tools/list  ->  available tools
  tools/call  ->  execute a tool
"""
from __future__ import annotations

import json
import queue
import subprocess
import threading
import time


class MCPError(RuntimeError):
    pass


class MCPClient:
    def __init__(self, name: str, command: str, args: list[str] | None = None,
                 cwd: str | None = None, timeout: float = 15.0):
        self.name = name
        self.command = command
        self.args = list(args or [])
        self.cwd = cwd
        self.timeout = timeout
        self._proc = None
        self._reader = None
        self._inbox: "queue.Queue[str]" = queue.Queue()
        self._msg_id = 0
        self.connected = False
        self.info = {}
        self.capabilities = {}
        self.tools_cache: list[dict] = []

    # --------------------------------------------------------------- #
    def start(self) -> None:
        try:
            self._proc = subprocess.Popen(
                [self.command, *self.args], cwd=self.cwd,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                text=True, bufsize=1)
        except OSError as e:
            raise MCPError(f"cannot start server {self.name!r}: {e}") from e
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._reader.start()
        self._initialize()

    def _read(self) -> None:
        assert self._proc and self._proc.stdout
        for line in self._proc.stdout:
            self._inbox.put(line.rstrip("\n"))

    # --------------------------------------------------------------- #
    def _send(self, method: str, params: dict | None = None,
              notify: bool = False) -> dict | None:
        if self._proc is None or self._proc.poll() is not None:
            raise MCPError(f"MCP server {self.name!r} is not running")
        payload = {"jsonrpc": "2.0", "method": method}
        if params:
            payload["params"] = params
        if notify:
            self._write(payload)
            return None
        self._msg_id += 1
        payload["id"] = self._msg_id
        self._write(payload)
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            try:
                line = self._inbox.get(timeout=deadline - time.time())
            except Exception:
                break
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if msg.get("id") == self._msg_id:
                if "error" in msg:
                    raise MCPError(
                        f"MCP {self.name!r} error: {msg['error']}")
                return msg.get("result", {})
        raise MCPError(f"MCP request {method} timed out on {self.name!r}")

    def _write(self, payload: dict) -> int:
        assert self._proc and self._proc.stdin
        self._proc.stdin.write(json.dumps(payload) + "\n")
        self._proc.stdin.flush()
        return 1

    # --------------------------------------------------------------- #
    def _initialize(self) -> None:
        result = self._send("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "E.V.", "version": "0.1.0"},
        })
        self.connected = bool(result)
        self.info = result.get("serverInfo", {})
        self.capabilities = result.get("capabilities", {})
        self._send("notifications/initialized", notify=True)

    # --------------------------------------------------------------- #
    def list_tools(self) -> list[dict]:
        result = self._send("tools/list") or {}
        self.tools_cache = result.get("tools", [])
        return self.tools_cache

    def call(self, name: str, arguments: dict | None = None) -> dict:
        result = self._send("tools/call",
                            {"name": name, "arguments": arguments or {}}) or {}
        content = result.get("content", [])
        return {"result": result, "content": content}

    def close(self) -> None:
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=3)
            except OSError:
                pass


import threading  # noqa: E402
import time      # noqa: E402