"""E.V. Web HUD server — aiohttp backend for the graphical interface.

Endpoints
---------
GET  /                HUD (static/index.html)
GET  /static/{file}   css/js assets
GET  /api/status      cpu/ram/gpu/disk/model  (JSON)
POST /api/chat        SSE stream: state|token|step|done|error events
POST /api/stt         browser audio (webm/ogg/wav) -> ffmpeg -> Vosk -> text
POST /api/tts         {"text": ...} -> Piper WAV bytes
GET  /api/model       current model + pool + installed list
POST /api/model       {"model": name} fix | {"model":"auto"} reset

All blocking work (agent.run, ffmpeg, TTS) runs in worker threads; the
event loop stays free. ``create_app`` takes the live Agent so the web UI
shares memory/tools with the CLI.
"""
from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from concurrent.futures import Future as CfFuture
from pathlib import Path

from aiohttp import ClientError, web

from security import policy as sec_policy
from security.interactive import set_sudo_web_active

ROOT = Path(__file__).resolve().parent.parent.parent
STATIC = Path(__file__).resolve().parent / "static"


@web.middleware
async def _utf8_middleware(request: web.Request, handler):
    """Guarantee charset=utf-8 on text responses (html/css/js)."""
    resp = await handler(request)
    try:
        ct = resp.headers.get("Content-Type", "")
        if ("text/" in ct or "javascript" in ct) and "charset" not in ct.lower():
            resp.headers["Content-Type"] = ct + "; charset=utf-8"
    except Exception:  # noqa: BLE001 — headers may already be sent on streams
        pass
    return resp


# ------------------------------------------------------------------ #
# system probes (cheap, called from /api/status)                     #
# ------------------------------------------------------------------ #
def _cpu_load() -> float:
    """CPU % from /proc/stat. Always returns a number: on the very first
    call it takes a tiny second sample so the HUD never shows null."""
    try:
        def sample() -> tuple[int, int]:
            with open("/proc/stat", encoding="ascii") as fh:
                parts = fh.readline().split()[1:]
            vals = [int(x) for x in parts]
            idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
            return idle, sum(vals)

        idle, total = sample()
        if not hasattr(_cpu_load, "prev"):
            _cpu_load.prev = (idle, total)          # type: ignore[attr-defined]
            time.sleep(0.15)                        # short window for a real delta
            idle, total = sample()
        p_idle, p_total = _cpu_load.prev            # type: ignore[attr-defined]
        _cpu_load.prev = (idle, total)              # type: ignore[attr-defined]
        d_total, d_idle = total - p_total, idle - p_idle
        return round(100.0 * (1.0 - d_idle / d_total), 1) if d_total else 0.0
    except (OSError, ValueError, IndexError):
        return 0.0


def _ram() -> dict:
    try:
        info = {}
        with open("/proc/meminfo", encoding="ascii") as fh:
            for line in fh:
                k, v = line.split(":", 1)
                info[k] = int(v.strip().split()[0]) * 1024
        used = info["MemTotal"] - info["MemAvailable"]
        return {"used_gb": round(used / 2**30, 1),
                "total_gb": round(info["MemTotal"] / 2**30, 1),
                "percent": round(100.0 * used / info["MemTotal"], 1)}
    except (OSError, KeyError, ValueError):
        return {}


def _gpu() -> dict:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,"
             "memory.total,temperature.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=4).stdout.strip()
        u, mu, mt, t = [x.strip() for x in out.split(",")]
        return {"util": int(u), "mem_used": int(mu), "mem_total": int(mt),
                "temp": int(t)}
    except (OSError, ValueError, subprocess.SubprocessError):
        return {}


def _disk() -> dict:
    try:
        u = shutil.disk_usage(ROOT)
        return {"used_gb": round(u.used / 2**30, 1),
                "total_gb": round(u.total / 2**30, 1),
                "percent": round(100.0 * u.used / u.total, 1)}
    except OSError:
        return {}
