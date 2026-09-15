#!/usr/bin/env python3
"""Smoke test for the E.V. web HUD server (aiohttp) — no real agent needed.

Run:  .venv/bin/python3 _smoke_web.py
Spins up the HUD app on 127.0.0.1:8799 with a stub agent and checks every
endpoint: HUD page, static assets, path-traversal guard, /api/status,
/api/model (get/fix/auto), SSE chat (state|token|step|done), real Piper
TTS, STT with a generated WAV, and empty-message 400.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


class StubRouter:
    mode = "auto"
    fixed = None
    override = None
    available = ["qwen3.5:4b", "minimax-m3:cloud"]

    def current(self):
        return self.override or self.fixed

    def pool(self):
        return self.available

    def set_override(self, m):
        self.override = m
        return m


class StubTools:
    """Mimics core.ToolOrchestrator: the real Agent keeps THIS object on
    ``.router``. Regression guard for the ``'ToolOrchestrator' object has
    no attribute 'current'`` crash — it deliberately has no current/pool."""

    def dispatch(self, name, args):
        return {"ok": True}

    def names(self):
        return ["filesystem.list"]


class StubAgent:
    # same shape as core.Agent: .router = tool orchestrator,
    # .model_router = the actual ModelRouter
    router = StubTools()
    model_router = StubRouter()
    model_override = None

    def run(self, text, on_stream=None, on_step=None):
        if on_step:
            on_step({"step": 1, "tool": "filesystem.list",
                     "args": {"path": "~/Desktop"},
                     "result": "3 items: a.txt, b.png, e.v"})
        for tok in ["سلام ", "مهدی! ", "هستهٔ ", "E.V. ", "آنلاین ", "است."]:
            if on_stream:
                on_stream(tok)
        return "سلام مهدی! هستهٔ E.V. آنلاین است."


class PermStubTools:
    def dispatch(self, name, args):
        return {"ok": True}

    def names(self):
        return ["filesystem.list"]


class PermStubAgent:
    """Mirrors the real wiring: one Approval shared by the PermissionEngine
    and the derived ShellPermissionEngine, exposed at agent.router.perm —
    exactly what ui.web.server._find_approvals() has to discover.  The run
    gates a Level-4 destructive action, so the web bridge must ask the HUD."""

    def __init__(self):
        from security.approval import Approval
        from security.permissions import (PermissionEngine,
                                          PermissionDenied)
        self.approval = Approval(confirm=False)     # hook decides, else deny
        engine = PermissionEngine(auto_approve_until=2,
                                  approval=self.approval)
        tools = PermStubTools()
        tools.perm = engine
        self.router = tools
        self.model_router = StubRouter()
        self.model_override = None
        self._PermissionDenied = PermissionDenied

    def run(self, text, on_stream=None, on_step=None):
        try:
            # policy.action_level("delete_file") ->  4 (destructive; the only
            # level still gated under the frictionless-operation rule).
            self.router.perm.authorize("delete_file", {"path": "/etc/shadow"})
        except self._PermissionDenied:
            return "دسترسی رد شد."
        for tok in ["دسترسی ", "تأیید ", "شد."]:
            if on_stream:
                on_stream(tok)
        return "دسترسی تأیید شد."


config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
config["web"] = {"host": "127.0.0.1", "port": 8799}

from ui.web.server import create_app  # noqa: E402

app = create_app(StubAgent(), config)

from aiohttp import web  # noqa: E402
import asyncio  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402

runner = web.AppRunner(app)
loop = asyncio.new_event_loop()


def serve():
    asyncio.set_event_loop(loop)
    loop.run_until_complete(runner.setup())
    loop.run_until_complete(
        web.TCPSite(runner, "127.0.0.1", 8799).start())
    loop.run_forever()


threading.Thread(target=serve, daemon=True).start()
time.sleep(1.2)
print("SERVER_UP http://127.0.0.1:8799/")

import urllib.request  # noqa: E402
import urllib.error  # noqa: E402


def get(path):
    with urllib.request.urlopen("http://127.0.0.1:8799" + path, timeout=10) as r:
        return r.status, r.headers.get("Content-Type", ""), r.read()


def post(path, data, ctype):
    req = urllib.request.Request("http://127.0.0.1:8799" + path, data=data,
                                 headers={"Content-Type": ctype})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.status, r.headers.get("Content-Type", ""), r.read()


fails = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + (" " + extra if extra else ""))
    if not cond:
        fails.append(name)


# 1. HUD page
st, ct, body = get("/")
check("GET /", st == 200 and b"coreWrap" in body and "text/html" in ct,
      f"{st} {ct} {len(body)}B")

# 2. static assets
for f, marker in (("hud.css", "--accent"), ("hud.js", "sendMessage")):
    st, ct, body = get("/static/" + f)
    check(f"GET /static/{f}", st == 200 and marker.encode() in body,
          f"{st} {ct} {len(body)}B")

# 3. path traversal guard
try:
    st, _, _ = get("/static/..%2F..%2Fserver.py")
    check("traversal blocked", st >= 400, f"status={st}")
except Exception:
    check("traversal blocked", True)

# 4. status
st, ct, body = get("/api/status")
d = json.loads(body)
check("GET /api/status", st == 200 and "ram" in d and "model" in d
      and d["model"]["pool"], f"cpu={d.get('cpu')} ram%={d['ram'].get('percent')}")
check("status cpu numeric (first call)",
      isinstance(d.get("cpu"), (int, float)), f"cpu={d.get('cpu')}")
check("status gpu.available flag", isinstance(d.get("gpu", {}).get("available"), bool),
      f"gpu={d.get('gpu')}")

# 4b. charset on text responses (Persian must never mojibake)
for path in ("/", "/static/hud.js", "/static/hud.css"):
    _, ct, _ = get(path)
    check(f"charset {path}", "charset=utf-8" in ct.lower(), ct)

# 5. model get/set
st, _, body = get("/api/model")
check("GET /api/model", st == 200 and json.loads(body)["mode"] == "auto")
st, _, body = post("/api/model", json.dumps({"model": "qwen3.5:4b"}).encode(),
                   "application/json")
d = json.loads(body)
check("POST /api/model fix", st == 200 and d["mode"] == "fixed"
      and d["current"] == "qwen3.5:4b")
st, _, body = post("/api/model", json.dumps({"model": "auto"}).encode(),
                   "application/json")
check("POST /api/model auto", st == 200 and json.loads(body)["mode"] == "auto")

# 6. SSE chat
st, ct, body = post("/api/chat", json.dumps({"message": "سلام"}).encode(),
                    "application/json")
txt = body.decode()
check("POST /api/chat SSE", st == 200 and "text/event-stream" in ct
      and "charset" in ct and "event: token" in txt and "event: step" in txt
      and "event: done" in txt and "filesystem.list" in txt
      and "آنلاین" in txt, f"{len(txt)}B")

# 6b. token payloads are JSON strings — client unjson() must reconstruct text
tokens = []
frames = txt.split("\n\n")
for fr in frames:
    ev = dat = None
    for ln in fr.splitlines():
        if ln.startswith("event:"):
            ev = ln[6:].strip()
        elif ln.startswith("data:"):
            dat = ln[5:].strip()
    if ev == "token" and dat is not None:
        try:
            tokens.append(json.loads(dat))
        except Exception:
            tokens.append(None)
check("SSE tokens are JSON strings",
      all(isinstance(t, str) for t in tokens) and tokens,
      f"{len(tokens)} tokens")
check("SSE text reconstruction",
      "".join(tokens) == "سلام مهدی! هستهٔ E.V. آنلاین است.",
      repr("".join(tokens))[:60])

# 7. TTS (real Piper)
try:
    st, ct, wav = post("/api/tts", json.dumps(
        {"text": "تست صدا ای وی"}).encode(), "application/json")
    check("POST /api/tts", st == 200 and len(wav) > 4000 and "audio" in ct,
          f"{st} {ct} {len(wav)}B")
except Exception as e:
    check("POST /api/tts", False, str(e)[:120])

# 8. STT with a generated tone WAV (expect 200; text likely empty)
import subprocess  # noqa: E402
p = subprocess.run(
    ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
     "-ar", "16000", "-ac", "1", "-f", "wav", "pipe:1"],
    capture_output=True)
try:
    st, ct, body = post("/api/stt", p.stdout, "audio/wav")
    check("POST /api/stt", st == 200
          and json.loads(body).get("text") is not None,
          f"({len(p.stdout)}B -> {body[:60]!r})")
except Exception as e:
    check("POST /api/stt", False, str(e)[:120])

# 9. empty chat -> 400
try:
    st, _, _ = post("/api/chat", json.dumps({"message": ""}).encode(),
                    "application/json")
    check("empty chat 400", st == 400, f"status={st}")
except urllib.error.HTTPError as e:
    check("empty chat 400", e.code == 400, f"status={e.code}")

# 10. permission bridge — a Level-4 destructive request surfaces as an SSE event and is
# resolved through POST /api/permission (HUD approve/deny round-trip)
app2 = create_app(PermStubAgent(), config)
runner2 = web.AppRunner(app2)


async def _serve2():
    await runner2.setup()
    await web.TCPSite(runner2, "127.0.0.1", 8800).start()


loop.call_soon_threadsafe(lambda: loop.create_task(_serve2()))
time.sleep(1.0)

import http.client  # noqa: E402

res2 = {"lines": [], "status": None, "ct": ""}


def chat_stream_2():
    conn = http.client.HTTPConnection("127.0.0.1", 8800, timeout=180)
    conn.request("POST", "/api/chat",
                 json.dumps({"message": "بررسی sudo"}).encode(),
                 {"Content-Type": "application/json"})
    r = conn.getresponse()
    res2["status"] = r.status
    res2["ct"] = r.headers.get("Content-Type", "")
    while True:
        ln = r.readline()
        if not ln:
            break
        res2["lines"].append(ln.decode("utf-8", "replace"))
    conn.close()


th = threading.Thread(target=chat_stream_2, daemon=True)
th.start()

pid = None
deadline = time.time() + 20
while time.time() < deadline and pid is None:
    lines = res2["lines"]
    for i, ln in enumerate(lines):
        if ln.startswith("event: permission") and i + 1 < len(lines):
            try:
                pid = json.loads(lines[i + 1][5:])["id"]
            except Exception:
                pid = None
    if pid is None:
        time.sleep(0.05)
evs = [l[6:].strip() for l in res2["lines"] if l.startswith("event:")]
check("SSE permission event raised", pid is not None, f"events={evs}")

if pid:
    req = urllib.request.Request("http://127.0.0.1:8800/api/permission",
                                 data=json.dumps({"id": pid,
                                                  "allow": True}).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            st, body = r.status, r.read()
        check("POST /api/permission allow", st == 200
              and json.loads(body).get("allowed") is True,
              body[:60].decode("utf-8", "replace"))
    except Exception as e:
        check("POST /api/permission allow", False, str(e)[:120])

th.join(timeout=40)
txt2 = "".join(res2["lines"])
check("approved Level-4 run completes with done",
      res2["status"] == 200 and "event: done" in txt2 and "تأیید شد" in txt2,
      f"status={res2['status']} {len(txt2)}B")

# 10b. unknown/expired id -> 404
st = None
try:
    req = urllib.request.Request("http://127.0.0.1:8800/api/permission",
                                 data=json.dumps({"id": "does-not-exist",
                                                  "allow": True}).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        st = r.status
except urllib.error.HTTPError as e:
    st = e.code
except Exception:
    st = None
check("POST /api/permission unknown id 404", st == 404, f"status={st}")

# 11. session-history passthrough — reopening an old conversation sends its
#     own transcript; the bridge has to hand it to agent.run(history=...)
#     sanitised (roles filtered, blanks dropped, newest 24 kept) and must
#     keep the kwarg OUT when the client sends none.  The latter is guarded
#     by test 6 above: StubAgent.run has a strict signature, so a server
#     that always passed history would blow up there.
seen = {}


class HistStubAgent(StubAgent):
    def run(self, text, on_stream=None, on_step=None, history=None):
        seen["history"] = history
        if on_stream:
            on_stream("باشه.")
        return "باشه."


app3 = create_app(HistStubAgent(), config)
runner3 = web.AppRunner(app3)


async def _serve3():
    await runner3.setup()
    await web.TCPSite(runner3, "127.0.0.1", 8801).start()


loop.call_soon_threadsafe(lambda: loop.create_task(_serve3()))
time.sleep(1.0)


def chat_8801(payload):
    req = urllib.request.Request("http://127.0.0.1:8801/api/chat",
                                 data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", "replace")


chat_8801({"message": "ادامه بده", "history": [
    {"role": "user", "content": "ربات تلگرامم بالا نمیاد"},
    {"role": "assistant", "content": "دارم بررسی می‌کنم."},
    {"role": "system", "content": "MUST BE DROPPED"},
    "not-a-dict",
    {"role": "user", "content": "   "},
]})
hist = seen.get("history")
check("history passthrough sanitised",
      isinstance(hist, list) and len(hist) == 2
      and [h["role"] for h in hist] == ["user", "assistant"]
      and hist[0]["content"] == "ربات تلگرامم بالا نمیاد"
      and hist[1]["content"] == "دارم بررسی می‌کنم.",
      f"history={hist}")

bulk = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"m{i}"}
        for i in range(26)]
chat_8801({"message": "ادامه بده", "history": bulk})
hist = seen.get("history") or []
check("history capped to newest 24",
      len(hist) == 24 and hist[0]["content"] == "m2"
      and hist[-1]["content"] == "m25",
      f"n={len(hist)} first={(hist or [{}])[0].get('content')}")

seen.clear()
chat_8801({"message": "سلام"})
check("no history -> not seeded", seen.get("history") is None,
      f"history={seen.get('history')}")

print("\n" + ("ALL_WEB_SMOKE_PASS" if not fails else f"FAILED: {fails}"))
sys.exit(1 if fails else 0)
