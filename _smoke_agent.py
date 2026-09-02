"""Integration test: full Agent ReAct loop using a fake Ollama client.

Validates: intent -> Router -> Context -> Agent loop -> tool dispatch (native
+ MCP via orchestrator) -> memory persistence -> final answer.
Offline: no real model/server needed.
"""
import json
import sys
import tempfile

sys.path.insert(0, '.')

from models.llm import LLMError
from memory.long_term import LongTermMemory
from memory.short_term import ShortTermMemory
from memory.episodic import EpisodicMemory
from security.permissions import PermissionEngine
from security.approval import Approval
from tools.router import ToolRouter
from tools.mcp.registry import MCPRegistry
from core.capability_manager import CapabilityManager
from core.tool_router import ToolOrchestrator
from core.context import ContextBuilder
from core.router import ModelRouter
from core.agent import Agent

cfg = json.load(open('config.json'))


class FakeLLM:
    """Canned responses driving the ReAct loop through 2 tool rounds."""
    def __init__(self):
        self.calls = 0
        self.last_model = None

    def chat(self, messages, tools=None, model=None, **kw):
        self.calls += 1
        self.last_model = model
        if self.calls == 1:
            return {"message": {
                "content": "I'll check the GPU.",
                # arguments as a DICT (this is the case that crashed)
                "tool_calls": [{"function": {
                    "name": "gpu_status",
                    "arguments": {"foo": "dict-form"}}}]}}
        if self.calls == 2:
            return {"message": {
                "content": "Let me verify the file list.",
                "tool_calls": [{"function": {
                    "name": "fs_list_directory",
                    "arguments": "{\"path\": \".\"}"}}]}}
        return {"message": {
            "content": "GPU active and workspace scanned. Done.",
            "tool_calls": []}}

    def generate(self, *a, **k):
        return "ok"

    def list_models(self):
        return ["qwen3.5:4b", "gemma3:1b-it-q4_K_M"]


fake = FakeLLM()