# ------------------------------------------------------------------ #
# audio helpers                                                      #
# ------------------------------------------------------------------ #
def _to_pcm16(audio: bytes, mime: str) -> bytes:
    """Convert browser audio (webm/ogg/mp4/wav) to 16 kHz mono s16le PCM."""
    suffix = ".webm" if "webm" in mime else ".ogg" if "ogg" in mime \
        else ".mp4" if ("mp4" in mime or "aac" in mime) else ".wav"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as src:
        src.write(audio)
        src_path = src.name
    try:
        proc = subprocess.run(
            ["ffmpeg", "-y", "-i", src_path, "-ar", "16000", "-ac", "1",
             "-f", "s16le", "-acodec", "pcm_s16le", "pipe:1"],
            capture_output=True, timeout=20)
        if proc.returncode != 0 or not proc.stdout:
            raise RuntimeError(proc.stderr.decode(errors="replace")[-300:])
        return proc.stdout
    finally:
        Path(src_path).unlink(missing_ok=True)


def _model_router(agent):
    """Resolve the ModelRouter on the agent.

    The real ``core.Agent`` keeps the tool orchestrator on ``.router`` and
    the ModelRouter on ``.model_router``; stubs/older wiring may expose the
    ModelRouter directly as ``.router``. Anything without current()/pool()
    never qualifies.
    """
    for attr in ("model_router", "router"):
        r = getattr(agent, attr, None)
        if r is not None and callable(getattr(r, "current", None)) \
                and callable(getattr(r, "pool", None)):
            return r
    return None


def _model_info(agent) -> dict:
    """Model info for /api/status + /api/model.

    Must never raise — a broken router used to 500 the whole status
    endpoint and left the HUD gauges empty.
    """
    try:
        r = _model_router(agent)
        if r is None:
            return {"current": getattr(agent, "model_override", None),
                    "mode": "auto", "pool": [], "available": []}
        return {
            "current": getattr(agent, "model_override", None) or r.current(),
            "mode": r.mode,
            "pool": r.pool(),
            "available": r.available,
        }
    except Exception as e:  # noqa: BLE001 — degrade, don't kill /api/status
        return {"current": None, "mode": "auto", "pool": [],
                "available": [], "error": str(e)}


def _tools_info(agent) -> dict:
    """Tool inventory for the CORE panel — read-only, never raises."""
    try:
        orch = getattr(agent, "router", None)
        names = orch.names() if callable(getattr(orch, "names", None)) else []
        return {"count": len(names), "names": list(names)}
    except Exception:  # noqa: BLE001 — degrade, don't kill /api/status
        return {"count": 0, "names": []}


# approval requests currently waiting for a HUD answer: id -> future
pending_perms: dict[str, CfFuture] = {}


def _find_approvals(agent) -> list:
    """Collect the distinct security.approval.Approval objects wired into
    the agent's permission engines.  main.py builds ONE Approval shared by
    PermissionEngine and the derived ShellPermissionEngine, so this usually
    returns a single object; walking every alias keeps the web bridge
    correct even if the wiring ever uses separate engines."""
    out: list = []
    seen: set[int] = set()

    def add(obj) -> None:
        if (obj is not None and id(obj) not in seen
                and callable(getattr(obj, "ask", None))
                and hasattr(obj, "confirm")):
            seen.add(id(obj))
            out.append(obj)

    orch = getattr(agent, "router", None)                # ToolOrchestrator
    for node in (orch, getattr(orch, "native", None)):   # + inner ToolRouter
        eng = getattr(node, "perm", None)                # PermissionEngine
        add(getattr(eng, "approval", None))
        sp = getattr(node, "shell_perm", None)           # ShellPermissionEngine
        add(getattr(getattr(sp, "delegate", None), "approval", None))
    return out


