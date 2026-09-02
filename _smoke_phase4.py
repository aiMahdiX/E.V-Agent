#!/usr/bin/env python3
"""Phase 4 smoke tests — Camera / Vision."""
import base64
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PASS = []


def ok(name, cond, extra=""):
    if cond:
        PASS.append(name)
        print(f"  [ok] {name}")
    else:
        raise AssertionError(f"{name} FAILED {extra}")


# ---- 1. router registration ------------------------------------- #
from tools.router import ToolRouter

r = ToolRouter(workspace=".")
names = r.names()
ok("camera_list registered", "camera_list" in names)
ok("camera_capture registered", "camera_capture" in names)
ok("vision_describe registered", "vision_describe" in names)
ok("vision_screen registered", "vision_screen" in names)

# ---- 2. camera_list ---------------------------------------------- #
from tools.camera import camera_list, capture_frame

listing = camera_list()
has_cam = bool(listing.get("devices"))
if has_cam:
    ok("camera_list finds devices", listing["devices"][0].startswith("/dev/video"))
else:
    print("  [skip] no /dev/video* present -> capture tests limited")

# ---- 3. real frame capture ---------------------------------------- #
if has_cam:
    cap = capture_frame(path="/tmp/ev_p4_frame.png", index=0)
    ok("capture_frame ok", cap.get("ok") is True, str(cap))
    ok("frame file exists+nonempty",
       os.path.exists("/tmp/ev_p4_frame.png")
       and os.path.getsize("/tmp/ev_p4_frame.png") > 1000)

# ---- 4. VisionModel unit (fake client, no live ollama needed) ----- #
from models.vision import VisionModel


class FakeClient:
    model = "fake-main"

    def __init__(self):
        self.last_payload = None

    def _post(self, path, payload):
        self.last_payload = payload
        return {"response": "یک مرد پشت میز کار"}  # channel response


fc = FakeClient()
vm = VisionModel(fc, model="qwen3.5:4b")

tmp_img = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
tmp_img.write(b"\x89PNG\r\n\x1a\nFAKEIMGDATA" * 64)
tmp_img.close()

out = vm.describe(tmp_img.name, "چه می‌بینی؟")
ok("describe returns model text", out == "یک مرد پشت میز کار", out)
p = fc.last_payload
ok("images field is base64 string",
   isinstance(p["images"], list) and isinstance(p["images"][0], str))
base64.b64decode(p["images"][0])           # must decode cleanly
ok("think disabled in payload", p.get("think") is False,
   "thinking-capable vision models otherwise put answer in wrong channel")
ok("model passed through", p["model"] == "qwen3.5:4b")
ok("missing image handled",
   "not found" in vm.describe("/no/such/file.png"))

# empty-response fallback to thinking channel


class ThinkingClient(FakeClient):
    def _post(self, path, payload):
        return {"response": "", "thinking": "پاسخ در کانال تفکر"}


out2 = VisionModel(ThinkingClient(), model="m").describe(tmp_img.name, "x")
ok("falls back to thinking channel", out2 == "پاسخ در کانال تفکر", out2)

os.unlink(tmp_img.name)

# ---- 5. tools/vision glue ------------------------------------------ #
import tools.vision as tv


class FakeVM:
    def describe(self, path, prompt=""):
        return f"[{path}] توصیف شد"


tv.set_vision_model(None)
res_none = tv.describe_image("/tmp/whatever.png")
ok("describe_image w/o model errors cleanly", "error" in res_none)

tv.set_vision_model(FakeVM())
res = tv.describe_image("/tmp/pic.png", "توضیح بده")
ok("describe_image routes to model",
   res["ok"] and "توصیف" in res["description"], str(res))
res2 = tv.describe_image("/tmp/pic.png")     # default Persian-safe call
ok("default prompt accepted", res2["description"] == "[/tmp/pic.png] توصیف شد")
tv.set_vision_model(None)                    # restore neutral state

# ---- 6. dispatch-level integration (regression: native tools must
#         accept the injected workspace kwarg) ---------------------- #
from pathlib import Path
from security.permissions import PermissionEngine
from security.approval import Approval

perm = PermissionEngine(auto_approve_until=2,
                        approval=Approval(confirm=False))
native = ToolRouter(workspace=Path("."))
r2 = native.dispatch("camera_list", {})
ok("dispatch camera_list", "error" not in r2, str(r2))
if has_cam:
    r3 = native.dispatch("camera_capture",
                         {"path": "/tmp/ev_p4_dispatch.png"})
    ok("dispatch camera_capture", r3.get("ok") is True, str(r3))
    os.unlink("/tmp/ev_p4_dispatch.png")

tv.set_vision_model(FakeVM())
fake_describe = native.dispatch(
    "vision_describe", {"path": "/tmp/pic.png"})
ok("dispatch vision_describe",
   fake_describe["description"] == "[/tmp/pic.png] توصیف شد",
   str(fake_describe))
tv.set_vision_model(None)

# ---- 7. MCP vision server over stdio ------------------------------- #
server = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "mcp_servers", "vision", "server.py")
proc = subprocess.Popen(
    [sys.executable, server], stdin=subprocess.PIPE,
    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)


def rpc(msg):
    proc.stdin.write(json.dumps(msg) + "\n")
    proc.stdin.flush()
    line = proc.stdout.readline()
    return json.loads(line) if line.strip() else {}


try:
    init = rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    ok("mcp initialize", init["result"]["serverInfo"]["name"] == "Vision")
    lst = rpc({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    mtools = [t["name"] for t in lst["result"]["tools"]]
    ok("mcp exposes 4 tools",
       set(mtools) == {"camera_list", "camera_capture",
                       "vision_describe", "vision_screen"}, str(mtools))
finally:
    proc.terminate()

print(f"\nPHASE 4 SMOKE TESTS PASSED ({len(PASS)} checks)")