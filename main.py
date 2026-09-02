#!/usr/bin/env python3
"""E.V. — Local Multimodal OS Agent.

Entry point. Wires config, memory, tools, security, and the Agent, then
starts the CLI REPL. Phase 1 MVP: Ollama + Agent Core + Shell/Filesystem +
Memory + CLI.
"""
from __future__ import annotations

import json
import subprocess
import sys
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from models.llm import OllamaClient, LLMError                  # noqa: E402
from memory.long_term import LongTermMemory                    # noqa: E402
from memory.short_term import ShortTermMemory                  # noqa: E402
from memory.episodic import EpisodicMemory                     # noqa: E402
from tools.router import ToolRouter                            # noqa: E402
from tools.mcp.registry import MCPRegistry                     # noqa: E402
from tools.mcp import discovery                                # noqa: E402
from security.permissions import PermissionEngine              # noqa: E402
from security.approval import Approval                         # noqa: E402
from core.context import ContextBuilder                        # noqa: E402
from core.router import ModelRouter                            # noqa: E402
from core.capability_manager import CapabilityManager, Capability  # noqa: E402
from core.tool_router import ToolOrchestrator                  # noqa: E402
from core.agent import Agent                                   # noqa: E402
from ui.cli.repl import CLI                                    # noqa: E402
from tasks.manager import TaskManager                          # noqa: E402


def load_config() -> dict:
    cfg_path = ROOT / "config.json"
    with open(cfg_path, encoding="utf-8") as fh:
        return json.load(fh)


def ensure_dirs(config: dict) -> None:
    Path(config["agent"]["data_dir"]).mkdir(exist_ok=True)
    Path(config["logging"]["dir"]).mkdir(parents=True, exist_ok=True)
    Path(config["memory"]["long_term_db"]).parent.mkdir(exist_ok=True)


def ensure_ollama(host: str) -> bool:
    """Return True if the Ollama API answers; start 'ollama serve' if not."""
    if OllamaClient(host=host, timeout=5).is_available():
        return True
    print("Ollama not running — starting 'ollama serve' in background …")
    try:
        with open("data/logs/ollama.log", "ab") as log:
            subprocess.Popen(["ollama", "serve"], stdout=log, stderr=log,
                             start_new_session=True)
        for _ in range(30):
            if OllamaClient(host=host, timeout=2).is_available():
                return True
            import time
            time.sleep(1)
    except OSError as e:
        print(f"Could not start ollama: {e}")
        return False
    return False


def seed_memory(mem: LongTermMemory, config: dict) -> None:
    a = config.get("agent", {})
    defaults = {
        "user_name": a.get("user_name", "Mahdi"),
        "preferred_language": a.get("language", "Persian"),
        "agent_name": a.get("name", "E.V."),
        "gpu": "NVIDIA GeForce RTX 3050 Laptop (4GB)",
        "os": "Ubuntu (Linux)",
    }
    for k, v in defaults.items():
        if mem.recall(k) is None:
            mem.remember(k, v)


def make_voice_loop(config: dict, agent):
    """Construct the hands-free VoiceLoop from config (Phase 2)."""
    import os
    from pathlib import Path
    # resolve model paths relative to the project root so VoiceLoop works
    # regardless of the caller's current working directory
    root = Path(__file__).resolve().parent

    from voice.session import VoiceLoop
    from voice.stt import VoskSTT, find_model
    from voice.tts import VoiceTTS
    from voice.wakeword import WakeWord
    from voice.vad import VAD

    v = config.get("voice", {})
    stt_model = v.get("stt_model") or find_model()
    if stt_model and not os.path.isabs(stt_model):
        stt_model = str(root / stt_model)

    def status(msg):
        print(f"[voice] {msg}")

    stt = VoskSTT(model_path=stt_model)
    wake = WakeWord(words=tuple(v.get("wake_words", ["e.v", "ای وی"])),
                    stt=stt, vad=VAD(frame_ms=20),
                    sensitivity=int(v.get("wake_sensitivity", 2)))
    piper_model = v.get("tts_piper_model",
                        "data/models/piper/fa_IR-amir-medium.onnx")
    if not os.path.isabs(piper_model):
        piper_model = str(root / piper_model)
    tts = VoiceTTS(backend=v.get("tts_backend", "piper"),
                   model_path=piper_model)
    return VoiceLoop(agent, stt=stt, tts=tts, wake=wake,
                     on_status=status)


def gpu_probe() -> str:
    try:
        out = subprocess.run(["nvidia-smi"], capture_output=True,
                             text=True).stdout
        return out.strip()[:1200]
    except OSError:
        return "nvidia-smi unavailable"


def models_probe(client: OllamaClient) -> str:
    try:
        return "\n".join(client.list_models()) or "(no models pulled)"
    except LLMError as e:
        return f"error: {e}"