def create_app(agent, config: dict) -> web.Application:
    v = config.get("voice", {})
    stt_model = v.get("stt_model") or None
    if stt_model and not Path(stt_model).is_absolute():
        stt_model = str(ROOT / stt_model)
    piper_model = v.get("tts_piper_model",
                        "data/models/piper/fa_IR-amir-medium.onnx")
    if not Path(piper_model).is_absolute():
        piper_model = str(ROOT / piper_model)

    from voice.stt import VoskSTT
    from models.tts import TTSModel

    class _Lazy:
        """Build a voice backend on first use — HUD boots without it."""
        def __init__(self, factory):
            self._factory, self._obj, self._err = factory, None, None
            self._lock = threading.Lock()

        def get(self):
            if self._err:
                raise RuntimeError(self._err)
            if self._obj is None:
                with self._lock:
                    if self._obj is None:
                        try:
                            self._obj = self._factory()
                        except Exception as e:  # noqa: BLE001
                            self._err = str(e)
                            raise
            return self._obj

    stt_lazy = _Lazy(lambda: VoskSTT(model_path=stt_model))
    tts_lazy = _Lazy(lambda: TTSModel(
        backend=v.get("tts_backend", "piper"), model_path=piper_model))
    try:  # preload Piper so the first spoken reply is instant
        tts_lazy.get().warm()
    except Exception:  # noqa: BLE001 - offline voice is best-effort
        pass

    # ---------------- GET / + /static/{name} ---------------- #
    _TEXT_MIME = {".html": "text/html", ".css": "text/css",
                  ".js": "application/javascript",
                  ".json": "application/json", ".svg": "image/svg+xml"}
    _BIN_MIME = {".png": "image/png", ".ico": "image/x-icon",
                 ".woff2": "font/woff2"}

    async def index(_req: web.Request) -> web.Response:
        return web.Response(
            body=(STATIC / "index.html").read_bytes(),
            content_type="text/html", charset="utf-8",
            headers={"Cache-Control": "no-cache"})

    async def static_ep(req: web.Request) -> web.Response:
        # resolve from the request path so sub-paths (e.g. /static/fonts/)
        # work with the same handler; the startswith() check below still
        # blocks anything that escapes STATIC (path traversal).
        rel = req.path.removeprefix("/static/")
        p = (STATIC / rel).resolve()
        mime = _TEXT_MIME.get(p.suffix, _BIN_MIME.get(p.suffix))
        if (not mime or not p.is_file()
                or not str(p).startswith(str(STATIC.resolve()))):
            raise web.HTTPNotFound()
        st = p.stat()
        etag = f'W/"{st.st_size:x}-{int(st.st_mtime):x}"'
        if req.headers.get("If-None-Match") == etag:
            return web.Response(status=304, headers={"ETag": etag})
        resp = web.Response(body=p.read_bytes(), content_type=mime,
                            charset="utf-8" if p.suffix in _TEXT_MIME else None)
        resp.headers["Cache-Control"] = "no-cache"
        resp.headers["ETag"] = etag
        return resp

    # ---------------- GET /api/status ---------------- #
    async def status(_req: web.Request) -> web.json_response:
        loop = asyncio.get_event_loop()
        cpu = await loop.run_in_executor(None, _cpu_load)
        ram = await loop.run_in_executor(None, _ram)
        gpu = await loop.run_in_executor(None, _gpu)
        disk = await loop.run_in_executor(None, _disk)
        gpu_out: dict = {"available": False}
        if gpu:
            gpu_out = {
                "available": True,
                "util": gpu["util"],
                "percent": gpu["util"],
                "temp": gpu["temp"],
                "vram": {
                    "used_gb": round(gpu["mem_used"] / 1024, 1),
                    "total_gb": round(gpu["mem_total"] / 1024, 1),
                    "percent": round(100.0 * gpu["mem_used"]
                                     / gpu["mem_total"], 1)
                    if gpu.get("mem_total") else 0,
                },
            }
        return web.json_response({
            "cpu": cpu, "ram": ram, "gpu": gpu_out, "disk": disk,
            "model": _model_info(agent), "tools": _tools_info(agent),
            "ts": time.time(),
        })

    # ---------------- POST /api/chat (SSE) ---------------- #
    async def chat(req: web.Request) -> web.StreamResponse:
        body = await req.json()
        user_input = str(body.get("message", "")).strip()
        if not user_input:
            return web.json_response({"error": "empty message"}, status=400)

        resp = web.StreamResponse(headers={
            "Content-Type": "text/event-stream; charset=utf-8",
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        })
        await resp.prepare(req)
        loop = asyncio.get_event_loop()
        q: asyncio.Queue = asyncio.Queue()
        mine: set[str] = set()        # permission ids raised by THIS run
        state = {"dead": False}       # client gone -> auto-deny approvals
        APPROVAL_TIMEOUT = 180        # s — HUD button window

        def cb_stream(delta: str) -> None:
            loop.call_soon_threadsafe(q.put_nowait, ("token", delta))

        def cb_step(info: dict) -> None:
            loop.call_soon_threadsafe(q.put_nowait, ("step", info))

        def web_ask(level: int, action: str, args: dict,
                    auto_approve_until: int):
            """Runs on the agent worker thread: push the approval question
            to the HUD as an SSE event, then block until the user answers
            (or timeout / client disconnect -> deny)."""
            if state["dead"]:
                return False
            rid = uuid.uuid4().hex
            fut: CfFuture = CfFuture()
            pending_perms[rid] = fut
            mine.add(rid)
            loop.call_soon_threadsafe(q.put_nowait, ("permission", {
                "id": rid, "level": level,
                "level_name": sec_policy.describe_level(level),
                "action": action, "args": args,
                "auto_approve_until": auto_approve_until,
                "timeout": APPROVAL_TIMEOUT}))
            try:
                return bool(fut.result(timeout=APPROVAL_TIMEOUT))
            except Exception:  # noqa: BLE001 — timeout/cancel/disconnect
                return False
            finally:
                mine.discard(rid)
                pending_perms.pop(rid, None)

        hooks = _find_approvals(agent)
        prev = [(a, a.ask_hook) for a in hooks]
        for a in hooks:
            a.ask_hook = web_ask

        async def run_agent():
            def blocking():
                loop.call_soon_threadsafe(q.put_nowait, ("state", "thinking"))
                # This request is served through the web HUD: sudo must pop
                # the graphical polkit dialog (pkexec)) here — not a terminal
                # prompt.  Cleared when the worker finishes so a later REPL
                # request asks for the password on its own TTY.

                set_sudo_web_active(True)
                try:
                    return agent.run(user_input, on_stream=cb_stream,
                                     on_step=cb_step)
                except Exception as e:  # noqa: BLE001
                    return f"[Error] {e}"
                finally:
                    set_sudo_web_active(False)
                    # worker thread finished -> hand the prompt back to CLI
                    for a, hook in prev:
                        a.ask_hook = hook

            answer = await loop.run_in_executor(None, blocking)
            q.put_nowait(("state", "idle"))
            q.put_nowait(("done", {"answer": answer,
                                   "model": _model_info(agent)}))

        runner = asyncio.ensure_future(run_agent())
        try:
            while True:
                event, data = await q.get()
                payload = json.dumps(data, ensure_ascii=False)
                await resp.write(
                    f"event: {event}\ndata: {payload}\n\n".encode())
                if event == "done":
                    break
        except (ConnectionError, ClientError):
            # browser closed/reloaded mid-stream.  This used to crash with
            # ClientConnectionResetError ("Cannot write to closing
            # transport") — stop cleanly instead.
            pass
        finally:
            state["dead"] = True
            if not runner.done():
                runner.cancel()
            try:
                await runner
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            for rid in list(mine):     # unblock a thread stuck on approval
                fut = pending_perms.pop(rid, None)
                if fut is not None and not fut.done():
                    fut.cancel()
        return resp

    # ---------------- POST /api/permission ---------------- #
    async def permission_ep(req: web.Request) -> web.json_response:
        """HUD answers an approval question raised during agent.run."""
        try:
            body = await req.json()
        except Exception:  # noqa: BLE001
            return web.json_response({"error": "bad json"}, status=400)
        rid = str(body.get("id", ""))
        allow = bool(body.get("allow", False))
        fut = pending_perms.get(rid)
        if fut is None:
            return web.json_response(
                {"error": "unknown or expired request"}, status=404)
        if not fut.done():
            fut.set_result(bool(allow))   # concurrent.futures -> thread-safe
        return web.json_response({"ok": True, "allowed": allow})

    # ---------------- POST /api/stt ---------------- #
    async def stt_ep(req: web.Request) -> web.json_response:
        raw = await req.read()
        if not raw:
            return web.json_response({"error": "no audio"}, status=400)
        mime = req.headers.get("Content-Type", "audio/webm")

        def blocking() -> str:
            pcm = _to_pcm16(raw, mime)
            return stt_lazy.get().transcribe_bytes(pcm)

        try:
            text = await asyncio.get_event_loop().run_in_executor(
                None, blocking)
        except FileNotFoundError:
            return web.json_response(
                {"error": "ffmpeg not found"}, status=503)
        except RuntimeError as e:
            return web.json_response({"error": str(e)}, status=503)
        except Exception as e:  # noqa: BLE001
            return web.json_response({"error": str(e)}, status=500)
        return web.json_response({"text": text.strip()})

    # ---------------- POST /api/tts ---------------- #
    async def tts_ep(req: web.Request) -> web.StreamResponse:
        body = await req.json()
        text = str(body.get("text", "")).strip()
        if not text:
            return web.json_response({"error": "no text"}, status=400)

        def blocking() -> str:
            out = tempfile.mktemp(suffix=".wav")
            return str(tts_lazy.get().synthesize(text, out))

        try:
            wav = await asyncio.get_event_loop().run_in_executor(
                None, blocking)
        except RuntimeError as e:
            return web.json_response({"error": str(e)}, status=503)
        except Exception as e:  # noqa: BLE001
            return web.json_response({"error": str(e)}, status=500)
        p = Path(wav)
        data = p.read_bytes()
        p.unlink(missing_ok=True)
        resp = web.StreamResponse(headers={
            "Content-Type": ("audio/mpeg" if p.suffix == ".mp3"
                             else "audio/wav"),
            "Cache-Control": "no-cache"})
        await resp.prepare(req)
        await resp.write(data)
        await resp.write_eof()
        return resp

    # ---------------- GET/POST /api/model ---------------- #
    async def model_get(_req: web.Request) -> web.json_response:
        return web.json_response(_model_info(agent))

    async def model_post(req: web.Request) -> web.json_response:
        body = await req.json()
        name = str(body.get("model", "")).strip()
        router = _model_router(agent)
        if router is None:
            return web.json_response(
                {"error": "model router unavailable"}, status=503)
        if not name or name == "auto":
            router.mode = "auto"
            router.override = None
            router.fixed = None
            if hasattr(agent, "model_override"):
                agent.model_override = None
        else:
            router.set_override(name)
            router.fixed = name
            router.mode = "fixed"
            if hasattr(agent, "model_override"):
                agent.model_override = name
        return web.json_response(_model_info(agent))

    app = web.Application(middlewares=[_utf8_middleware],
                          client_max_size=32 * 1024 * 1024)
    app.router.add_get("/", index)
    app.router.add_get("/api/status", status)
    app.router.add_post("/api/chat", chat)
    app.router.add_post("/api/permission", permission_ep)
    app.router.add_post("/api/stt", stt_ep)
    app.router.add_post("/api/tts", tts_ep)
    app.router.add_get("/api/model", model_get)
    app.router.add_post("/api/model", model_post)
    if STATIC.is_dir():
        app.router.add_get("/static/{name}", static_ep)
        # fonts live one level deeper: /static/fonts/{name}
        app.router.add_get("/static/fonts/{name}", static_ep)
    return app


def start_web(agent, config: dict):
    """Start the HUD server on a background thread. Returns runner."""
    wc = config.get("web", {})
    host = wc.get("host", "127.0.0.1")
    port = int(wc.get("port", 8765))
    import threading
    app = create_app(agent, config)
    runner = web.AppRunner(app)
    ready = threading.Event()
    err: list[str] = []

    def _serve() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(runner.setup())
            site = web.TCPSite(runner, host, port)
            loop.run_until_complete(site.start())
            ready.set()
            loop.run_forever()
        except Exception as e:  # noqa: BLE001
            err.append(str(e))
            ready.set()

    threading.Thread(target=_serve, daemon=True,
                     name="ev-web-hud").start()
    ready.wait(timeout=10)
    if err:
        raise RuntimeError(err[0])
    return runner
