#!/usr/bin/env python3
"""MCP vision server — expose camera capture + describe over JSON-RPC stdio.

Tools:
    camera_list            -> list devices
    camera_capture         -> (index?, path?) capture a frame to a file
    vision_describe        -> (path, prompt?) describe an image
    vision_screen          -> (prompt?) capture screen and describe
"""
from __future__ import annotations

import json
import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from tools.camera import camera_list, capture_frame        # noqa: E402
from tools.vision import describe_image, describe_screen   # noqa: E402

TOOLS = [
    {"name": "camera_list",
     "description": "List available webcam / video devices.",
     "inputSchema": {"type": "object", "properties": {}, "required": []}},
    {"name": "camera_capture",
     "description": "Capture a single frame from a webcam.",
     "inputSchema": {"type": "object",
                     "properties": {"path": {"type": "string"},
                                    "index": {"type": "integer"}},
                     "required": []}},
    {"name": "vision_describe",
     "description": "Describe the contents of an image file.",
     "inputSchema": {"type": "object",
                     "properties": {"path": {"type": "string"},
                                    "prompt": {"type": "string"}},
                     "required": ["path"]}},
    {"name": "vision_screen",
     "description": "Capture the screen and describe what is visible.",
     "inputSchema": {"type": "object",
                     "properties": {"prompt": {"type": "string"}},
                     "required": []}},
]

_HANDLERS = {
    "camera_list": lambda a: camera_list(),
    "camera_capture": lambda a: capture_frame(
        path=a.get("path", "data/camera/mcp_frame.png"),
        index=int(a.get("index", 0))),
    "vision_describe": lambda a: describe_image(
        str(a.get("path", "")), str(a.get("prompt", "describe the image"))),
    "vision_screen": lambda a: describe_screen(
        str(a.get("prompt", "describe this screen"))),
}


def _main() -> None:
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
                "serverInfo": {"name": "Vision", "version": "1.0.0"}}}
            sys.stdout.write(json.dumps(out) + "\n")
        elif method == "notifications/initialized":
            continue
        elif method == "tools/list":
            out = {"jsonrpc": "2.0", "id": ident, "result": {"tools": TOOLS}}
            sys.stdout.write(json.dumps(out) + "\n")
        elif method == "tools/call":
            name = msg.get("params", {}).get("name")
            args = msg.get("params", {}).get("arguments", {})
            handler = _HANDLERS.get(name)
            if handler is None:
                out = {"jsonrpc": "2.0", "id": ident, "error": {
                    "code": -32601, "message": f"unknown tool {name}"}}
            else:
                try:
                    result = handler(args)
                    out = {"jsonrpc": "2.0", "id": ident, "result": {
                        "content": [{"type": "text",
                                     "text": json.dumps(result)}]}}
                except Exception as e:  # noqa: BLE001
                    out = {"jsonrpc": "2.0", "id": ident, "error": {
                        "code": -32603, "message": f"{type(e).__name__}: {e}"}}
            sys.stdout.write(json.dumps(out) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    _main()