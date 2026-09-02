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
                 model: str | None = None, turbo_threshold: float = 0.3):
        self.llm = llm
        self.router = router
        self.context = context
        self.memory = memory
        self.episodic = episodic
        self.model_router = model_router
        self.max_iterations = max_iterations
        self.model_override = model
        self.turbo_threshold = turbo_threshold
        self.intent_engine = IntentEngine()
        self.last_toolcalls: list[dict] = []
        self.heartbeat_seconds = 8   # live-progress tick while a tool runs
        # a task that hit the iteration cap stays here so the user can say
        # «ادامه بده» and we resume exactly where we stopped instead of
        # discarding the transcript.
        self._pending_task: dict | None = None

    # -------------------------------------------------------------- #
    def _build(self, user_input: str) -> tuple[list[dict], str]:
        intent = self.intent_engine.detect(user_input)
        model = self.model_override or self.model_router.choose(
            user_input, intent)
        history = self.memory.recent()
        messages = [{"role": "system",
                     "content": self.context.system_prompt()},
                    *history,
                    {"role": "user", "content": user_input}]
        return messages, model

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
            content = "[پاسخی دریافت نشد — مدل خروجی خالی/ناقص داد. دوباره بپرسید.]"
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

    # Human-friendly Persian labels fothe step feed so the user sees
    # "الان دارم «دوربین» را اجرا می‌کنم..." while a tool is running —
    # this is the only live feedback during a long shell command.
    _TOOL_LABELS = {
        "shell_run_command": "دستور شل", "run_command": "دستور شل",
        "camera_look": "دوربین", "camera_capture": "عکس‌برداری دوربین",
        "camera_list": "لیست دوربین‌ها",
        "browser_launch": "مرورگر", "browser_open": "باز کردن صفحه",
        "browser_read": "خواندن صفحه", "browser_click": "کلیک مرورگر",
        "browser_type": "تایپ در مرورگر", "browser_scroll": "اسکرول مرورگر",
        "browser_screenshot": "اسکرین‌شات مرورگر",
        "gpu_status": "وضعیت GPU", "gpu_temperature": "دمای GPU",
        "fs_read_file": "خواندن فایل", "fs_write_file": "نوشتن فایل",
        "fs_edit_file": "ویرایش فایل", "fs_list_directory": "لیست پوشه",
        "fs_create_file": "ساخت فایل", "fs_search_files": "جستجو در فایل‌ها",
        "capture_screen": "گرفتن اسکرین‌شات", "vision_describe": "توصیف تصویر",
        "vision_screen": "تحلیل صفحه",
        "process_list": "لیست فرایندها", "process_kill": "پایان فرایند",
        "kill_process": "پایان فرایند", "process_start": "شروع فرایند",
        "service_status": "وضعیت سرویس", "service_restart": "راه‌اندازی مجدد سرویس",
        "service_start": "شروع سرویس", "service_stop": "توقف سرویس",
        "pip_install": "نصب پکیج پایتون", "apt_install": "نصب پکیج",
        "network_change": "تغییر شبکه",
        "write_file": "نوشتن فایل", "read_file": "خواندن فایل",
        "list_directory": "لیست پوشه", "search_files": "جستجو",
        "delete_file": "حذف فایل", "mkdir": "ساخت پوشه",
        "copy_file": "کپی فایل", "move_file": "انتقال فایل",
        "edit_file": "ویرایش فایل",
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
        """Build a live Persian announcement shown *before* a tool runs,
        so a long shell command never looks silent.  Includes the command
        itself for the shell tool — the most important case."""
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
        base = f"الان دارم «{label}» را اجرا می‌کنم"
        return base + ((" — " + " ".join(parts)) if parts else "")

    def _recover_answer(self, transcript: list, user_input: str,
                        messages: list[dict], model: str) -> str:
        """Model emitted only junk ("}") — build a real Persian reply from
        the tool results instead of echoing the junk."""
        # Prettiest path: vision tools carry a human `description` field.
        for t in reversed(transcript):
            if "tool" not in t or "result" not in t:
                continue
            r = t.get("result") or {}
            if isinstance(r, dict) and r.get("description"):
                desc = str(r["description"]).strip()
                if not desc:
                    continue
                head = {"camera_look": "دوربین را فعال کردم و این را دیدم: ",
                        "vision_screen": "صفحه‌نمایش را بررسی کردم: ",
                        "vision_describe": "تصویر را بررسی کردم: "
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
                        "content": ("ادامه بده — همان کار ناتمام را تا پایان "
                                   "ادامه بده و کاملش کن.")})
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
                        "شما هنوز ابزاری اجرا نکرده‌اید. درخواست کاربر "
                        "به ابزار نیاز دارد — همین حالا یک ابزار واقعی "
                        "(مثل browser_launch، shell_run_command، "
                        "fs_* ...) را صدا بزنید. فقط توصیف نکنید؛ عمل کنید."),
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
                                         f"⏳ هنوز دارم «{label}» را اجرا می‌کنم — "
                                         f"{waited} ثانیه گذشته، لطفاً صبر کن...")})
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

    def run(self, user_input: str, on_stream=None, on_step=None) -> str:
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
            messages, model = self._build(user_input)
            if model:
                return self._turbo_quick(messages, user_input, model,
                                         on_stream)

        messages, model = self._build(user_input)
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
                            "شما هنوز ابزاری اجرا نکرده‌اید. درخواست کاربر "
                            "به ابزار نیاز دارد — همین حالا یک ابزار واقعی "
                            "(مثل browser_launch، shell_run_command، "
                            "fs_* ...) را صدا بزنید. فقط توصیف نکنید؛ عمل کنید."),
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
                # live progress: announce *before* dispatching so the user
                # sees "الان دارم ..." while a slow command (sudo apt...) is running.
                if on_step is not None:
                    try:
                        on_step({"step": step, "phase": "start", "tool": name,
                                 "args": args,
                                 "message": self._describe_step(name, args),
                                 "ts": time.time()})
                    except Exception:
                        pass
                # heartbeat: a slow command (sudo apt purge...) must keep
                # talking — every 8s while it runs, show "هنوز دارم ...
                # را اجرا می‌کنم — N ثانیه گذشته...".
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
                                             f"⏳ هنوز دارم «{label}» را اجرا می‌کنم — "
                                             f"{waited} ثانیه گذشته، لطفاً صبر کن...")})
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

            self.last_toolcalls = results

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
                    "به حداکثر تعداد گام ابزار رسیده‌ای. کارهای انجام‌شده و "
                    "یافته‌ها را در حداکثر ۴ خط فارسی خلاصه کن: وضعیت فعلی "
                    "چیست و اگر کاری ناتمام مانده صریح بگو. ابزار صدا نزن."),
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
        lines = [f"به سقف {self.max_iterations} گام رسیدم؛ آنچه انجام شد:"]
        if tools_used:
            lines.append("ابزارها: " + ", ".join(tools_used[-6:]))
        last = transcript[-1] if transcript else {}
        if "result" in last:
            rs = json.dumps(last["result"], ensure_ascii=False, default=str)
            lines.append("آخرین نتیجه: " + rs[:300])
        lines.append("برای ادامه بگو «ادامه بده».")
        self.episodic.record(
            f"Task '{user_input}' hit iteration cap",
            {"steps": self.max_iterations, "tools": tools_used[-6:]})
        return "\n".join(lines)
