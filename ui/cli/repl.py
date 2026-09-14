"""CLI REPL — the text gateway to E.V. (architecture §1)."""
from __future__ import annotations

import shlex
import time

from core.agent import Agent


class CLI:
    def __init__(self, agent, config, on_exit=None, on_remember=None,
                 on_episodes=None, on_gpu=None, on_models=None, on_tasks=None,
                 on_model_router=None, on_model_list=None,
                 on_capabilities=None, on_tools=None, on_voice=None,
                 on_hud=None):
        self.agent = agent
        self.config = config
        self._exit = on_exit
        self._remember = on_remember
        self._episodes = on_episodes
        self._gpu = on_gpu
        self._models = on_models
        self._tasks = on_tasks
        self._model_router = on_model_router
        self._model_list = on_model_list
        self._capabilities = on_capabilities
        self._tools = on_tools
        self._voice_runfunc = on_voice
        self._hud = on_hud
        self.running = True

    def _print_banner(self):
        name = self.config.get("agent", {}).get("name", "E.V.")
        print("=" * 56)
        print(f"  {name} — Local Multimodal OS Agent   (type /help)")
        print("=" * 56)

    def _dispatch_slash(self, line: str) -> bool:
        parts = shlex.split(line)
        cmd = parts[0].lower()
        if cmd in ("/exit", "/quit", "/q"):
            self.running = False
            return True
        if cmd == "/help":
            self._help()
            return True
        if cmd == "/clear":
            self.agent.memory.clear()
            print("Conversation cleared.")
            return True
        if cmd == "/gpu":
            print(self._gpu() if self._gpu else "gpu probe unavailable")
            return True
        if cmd == "/models":
            print(self._models() if self._models else "models probe unavailable")
            return True
        if cmd == "/remember" and len(parts) >= 3 and self._remember:
            self._remember(parts[1], " ".join(parts[2:]))
            print(f"remembered {parts[1]}")
            return True
        if cmd == "/episodes" and self._episodes:
            for ep in self._episodes(10):
                print(f"- {ep['summary'][:120]}")
            return True
        if cmd == "/tasks" and self._tasks:
            for t in self._tasks():
                print(f"[{t.id}] {t.status}: {t.description}")
            return True
        if cmd == "/capabilities" and self._capabilities:
            print("\n".join(self._capabilities()))
            return True
        if cmd == "/tools" and self._tools:
            print("Tools: " + ", ".join(self._tools()))
            return True
        if cmd == "/model":
            self._toggle_model(parts)
            return True
        if cmd in ("/voice", "/hear"):
            self._start_voice()
            return True
        if cmd == "/hud":
            if self._hud:
                self._hud()
            else:
                print("HUD unavailable (web server not running)")
            return True
        return False

    def _start_voice(self) -> None:
        """Start the hands-free voice loop (wake word -> STT -> agent -> TTS)."""
        if self._voice_runfunc is not None:
            print("Starting voice loop… (say 'ای وی' / 'E.V.', then talk)")
            try:
                self._voice_runfunc()
            except Exception as e:  # noqa: BLE001
                print(f"[voice] error: {e}")
        else:
            print("voice loop unavailable (no voice components wired)")

    def _toggle_model(self, parts) -> None:
        router = self._model_router
        if not router:
            print("model router unavailable")
            return
        if len(parts) == 1:
            print(f"current: {router.current() or 'auto'}")
            print("pool: " + (", ".join(router.pool()) or "(none)"))
            return
        action = parts[1].lower()
        if action == "auto":
            router.set_override(None)
            router.mode = "auto"
            print("model selection: auto")
        elif action == "list":
            models = self._model_list() if self._model_list else []
            print(("\n".join(models)) if models else "(no models)")
        else:
            router.set_override(action)
            router.mode = "fixed"
            print(f"model: {action}")

    def _help(self):
        print("""
Commands:
  <free text>     talk to E.V. (ReAct + tools)
  /gpu            GPU status            /models     show ollama models
  /model [name]   show/set model (auto|list|<name>)
  /capabilities   native + MCP capabilities
  /tools          list of available tools (native + MCP)
  /remember k v   store a fact          /episodes   recent episodic memory
  /tasks          list tasks             /clear     reset conversation
  /hud            open the graphical web HUD (browser)
  /help           this help              /exit      quit
""")

    def run(self):
        self._print_banner()
        while self.running:
            try:
                line = input("\nev> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not line:
                continue
            if line.startswith("/"):
                self._dispatch_slash(line)
                continue
            try:
                t0 = time.time()
                first = [True]

                def _on_stream(delta: str) -> None:
                    if first[0]:
                        print()
                        first[0] = False
                    print(delta, end="", flush=True)

                def _brief_result(result) -> str:
                    """Compact, human summary of a tool result for the live feed."""
                    if not isinstance(result, dict):
                        s = str(result); return s[:120]
                    if result.get("blocked"):
                        return "مسدود شد: " + str(result.get("error") or "")[:110]
                    if result.get("error"):
                        return "خطا: " + str(result["error"])[:110]
                    desc = result.get("description")
                    if isinstance(desc, str) and desc.strip():
                        return desc.strip()[:110]
                    if result.get("exit_code") is not None:
                        tail = ""
                        for k in ("stderr", "stdout"):
                            v = str(result.get(k) or "").strip()
                            if v:
                                tail = v.splitlines()[-1][:80]
                                break
                        return f"exit={result['exit_code']} {tail}".strip()[:130]
                    if "entries" in result:
                        n = result["entries"]
                        return f"{len(n) if isinstance(n, (list, dict)) else '?'} مورد یافت شد"
                    s = str(result)
                    return s[:120]

                def _on_step(info: dict) -> None:
                    """Live progress during tool work: announce BEFORE the tool
                    runs (phase=start) and briefly summarize AFTER (phase=done.."""
                    phase = info.get("phase")
                    tool = info.get("tool", "")
                    if phase == "start":
                        msg = info.get("message") or f"الان دارم «{tool}» را اجرا می‌کنم..."
                        print(f"\n⚙️ {msg}", flush=True)
                    elif phase == "progress":
                        msg = info.get("message") or "هنوز در حال انجام..."
                        print(f"\n⏳ {msg}", flush=True)
                    else:
                        tail = _brief_result(info.get("result"))
                        mark = "✅" if phase == "done" else "⚙️"
                        print(f"{mark} [{tool}] {tail}", flush=True)

                answer = self.agent.run(line, on_stream=_on_stream,
                                         on_step=_on_step)
                if first[0]:
                    print("\n" + answer)
                else:
                    print()
                print(f"\n[inferred in {time.time()-t0:.1f}s]")
            except KeyboardInterrupt:
                print("\n(interrupted)")
