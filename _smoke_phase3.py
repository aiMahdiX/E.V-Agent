#!/usr/bin/env python3
"""Phase 3 smoke tests: browser + screen + gui + MCP browser server.

Runs without real desktop access where possible. Browser tests drive a
headless system Chrome (or Playwright's own chromium if present).
"""
import sys
sys.path.insert(0, ".")

FAILED = []


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    if not cond:
        FAILED.append(name)
    print(f"[{status}] {name}{(' ' + detail) if detail else ''}")


# --------------------------------------------------------------------- #
# 1. Native tool registration
# --------------------------------------------------------------------- #
from tools.router import ToolRouter

router = ToolRouter(workspace=".")
names = router.names()
for tool in ("browser_open", "browser_click", "browser_type",
             "browser_read", "browser_screenshot", "capture_screen",
             "gui_click", "gui_type", "gui_screenshot"):
    check(f"registered {tool}", tool in names)

# --------------------------------------------------------------------- #
# 2. Browser native dispatch (headless Chrome)
# --------------------------------------------------------------------- #
try:
    res = router.dispatch("browser_open",
                          {"url": "data:text/html,<h1>E.V. phase3</h1>"})
    check("browser_open headless", res.get("ok"), str(res))
    if res.get("ok"):
        read = router.dispatch("browser_read", {})
        check("browser_read sees text", "phase3" in str(read.get("text")),
              str(read)[:120])
        shot = router.dispatch("browser_screenshot",
                               {"path": "data/screenshots/browser_smoke.png"})
        check("browser_screenshot", shot.get("ok") and shot.get("size", 0) > 0,
              str(shot)[:120])
except Exception as e:  # noqa: BLE001
    check("browser dispatch", False, f"{type(e).__name__}: {e}")

# --------------------------------------------------------------------- #
# 3. Screen tool (capture_screen attempts desktop; may gracefully error)
# --------------------------------------------------------------------- #
res = router.dispatch("capture_screen",
                      {"path": "data/screenshots/screen_smoke.png"})
check("capture_screen callable", "error" not in str(res) or
      "not available" in str(res) or res.get("ok"),
      str(res)[:160])

# --------------------------------------------------------------------- #
# 4. GUI tools (may be unavailable on headless/Wayland — must not crash)
# --------------------------------------------------------------------- #
for tool, args in (("gui_click", {"x": 100, "y": 100}),
                   ("gui_type", {"text": "hi"})):
    res = router.dispatch(tool, args)
    check(f"{tool} callable", isinstance(res, dict), str(res)[:120])

# --------------------------------------------------------------------- #
# 5. MCP browser server (stdio JSON-RPC handshake)
# --------------------------------------------------------------------- #
import json
import subprocess
import os

srv = os.path.join("mcp_servers", "browser", "server.py")
try:
    proc = subprocess.Popen(
        [sys.executable, srv],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, text=True)
    init = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2024-11-05",
                       "capabilities": {}, "clientInfo": {}}}
    proc.stdin.write(json.dumps(init) + "\n")
    proc.stdin.flush()
    line = proc.stdout.readline()
    resp = json.loads(line)
    check("MCP browser initialize", resp.get("result", {}).get("serverInfo", {}).get("name") == "Browser",
          line.strip()[:120])
    proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 2,
                                 "method": "tools/list"}) + "\n")
    proc.stdin.flush()
    line = proc.stdout.readline()
    resp = json.loads(line)
    tools = [t["name"] for t in resp.get("result", {}).get("tools", [])]
    check("MCP browser tools/list", "browser_open" in tools, str(tools))
    proc.terminate()
except Exception as e:  # noqa: BLE001
    check("MCP browser server", False, f"{type(e).__name__}: {e}")

# --------------------------------------------------------------------- #
print()
if FAILED:
    print("PHASE 3 SMOKE: FAILED ->", FAILED)
    sys.exit(1)
print("ALL PHASE 3 SMOKE TESTS PASSED")
sys.exit(0)