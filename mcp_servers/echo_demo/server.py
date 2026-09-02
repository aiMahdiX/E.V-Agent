#!/usr/bin/env python3
"""A minimal MCP server for protocol testing.

Implements the JSON-RPC 2.0 stdio transport handshake and one tool. Used to
validate E.V.'s MCP client end-to-end without external dependencies.
"""
from __future__ import annotations

import json
import sys


def _main() -> None:
    tools = [{
        "name": "echo_demo_echo",
        "description": "Return the given text unchanged.",
        "inputSchema": {"type": "object",
                        "properties": {"text": {"type": "string"}},
                        "required": ["text"]},
    }]
    for line in sys.stdin:
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        method = msg.get("method")
        ident = msg.get("id")
        if method == "initialize":
            out = {"jsonrpc": "2.0", "id": ident, "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "EchoDemo", "version": "1.0.0"}}}
            sys.stdout.write(json.dumps(out) + "\n")
        elif method == "notifications/initialized":
            continue
        elif method == "tools/list":
            out = {"jsonrpc": "2.0", "id": ident,
                   "result": {"tools": tools}}
            sys.stdout.write(json.dumps(out) + "\n")
        elif method == "tools/call":
            name = msg.get("params", {}).get("name")
            args = msg.get("params", {}).get("arguments", {})
            if name == "echo_demo_echo":
                out = {"jsonrpc": "2.0", "id": ident, "result": {
                    "content": [{"type": "text",
                                 "text": args.get("text", "")}]}}
            else:
                out = {"jsonrpc": "2.0", "id": ident, "error": {
                    "code": -32601, "message": f"unknown tool {name}"}}
            sys.stdout.write(json.dumps(out) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    _main()