def main() -> int:
    config = load_config()
    ensure_dirs(config)

    ollama_cfg = config["ollama"]
    host = ollama_cfg["host"]
    if not ensure_ollama(host):
        print("[FATAL] Could not reach or start Ollama. "
              "Start it manually: ollama serve")
        return 1

    client = OllamaClient(
        host=host,
        model=ollama_cfg.get("default", ollama_cfg["models"]["main"]),
        timeout=ollama_cfg["timeout"],
        cloud_timeout=ollama_cfg.get("cloud_timeout", 45),
        fallback_model=ollama_cfg.get("fallback") or None,
        keep_alive=ollama_cfg.get("keep_alive", "30m"),
        num_predict=ollama_cfg.get("max_tokens", 512),
        num_ctx=ollama_cfg.get("num_ctx", 8192),
        think=ollama_cfg.get("think", False),
    )

    long_mem = LongTermMemory(config["memory"]["long_term_db"])
    seed_memory(long_mem, config)
    short_mem = ShortTermMemory(config["memory"]["short_term_max_messages"])
    episodic = EpisodicMemory(long_mem)

    approval = Approval(confirm=True)
    perm = PermissionEngine(
        auto_approve_until=config["security"]["auto_approve_until_level"],
        approval=approval)

    # GUI sudo: an approved `sudo ...` shell command runs via pkexec so the
    # desktop polkit agent asks for the root password in a graphical dialog.
    from tools.shell import set_sudo_via_pkexec
    set_sudo_via_pkexec(config["security"].get("sudo_via_pkexec", True))

    # ---- hybrid tool layer --------------------------------------- #
    native_router = ToolRouter(workspace=ROOT, perm=perm)
    mcp_registry = MCPRegistry()
    capabilities = CapabilityManager(config)

    # connect any enabled MCP servers found in tools.mcp_dir
    mcp_dir = config.get("tools", {}).get("mcp_dir", "mcp_servers")
    connected = discovery.connect(mcp_registry,
                                  {"mcp": {"servers_dir": mcp_dir}})
    for name in connected:
        # register newly connected servers as capabilities
        cap_client = mcp_registry.clients.get(name)
        if cap_client:
            capabilities.register(Capability(
                name, "mcp", priority=60, provider=name,
                tools=[t.get("name") for t in cap_client.tools_cache],
                needs_approval=True))

    orchestrator = ToolOrchestrator(native_router, mcp_registry,
                                    capabilities, perm=perm)

    # ---- vision (Phase 4) ---------------------------------------- #
    try:
        from models.vision import VisionModel
        from tools.vision import set_vision_model
        vision_model_name = ollama_cfg.get("models", {}).get("vision",
                                                          client.model)
        set_vision_model(VisionModel(client, model=vision_model_name))
    except Exception as e:  # noqa: BLE001
        print(f"[vision] init failed: {e}")

    # ---- dynamic model router (any model present in Ollama) ----------- #
    sel = config.get("model_selection", {})
    model_router = ModelRouter(
        client=client,
        preferred=ollama_cfg["models"],
        mode=sel.get("mode", "auto"),
        fixed=sel.get("fixed"),
        include_cloud=sel.get("include_cloud", True),
    )
    try:
        model_router.refresh()
    except LLMError:
        pass

    context = ContextBuilder(config, long_mem, orchestrator.names())
    agent = Agent(client, orchestrator, context, short_mem, episodic,
                  model_router,
                  max_iterations=config["agent"]["max_react_iterations"],
                  turbo_threshold=config["agent"].get("turbo_threshold", 0.3))

    # Preload the tool-capable local model so the first reply is instant.
    warm_model = model_router.current()
    if not warm_model:
        # default to the main preference if it exists locally, else a
        # sensible pick from the router's pool
        main_pref = ollama_cfg["models"].get("main")
        pool = model_router.pool()
        warm_model = (main_pref if main_pref in pool
                      else (pool[0] if pool else client.model))
    client.warm(warm_model)

    tasks = TaskManager()

    # ---- web HUD (graphical interface) ---------------------------- #
    hud_url = None
    if config.get("web", {}).get("enabled", True):
        try:
            from ui.web.server import start_web
            start_web(agent, config)
            wc = config.get("web", {})
            hud_url = (f"http://{wc.get('host', '127.0.0.1')}"
                       f":{wc.get('port', 8765)}/")
            print(f"[hud] web interface ready at {hud_url}  (/hud to open)")
        except Exception as e:  # noqa: BLE001
            print(f"[hud] web interface failed: {e}")

    cli = CLI(
        agent, config,
        on_remember=long_mem.remember,
        on_episodes=long_mem.episodes,
        on_gpu=gpu_probe,
        on_models=lambda: models_probe(client),
        on_tasks=tasks.all,
        on_model_router=model_router,
        on_model_list=lambda: client.list_models() if client else [],
        on_capabilities=lambda: orchestrator.capabilities_summary(),
        on_tools=lambda: orchestrator.names(),
        on_voice=lambda: make_voice_loop(config, agent).run(),
        on_hud=(lambda: webbrowser.open(hud_url)) if hud_url else None,
    )
    cli.run()
    mcp_registry.close_all()
    try:
        from tools.browser import _cleanup
        _cleanup()
    except Exception:  # noqa: BLE001
        pass
    long_mem.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
