"""Live latency check against real Ollama (qwen3.5:4b, think off, keep_alive).

Measures: model warm time, first light question (turbo streamed), and a
tool-requiring task (ReAct round-trip). All offline, uses local GPU.
"""
import sys, json, time
sys.path.insert(0, '.')

cfg = json.load(open('config.json'))
o = cfg['ollama']
model = o['models']['main']

from models.llm import OllamaClient
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

client = OllamaClient(host=o['host'], model=model, timeout=o['timeout'],
                      keep_alive=o.get('keep_alive', '30m'),
                      num_predict=o.get('max_tokens', 512),
                      num_ctx=o.get('num_ctx', 8192),
                      think=o.get('think', False))
print('model available:', client.is_available())

t0 = time.time()
client.warm(model)
print(f'warm (model into VRAM): +{time.time()-t0:.2f}s')

long_mem = LongTermMemory(db_path='/tmp/ev_latency.db')
short_mem = ShortTermMemory(10)
episodic = EpisodicMemory(long_mem)
perm = PermissionEngine(auto_approve_until=2, approval=Approval(confirm=False))
native = ToolRouter(workspace=None, perm=perm)
mcp = MCPRegistry()
caps = CapabilityManager(cfg)
orch = ToolOrchestrator(native, mcp, caps, perm=perm)
mrouter = ModelRouter(client=client, preferred=o['models'])
mrouter.refresh()
print('router pool (local):', mrouter.pool())
ctx = ContextBuilder(cfg, long_mem, orch.names())
agent = Agent(client, orch, ctx, short_mem, episodic, mrouter,
              max_iterations=6, turbo_threshold=0.3)

# 1) turbo streamed light question
t0 = time.time()
deltas = []
ok = agent.run('سلام، چه خبر؟', on_stream=deltas.append)
print(f'Q1 streamed deltas: {len(deltas)}, answer chars: {len(ok)}')
print(f'Q1 latency: {time.time()-t0:.2f}s   -> {ok[:80]!r}')

# 2) tool task (ReAct)
t0 = time.time()
out = agent.run('فقط یک دستور ساده بزن: echo hello-fast رو اجرا کن')
print(f'Q2 (tool) latency: {time.time()-t0:.2f}s   -> {out[:80]!r}')

long_mem.close()