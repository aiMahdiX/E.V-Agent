#!/usr/bin/env python3
"""MCP browser server — exposes browser automation over JSON-RPC stdio.

Protocol mirrors the echo_demo server (MCP stdio transport) so E.V.'s
existing MCP client can call browser tools through capabilities.

Tools:
    browser_open   (url)
    browser_click  (selector)
    browser_read   (url?)
    browser_type   (text, selector?)
    browser_screenshot (path?)
"""
from __future__ import annotations

import json
import os
import sys

# make the project importable when launched via cwd=mcp_servers/browser
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from tools.browser import (  # noqa: E402
    open_page, click_selector, page_text, type_text, screenshot,
    browser_launch, browser_scroll, browser_links)

TOOLS = [
    {"name": "browser_open",
     "description": "Open a URL in the headless browser.",
     "inputSchema": {"type": "object",
                     "properties": {"url": {"type": "string"}},
                     "required": ["url"]}},
    {"name": "browser_launch",
     "description": "Open a URL in a visible system browser window.",
     "inputSchema": {"type": "object",
                     "properties": {"url": {"type": "string"}},
                     "required": ["url"]}},
    {"name": "browser_click",
     "description": "Click an element by CSS selector.",
     "inputSchema": {"type": "object",
                     "properties": {"selector": {"type": "string"}},
                     "required": ["selector"]}},
    {"name": "browser_read",
     "description": "Read the visible text of a page.",
     "inputSchema": {"type": "object",
                     "properties": {"url": {"type": "string"}},
                     "required": []}},
    {"name": "browser_type",
     "description": "Type text into the page.",
     "inputSchema": {"type": "object",
                     "properties": {"text": {"type": "string"},
                                    "selector": {"type": "string"}},
                     "required": ["text"]}},
    {"name": "browser_screenshot",
     "description": "Capture a screenshot of the browser page.",
     "inputSchema": {"type": "object",
                     "properties": {"path": {"type": "string"}},
                     "required": []}},
    {"name": "browser_scroll",
     "description": "Scroll the current page (pixels or top/bottom).",
     "inputSchema": {"type": "object",
                     "properties": {"amount": {"type": "string"}},
                     "required": []}},
    {"name": "browser_links",
     "description": "List visible links on the current page.",
     "inputSchema": {"type": "object",
                     "properties": {"limit": {"type": "integer"}},
                     "required": []}},
]

_HANDLERS = {
    "browser_launch": lambda a: browser_launch(a.get("url", "")),
    "browser_scroll": lambda a: browser_scroll(str(a.get("amount", "600"))),
    "browser_links": lambda a: browser_links(int(a.get("limit", 15))),
    "browser_open": lambda a: open_page(a.get("url", "")),
    "browser_click": lambda a: click_selector(a.get("selector", "")),
    "browser_read": lambda a: page_text(a.get("url") or None),
    "browser_type": lambda a: type_text(a.get("text", ""),
                                        a.get("selector", "//body")),
    "browser_screenshot": lambda a: screenshot(
        a.get("path", "data/screenshots/browser.png")),
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
                "serverInfo": {"name": "Browser", "version": "1.0.0"}}}
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
