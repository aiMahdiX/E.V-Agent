# E.V. — Local Multimodal OS Agent

E.V. is a local-first multimodal OS agent for a Linux laptop with an NVIDIA
GPU. This repository implements the **Phase 1 MVP** and a **hybrid tool
architecture** (native tools + MCP) with the remaining phases scaffolded as
clear interfaces.

## Hardware layer
- **CPU**: Intel i7-11600H (12 threads)
- **RAM**: 16 GB (14 GB usable)
- **GPU**: NVIDIA RTX 3050 Laptop (4 GB)
- **OS** : Ubuntu / Linux
- **LLM**: Ollama (local)

## What is implemented (Phase 1 + hybrid)
- **Agent Core** — ReAct loop over Ollama's native tool-calling protocol
  (`core/agent.py`)
- **Ollama client** — pure-stdlib HTTP client (`models/llm.py`)
- **Dynamic Model Router** — uses *any* model present in Ollama: smallest for
  simple chat, largest for planning/troubleshooting, honors `fast/main/vision`
  preferences when those exact models exist (`core/router.py`)
- **Hybrid Tool Layer**
  - Capability Manager (`core/capability_manager.py`) — knows what E.V. can do
  - Tool Orchestrator (`core/tool_router.py`) — decides native vs MCP per call
  - native tools: Shell / Filesystem / Process / Services / GPU (`tools/`)
  - MCP client + registry + discovery (`tools/mcp/`) — stdio JSON-RPC
- **Memory** — short-term window + long-term SQLite facts + episodic events
  (`memory/`)
- **Security** — permission Levels 0..4 gating every action (`security/`)
- **CLI** — interactive `ev>` REPL (`ui/cli/repl.py`)

Phase 1 runs entirely on the Python standard library — no third-party
installs required (the MCP client is dependency-free too).

## Hybrid tool architecture

```
                    E.V. Brain
                        |
                Tool Orchestrator
                        |
            +-----------+------------+
            |                        |
      Native Tools              MCP Client
      (direct calls)            (protocol)
            |                        |
            |                +-------+--------+--------+
            |                |        |        |        |
            |             Game    Browser   Vision    Home
            v
     Python Runtime / Linux APIs / SQLite / subprocess
```

The orchestrator consults the Capability Manager before each dispatch and
tilt the decision by priority (config), applying a stricter security posture
to MCP tools (`needs_approval`).

## MCP servers

Drop a manifest at `mcp_servers/<name>/server.json`:

```json
{
  "name": "echo_demo",
  "enabled": true,
  "command": "python3",
  "args": ["server.py"]
}
```

At startup E.V. discovers every enabled server, connects over stdio, indexes
its `tools/list`, registers a Capability, and exposes those tools to the LLM.
A working reference server is at `mcp_servers/echo_demo/`. Skeletons for
`vision`, `game`, `browser`, `home` are present but disabled.

## Quick start

```bash
cd /home/aimahdix/Desktop/e.v
chmod +x setup.sh
./setup.sh              # venv + start Ollama + pull model (qwen3:4b)
.venv/bin/python3 main.py
```

Choose a different setup model:
```bash
./setup.sh qwen3:8b
```

Talk to E.V.:
```
ev> وضعیت GPU رو بگو
ev> فایل‌های پروژه رو لیست کن
ev> Ollama سرویس رو چک کن
```

### CLI commands
| command | meaning |
|---|---|
| `/gpu` | GPU status |
| `/models` | list pulled Ollama models |
| `/model [name]` | show current model, or force `auto`/`list`/`<name>` |
| `/capabilities` | native + connected MCP capabilities |
| `/tools` | list available tools (native + MCP) |
| `/remember <key> <value>` | store a long-term fact |
| `/episodes` | recent episodic memory |
| `/tasks` | list tracked tasks |
| `/hud` | open the graphical web HUD in the browser |
| `/clear` | reset conversation |
| `/exit` | quit |

## Configuration (`config.json`)
- `ollama.models` — preferred `fast`/`main`/`vision` names (used only if they
  exist locally; else the router falls back to size-based picks)
- `ollama.default` — the model used for warm-up / generic calls
- `ollama.keep_alive`, `ollama.think`, `ollama.max_tokens`, `ollama.num_ctx`
  — latency tuning (see Turbo mode below)
