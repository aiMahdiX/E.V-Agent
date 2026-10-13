# E.V. — Local Multimodal OS Agent

E.V. is a local-first multimodal agent for Linux. It combines a ReAct agent,
native operating-system tools, optional MCP integrations, local or hosted
language models, and a web HUD. Hardware-dependent capabilities degrade
gracefully when their optional runtimes or devices are unavailable.

## Hardware layer
- Setup detects the current CPU, available RAM, free disk, and NVIDIA VRAM.
- It recommends a local model when resources permit; cloud is an available
  alternative when selected by the user or when local inference is unsuitable.
- **Inference choices**: Ollama local, or a configured hosted provider such as
  OpenAI, Gemini, OpenRouter, Groq, DeepSeek, Mistral, Together AI, xAI, or
  Ashna AI. Other OpenAI-compatible endpoints can be entered manually.

## What is implemented (Phase 1 + hybrid)
- **Agent Core** — ReAct loop over provider-neutral tool-calling
  (`core/agent.py`)
- **LLM providers** — Ollama plus configurable OpenAI-compatible APIs
  (including Ashna.ai), with a small provider factory registry (`models/llm.py`)
- **Dynamic Model Router** — uses *any* model present in Ollama: smallest for
  simple chat, largest for planning/troubleshooting, honors `fast/main/vision`
  preferences when those exact models exist (`core/router.py`)
- **Hybrid Tool Layer**
  - Capability Manager (`core/capability_manager.py`) — knows what E.V. can do
  - Tool Orchestrator (`core/tool_router.py`) — decides native vs MCP per call
  - native tools: Shell / Filesystem / Process / Services / GPU (`tools/`)
  - MCP client + registry + discovery (`tools/mcp/`) — stdio JSON-RPC
- **Memory** — short-term window + long-term SQLite facts + episodic events
  (`memory/`); relevant past events are retrieved locally into each request
- **Security** — permission Levels 0..4 gating every action (`security/`)
- **CLI** — interactive `ev>` REPL (`ui/cli/repl.py`)

Ollama remains dependency-free. The base install adds `aiohttp` for the local
web HUD. OpenAI-compatible API providers additionally require the optional
`openai` package and their provider API key; the provider wizard installs the
SDK after the user chooses a hosted provider.

## Telegram remote control

The optional Telegram gateway accepts private messages only from explicitly
allowlisted Telegram user IDs. Revoke any bot token pasted into chat or source
control, then configure the replacement token and your numeric Telegram user
ID in the shell before starting E.V.:

```bash
export TELEGRAM_BOT_TOKEN='token-from-BotFather'
export TELEGRAM_ALLOWED_USER_IDS='123456789'
.venv/bin/python main.py
```

Multiple allowed IDs can be comma-separated. Without both variables the
gateway stays disabled. Sensitive actions still require a one-time `/approve
<code>` or `/deny <code>` reply in the same private chat; approval codes expire
after two minutes. The bot does not expose a public HTTP endpoint.

## Languages

The CLI, Telegram status messages, and web HUD use English. Text replies are
prompted to follow the language of each current user message; that takes
precedence over `agent.language` and older profile or memory preferences.
Set `agent.language` to `auto` to keep this behavior as the default. The
current voice pipeline is still Persian-specific: its bundled Vosk STT model
and default Piper voice are Persian, so multilingual typed chat is supported
but multilingual speech recognition and synthesis are not yet provided.

## Phase 7 — Self-improvement loop (Skills + Semantic memory)

E.V. now has the learning loop that makes it *better the longer it runs* —
patterned after Hermes Agent's skill system, but sized for a 4 GB laptop:

- **Skills** (`skills/`) — every successful multi-tool run is consolidated
  into a reusable, versioned skill (`data/skills.json`): goal, observed tool
  steps, tags, usage counters. The top-k skills are injected into the system
  prompt, so proven plans are replayed instead of re-derived. The model can
  list/run/create skills through the `skill_list` / `skill_run` /
  `skill_create` tools, and you can manage them in the CLI:

  ```
  /skills              # list learned skills
  /skills run <id>     # replay a skill now
  /skills rm <id>      # delete one
  ```

  Replay adapts to drift: each step's arguments are re-checked by the LLM
  against the current situation before dispatch, and results/usage are
  recorded back into the skill.

- **Semantic memory** (`memory/semantic.py` + `memory/embeddings.py`) —
  retrieval upgraded from plain TF-IDF to a blended score: character n-gram
  hash embeddings (dependency-free, Persian + Latin) **plus** true neural
  embeddings via the local Ollama server (`/api/embed`, default model
  `nomic-embed-text`) whenever it is available — automatic hash fallback
  otherwise. Facts and episodes are labeled (`[fact]` / `[episode]`) in the
  prompt so the model knows where a memory came from.

