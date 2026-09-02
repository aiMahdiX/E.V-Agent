"""Smoke test for the hybrid tool architecture + MCP + dynamic model router."""
import sys, json
sys.path.insert(0, '.')

cfg = json.load(open('config.json'))

# ---- Capability Manager ------------------------------------------ #
from core.capability_manager import CapabilityManager
caps = CapabilityManager(cfg)
assert caps.has('vision'), 'vision capability missing'
assert caps.has('shell'), 'native shell capability missing'
print('capabilities:', len(caps.all()))
print('\n'.join('  ' + c.summary() for c in caps.all()))

# ---- MCP client round-trip (echo demo server) ---------------------- #
from tools.mcp.client import MCPClient
from tools.mcp.registry import MCPRegistry
from tools.mcp import discovery

reg = MCPRegistry()
connected = discovery.connect(reg, {"mcp": {"servers_dir": "mcp_servers"}})
assert 'echo_demo' in connected, f'echo_demo not connected: {connected}'
echo_tools = reg.tool_schemas()
names = [t['function']['name'] for t in echo_tools]
assert 'echo_demo_echo' in names, names
print('MCP connected:', connected, '-> tools:', names)

res = reg.call('echo_demo_echo', {'text': 'hello ev'})
assert 'hello ev' in str(res), res
print('MCP tool call round-trip OK:', res['content'][0]['text'])
reg.close_all()

# ---- Tool Orchestrator routes MCP vs native ------------------------ #
from tools.mcp.registry import MCPRegistry
from tools.router import ToolRouter
from security.permissions import PermissionEngine
from security.approval import Approval
from core.tool_router import ToolOrchestrator

reg = MCPRegistry()
discovery.connect(reg, {"mcp": {"servers_dir": "mcp_servers"}})
caps = CapabilityManager(cfg)
# patch the echo demo as a capability with the demo tool
caps.register(__import__('core.capability_manager', fromlist=['Capability']).Capability(
    'echo_demo', 'mcp', priority=90, provider='echo_demo',
    tools=['echo_demo_echo'], needs_approval=False))
perm = PermissionEngine(auto_approve_until=2, approval=Approval(confirm=False))
native = ToolRouter(workspace='.', perm=perm)
orch = ToolOrchestrator(native, reg, caps, perm=perm)
print('orchestrator names include mcp:', 'echo_demo_echo' in orch.names())
res = orch.dispatch('echo_demo_echo', {'text': 'via orchestrator'})
assert 'via orchestrator' in str(res), res
assert orch.last_route[1][0] == 'mcp', orch.last_route
print('orchestrator mcp route OK:', orch.last_route)
res = orch.dispatch('shell_run_command', {'command': 'echo native-check'})
assert res.get('exit_code') == 0
print('orchestrator native route OK:', res['stdout'].strip())
reg.close_all()

# ---- Dynamic model selection from "installed" pool ---------------- #
from core.router import ModelRouter
pool0 = ['llama3.2:3b', 'qwen3:8b', 'gemma4:12b']
PREF = {'main': 'qwen3.5:4b', 'fast': 'qwen3.5:4b'}  # explicit, not live cfg
# exact preferred model not installed locally -> smallest available wins
mr = ModelRouter(preferred=PREF, available=pool0)
assert mr.choose('سلام') == 'llama3.2:3b', mr.choose('سلام')
# complex task -> biggest available
mr3 = ModelRouter(preferred={}, available=pool0)
assert mr3.choose('سیستم رو دیباگ کن و سرویس رو درست کن') == 'gemma4:12b'
# with the exact preferred model present, it wins
mr5 = ModelRouter(preferred=PREF,
                  available=['llama3.2:3b', 'qwen3.5:4b', 'qwen3:8b'])
assert mr5.choose('سلام') == 'qwen3.5:4b', mr5.choose('سلام')
# cloud preferences are reachable even when absent from the local listing
mr6 = ModelRouter(preferred={'main': 'minimax-m3:cloud',
                             'fast': 'minimax-m3:cloud'},
                  available=['llama3.2:3b', 'qwen3.5:4b'])
assert mr6.choose('سلام') == 'minimax-m3:cloud', mr6.choose('سلام')
print('dynamic model routing OK (small/llama3.2:3b big/gemma4:12b preferred/qwen3:4b)')
print('ALL HYBRID SMOKE TESTS PASSED')