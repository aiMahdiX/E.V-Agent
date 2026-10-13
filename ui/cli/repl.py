"""CLI REPL — the text gateway to E.V. (architecture §1)."""
from __future__ import annotations

import shlex
import re
import time
import json
import getpass

from core.agent import Agent
from tools.mcp.installer import MCPInstallError


class CLI:
    def __init__(self, agent, config, on_exit=None, on_remember=None,
                 on_episodes=None, on_gpu=None, on_models=None, on_tasks=None,
                 on_model_router=None, on_model_list=None,
                 on_capabilities=None, on_tools=None, on_voice=None,
                 on_hud=None, on_schedule=None, on_cancel_schedule=None,
                 on_run_task=None, on_task_new=None, on_integrations=None,
                 on_brief=None, on_skills=None, on_skill_run=None,
                 on_skill_create=None, on_skill_delete=None, on_settings=None,
                 on_settings_update=None, on_credentials_update=None,
                 on_mcp_list=None, on_mcp_install=None, on_mcp_enable=None,
                 on_mcp_disable=None, on_voice_setup=None,
                 on_voice_doctor=None):
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
        self._integrations = on_integrations
        self._brief = on_brief
        self._voice_runfunc = on_voice
        self._hud = on_hud
        self._schedule = on_schedule
        self._cancel_schedule = on_cancel_schedule
        self._run_task = on_run_task
        self._task_new = on_task_new
        self._skills = on_skills
        self._skill_run = on_skill_run
        self._skill_create = on_skill_create
        self._skill_delete = on_skill_delete
        self._settings = on_settings
        self._settings_update = on_settings_update
        self._credentials_update = on_credentials_update
        self._mcp_list = on_mcp_list
        self._mcp_install = on_mcp_install
        self._mcp_enable = on_mcp_enable
        self._mcp_disable = on_mcp_disable
        self._voice_setup = on_voice_setup
        self._voice_doctor = on_voice_doctor
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
        if cmd == "/skills":
            return self._skills_command(parts)
        if cmd == "/mcp":
            return self._mcp_command(parts)
        if cmd == "/tasks" and self._tasks:
            for t in self._tasks():
                print(f"[{t.id}] {t.status}: {t.description}")
            return True
        if cmd == "/schedules" and self._tasks:
            scheduled = [t for t in self._tasks()
                         if t.next_run_at is not None or t.status == "due"]
            if not scheduled:
                print("No active schedules.")
            for task in scheduled:
                when = (time.strftime("%Y-%m-%d %H:%M:%S",
                                      time.localtime(task.next_run_at))
                        if task.next_run_at else "Due now")
                print(f"[{task.id}] {when} | {task.description} "
                      f"(due={task.due_count})")
            return True
        if cmd == "/schedule":
            self._schedule_task(parts)
            return True
        if cmd == "/cancel" and len(parts) == 2:
            cancelled = (self._cancel_schedule(parts[1])
                         if self._cancel_schedule else False)
            print("Schedule cancelled." if cancelled
                else "Schedule not found.")
            return True
        if cmd == "/run" and len(parts) == 2:
            if self._run_task:
                print(self._run_task(parts[1]))
            else:
                print("Task execution is unavailable.")
            return True
        if cmd == "/capabilities" and self._capabilities:
            print("\n".join(self._capabilities()))
            return True
        if cmd == "/tools" and self._tools:
            print("Tools: " + ", ".join(self._tools()))
            return True
        if cmd == "/integrations" and self._integrations:
            print("Integrations: " + ", ".join(self._integrations()))
            return True
        if cmd == "/settings":
            self._settings_command(line)
            return True
        if cmd in {"/permission", "/permissions"}:
            self._permission_command(parts)
            return True
        if cmd == "/brief":
            result = self._brief() if self._brief else None
            if not result:
                print("Briefing unavailable.")
            else:
                print(result.get("summary", result) if isinstance(result, dict)
                      else result)
                for task in (result.get("tasks", []) if isinstance(result, dict) else [])[:5]:
                    print(f"- [{task.get('priority', 'medium')}] "
                          f"{task.get('title', 'Untitled')}")
            return True
        if cmd == "/model":
            self._toggle_model(parts)
            return True
        if cmd in ("/voice", "/hear"):
            return self._voice_command(parts)
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
            print("Starting voice loop… (say 'E.V.', then talk)")
            try:
                self._voice_runfunc()
            except Exception as e:  # noqa: BLE001
                print(f"[voice] error: {e}")
        else:
            print("voice loop unavailable (no voice components wired)")

    def _voice_command(self, parts: list[str]) -> bool:
        action = parts[1].casefold() if len(parts) > 1 else "start"
        if action == "start":
            self._start_voice()
        elif action == "setup":
            if self._voice_setup is None:
                print("Voice setup is unavailable.")
            else:
                self._voice_setup()
        elif action in {"doctor", "diagnose"}:
            if self._voice_doctor is None:
                print("Voice diagnostics are unavailable.")
            else:
                print(json.dumps(self._voice_doctor(), ensure_ascii=False,
                                 indent=2))
        else:
            print("Usage: /voice [start | setup | doctor]")
        return True

    def _settings_command(self, line: str) -> None:
        if self._settings is None:
            print("Settings are unavailable.")
            return
        try:
            parts = shlex.split(line)
            if len(parts) == 1:
                snapshot = self._settings()
                print("Sections: " + ", ".join(snapshot["config"]))
                for connection in snapshot["connections"]:
                    state = "configured" if connection["configured"] else "not configured"
                    print(f"- {connection['label']}: {state}")
                    print("/settings show <section> | /settings set <path> <value> | "
                        "/settings secret <environment-variable>")
                return
            action = parts[1].lower()
            if action == "show" and len(parts) == 3:
                snapshot = self._settings()
                section = parts[2]
                if section == "integrations":
                    print(json.dumps(snapshot["connections"], ensure_ascii=False,
                                     indent=2))
                elif section in snapshot["config"]:
                    print(json.dumps(snapshot["config"][section],
                                     ensure_ascii=False, indent=2))
                else:
                    print(f"Settings section not found: {section}")
                return
            if action == "set" and self._settings_update and len(parts) >= 4:
                match = re.match(r"^/settings\s+set\s+\S+\s+(.+)$", line.strip())
                if match is None:
                    raise ValueError("Enter a settings value")
                path = parts[2]
                if path.startswith("EV__"):
                    path = ".".join(path[4:].lower().split("__"))
                raw = match.group(1).strip()
                try:
                    value = json.loads(raw)
                except json.JSONDecodeError:
                    value = raw
                self._settings_update({path: value})
                print("Saved and applied." if path in {
                    "security.auto_approve_until_level",
                    "security.sudo_via_pkexec",
                }
                      else "Saved. Restart E.V. to apply this setting.")
                return
            if action == "secret" and self._credentials_update and len(parts) == 3:
                value = getpass.getpass(f"{parts[2]} (empty = clear): ")
                self._credentials_update({parts[2]: value})
                print("Secret saved. Its value is never displayed.")
                return
            print("Usage: /settings | /settings show <section> | "
                "/settings set <path> <value> | /settings secret <environment-variable>")
        except (KeyError, ValueError, TypeError) as exc:
            print(f"Settings error: {exc}")

    def _permission_command(self, parts: list[str]) -> None:
        if self._settings is None:
            print("Permission settings are unavailable.")
            return
        try:
            if len(parts) == 3 and parts[1].casefold() == "set":
                try:
                    level = int(parts[2])
                except ValueError as exc:
                    raise ValueError("Level must be an integer from 0 to 4.") from exc
                if not 0 <= level <= 4:
                    raise ValueError("Level must be between 0 and 4.")
                if self._settings_update is None:
                    raise ValueError("Permission settings are read-only.")
                self._settings_update({
                    "security.auto_approve_until_level": level,
                })
                print(f"Auto-approval limit set to Level {level} (applies immediately).")
                print("Levels 3 and 4 always require explicit approval; sudo always asks for your system password.")
                return
            if len(parts) != 1:
                raise ValueError("Usage: /permission [set 0..4]")
            snapshot = self._settings()
            config = snapshot["config"]
            security = config.get("security", {})
            current = security.get("auto_approve_until_level", 2)
            print(f"Automatic approval currently extends through Level {current}.")
            print("0 Safe/read-only | 1 Workspace writes | 2 System actions")
            print("3 Privileged | 4 Destructive")
            print("Levels 3 and 4 always require explicit approval. sudo commands also require system authentication.")
            print("Set with /permission set <0..4>.")
        except (KeyError, ValueError, TypeError) as exc:
            print(f"Permission settings error: {exc}")

    @staticmethod
    def _duration(text: str) -> int:
        match = re.fullmatch(r"(\d+)(s|m|h|d)", text.lower())
        if not match:
            raise ValueError("Enter a duration such as 30s, 10m, 2h, or 1d")
        amount = int(match.group(1))
        scale = {"s": 1, "m": 60, "h": 3600, "d": 86400}[match.group(2)]
        seconds = amount * scale
        if seconds < 1 or seconds > 365 * 86400:
            raise ValueError("Duration must be between 1 second and 365 days")
        return seconds

    def _skills_command(self, parts: list[str]) -> bool:
        """Handle `/skills`, `/skills run <id>`, and `/skills rm <id>`."""
        if self._skills is None:
            print("Skill system is unavailable.")
            return True
        if len(parts) >= 3 and parts[1] == "run":
            if self._skill_run is None:
                print("Skill execution is unavailable.")
                return True
            result = self._skill_run(parts[2])
            ok = bool(result.get("ok")) if isinstance(result, dict) else False
            if ok:
                print(f"Skill completed: {result.get('name', parts[2])}")
            else:
                print(f"Skill failed: {parts[2]}")
            for step in (result.get("steps") or []) if isinstance(result, dict) else []:
                mark = "✓" if not step.get("failed") else "✗"
                print(f"  {mark} {step.get('tool')}")
            return True
        if len(parts) >= 3 and parts[1] == "rm":
            if self._skill_delete is None:
                print("Skill deletion is unavailable.")
                return True
            ok = bool(self._skill_delete(parts[2]))
            print("Skill deleted." if ok else "Skill not found.")
            return True
        skills = self._skills()
        if not skills:
            print("No skills learned yet. E.V. creates skills after "
                "successful multi-step tasks.")
            return True
        for s in skills:
            print(f"[{s['id']}] {s.get('name', '')} "
                  f"({s.get('success_count', 0)} successes, "
                  f"{s.get('usage_count', 0)} runs) — "
                  f"{(s.get('goal') or '')[:70]}")
        return True

    def _mcp_command(self, parts: list[str]) -> bool:
        if len(parts) == 1 or parts[1] == "list":
            servers = self._mcp_list() if self._mcp_list else []
            if not servers:
                print("No MCP servers installed.")
                return True
            for server in servers:
                state = "enabled" if server["enabled"] else "disabled"
                print(f"[{state}] {server['id']} ({server['name']}) — "
                      f"{server['command']}")
            return True
        if len(parts) == 3 and parts[1] == "install":
            if self._mcp_install is None:
                print("MCP installation is unavailable.")
                return True
            try:
                server = self._mcp_install(parts[2])
            except MCPInstallError as exc:
                print(f"Installation failed: {exc}")
                return True
            print(f"Repository downloaded and left disabled: {server['id']} "
                f"({server['name']}). Review its code before enabling it "
                f"with /mcp enable {server['id']}.")
            return True
        if len(parts) == 3 and parts[1] in {"enable", "disable"}:
            callback = (self._mcp_enable if parts[1] == "enable"
                        else self._mcp_disable)
            if callback is None:
                print("MCP management is unavailable.")
                return True
            try:
                server = callback(parts[2])
            except MCPInstallError as exc:
                print(f"Update failed: {exc}")
                return True
            state = "enabled" if server["enabled"] else "disabled"
            print(f"MCP server {server['id']} is now {state}; "
                "restart E.V. to apply the change.")
            if server["enabled"]:
                print("The command in server.json will run on next startup.")
            return True
        print("Usage: /mcp list | /mcp install <GitHub URL> | "
              "/mcp enable <id> | /mcp disable <id>")
        return True

    def _schedule_task(self, parts: list[str]) -> None:
        if self._schedule is None or len(parts) < 3:
            print("Usage: /schedule in 10m <task> | "
                "/schedule every 1h <task>")
            return
        try:
            if parts[1].lower() == "in":
                delay = self._duration(parts[2])
                interval = None
                description = " ".join(parts[3:])
            elif parts[1].lower() == "every":
                delay = self._duration(parts[2])
                interval = delay
                description = " ".join(parts[3:])
            else:
                raise ValueError("Use 'in' or 'every'")
            if not description.strip():
                raise ValueError("Task description cannot be empty")
            if self._task_new is None:
                raise ValueError("Task management is unavailable")
            task = self._task_new(description)
            if task is None:
                raise ValueError("Could not create task")
            self._schedule(task.id, delay, interval)
            print(f"Scheduled: {task.id} — {description}")
        except (ValueError, KeyError) as exc:
            print(f"Scheduling error: {exc}")

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
  /integrations   list of platform integrations (Calendar/Gmail/Notion/GitHub)
    /permission     show/set automatic approval limit (0..4)
    /settings       inspect/update settings; set secrets with hidden input
    /brief          local system, task, and connected-service briefing
  /remember k v   store a fact          /episodes   recent episodic memory
  /skills         learned skills;        /skills run <id>  replay one
    /mcp            install/list/enable/disable GitHub MCP servers
    /voice          start voice; /voice setup or /voice doctor
  /tasks          list tasks             /clear     reset conversation
    /schedule in 10m <task>  remind once; every 1h <task> repeats
    /schedules      show scheduled tasks   /cancel <id> cancel schedule
    /run <id>       explicitly execute a due/scheduled task
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
                        return "Blocked: " + str(result.get("error") or "")[:110]
                    if result.get("error"):
                        return "Error: " + str(result["error"])[:110]
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
                        return f"{len(n) if isinstance(n, (list, dict)) else '?'} items found"
                    s = str(result)
                    return s[:120]

                def _on_step(info: dict) -> None:
                    """Live progress during tool work: announce BEFORE the tool
                    runs (phase=start) and briefly summarize AFTER (phase=done.."""
                    phase = info.get("phase")
                    tool = info.get("tool", "")
                    if phase == "start":
                        msg = info.get("message") or f"Running {tool}..."
                        print(f"\n⚙️ {msg}", flush=True)
                    elif phase == "progress":
                        msg = info.get("message") or "Still working..."
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
