"""Agent Core — the brain of E.V. (architecture §4, §6, §19).

Implements the ReAct loop over the Ollama native tool-calling protocol:

    THINK -> PLAN -> TOOL -> OBSERVE -> EVALUATE -> CONTINUE / FIX / FINISH

The system prompt + live state come from ContextBuilder; every tool call is
routed through ToolRouter (which permission-gates it) and the whole transcript
is persisted to episodic memory.
"""
from __future__ import annotations

import json
import re
import threading
import time

from models.llm import OllamaClient, LLMError
from core.context import ContextBuilder
from core.planner import IntentEngine, detect_complexity
from core.router import ModelRouter
from memory.short_term import ShortTermMemory
from memory.episodic import EpisodicMemory


class Agent:
    def __init__(self, llm: OllamaClient, router, context: ContextBuilder,
                 memory: ShortTermMemory, episodic: EpisodicMemory,
                 model_router: ModelRouter, max_iterations: int = 8,
                 model: str | None = None, turbo_threshold: float = 0.3,
                 skills=None):
        self.llm = llm
        self.router = router
        self.context = context
        self.memory = memory
        self.episodic = episodic
        self.model_router = model_router
        self.max_iterations = max_iterations
        self.model_override = model
        self.turbo_threshold = turbo_threshold
        self.skills = skills        # optional SkillEngine (Phase 7)
        self.intent_engine = IntentEngine()
        self.last_toolcalls: list[dict] = []
        self.heartbeat_seconds = 8   # live-progress tick while a tool runs
        # a task that hit the iteration cap stays here so the user can say
        # «ادامه بده» and we resume exactly where we stopped instead of
        # discarding the transcript.
        self._pending_task: dict | None = None

    # -------------------------------------------------------------- #
    def _build(self, user_input, history=None):
        intent = self.intent_engine.detect(user_input)
        model = self.model_override or self.model_router.choose(
            user_input, intent)
        if history:
            # a reopened web session supplies its OWN prior exchange so the
            # model "remembers" that conversation (global memory untouched)
            prior = [{"role": m["role"], "content": str(m.get("content") or "")}
                     for m in history[-24:]
                     if isinstance(m, dict)
                     and m.get("role") in ("user", "assistant")
                     and str(m.get("content") or "").strip()]
            prior.append({"role": "user", "content": user_input})
        else:
            prior = [*self.memory.recent(),
                     {"role": "user", "content": user_input}]
        messages = [{"role": "system",
                     "content": self.context.system_prompt(user_input)},
                    *prior]
        return messages, model

    def _learn_skill(self, user_input: str, final_answer: str,
                     transcript: list) -> None:
        """Self-improvement hook: consolidate successful multi-tool runs into
        reusable skills. Best-effort — never affects the agent's reply."""
        if self.skills is None:
            return
        try:
            outcome = self.skills.consolidate(user_input, final_answer,
                                              transcript)
            if outcome and outcome.get("action") == "created":
                self.episodic.record(
                    f"Skill created: {outcome.get('id')}",
                    {"goal": user_input[:120]})
        except Exception:  # noqa: BLE001 — learning must never break the turn
            pass

    # -------------------------------------------------------------- #
    def _turbo_quick(self, messages: list[dict], user: str, model: str,
                     on_stream=None) -> str:
        """Fast path: single streamed generation, no tool schemas.

        Used for simple questions/chat where no OS tool is needed.
        """
        content = ""
        try:
            for chunk in self.llm.chat_stream(messages, model=model):
                delta = (chunk.get("message") or {}).get("content") or ""
                if delta:
                    content += delta
                    if on_stream:
                        on_stream(delta)
                if chunk.get("done"):
                    break
        except LLMError as e:
            return f"[Error] {e}"
        if self._is_junk(content):
            content = "[No response received — the model returned empty or incomplete output. Please try again.]"
        self.memory.add_message({"role": "user", "content": user})
        self.memory.add_message({"role": "assistant", "content": content})
        self.episodic.record(
            f"Chat '{user[:60]}' -> {content[:120]}",
            {"mode": "turbo", "model": model})
        return content

    # --- textual tool-call fallback --------------------------------- #
    # Some models answer with narration plus an inline JSON block wrapped
    # in XML-ish tags instead of Ollama's native tool_calls format.
    _TAG_OPEN = "<" + "tool_call" + ">"
    _TAG_CLOSE = "<" + "/" + "tool_call" + ">"

    # Human-readable labels keep the live tool feed clear during long commands.
    _TOOL_LABELS = {
        "shell_run_command": "Shell command", "run_command": "Shell command",
        "camera_look": "Camera", "camera_capture": "Camera capture",
        "camera_list": "Camera list",
        "browser_launch": "Browser", "browser_open": "Open page",
        "browser_read": "Read page", "browser_click": "Browser click",
        "browser_type": "Browser input", "browser_scroll": "Browser scroll",
        "browser_screenshot": "Browser screenshot",
        "gpu_status": "GPU status", "gpu_temperature": "GPU temperature",
        "fs_read_file": "Read file", "fs_write_file": "Write file",
        "fs_edit_file": "Edit file", "fs_list_directory": "List directory",
        "fs_create_file": "Create file", "fs_search_files": "Search files",
        "capture_screen": "Capture screen", "vision_describe": "Describe image",
        "vision_screen": "Analyze screen",
        "process_list": "List processes", "process_kill": "Stop process",
        "kill_process": "Stop process", "process_start": "Start process",
        "service_status": "Service status", "service_restart": "Restart service",
        "service_start": "Start service", "service_stop": "Stop service",
        "pip_install": "Install Python package", "apt_install": "Install package",
        "network_change": "Change network",
        "write_file": "Write file", "read_file": "Read file",
        "list_directory": "List directory", "search_files": "Search files",
        "delete_file": "Delete file", "mkdir": "Create directory",
        "copy_file": "Copy file", "move_file": "Move file",
        "edit_file": "Edit file",
    }

    @classmethod
    def _extract_textual_tool_calls(cls, content: str):
        """Pull embedded tool-call JSON out of plain assistant text.

        Returns ``(calls, cleaned_content)``. Calls use the native
        ``{"function": {"name", "arguments"}}`` shape so the executor
        handles them identically.
        """
        if cls._TAG_OPEN not in content:
            return [], content
        pattern = re.compile(
            r"\s*" + re.escape(cls._TAG_OPEN) + r"\s*(\{.*?\})\s*"
            + re.escape(cls._TAG_CLOSE), re.S)

        calls: list[dict] = []

        def _grab(m: re.Match) -> str:
            try:
                obj = json.loads(m.group(1))
            except json.JSONDecodeError:
                return m.group(0)          # keep malformed text visible
            if isinstance(obj, dict) and obj.get("name"):
                calls.append({"function": {
                    "name": obj["name"],
                    "arguments": obj.get("arguments", {})}})
                return ""                  # strip from user-facing text
            return m.group(0)

        cleaned = pattern.sub(_grab, content).strip()
        return calls, cleaned

    # -------------------------------------------------------------- #
    @classmethod
    def _is_junk(cls, text) -> bool:
        """True if the model produced no real words — bare "}", stray
        punctuation, whitespace, empty. Those mean the model died mid-JSON
        (or hit its output cap) and must never be shown to the user."""
        t = (text or "").strip()
        if not t:
            return True
        remainder = re.sub(
            r"[\s{}()\[\]\"'`.,;:!؟?،…«»—ـ\-‌]+", "", t)
        return not remainder

    def _describe_step(self, name: str, args: dict) -> str:
        """Build an English live announcement shown before a tool runs."""
        label = self._TOOL_LABELS.get(name) or name
        parts = []
        if name in ("shell_run_command", "run_command"):
            cmd = str(args.get("command") or "").strip()
            if cmd:
                parts.append(cmd[:160])
        elif args:
            try:
                compact = json.dumps(args, ensure_ascii=False, default=str)
            except Exception:                       # noqa: BLE001
                compact = ""
            if compact and len(compact) < 120:
                parts.append(compact)
            elif compact:
                parts.append(compact[:117] + "...")
        base = f"Running {label}"
        return base + ((" — " + " ".join(parts)) if parts else "")

    @staticmethod
    def _tool_failed(result: dict | object) -> bool:
        if not isinstance(result, dict):
            return False
        return bool(result.get("blocked") is True or result.get("error"))

    def _recover_answer(self, transcript: list, user_input: str,
                        messages: list[dict], model: str) -> str:
        """Model emitted only junk; build a useful reply from tool results."""
        # Prettiest path: vision tools carry a human `description` field.
        for t in reversed(transcript):
            if "tool" not in t or "result" not in t:
                continue
            r = t.get("result") or {}
            if isinstance(r, dict) and r.get("description"):
                desc = str(r["description"]).strip()
                if not desc:
                    continue
                head = {"camera_look": "Camera result: ",
                    "vision_screen": "Screen analysis: ",
                    "vision_describe": "Image description: "
                        }.get(t["tool"], "")
                reply = head + desc
                self.memory.add_message({"role": "user",
                                         "content": user_input})
                self.memory.add_message({"role": "assistant",
                                         "content": reply})
                self.episodic.record(
                    f"Task '{user_input}' recovered from junk model output",
                    {"steps": len(transcript) - 1, "model": model,
                     "tool": t["tool"]})
                return reply
        # Generic case: let the cap-summarizer close it (LLM summary with a
        # deterministic structured fallback).
        return self._summarize_cap(messages, transcript, user_input, model)

    # -------------------------------------------------------------- #
