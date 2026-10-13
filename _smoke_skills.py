"""Smoke tests for Phase 7: skills + semantic memory + FTS5.

Offline — no Ollama, no network. Run:  .venv/bin/python3 _smoke_skills.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from skills import SkillEngine, SkillStore        # noqa: E402
from memory.embeddings import Embedder            # noqa: E402
from memory.semantic import SemanticMemory        # noqa: E402
from memory.long_term import LongTermMemory       # noqa: E402


class FakeLLM:
    """Minimal LLM stub for replay adaptation (returns original args)."""

    def chat(self, messages, tools=None, model=None, **kwargs):
        return {"message": {"role": "assistant", "content": "{}"}}


class FakeRouter:
    """Records dispatched calls and returns canned results."""

    def __init__(self, results=None):
        self.calls: list[tuple[str, dict]] = []
        self.results = results or {}

    def dispatch(self, name, arguments):
        self.calls.append((name, arguments))
        return self.results.get(name, {"ok": True, "echoed": arguments})


def test_store(tmp: Path) -> None:
    store = SkillStore(str(tmp / "skills.json"))
    sid = store.create("گرفتن وضعیت gpu", "وضعیت GPU رو بگو",
                       steps=[{"tool": "gpu_status", "args": {}}],
                       tags=["gpu", "وضعیت"])
    assert store.get(sid) is not None, "skill not persisted"
    # same name -> reinforce, not duplicate
    store.create("گرفتن وضعیت gpu", "وضعیت GPU رو بگو")
    assert store.count() == 1, "duplicate skill created"
    store.record_usage(sid, success=True)
    skill = store.get(sid)
    # create(1) + reinforce create(+1) + one successful usage(+1) = 3
    assert skill["usage_count"] == 1 and skill["success_count"] == 3, skill
    # reload from disk
    store2 = SkillStore(str(tmp / "skills.json"))
    assert store2.count() == 1, "skills.json did not survive reload"
    print("  [ok] SkillStore create/reinforce/persist")


def test_engine(tmp: Path) -> None:
    store = SkillStore(str(tmp / "skills.json"))
    engine = SkillEngine(store, llm=FakeLLM(), router=FakeRouter())
    transcript = [
        {"step": 0, "tool": "gpu_status", "args": {},
         "result": {"ok": True}},
        {"step": 1, "tool": "fs_read_file", "args": {"path": "x.txt"},
         "result": {"ok": True}},
    ]
    out = engine.consolidate("وضعیت gpu و فایل x رو چک کن",
                             "همه‌چیز خوب است", transcript)
    assert out and out["action"] == "created", f"no skill created: {out}"
    # single-tool runs must NOT create skills
    out2 = engine.consolidate("سوال ساده", "جواب",
                              [{"step": 0, "tool": "gpu_status", "args": {},
                                "result": {"ok": True}}])
    assert out2 is None, "single-tool run created a skill"
    # matching finds it again -> reinforce
    out3 = engine.consolidate("وضعیت gpu و فایل x رو چک کن",
                              "دوباره خوب است", transcript)
    assert out3 and out3["action"] == "reinforced", f"no match: {out3}"
    # context block includes the skill
    block = engine.context_block("وضعیت gpu")
    assert "gpu" in block.casefold(), "skill missing from context block"
    store.create("weather forecast", "check tomorrow's weather",
                 steps=[{"tool": "weather", "args": {}}])
    matched = engine.relevant("وضعیت gpu")
    assert matched and all(s["name"] != "weather forecast" for s in matched), matched
    assert len(engine.relevant("unmatched query")) == 3
    print("  [ok] SkillEngine consolidate/match/context")


def test_replay(tmp: Path) -> None:
    store = SkillStore(str(tmp / "skills.json"))
    router = FakeRouter(results={"gpu_status": {"ok": True, "temp": 60}})
    engine = SkillEngine(store, llm=FakeLLM(), router=router)
    sid = store.create("gpu check", "وضعیت gpu",
                       steps=[{"tool": "gpu_status", "args": {}}])
    result = engine.run_skill(sid)
    assert result.get("ok") is True, f"replay failed: {result}"
    assert router.calls == [("gpu_status", {})], "router not called correctly"
    skill = store.get(sid)
    assert skill["usage_count"] == 1, "usage not recorded on replay"
    # unknown skill -> blocked, no crash
    bad = engine.run_skill("nope")
    assert bad.get("blocked") is True
    print("  [ok] SkillEngine replay + usage recording")


def test_adapt_prompt_names_tool(tmp: Path) -> None:
    class PromptLLM:
        def __init__(self):
            self.prompt = ""

        def chat(self, messages, **kwargs):
            self.prompt = messages[0]["content"]
            return {"message": {"content": "{}"}}

    llm = PromptLLM()
    engine = SkillEngine(SkillStore(str(tmp / "skills.json")), llm=llm)
    skill = {"name": "check gpu", "goal": "check system status",
             "steps": [{"tool": "gpu_status"}]}
    engine._adapt_args(skill, 0, {}, {"goal": skill["goal"]})
    assert "tool gpu_status" in llm.prompt, llm.prompt
    print("  [ok] SkillEngine replay prompt includes tool name")


def test_semantic(tmp: Path) -> None:
    sem = SemanticMemory(embedder=Embedder.__new__(Embedder))
    # force hash backend deterministically for the test
    from memory.embeddings import HashEmbedder
    sem._embedder = HashEmbedder()
    sem.add("gpu: NVIDIA RTX 3050 Laptop 4GB", kind="fact")
    sem.add("user prefers Persian responses", kind="fact")
    sem.add("Task 'browser launch' -> opened chrome", kind="episode")
    hits = sem.search("مشخصات کارت گرافیک چیست؟", k=2)
    assert hits, "semantic search returned nothing"
    assert hits[0]["kind"] == "fact"
    assert "gpu" in hits[0]["text"].casefold() or "3050" in hits[0]["text"]
    print(f"  [ok] SemanticMemory retrieval (top hit: {hits[0]['text'][:40]})")


def test_fts(tmp: Path) -> None:
    db = str(tmp / "ev.db")
    mem = LongTermMemory(db)
    mem.remember_event("opened browser to check gpu temperature", {})
    mem.remember_event("ran apt upgrade on the laptop", {})
    hits = mem.search_events("gpu temperature", limit=3)
    assert hits and "gpu" in hits[0]["summary"], f"FTS miss: {hits}"
    sem = SemanticMemory()
    mem.attach_semantic(sem)
    sem.add("gpu temperature was 60C during the check", kind="episode")
    texts = mem.search_semantic("دمای gpu", limit=3)
    assert texts, "search_semantic returned nothing"
    mem.remember_session_message("web-session-a", "user",
                                 "Where did I save the GPU report?")
    mem.remember_session_message("web-session-a", "assistant",
                                 "The GPU report is in reports/system.txt")
    mem.remember_session_message("web-session-b", "assistant",
                                 "GPU temperature was stable")
    hits = mem.search_session_messages("GPU report", limit=10)
    assert len(hits) == 3 and all("gpu" in hit["content"].casefold()
                                  or "report" in hit["content"].casefold()
                                  for hit in hits), hits
    scoped = mem.search_session_messages("GPU", session_id="web-session-a")
    assert len(scoped) == 2 and all(
        hit["session_id"] == "web-session-a" for hit in scoped), scoped
    mem.close()
    mem = LongTermMemory(db)
    persisted = mem.search_session_messages("system.txt")
    assert persisted and persisted[0]["role"] == "assistant", persisted
    mem.close()
    print("  [ok] LongTermMemory FTS5 + semantic + session search")


def test_tool_registration(tmp: Path) -> None:
    from core.tool_router import ToolOrchestrator
    from tools.router import ToolRouter
    from tools.base import Tool
    from core.capability_manager import CapabilityManager

    store = SkillStore(str(tmp / "skills.json"))
    router = FakeRouter()
    engine = SkillEngine(store, llm=FakeLLM(), router=router)
    native = ToolRouter(workspace=tmp)
    history_mem = LongTermMemory(str(tmp / "history.db"))
    native.register(Tool(
        "session_search", "Search saved conversations",
        {"type": "object", "properties": {
            "query": {"type": "string"}}},
        lambda query, **_: {"ok": True,
                            "results": history_mem.search_session_messages(query)},
        level=0, required=["query"]))
    orchestrator = ToolOrchestrator(native, type("R", (), {
        "tool_schemas": lambda self: []})(), CapabilityManager({}))
    # attach the fake router for replay dispatch (engine.router.native path)
    engine.router = type("E", (), {"native": native})()  # wrapper
    engine.router.native = native
    import skills.tools as skill_tools
    skill_tools.register(engine)
    names = orchestrator.names()
    for expected in ("skill_list", "skill_run", "skill_create",
                     "session_search"):
        assert expected in names, f"{expected} not registered"
    result = native.dispatch("skill_list", {})
    assert result.get("ok") is True, f"skill_list dispatch failed: {result}"
    history_mem.remember_session_message("s1", "user", "find the GPU report")
    found = native.dispatch("session_search", {"query": "GPU report"})
    assert found["ok"] and found["results"], found
    # register a skill then run it via the tool surface
    store.create("demo", "دمو", steps=[{"tool": "gpu_status", "args": {}}])
    # replay dispatches through the engine's own router (the FakeRouter here)
    engine.router = router
    result = native.dispatch("skill_run", {"name": "demo"})
    assert result.get("ok") is True, f"skill_run via orchestrator failed: {result}"
    history_mem.close()
    print("  [ok] skill_* tools registered on orchestrator")


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        print("Phase 7 smoke:")
        test_store(tmp)
        test_engine(tmp)
        test_replay(tmp)
        test_adapt_prompt_names_tool(tmp)
        test_semantic(tmp)
        test_fts(tmp)
        test_tool_registration(tmp)
    print("ALL PASSED ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