- **FTS5 recall** (`memory/long_term.py`) — the episodic store now has a
  full-text index (BM25-ranked, trigger-maintained) with a LIKE fallback on
  older SQLite builds.

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

Public GitHub MCP repositories that follow this manifest format can be staged
from the CLI:

```text
/mcp install https://github.com/owner/repository
/mcp list
```

Installation clones the repository into the configured MCP directory and
forces its root-level `server.json` to `enabled: false`. Review the repository
and manifest before enabling it with `/mcp enable <id>`; the command in the
manifest will run on the next E.V. startup. Use `/mcp disable <id>` to prevent
future startup execution. E.V. does not install Python/npm dependencies
automatically, and this installer only accepts repositories with a valid
root-level `server.json` containing `name` and `command` (and optional string
`args`). MCP tools from unconfigured servers require approval by default.

### Optional Laya decision tools

[Laya](https://github.com/NandhaKishorM/laya) provides typed `choice`, `score`,
and yes/no decisions, plus routing and triage presets. It does not generate
chat responses and must not replace E.V.'s permission policy. To add its
official MCP tools without changing the base install:

```bash
.venv/bin/python3 -m pip install -r requirements-laya.txt
# then in E.V.:
/mcp enable laya
```

The server starts on CPU with checkpoint preloading disabled; its first
prediction may download model weights from Hugging Face. Every Laya tool call
uses E.V.'s normal MCP approval gate. Treat predictions as advisory until
validated on representative tasks, and keep privileged or destructive actions
behind the existing security controls. The adapter is a small launcher around
Laya's Apache-2.0 package; no upstream source is copied into this repository.

## Quick start

Requires Python 3.10 or newer. Local inference additionally requires Ollama;
cloud providers are configured separately through the setup wizard.

```bash
cd /path/to/e.v
chmod +x setup.sh
./setup.sh              # detect hardware; choose local, cloud, or manual setup
.venv/bin/python3 main.py
```

The recommendation uses available RAM, NVIDIA VRAM, and free disk space. In
interactive setup, choose local, cloud, or a manual local model. Cloud setup
supports `openai`, `gemini`, `openrouter`, `groq`, `deepseek`, `mistral`,
`together`, `xai`, `ashna`, and `custom` provider IDs. Other OpenAI-compatible
services can use `custom` with their API base URL and model ID.

Before asking for a key, setup explains that validation sends one short test
prompt and may incur a small charge. It saves the key only after validation,
inside the ignored `.env` file with mode `0600`. Normal chat text is then sent
to the selected provider; microphone audio is not enabled or uploaded by this
setup. Built-in tools remain available under the existing permission system.
Review optional MCP server code before enabling it.

Select cloud directly, or force automatic local recommendation:
```bash
./setup.sh --cloud gemini
./setup.sh --local
```

Choose a model manually:
```bash
./setup.sh --manual qwen3:4b
# An explicit model name remains supported:
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
| `/skills` | learned skills (`run <id>` / `rm <id>`) |
| `/mcp` | install/list/enable/disable GitHub MCP servers |
| `/settings` | inspect/update app settings and platform credentials |
| `/permission` | show/set the auto-approval limit (`/permission set 0..4`) |
| `/hud` | open the graphical web HUD in the browser |
| `/clear` | reset conversation |
| `/exit` | quit |

## Configuration (`.env` and `config.json`)
- `main.py` loads `.env` on startup; `EV__` variables map to nested config
  keys using double underscores (for example, `EV__OLLAMA__HOST`). Values
  should be JSON literals so strings, numbers, booleans, arrays, and `null`
  keep their types. Existing process environment variables override `.env`;
  `.env` overrides `config.json`.
- Copy `.env.example` to `.env` and put secrets such as `ASHNA_API_KEY` there.
  The local `.env` file is ignored by Git.
- `providers.default` selects the provider used when a model is not qualified
- `providers.instances` declares provider clients; model names use
  `provider:model-name` when routing to a specific provider
- Set `ASHNA_API_KEY` in the environment to enable the configured Ashna client;
  then set `model_selection.fixed` to `ashna:gpt-6-astra` to use it by default
- To switch the default config to Ashna, export the key before launching E.V.:
  ```bash
  export ASHNA_API_KEY="your-key"
  ```
  Set `providers.default` to `ashna`, `model_selection.mode` to `fixed`, and
  `model_selection.fixed` to `ashna:gpt-6-astra` in `config.json`.
- To add another compatible service, add an `openai-compatible` instance with
  its `base_url`, `model`, and `api_key_env`; for a different protocol, register
  a factory with `register_provider(name, factory)` in `models/llm.py`
- `ollama.models` — preferred `fast`/`main`/`vision` names (used only if they
  exist locally; else the router falls back to size-based picks)
- `ollama.default` — the model used for warm-up / generic calls
- `ollama.keep_alive`, `ollama.think`, `ollama.max_tokens`, `ollama.num_ctx`
  — latency tuning (see Turbo mode below)
- `model_selection.mode` — `auto` (default) or `fixed`
- Local-only model routing is the default (`include_cloud: false`); set it to
  `true` and choose a cloud model explicitly to enable remote inference
- `agent.language` — `auto` follows the current user message language and
  overrides older language preferences in profile memory
- `agent.turbo_threshold` — complexity cut-off for the streamed no-tools path
- `tools.native` / `tools.mcp` — capability priorities and providers
- `tools.mcp_dir` — directory scanned for MCP `server.json` manifests
- `security.auto_approve_until_level` — configure the automatic approval
  threshold (0..4) with `/permission set <0..4>` or HUD Settings. Level 3/4
  actions and MCP tools with `needs_approval: true` always require explicit
  approval, regardless of the threshold.
- Commands using `sudo` ask for the system password separately: the terminal
  uses a hidden password prompt, while the HUD uses the OS `pkexec` dialog.
  If the graphical prompt is unavailable, HUD execution is blocked.
- `agent.max_react_iterations` — ReAct loop cap
- `memory.semantic.embed_model` — Ollama embedding model for semantic
  retrieval (`nomic-embed-text` by default; automatic hash fallback when the
  model/server is missing)
- `memory.semantic.skills_top_k` — how many learned skills are injected into
  each system prompt (default 5)

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

Config: `web.enabled` (default `true`), `web.host`, `web.port`. The HUD has no
remote authentication and only starts on `localhost` or a loopback IP; remote
bind addresses are rejected because the API can execute local tools.
Disable by setting `"web": {"enabled": false, ...}`.

## Architecture map
| Phase | Area | Status |
|---|---|---|
| 1 | Ollama + Agent + Core + Shell/FS + Memory + CLI | **implemented** |
| 2 | Voice / Wake word / STT / TTS | **implemented** (`voice/`, `models/stt.py`, `models/tts.py`) |
| 3 | Screen / GUI / Browser (incl. MCP) | **implemented** (`tools/browser.py`, `tools/screen.py`, `tools/gui.py`) |
| 4 | Camera / Vision (incl. MCP) | **implemented** (`tools/camera.py`, `tools/vision.py`, `models/vision.py`) |
| — | Web HUD (`ui/web/`) | **implemented** (`main.py`, `ui/web/server.py`, `ui/web/static/`) |
| 5 | Local task reminders / scheduler + event bus | **implemented** (`tasks/scheduler.py`, `sensors/event_bus.py`, `sensors/system_monitor.py`, `sensors/gpu_monitor.py`) |
| 6 | Semantic memory / Personality / Self-recovery | **implemented** (`memory/semantic.py`, real embeddings + FTS5) |
| 7 | Skills / self-improvement loop | **implemented** (`skills/`) |

Local schedules survive restarts and only notify when due; they never execute
tasks unattended. Use `/schedule in 10m <task>` for a one-shot reminder or
`/schedule every 1h <task>` for a recurring reminder, `/schedules` to list,
`/cancel <TASK-ID>` to cancel, and `/run <TASK-ID>` to explicitly execute.

## Tests
```bash
.venv/bin/python3 _smoke.py          # Phase 1: policy/permission/tools/memory
.venv/bin/python3 _smoke_hybrid.py   # capabilities/MCP/orchestrator/model router
.venv/bin/python3 _smoke_agent.py    # Agent ReAct loop (offline, fake LLM)
.venv/bin/python3 _smoke_voice.py    # Phase 2: VAD + Vosk model + wake word
.venv/bin/python3 _smoke_phase3.py   # Phase 3: browser/screen/gui + MCP browser
.venv/bin/python3 _smoke_phase4.py   # Phase 4: camera capture + vision model + MCP vision
.venv/bin/python3 _smoke_skills.py   # Phase 7: skills + semantic + FTS5
.venv/bin/python3 _smoke_env.py      # .env config loading and environment precedence
.venv/bin/python3 _smoke_settings.py # terminal + HUD settings and secret handling
.venv/bin/python3 _smoke_security_controls.py # permission levels + terminal/HUD sudo prompts
.venv/bin/python3 _smoke_provider_setup.py # hosted-provider onboarding (offline)
.venv/bin/python3 _smoke_laya_mcp.py # optional Laya MCP safety and approval wiring
.venv/bin/python3 _smoke_web.py      # Web HUD server endpoints (SSE chat/TTS/STT/status)
.venv/bin/python3 _smoke_latency.py  # live latency benchmark (needs Ollama)
```

GitHub Actions runs the offline smoke subset on Python 3.11. Voice-device,
camera, browser-driver, and live-model checks remain local because they require
host hardware, system packages, or downloaded model weights.

## Latency / performance (Turbo mode)
These measurements and tuning notes are from an RTX 3050 Laptop with 4 GB VRAM:
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