# ---- unfinished-task continuation ----------------------------- #
    _CONTINUE_RE = re.compile(
        r"^(ادامه\s*(بده|ده|بفرست|)?|continue|ادامه|ادامه\s*بده|"
        r"ادامه\s*ده|بعدی|بعدش|برو\s*جلو|همین\s*کار\s*رو\s*ادامه\s*بده)$",
        re.IGNORECASE,
    )

    def _is_continue(self, text: str) -> bool:
        """Detect a \"continue the task\" request from the user."""
        t = (text or "").strip().strip("؟؟").strip()
        if not t:
            return False
        return bool(self._CONTINUE_RE.match(t)) or (
            len(t) <= 9 and "ادامه" in t
        )

    def _resume_pending(self, user_input: str, on_stream, on_step):
        """Continue an unfinished task from the SAME messages+transcript."""
        resume = self._pending_task
        if resume is None or not self._is_continue(user_input):
            return None
        self._pending_task = None        # consumed — finish it properly now
        intent = resume["intent"]
        model = resume["model"]
        messages = resume["messages"]
        transcript = resume["transcript"]
        nudged = resume.get("nudged", False)
        nudged_box = [nudged]     # shared mutable so _resume_step can update it
        step_offset = len(transcript)
        # Continue with more headroom than a fresh run:the resumed turn may
        # need a nudge round AND a final answer round on top of real steps.
        max_steps = step_offset + self.max_iterations + 2
        messages.append({"role": "user",
                "content": "Continue the unfinished task until it is complete."})
        for step in range(step_offset, max_steps):
            resp = self._resume_step(messages, transcript, step,
                                      model, intent, nudged_box,
                                      on_stream, on_step)
            if isinstance(resp, str):
                return resp
        # renewed cap — keep the state for yet another round
        self._pending_task = {
            "intent": intent, "model": model,
            "messages": messages, "transcript": transcript,
            "nudged": nudged,
        }
        return self._summarize_cap(messages, transcript, "<ادامه بده>", model)

    def _resume_step(self, messages, transcript, step, model, intent,
                         nudged_box, on_stream, on_step):
        """Run ONE resumed ReAct step (mirrors the loop inside ``run``)."""
        try:
            resp = self.llm.chat(
                messages, tools=self.router.schemas(), model=model)
        except LLMError as e:
            return f"[Error] {e}"
        msg = resp.get("message", {})
        content = msg.get("content") or ""
        tool_calls = list(msg.get("tool_calls") or [])
        text_calls, content = self._extract_textual_tool_calls(content)
        if text_calls:
            tool_calls.extend(text_calls)

        if content:
            transcript.append({"step": step, "assistant": content})

        assistant_msg = {"role": "assistant", "content": content or ""}
        if tool_calls:
            assistant_msg["tool_calls"] = tool_calls
        messages.append(assistant_msg)

        if not tool_calls:
            if self._is_junk(content):
                return self._recover_answer(transcript, "<ادامه بده>",
                                            messages, model)
            nudged = nudged_box[0] if nudged_box else False
            if intent in ("command", "task", "emergency", "observation") \
                    and content.strip()and not nudged:
                nudged_box[0] = True
                messages.append({
                    "role": "user",
                    "content": (
                        "No tool has been run yet, but this request requires "
                        "one. Call an appropriate available tool now; do not "
                        "just describe the action."),
                    })
            return None      # keep looping (need another inference round)
            return content

        results = []
        for tc in tool_calls:

            fn = tc.get("function", {})
            name = fn.get("name", "")
            args_raw = fn.get("arguments") or "{}"
            if isinstance(args_raw, str):
                try:
                    args = json.loads(args_raw)
                except (json.JSONDecodeError, TypeError):
                    args = {}
            elif isinstance(args_raw,dict):
                args = args_raw or {}
            else:
                args = {}
            if on_step is not None:
                try:
                    on_step({"step": step, "phase": "start", "tool": name,
                             "args": args,
                             "message": self._describe_step(name, args),
                             "ts": time.time()})
                except Exception:
                    pass
            stop_hb = threading.Event()

            def _heartbeat():
                label = self._TOOL_LABELS.get(name, name)
                waited = 0
                while not stop_hb.wait(self.heartbeat_seconds):
                    waited += self.heartbeat_seconds
                    if on_step is not None:
                        try:
                            on_step({"step": step, "phase": "progress",
                                     "tool": name,
                                     "message": (
                                         f"⏳ Still running {label} — "
                                         f"{waited} seconds elapsed...")})
                        except Exception:
                            pass

            hb = threading.Thread(target=_heartbeat, daemon=True)
            hb.start()
            try:
                result = self.router.dispatch(name, args)
            finally:
                stop_hb.set()
                hb.join(timeout=0.5)
            results.append({"name": name, "args": args,
                            "result": result})
            if on_step is not None:
                try:
                    on_step({"step": step, "phase": "done", "tool": name,
                             "args": args, "result": result})
                except Exception:
                    pass
            messages.append({
                "role": "tool",
                "content": json.dumps(result, ensure_ascii=False,
                                      default=str),
                "tool_call_id": tc.get("tool_call_id") or name,
            })
            transcript.append({"step": step, "tool": name,
                               "args": args, "result": result})
        return None      # keep looping (assistant already replied via on_stream)

    def run(self, user_input: str, on_stream=None, on_step=None,
            history=None, session_id: str = "cli") -> str:
        answer = self._run(user_input, on_stream=on_stream, on_step=on_step,
                           history=history)
        base = getattr(self.episodic, "base", None)
        remember = getattr(base, "remember_session_message", None)
        if callable(remember):
            try:
                remember(session_id, "user", user_input)
                remember(session_id, "assistant", answer)
            except Exception:  # noqa: BLE001 — persistence must not break a reply
                pass
        return answer

    def _run(self, user_input: str, on_stream=None, on_step=None,
             history=None) -> str:
        # Resume an unfinished task:when the user says «ادامه بده», continue
        # with the SAME transcript+messages, so the work isn't lost.

        resumed = self._resume_pending(user_input, on_stream, on_step)
        if resumed is not None:
            return resumed
 
        intent = self.intent_engine.detect(user_input)
        complex_req = detect_complexity(user_input) >= self.turbo_threshold

        # Fast path: light question/chat -> single streamed pass (no tools)
        if intent in ("question", "conversation") and not complex_req \
                and on_stream is not None:
            messages, model = self._build(user_input, history)
            if model:
                return self._turbo_quick(messages, user_input, model,
                                         on_stream)

        messages, model = self._build(user_input, history)
        transcript = [{"intent": intent, "model": model,
                       "user": user_input}]
        tool_intent = intent in ("command", "task", "emergency", "observation")
        # Allowed "final" tool-free replies for a tool-intent request.
        # If the model only narrates ("I will do X") without calling a tool,
        # we nudge it to actually act.
        nudged = False

        for step in range(self.max_iterations):
            try:
                resp = self.llm.chat(
                    messages, tools=self.router.schemas(), model=model)
            except LLMError as e:
                summary = f"Inference failed: {e}"
                self.episodic.record(summary, {"user": user_input})
                return f"[Error] {e}"

            msg = resp.get("message", {})
            content = msg.get("content") or ""
            tool_calls = list(msg.get("tool_calls") or [])

            # models that can't emit native tool_calls write them as text;
            # promote those to real calls so they actually execute.
            text_calls, content = self._extract_textual_tool_calls(content)
            if text_calls:
                tool_calls.extend(text_calls)

            if content:
                transcript.append({"step": step, "assistant": content})

            assistant_msg = {"role": "assistant", "content": content or ""}
            if tool_calls:
                assistant_msg["tool_calls"] = tool_calls
            messages.append(assistant_msg)

            if not tool_calls:
                # Degenerate-output guard FIRST: a bare "}" or stray
                # punctuation is not a narration — recover the real tool
                # result immediately instead of wasting a turn on a nudge.
                if self._is_junk(content):
                    return self._recover_answer(transcript, user_input,
                                                messages, model)
                # Persistence: if the task clearly needs tools (open a
                # browser, run a command, etc.) and the model produced
                # only narration with no tool call, push it once to act.
                if tool_intent and content.strip() and not nudged:
                    nudged = True
                    messages.append({
                        "role": "user",
                        "content": (
                            "No tool has been run yet, but this request requires "
                            "one. Call an appropriate available tool now; do not "
                            "just describe the action."),
                    })
                    continue
                self.memory.add_message({"role": "user",
                                         "content": user_input})
                self.memory.add_message({"role": "assistant",
                                         "content": content})
                self.episodic.record(
                    f"Task '{user_input}' -> {content[:120]}",
                    {"steps": len(transcript) - 1,
                     "intent": intent, "model": model,
                     "nudged": nudged})
                self._learn_skill(user_input, content, transcript)
                return content

            # execute each requested tool call
            results = []
            for tc in tool_calls:
                fn = tc.get("function", {})
                name = fn.get("name", "")
                args_raw = fn.get("arguments") or "{}"
                if isinstance(args_raw, str):
                    try:
                        args = json.loads(args_raw)
                    except (json.JSONDecodeError, TypeError):
                        args = {}
                elif isinstance(args_raw, dict):
                    args = args_raw or {}
                else:
                    args = {}
                # Announce before dispatch so a long-running tool stays visible.
                if on_step is not None:
                    try:
                        on_step({"step": step, "phase": "start", "tool": name,
                                 "args": args,
                                 "message": self._describe_step(name, args),
                                 "ts": time.time()})
                    except Exception:
                        pass
                # heartbeat: a slow command (sudo apt purge...) must keep
                # Send a progress update every few seconds while a tool runs.
                stop_hb = threading.Event()

                def _heartbeat():
                    label = self._TOOL_LABELS.get(name, name)
                    waited = 0
                    while not stop_hb.wait(self.heartbeat_seconds):
                        waited += self.heartbeat_seconds
                        if on_step is not None:
                            try:
                                on_step({"step": step, "phase": "progress",
                                         "tool": name,
                                         "message": (
                                             f"⏳ Still running {label} — "
                                             f"{waited} seconds elapsed...")})
                            except Exception:
                                pass

                hb = threading.Thread(target=_heartbeat, daemon=True)
                hb.start()
                try:
                    result = self.router.dispatch(name, args)
                finally:
                    stop_hb.set()
                    hb.join(timeout=0.5)
                results.append({"name": name, "args": args,
                                "result": result})
                if on_step is not None:
                    try:
                        on_step({"step": step, "phase": "done", "tool": name,
                                 "args": args, "result": result})
                    except Exception:
                        pass
                messages.append({
                    "role": "tool",
                    "content": json.dumps(result, ensure_ascii=False,
                                          default=str),
                    "tool_call_id": tc.get("tool_call_id") or name,
                })
                transcript.append({"step": step, "tool": name,
                                   "args": args, "result": result})

                if self._tool_failed(result):
                    messages.append({
                        "role": "user",
                            "content": (
                            f"Tool {name!r} failed with result: {result}. "
                            "Choose a valid, safe alternative tool and try again."
                        )
                    })
                    break

            self.last_toolcalls = results
            if any(self._tool_failed(item["result"]) for item in results):
                continue

        # iteration cap reached — keep the chain alive so the user can say
        # «ادامه بده» and we resume EXACTLY here (same messages+transcript).
        self._pending_task = {
            "intent": intent, "model": model,
            "messages": messages, "transcript": transcript,
            "nudged": nudged,
        }

        # wrap up cleanly instead of dumping raw JSON: ask the LLM once
        # (tool-free) for a short summary of the work done.


        return self._summarize_cap(messages, transcript, user_input, model)

    def _summarize_cap(self, messages, transcript, user_input,
                       model=None) -> str:
        tools_used = [t["tool"] for t in transcript if "tool" in t]
        try:
            wrap = list(messages) + [{
                "role": "user",
                "content": (
                    "The tool-step limit has been reached. Summarize the work "
                    "and findings in at most four lines, in the same language "
                    "as the user's original request. State clearly if anything "
                    "remains unfinished. Do not call tools."),
            }]
            resp = self.llm.chat(wrap, tools=None, model=model)
            content = ((resp.get("message") or {}).get("content") or "").strip()
            if content and not self._is_junk(content):
                # NOTE: do NOT clear _pending_task here — hitting the cap means
                # the job is genuinely unfinished; the user may still say
                # «ادامه بده» to continue.  Clearing happens when a real
                # completion path returns (resume consumed it, or fresh run).
                self.episodic.record(
                    f"Task '{user_input}' hit iteration cap (summarized)",
                    {"steps": self.max_iterations,
                     "tools": tools_used[-6:]})
                return content
        except Exception:
            pass
        # structured fallback — compact and human-readable
        lines = [f"Reached the {self.max_iterations}-step limit. Completed work:"]
        if tools_used:
            lines.append("Tools: " + ", ".join(tools_used[-6:]))
        last = transcript[-1] if transcript else {}
        if "result" in last:
            rs = json.dumps(last["result"], ensure_ascii=False, default=str)
            lines.append("Latest result: " + rs[:300])
        lines.append("Send 'continue' to resume.")
        self.episodic.record(
            f"Task '{user_input}' hit iteration cap",
            {"steps": self.max_iterations, "tools": tools_used[-6:]})
        return "\n".join(lines)