- `model_selection.mode` — `auto` (default) or `fixed`
- `agent.turbo_threshold` — complexity cut-off for the streamed no-tools path
- `tools.native` / `tools.mcp` — capability priorities and providers
- `tools.mcp_dir` — directory scanned for MCP `server.json` manifests
- `security.auto_approve_until_level` — auto-allow up to this Level (default 2)
- `agent.max_react_iterations` — ReAct loop cap

## Phase 2 — Voice (working)

Hands-free interaction over the arecord mic with a full local-first stack:

```text
🎙️ Mic (arecord/ALSA)
   └─ VAD (energy or WebRTC)  -> detect speech
   └─ STT  (Vosk, Persian model, offline)  -> transcript
   └─ Agent (same ReAct + tools as Phase 1)
   └─ TTS  (edge-tts neural Persian; espeak fallback) -> speaker
```

- **Wake word**: say **"ای وی"** (or "E.V.") to bring E.V. out of idle.
- **STT**: [Vosk](https://alphacephei.com/vosk/) small-Persian model shipped
  into `data/models/`, fully offline.
- **TTS**: `edge-tts` neural Persian voice by default (needs internet when
  synthesizing), `espeak` offline fallback.
- Configure under `config.json` → `voice` (backend, model, wake words, voice).

Enable with:
```bash
./setup_voice.sh            # one-time: installs deps + downloads fa model
.venv/bin/python3 main.py
# then inside the CLI:
ev> /voice
```

Live smoke (needs a mic + speaking):
```bash
.venv/bin/python3 _smoke_voice.py
```

## Phase 3 — Screen / GUI / Browser (working)

Full headless browser automation + screen capture, plus a native/MCP tool
surface for both.

- **Browser** (`tools/browser.py`) — Playwright driving *system* Google
  Chrome headlessly. Tools: `browser_open`, `browser_click`, `browser_read`,
  `browser_type`, `browser_screenshot`. No separate browser download needed;
  it reuses `/usr/bin/google-chrome-stable`.
- **Screen** (`tools/screen.py`) — `capture_screen` via `scrot` /
  `gnome-screenshot` / `import`(ImageMagick), with a browser fallback.
- **GUI** (`tools/gui.py`) — `gui_click`, `gui_type`, `gui_screenshot`
  (xdotool or pyautogui; reports cleanly when the tool isn't available).
- **MCP browser server** (`mcp_servers/browser/server.py`) — stdio JSON-RPC
  server exposing the same `browser_*` tools through the MCP registry.

Enable the MCP browser server in `config.json` → `tools.mcp.browser`.

## Phase 4 — Camera / Vision (working)

Real webcam capture + local multimodal image understanding.

- **Camera** (`tools/camera.py`) — `camera_list` (detects `/dev/video*`) and
  `camera_capture` (single frame via OpenCV, ffmpeg fallback). Level-1 tools.
- **Vision** (`models/vision.py`) — `VisionModel.describe()` sends a base64
  image + prompt to Ollama's multimodal model (`qwen3.5:4b` per
  `ollama.models.vision`). `think:false` is forced because thinking-capable
  vision models otherwise dump the answer into the `thinking` channel and
  leave `response` empty; there is a thinking-channel fallback anyway.
- **Vision tools** (`tools/vision.py`) — `vision_describe` (any image file)
  and `vision_screen` (grab screen → describe it). Initialized in `main.py`
  after the Ollama client; fails soft when no camera / no vision model.
- **MCP vision server** (`mcp_servers/vision/server.py`) — stdio JSON-RPC
  exposing `camera_list`, `camera_capture`, `vision_describe`,
  `vision_screen` through the MCP registry (`mcp_servers/vision/server.json`,
  `enabled: true`).

Try it in the REPL: «با دوربین ببین تو اتاق کیه؟» or
«از صفحه یک عکس بگیر و بگو چی می‌بینم».

## Web HUD (working)
A JARVIS-style graphical interface served by E.V. itself — no internet,
no build step, vanilla JS.

```bash
.venv/bin/python3 main.py     # HUD starts automatically on 127.0.0.1:8765
# then open http://127.0.0.1:8765  (or type /hud inside the CLI)
```

What you get (`ui/web/`):
- **Reactive core** — orbiting particle core + waveform that shift color
  with the agent state (idle / listening / thinking / speaking / error)
- **Live gauges** — CPU / RAM / GPU / VRAM / DISK polled from `/api/status`
- **Streaming chat** — tokens arrive over SSE (`/api/chat`), tool steps land
  in a live activity feed from the `step` events
- **Voice** — hold the mic button (or Space) to record → `/api/stt`
  (ffmpeg → Vosk); replies are spoken via `/api/tts` (Piper) with a mute toggle
- **Model selector** — switch between installed Ollama models or `auto`
  (`GET/POST /api/model`, shared with the CLI's `/model` command)

Endpoints: `GET /`, `GET /static/*`, `GET /api/status`, `POST /api/chat`
(SSE: `state|token|step|done`), `POST /api/stt`, `POST /api/tts`,
`GET|POST /api/model`. All heavy work (agent loop, ffmpeg, TTS) runs in
worker threads; voice back-ends load lazily so the HUD boots even without
Vosk/Piper models installed.

Config: `web.enabled` (default `true`), `web.host`, `web.port`.
Disable by setting `"web": {"enabled": false, ...}`.

## Architecture map (future)
| Phase | Area | Status |
|---|---|---|
| 1 | Ollama + Agent + Core + Shell/FS + Memory + CLI | **implemented** |
| 2 | Voice / Wake word / STT / TTS | **implemented** (`voice/`, `models/stt.py`, `models/tts.py`) |
| 3 | Screen / GUI / Browser (incl. MCP) | **implemented** (`tools/browser.py`, `tools/screen.py`, `tools/gui.py`) |
| 4 | Camera / Vision (incl. MCP) | **implemented** (`tools/camera.py`, `tools/vision.py`, `models/vision.py`) |
| — | Web HUD (`ui/web/`) | **implemented** (`main.py`, `ui/web/server.py`, `ui/web/static/`) |
| 5 | Proactive monitoring / Event bus | scaffolded (`sensors/event_bus.py`) |
| 6 | Semantic memory / Personality / Self-recovery | scaffolded (`memory/semantic.py`) |

## Tests
```bash
.venv/bin/python3 _smoke.py          # Phase 1: policy/permission/tools/memory
.venv/bin/python3 _smoke_hybrid.py   # capabilities/MCP/orchestrator/model router
.venv/bin/python3 _smoke_agent.py    # Agent ReAct loop (offline, fake LLM)
.venv/bin/python3 _smoke_voice.py    # Phase 2: VAD + Vosk model + wake word
.venv/bin/python3 _smoke_phase3.py   # Phase 3: browser/screen/gui + MCP browser
.venv/bin/python3 _smoke_phase4.py   # Phase 4: camera capture + vision model + MCP vision
.venv/bin/python3 _smoke_web.py      # Web HUD server endpoints (SSE chat/TTS/STT/status)
.venv/bin/python3 _smoke_latency.py  # live latency benchmark (needs Ollama)
```

## Latency / performance (Turbo mode)
E.V. is tuned for low latency on the RTX 3050:
- **Warm preload** — the local model is loaded into VRAM at startup
  (`client.warm`).
- **keep_alive 30m** — the model stays resident between turns; no reload
  stall (was the dominant cost).
- **think=false** — reasoning tokens disabled for Qwen3.5 (big speedup for
  simple turns).
- **num_predict cap** — answers are bounded so completion doesn't drag.
- **Turbo path** — simple greetings/questions route to a *single streamed
  generation* (no tool schemas, no ReAct loop). The CLI prints tokens live.
- **Cloud-model filtering** — the router never picks `*-cloud` models for
  local tasks (avoid slow remote round-trips).
- **Cached context** — the persona and OS probes are cached (30 s TTL), so
  building the prompt is cheap.

Measured on this machine (qwen3.5:4b, model already loaded, think off):
```
Q1 greeting/question (streamed): ~3 s     (first tokens in <1 s)
Q2 tool task (shell round-trip):  ~4 s
app startup after warm:            <1 s
```

## Notes
- `qwen3:4b` fits in 4 GB VRAM. Pull `qwen3:8b` / `gemma4:12b` and the router
  picks them automatically for complex work.
- Unrecognized shell commands escalate to Level 3 (require approval), never
  assumed safe.
- `data/ev.db` holds long-term memory; `data/logs/` holds audit + permission
  logs.