with tempfile.TemporaryDirectory() as d:
    long_mem = LongTermMemory(db_path=f"{d}/ev.db")
    short_mem = ShortTermMemory(20)
    episodic = EpisodicMemory(long_mem)

    perm = PermissionEngine(auto_approve_until=2,
                            approval=Approval(confirm=False))
    native = ToolRouter(workspace=None, perm=perm)
    mcp = MCPRegistry()   # no servers connected in this test
    caps = CapabilityManager(cfg)
    orch = ToolOrchestrator(native, mcp, caps, perm=perm)

    mrouter = ModelRouter(preferred=cfg['ollama']['models'],
                          available=['qwen3.5:4b', 'gemma3:1b-it-q4_K_M'])
    ctx = ContextBuilder(cfg, long_mem, orch.names())

    agent = Agent(fake, orch, ctx, short_mem, episodic, mrouter,
                  max_iterations=4)
    steps = []
    out = agent.run("وضعیت GPU رو چک کن و فایل ها رو لیست کن",
                      on_step=steps.append)

    assert fake.calls in (3, 4), f"expected 3-4 llm calls, got {fake.calls}"
    # the configured (cloud) preference wins over local pool size sorting
    assert fake.last_model == cfg['ollama']['models']['fast'], fake.last_model
    assert "GPU" in out, out
    assert "tool" in json.dumps(agent.last_toolcalls) or agent.last_toolcalls
    # ---- live progress feed (a long tool run must announce itself BEFORE
    # it finishes — roydاد «الان دارم ...» قبل از اجرا) ---- #
    starts = [s for s in steps if s.get("phase") == "start"]
    dones = [s for s in steps if s.get("phase") == "done"]
    assert starts, f"no start events emitted, steps={steps}"
    assert dones, f"no done events emitted, steps={steps}"
    assert all("message" in s and s["message"].strip() for s in starts), starts
    shell_done = next((d for d in dones if d.get("tool") == "shell_run_command"), None)
    if shell_done:
        assert "exit_code" in (shell_done.get("result") or {}), shell_done
    print("progress feed: start/done events OK ->",
          ", ".join(s["tool"] for s in starts))
    # episodic memory recorded the finished task
    eps = long_mem.episodes()
    assert eps and "GPU" in eps[0]["summary"], eps
    # short-term memory kept the exchange for context
    assert len(short_mem.to_list()) >= 2, short_mem.to_list()
    # permissions were audited (2 native tool calls)
    assert len(perm.reviewed) == 2, [r for r in perm.reviewed]

    print("llm calls:", fake.calls)
    print("final:", out)
    print("episodic:", eps[0]["summary"][:60])

    # ---- persistence/nudge behavior ---- #
    class NarrationOnly(FakeLLM):
        """Model that narrates 'I will do it' but never calls a tool."""
        def chat(self, messages, tools=None, model=None, **kw):
            self.calls += 1
            return {"message": {
                "content": "الان باز می‌کنم. یک لحظه…",
                "tool_calls": []}}

    n_fake = NarrationOnly()
    n_agent = Agent(n_fake, orch, ctx, short_mem, episodic, mrouter,
                    max_iterations=4, turbo_threshold=0.3)
    n_out = n_agent.run("یه تب جدید باز کن و ویکی‌پدیای بتمن بیار")
    # narrative-only model: after the first reply the agent must nudge once,
    # then accept the second (still tool-free) reply as final.
    assert n_fake.calls >= 2, f"expected nudge, calls={n_fake.calls}"
    print("nudge test: calls =", n_fake.calls, "-> model was pushed once")

    # ---- textual tool-call promotion (Phase 4 E2E regression) ---- #
    # Cloud models sometimes write tool calls inline in the text instead of
    # using Ollama's native tool_calls format; they must still execute.
    from core.planner import detect_intent

    assert detect_intent("با دوربین ببین تو اتاق کیه؟") == "task", \
        "camera request must classify as task (not question)"
    assert detect_intent("وضعیت GPU رو چک کن") == "task", "check-ctrl stays task"

    OPEN_TAG = "<" + "tool_call" + ">"
    CLOSE_TAG = "<" + "/" + "tool_call" + ">"


    class TextToolLLM(FakeLLM):
        """Replies with narration + an inline text tool call."""
        def __init__(self):
            super().__init__()
            self.tool_seen = False

        def chat(self, messages, tools=None, model=None, **kw):
            self.calls += 1
            if any(m.get("role") == "tool" for m in messages):
                self.tool_seen = True
            if self.calls == 1:
                return {"message": {"content": (
                    "الان نگاه می‌کنم." + OPEN_TAG
                    + '\n{"name": "gpu_status", "arguments": {}}\n'
                    + CLOSE_TAG)}}
            return {"message": {"content": "دیدم؛ همه چیز اوکیه.",
                                "tool_calls": []}}

    t_fake = TextToolLLM()
    t_agent = Agent(t_fake, orch, ctx, short_mem, episodic, mrouter,
                    max_iterations=6)
    t_out = t_agent.run("وضعیت GPU رو ببین")
    # the textual tool call was promoted and really executed via dispatch
    assert t_fake.tool_seen, "textual tool call was not executed!"
    # the raw tag must never leak into the user-facing reply
    assert OPEN_TAG not in t_out and CLOSE_TAG not in t_out, t_out
    assert len(t_agent.last_toolcalls) >= 1 \
        and t_agent.last_toolcalls[0]["name"] == "gpu_status", \
        t_agent.last_toolcalls
    print("textual tool-call test: inline call executed ->",
          t_agent.last_toolcalls[0]["name"])

    # ---- degenerate '}' output guard (Phase 4 regression) ---- #
    # A cloud model sometimes executes camera_look correctly but then dies
    # mid-JSON and the next stop-token round replies with nothing but "}".
    # We must surface the real tool result, never echo the "}".
    class JunkLLM(FakeLLM):
        def chat(self, messages, tools=None, model=None, **kw):
            self.calls += 1
            if self.calls == 1:
                return {"message": {"role": "assistant", "content": "",
                        "tool_calls": [{"function": {
                            "name": "camera_look",
                            "arguments": {"index": 0,
                                          "prompt": "توصیف دقیق تصویر"}}}]}}
            return {"message": {"role": "assistant", "content": "}",  # <-- the bug
                                "tool_calls": []}}

    j_fake = JunkLLM()

    class CamRouter:
        """Minimal orchestrator stand-in that only answers camera_look."""
        def schemas(self):
            return [{"type": "function", "function": {
                "name": "camera_look",
                "parameters": {"type": "object",
                               "properties": {"index": {"type": "integer"},
                                              "prompt": {"type": "string"}}}}}]
        def dispatch(self, name, args):
            assert name == "camera_look", name
            return {"ok": True, "camera": "/dev/video0",
                    "description": "یک اتاق روشن با میز و مانیتور.",
                    "path": "data/camera/frame.png"}
        def names(self):
            return ["camera_look"]

    j_agent = Agent(j_fake, CamRouter(), ctx, short_mem, episodic, mrouter,
                    max_iterations=6)
    j_out = j_agent.run("دوربین رو باز کن و آنچه که میبینی رو بگو")
    assert "یک اتاق روشن با میز و مانیتور" in j_out, j_out
    assert "}" not in j_out, j_out
    assert j_fake.calls == 2, \
        f"junk guard must recover immediately (no extra nudge), calls={j_fake.calls}"
    assert j_agent._is_junk("}") and j_agent._is_junk("") \
        and j_agent._is_junk("...؟؟") and not j_agent._is_junk("بله")
    print(f"degenerate '}}' guard: camera result surfaced after "
          f"{j_fake.calls} llm calls -> {j_out[:40]!r}")

    # ---- live progress feed (user friction: a long tool run must announce
    # itself BEFORE it finishes — «الان دارم ...» (start) then while it runs
    # (progress) then a ✅ summary (done), in that order) ---- #
    p_steps = []
    p_fake = FakeLLM()     # fresh instance:the shared `fake` already spent its
    # tool-call round in the first run above
    p_agent = Agent(p_fake, orch, ctx, short_mem, episodic, mrouter,
                    max_iterations=6)
    p_out = p_agent.run("وضعیت GPU رو چک کن و فایل ها رو لیست کن",
                      on_step=p_steps.append)
    p_phases = [s.get("phase") for s in p_steps]
    assert "start" in p_phases and "done" in p_phases, \
        f"live feed missing start/done, phases={p_phases}"
    assert all(s.get("message") and s["message"].strip()
               for s in p_steps if s.get("phase") == "start"), p_steps
    # start always precedes the following done for the same tool
    start_first = next(s for s in p_steps if s.get("phase") == "start")
    assert start_first.get("tool") and p_out, (start_first, p_out)
    print("live progress feed: start/done emitted OK ->",
          ", ".join(f"{s.get('phase')}:{s.get('tool')}" for s in p_steps[:6]))

    print("ALL AGENT INTEGRATION TESTS PASSED")