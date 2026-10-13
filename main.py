#!/usr/bin/env python3
"""E.V. — Local Multimodal OS Agent.

Entry point. Wires config, memory, tools, security, and the Agent, then
starts the CLI REPL. Phase 1 MVP: Ollama + Agent Core + Shell/Filesystem +
Memory + CLI.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import webbrowser
from contextlib import ExitStack
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from models.llm import (LLMError, OllamaClient, ProviderClient,
                        create_provider,
                        select_provider_instances)                # noqa: E402
from memory.long_term import LongTermMemory                    # noqa: E402
from memory.short_term import ShortTermMemory                  # noqa: E402
from memory.episodic import EpisodicMemory                     # noqa: E402
from tools.router import ToolRouter                            # noqa: E402
from tools.base import Tool                                    # noqa: E402
from tools.mcp.registry import MCPRegistry                     # noqa: E402
from tools.mcp import discovery                                # noqa: E402
from tools.mcp.installer import (install_github_server,
                                list_installed_servers,
                                set_server_enabled)               # noqa: E402
from security.permissions import PermissionEngine              # noqa: E402
from security.approval import Approval                         # noqa: E402
from core.context import ContextBuilder                        # noqa: E402
from core.router import ModelRouter                            # noqa: E402
from core.capability_manager import CapabilityManager           # noqa: E402
from core.tool_router import ToolOrchestrator                  # noqa: E402
from core.agent import Agent                                   # noqa: E402
from ui.cli.repl import CLI                                    # noqa: E402
from tasks.manager import TaskManager                          # noqa: E402
from tasks.scheduler import Scheduler                          # noqa: E402
from tasks.queue import EventDrivenTaskQueue                   # noqa: E402
from sensors.event_bus import EventBus                         # noqa: E402
from sensors.system_monitor import SystemMonitor               # noqa: E402
from sensors.gpu_monitor import GPUMonitor                     # noqa: E402
from core.briefing import build_brief                             # noqa: E402
from ui.telegram import TelegramGateway                        # noqa: E402
from skills import SkillEngine, SkillStore                    # noqa: E402
from skills import tools as skill_tools                        # noqa: E402
from memory.embeddings import Embedder                     # noqa: E402
from memory.semantic import SemanticMemory                  # noqa: E402
from core.settings import SettingsStore                       # noqa: E402


def _read_env_file(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    values = {}
    for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        name, separator, value = line.partition("=")
        if not separator or not name.strip():
            raise ValueError(f"Invalid .env entry at {path}:{line_number}")
        values[name.strip()] = value.strip()
    return values


def _env_value(raw: str):
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
            return raw[1:-1]
        return raw


def _set_config_value(config: dict, path: list[str], value) -> None:
    current = config
    for part in path[:-1]:
        key = next((key for key in current
                    if key.casefold() == part.casefold()), None)
        if key is None or not isinstance(current[key], dict):
            raise ValueError(f"Unknown .env config path: EV__{'__'.join(path)}")
        current = current[key]
    key = next((key for key in current
                if key.casefold() == path[-1].casefold()), None)
    if key is None:
        raise ValueError(f"Unknown .env config path: EV__{'__'.join(path)}")
    current[key] = value


def load_config(config_path: Path | None = None,
                env_path: Path | None = None,
                environ: dict[str, str] | None = None) -> dict:
    cfg_path = config_path or ROOT / "config.json"
    with open(cfg_path, encoding="utf-8") as fh:
        config = json.load(fh)

    environment = os.environ if environ is None else environ
    env_values = _read_env_file(env_path or ROOT / ".env")
    for name, raw in env_values.items():
        if not name.startswith("EV__"):
            environment.setdefault(name, str(_env_value(raw)))

    names = set(env_values)
    names.update(name for name in environment if name.startswith("EV__"))
    for name in names:
        if not name.startswith("EV__"):
            continue
        raw = environment.get(name, env_values.get(name))
        if raw is not None:
            _set_config_value(config, name[4:].split("__"), _env_value(raw))
    return config


def ensure_dirs(config: dict) -> None:
    Path(config["agent"]["data_dir"]).mkdir(parents=True, exist_ok=True)
    Path(config["logging"]["dir"]).mkdir(parents=True, exist_ok=True)
    Path(config["memory"]["long_term_db"]).parent.mkdir(
        parents=True, exist_ok=True)


def ensure_ollama(host: str) -> bool:
    """Return True if the Ollama API answers; start 'ollama serve' if not."""
    if OllamaClient(host=host, timeout=5).is_available():
        return True
    print("Ollama not running — starting 'ollama serve' in background …")
    try:
        log_path = ROOT / "data" / "logs" / "ollama.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("ab") as log:
            subprocess.Popen(["ollama", "serve"], stdout=log, stderr=log,
                             start_new_session=True)
        for _ in range(30):
            if OllamaClient(host=host, timeout=2).is_available():
                return True
            time.sleep(1)
    except OSError as e:
        print(f"Could not start ollama: {e}")
        return False
    return False


def seed_memory(mem: LongTermMemory, config: dict) -> None:
    a = config.get("agent", {})
    defaults = {
        "user_name": a.get("user_name", "User"),
        "preferred_language": a.get("language", "auto"),
        "agent_name": a.get("name", "E.V."),
    }
    for k, v in defaults.items():
        if mem.recall(k) is None:
            mem.remember(k, v)


def make_voice_loop(config: dict, agent):
    """Construct the hands-free VoiceLoop from config (Phase 2)."""
    # resolve model paths relative to the project root so VoiceLoop works
    # regardless of the caller's current working directory
    from voice.session import VoiceLoop
    from voice.stt import VoskSTT, find_model
    from voice.tts import VoiceTTS
    from voice.router import SpeechRouter
    from voice.wakeword import WakeWord
    from voice.vad import VAD
    from voice.config import normalize_voice_config

    v = normalize_voice_config({"voice": config.get("voice", {})})["voice"]
    speech = SpeechRouter(v, data_root=ROOT / "data" / "models")
    wake_language = v.get("wake_language", "fa")
    wake_models = speech.available_vosk_models()
    wake_model = wake_models.get(wake_language) or v.get("stt_model") or find_model(
        ROOT / "data" / "models")
    if wake_model and not Path(wake_model).is_absolute():
        wake_model = str(ROOT / wake_model)
    wake_stt = VoskSTT(model_path=wake_model)

    def status(msg):
        print(f"[voice] {msg}")

    wake = WakeWord(words=tuple(v.get("wake_words", ["e.v", "ای وی"])),
                    stt=wake_stt,
                    vad=VAD(mode=v.get("vad_mode", "energy"),
                            frame_ms=int(v.get("vad_frame_ms", 20)),
                            threshold=float(v.get("vad_threshold", 180))),
                    sensitivity=int(v.get("wake_sensitivity", 2)))
    tts = VoiceTTS(config=v, data_root=ROOT / "data" / "models")
    return VoiceLoop(agent, stt=speech, tts=tts, wake=wake,
                     on_status=status)


def gpu_probe() -> str:
    try:
        out = subprocess.run(["nvidia-smi"], capture_output=True,
                             text=True, timeout=3, check=False).stdout
        return out.strip()[:1200]
    except (OSError, subprocess.SubprocessError):
        return "nvidia-smi unavailable"


def models_probe(client: ProviderClient) -> str:
    try:
        return "\n".join(client.list_models()) or "(no models pulled)"
    except LLMError as e:
        return f"error: {e}"


def _provider_credentials_configured(settings: dict) -> bool:
    env_name = settings.get("api_key_env")
    return (not env_name or bool(settings.get("api_key")
                                 or os.getenv(str(env_name))))


def due_task_notification(task) -> str | None:
    if task.description.startswith("Check high CPU load alert"):
        return None
    missed = (f" ({task.due_count} occurrences, including missed runs)"
              if task.due_count > 1 else "")
    return (f"\n[task due] {task.id}: {task.description}{missed} "
            f"— run it with /run {task.id}")


def main() -> int:
    with ExitStack() as cleanup:
        return _run(cleanup)


def _run(cleanup: ExitStack) -> int:
    from voice.config import normalize_voice_config
    config = normalize_voice_config(load_config())
    settings_store = SettingsStore(config, ROOT / ".env")
    ensure_dirs(config)
    from voice.installer import VoiceInstallManager
    from voice.secrets import VoiceSecretStore
    voice_installer = VoiceInstallManager(ROOT)
    voice_secrets = VoiceSecretStore(
        ROOT / "data" / "voice" / "secrets.json")

    ollama_cfg = config["ollama"]
    host = ollama_cfg["host"]
    operating_mode = str(config.get("operating_mode", "local")).casefold()
    cloud_text_allowed = bool(config.get("cloud", {}).get("allow_text", False))
    provider_mode = operating_mode
    if operating_mode == "local" or (operating_mode == "hybrid"
                                      and not cloud_text_allowed):
        provider_mode = "local"
    if operating_mode == "cloud" and not cloud_text_allowed:
        print("[privacy] Cloud-only needs explicit text-processing consent; "
              "using local-only routing.")
        provider_mode = "local"
    default_model = ollama_cfg.get("default", ollama_cfg["models"]["main"])
    if provider_mode == "local" and "cloud" in str(default_model).casefold():
        default_model = ollama_cfg["models"]["main"]
    ollama_client = OllamaClient(
        host=host,
        model=default_model,
        timeout=ollama_cfg["timeout"],
        cloud_timeout=ollama_cfg.get("cloud_timeout", 45),
        fallback_model=ollama_cfg.get("fallback") or None,
        keep_alive=ollama_cfg.get("keep_alive", "30m"),
        num_predict=ollama_cfg.get("max_tokens", 512),
        num_ctx=ollama_cfg.get("num_ctx", 8192),
        think=ollama_cfg.get("think", False),
    )

    provider_cfg = config.get("providers", {})
    provider_instances = select_provider_instances(
        provider_cfg.get("instances", {}), provider_mode)
    default_provider = provider_cfg.get("default", "ollama")
    if ":" in default_provider:
        default_provider = default_provider.split(":", 1)[0]
    if provider_mode == "local" and default_provider not in provider_instances:
        default_provider = "ollama"
    if (operating_mode == "cloud"
            and (default_provider not in provider_instances
                 or provider_instances.get(default_provider, {}).get("type", default_provider)
                 == "ollama")):
        print("[privacy] No configured remote text provider for Cloud-only; "
              "using local-only routing.")
        provider_mode = "local"
        provider_instances = select_provider_instances(
            provider_cfg.get("instances", {}), "local")
        default_provider = "ollama"
    clients = {}
    for name, provider_settings in provider_instances.items():
        if not _provider_credentials_configured(provider_settings):
            continue
        provider_type = provider_settings.get("type", name)
        if provider_type == "ollama":
            clients[name] = ollama_client
        else:
            try:
                clients[name] = create_provider(provider_type, provider_settings)
            except LLMError as e:
                print(f"[provider:{name}] unavailable: {e}")
    if not clients:
        clients["ollama"] = ollama_client
    if default_provider not in clients:
        print(f"[FATAL] Default provider is not configured: {default_provider}")
        return 1
    if default_provider == "ollama" and not ensure_ollama(host):
        print("[FATAL] Could not reach or start Ollama. "
              "Start it manually: ollama serve")
        return 1
    configured_models = {
         name: ([provider_settings["model"]]
             if provider_settings.get("model") else [])
         for name, provider_settings in provider_instances.items()
         if (provider_settings.get("type", name) != "ollama"
             and _provider_credentials_configured(provider_settings))
    }
    client = ProviderClient(clients, default_provider, configured_models)

    long_mem = LongTermMemory(config["memory"]["long_term_db"])
    cleanup.callback(long_mem.close)
    seed_memory(long_mem, config)
    short_mem = ShortTermMemory(config["memory"]["short_term_max_messages"])
    episodic = EpisodicMemory(long_mem)

    # ---- semantic memory (Phase 7): hash embeddings always; true neural
    # embeddings automatically when a local Ollama embed model is present.
    sem_cfg = config.get("memory", {}).get("semantic", {})
    embedder = Embedder(host=ollama_cfg["host"],
                        model=sem_cfg.get("embed_model", "nomic-embed-text"))
    semantic = SemanticMemory(embedder=embedder)
    long_mem.attach_semantic(semantic)
    print(f"[memory] semantic embeddings: {embedder.model}"
          f"{' (neural)' if embedder.neural else ' (hash fallback)'}")

    approval = Approval(confirm=True)
    perm = PermissionEngine(
        auto_approve_until=config["security"]["auto_approve_until_level"],
        approval=approval, config=config)

    # GUI sudo: an approved `sudo ...` shell command runs via pkexec so the
    # desktop polkit agent asks for the root password in a graphical dialog.
    from tools.shell import set_sudo_via_pkexec
    set_sudo_via_pkexec(config)

    # ---- hybrid tool layer --------------------------------------- #
    native_router = ToolRouter(workspace=ROOT, perm=perm)
    from tools.browser import _cleanup as cleanup_browser
    cleanup.callback(cleanup_browser)

    native_router.register(Tool(
        name="session_search",
        description="Search saved user and assistant messages across past sessions.",
        parameters={"type": "object", "properties": {
            "query": {"type": "string", "description": "Words to search for"},
            "session_id": {"type": "string", "description": "Optional session ID"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 20},
        }},
        required=["query"],
        fn=lambda query, session_id=None, limit=10, **_: {
            "ok": True,
            "results": long_mem.search_session_messages(
                query, session_id=session_id, limit=limit),
        },
    ))
    mcp_registry = MCPRegistry()
    cleanup.callback(mcp_registry.close_all)
    capabilities = CapabilityManager(config)

    # connect any enabled MCP servers found in tools.mcp_dir
    mcp_dir = config.get("tools", {}).get("mcp_dir", "mcp_servers")
    mcp_servers_dir = Path(mcp_dir)
    if not mcp_servers_dir.is_absolute():
        mcp_servers_dir = ROOT / mcp_servers_dir
    connected = discovery.connect(mcp_registry,
                                  {"mcp": {"servers_dir": str(mcp_servers_dir)}})
    for name in connected:
        cap_client = mcp_registry.clients.get(name)
        if cap_client:
            capabilities.register_mcp_server(
                name, [tool.get("name") for tool in cap_client.tools_cache
                       if tool.get("name")])

    orchestrator = ToolOrchestrator(native_router, mcp_registry,
                                    capabilities, perm=perm)

    # ---- skills (Phase 7): the self-improvement loop -------------- #
    skill_store = SkillStore(str(ROOT / "data" / "skills.json"))
    skill_engine = SkillEngine(skill_store, llm=client,
                               router=orchestrator,
                               top_k=int(sem_cfg.get("skills_top_k", 5)))
    skill_tools.register(skill_engine)
    print(f"[skills] {skill_store.count()} skill(s) loaded")

    # index long-term facts into the semantic index so recall improves
    # every session (episodes are indexed as they are recorded).
    for key, value in long_mem.all_facts().items():
        semantic.add(f"{key}: {value}", kind="fact")
    try:
        from models.vision import VisionModel
        from tools.vision import set_vision_model
        if OllamaClient(host=host, timeout=2).is_available():
            vision_model_name = ollama_cfg.get("models", {}).get(
                "vision", ollama_client.model)
            set_vision_model(VisionModel(ollama_client,
                                         model=vision_model_name))
    except Exception as e:  # noqa: BLE001
        print(f"[vision] init failed: {e}")

    # ---- dynamic model router (models exposed by configured providers) ---- #
    sel = config.get("model_selection", {})
    if provider_mode == "local":
        model_mode, fixed_model = "auto", None
        preferred_models = ollama_cfg.get("models", {})
        include_cloud = False
    else:
        model_mode = sel.get("mode", "auto")
        fixed_model = sel.get("fixed")
        preferred_models = provider_cfg.get("preferred", ollama_cfg["models"])
        include_cloud = sel.get("include_cloud", False)
    model_router = ModelRouter(
        client=client,
        preferred=preferred_models,
        mode=model_mode,
        fixed=fixed_model,
        include_cloud=include_cloud,
    )
    try:
        model_router.refresh()
    except LLMError as exc:
        print(f"[model-router] refresh skipped: {exc}")

    context = ContextBuilder(config, long_mem, orchestrator.names())
    context.attach_skills(skill_engine)
    agent = Agent(client, orchestrator, context, short_mem, episodic,
                  model_router,
                  max_iterations=config["agent"]["max_react_iterations"],
                  turbo_threshold=config["agent"].get("turbo_threshold", 0.3),
                  skills=skill_engine)

    # Preload the tool-capable local model so the first reply is instant.
    local_models = []
    try:
        local_models = ollama_client.list_models()
    except LLMError as exc:
        print(f"[model] local model listing failed: {exc}")
    preferred_local = ollama_cfg["models"].get("main")
    warm_model = (preferred_local if preferred_local in local_models
                  else (local_models[0] if local_models else None))
    if warm_model:
        try:
            ollama_client.warm(warm_model)
        except LLMError as exc:
            print(f"[model] local warm-up skipped: {exc}")
    else:
        print("[model] local warm-up skipped: no Ollama model available")

    telegram = TelegramGateway.from_environment(agent)
    if telegram:
        telegram.start()
        cleanup.callback(telegram.stop)
        print("[telegram] private control gateway started")
    elif os.getenv("TELEGRAM_BOT_TOKEN"):
        print("[telegram] disabled: set TELEGRAM_ALLOWED_USER_IDS")

    tasks = TaskManager(store=str(ROOT / "data" / "tasks.json"))

    def task_due(task):
        notification = due_task_notification(task)
        if notification:
            print(notification, flush=True)

    scheduler = Scheduler(tasks, on_due=task_due)
    scheduler.start()
    cleanup.callback(scheduler.stop)

    local_bus = EventBus()
    proactive_queue = EventDrivenTaskQueue(tasks, scheduler)
    proactive_queue.subscribe(local_bus)
    system_monitor = SystemMonitor(local_bus, poll_seconds=5.0)
    system_monitor.start()
    cleanup.callback(system_monitor.stop)
    gpu_monitor = GPUMonitor(local_bus, threshold=85, poll_seconds=6.0)
    gpu_monitor.start()
    cleanup.callback(gpu_monitor.stop)

    # ---- web HUD (graphical interface) ---------------------------- #
    hud_url = None
    if config.get("web", {}).get("enabled", True):
        try:
            from ui.web.server import start_web
            start_web(agent, config, briefing=lambda system=None:
                      build_brief(tasks.all(), system=system, mcp=mcp_registry),
                      settings=settings_store,
                      voice_installer=voice_installer,
                      voice_secrets=voice_secrets)
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
        on_schedule=lambda task_id, delay, interval=None:
            scheduler.schedule(task_id, delay, interval),
        on_task_new=tasks.new,
        on_cancel_schedule=scheduler.cancel,
        on_run_task=lambda task_id: run_task(agent, tasks, task_id),
        on_model_router=model_router,
        on_model_list=lambda: client.list_models() if client else [],
        on_capabilities=lambda: orchestrator.capabilities_summary(),
        on_tools=lambda: orchestrator.names(),
        on_skills=lambda: skill_store.list(),
        on_skill_run=lambda sid: skill_engine.run_skill(sid),
        on_skill_create=lambda name, goal, steps=None:
            skill_store.create(name, goal, steps=steps),
        on_skill_delete=skill_store.delete,
        on_voice=lambda: make_voice_loop(config, agent).run(),
        on_voice_setup=lambda: _voice_setup(
            config, settings_store, voice_installer, voice_secrets),
        on_voice_doctor=lambda: _voice_doctor(
            config, voice_installer, voice_secrets),
        on_brief=lambda: build_brief(tasks.all(), mcp=mcp_registry),
        on_hud=(lambda: webbrowser.open(hud_url)) if hud_url else None,
        on_settings=settings_store.snapshot,
        on_settings_update=settings_store.update_config,
        on_credentials_update=settings_store.update_credentials,
        on_mcp_list=lambda: list_installed_servers(mcp_servers_dir),
        on_mcp_install=lambda url: install_github_server(
            url, mcp_servers_dir),
        on_mcp_enable=lambda sid: set_server_enabled(
            mcp_servers_dir, sid, True),
        on_mcp_disable=lambda sid: set_server_enabled(
            mcp_servers_dir, sid, False),
    )
    cli.run()
    return 0


def _voice_setup(config: dict, settings_store, installer, secrets_store) -> dict:
    from voice.setup import run_setup_wizard
    return run_setup_wizard(config, installer, secrets_store,
                            update_config=settings_store.update_config)


def _voice_doctor(config: dict, installer, secrets_store) -> dict:
    from voice.hardware import detect_hardware, recommend_configuration
    voice_cfg = config.get("voice", {})
    report = detect_hardware(ROOT / "data" / "models")
    recommendation = recommend_configuration(
        report, languages=voice_cfg.get("languages", ["fa"]),
        purpose=voice_cfg.get("purpose", "assistant"),
        budget=voice_cfg.get("budget_preference", "minimum_cost"))
    return {"hardware": report, "recommendation": recommendation,
            "installations": installer.inventory(),
            "credentials": secrets_store.status(),
            "routing": {"operating_mode": config.get("operating_mode", "local"),
                        "audio_upload_allowed": bool(
                            voice_cfg.get("allow_cloud_audio")),
                        "live_enabled": bool(
                            config.get("live", {}).get("enabled"))}}


def run_task(agent, tasks: TaskManager, task_id: str) -> str:
    task = tasks.get(task_id)
    if task is None:
        return f"Task not found: {task_id}"
    if task.status == "running":
        return f"Task is already running: {task_id}"
    tasks.update(task_id, status="running")
    tasks.add_step(task_id, "started", "running")
    try:
        result = agent.run(task.description)
    except Exception as exc:  # keep failures visible in the durable task record
        tasks.update(task_id, status="failed",
                     result={"error": str(exc)})
        tasks.add_step(task_id, "failed", str(exc)[:240])
        return f"Task failed: {exc}"
    tasks.update(task_id, status="done", result={"answer": result})
    tasks.add_step(task_id, "completed", "done")
    return result


if __name__ == "__main__":
    sys.exit(main())
