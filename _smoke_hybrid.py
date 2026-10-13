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
assert 'messaging' in connected, f'messaging MCP not connected: {connected}'
echo_tools = reg.tool_schemas()
names = [t['function']['name'] for t in echo_tools]
assert 'echo_demo_echo' in names, names
assert 'messaging_list_channels' in names, names
assert 'messaging_recent_messages' in names, names
assert 'messaging_extract_tasks' in names, names
print('MCP connected:', connected, '-> tools:', names)

res = reg.call('echo_demo_echo', {'text': 'hello ev'})
assert 'hello ev' in str(res), res
print('MCP tool call round-trip OK:', res['content'][0]['text'])
missing = reg.call('messaging_list_channels', {'platform': 'telegram'})
assert 'not configured' in str(missing).lower(), missing
print('messaging MCP missing-credential guard OK')
task_payload = json.loads(reg.call(
    'messaging_extract_tasks', {
        'messages': [
            {'id': 'm1', 'text': 'Please review the release plan'},
            {'id': 'm2', 'text': 'URGENT: fix the production blocker'},
            {'id': 'm3', 'text': 'hello there'},
        ],
    })['content'][0]['text'])
assert [item['id'] for item in task_payload['tasks']] == ['m2', 'm1'], task_payload
assert task_payload['tasks'][0]['priority'] == 'urgent', task_payload
print('messaging MCP task extraction and priority OK')
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
for name in connected:
    client = reg.clients[name]
    caps.register_mcp_server(
        name, [tool.get('name') for tool in client.tools_cache
               if tool.get('name')])
browser_cap = caps.by_tool('browser_open', 'mcp')
vision_cap = caps.by_tool('vision_describe', 'mcp')
assert 'shell_run_command' in caps.native_tools()
assert 'gpu_temperature' in caps.native_tools()
assert browser_cap and browser_cap.priority == 70
assert browser_cap.needs_approval is True
assert vision_cap and vision_cap.priority == 90
assert vision_cap.needs_approval is False
# patch the echo demo as a capability with the demo tool
caps.register(__import__('core.capability_manager', fromlist=['Capability']).Capability(
    'echo_demo', 'mcp', priority=90, provider='echo_demo',
    tools=['echo_demo_echo'], needs_approval=False))
perm = PermissionEngine(auto_approve_until=2, approval=Approval(confirm=False))
native = ToolRouter(workspace='.', perm=perm)

class PriorityMCP:
    def tool_schemas(self, provider=None):
        schemas = {
            'browser': ('browser_open', 'MCP priority probe'),
            'gpu-probe': ('gpu_status', 'Lower-priority MCP probe'),
        }
        return [
            {'type': 'function', 'function': {
                'name': tool_name,
                'description': description,
                'parameters': {'type': 'object', 'properties': {}}}}
            for source, (tool_name, description) in schemas.items()
            if provider in (None, source)
        ]

    def call(self, name, arguments, provider=None):
        return {'ok': True, 'provider': provider, 'tool': name}

approval_calls = []
priority_perm = PermissionEngine(
    auto_approve_until=2,
    approval=Approval(confirm=False,
                      ask_hook=lambda **kwargs:
                      approval_calls.append(kwargs) or True))
priority_orch = ToolOrchestrator(
    native, PriorityMCP(), caps, perm=priority_perm)
browser_schema = next(schema for schema in priority_orch.schemas()
                      if schema['function']['name'] == 'browser_open')
assert browser_schema['function']['description'] == 'MCP priority probe'
priority_result = priority_orch.dispatch('browser_open', {'url': 'https://example.test'})
assert priority_result['provider'] == 'browser', priority_result
assert approval_calls, 'MCP needs_approval policy was not applied'
assert priority_perm.reviewed[-1]['outcome'] == 'allowed'

from tools.base import Tool
native.register(Tool(
    'gpu_status', 'Native priority probe',
    {'type': 'object', 'properties': {}},
    lambda **_: {'provider': 'native'}))
caps.register(__import__('core.capability_manager', fromlist=['Capability']).Capability(
    'gpu_mcp_probe', 'mcp', priority=60, provider='gpu-probe',
    tools=['gpu_status'], needs_approval=False))
gpu_schema = next(schema for schema in priority_orch.schemas()
                  if schema['function']['name'] == 'gpu_status')
assert gpu_schema['function']['description'] == 'Native priority probe'
assert priority_orch.dispatch('gpu_status', {})['provider'] == 'native'

orch = ToolOrchestrator(native, reg, caps, perm=perm)
print('orchestrator names include mcp:', 'echo_demo_echo' in orch.names())
res = orch.dispatch('echo_demo_echo', {'text': 'via orchestrator'})
assert 'via orchestrator' in str(res), res
assert orch.last_route[1][0] == 'mcp', orch.last_route
print('orchestrator mcp route OK:', orch.last_route)
caps.register(__import__('core.capability_manager', fromlist=['Capability']).Capability(
    'echo_demo', 'mcp', priority=90, provider='echo_demo',
    tools=['echo_demo_echo'], needs_approval=True))
approval_test = PermissionEngine(auto_approve_until=4,
                                 approval=Approval(confirm=False))
guarded = ToolOrchestrator(native, reg, caps, perm=approval_test)
blocked = guarded.dispatch('echo_demo_echo', {'text': 'must approve'})
assert blocked.get('blocked') is True, blocked
print('MCP needs_approval enforced above auto-approval threshold: OK')
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

# ---- Provider model aggregation ----------------------------------- #
from models.llm import ProviderClient

class ModelProvider:
    def __init__(self, models):
        self.models = models

    def list_models(self):
        return self.models

providers = ProviderClient(
    {'local': ModelProvider(['qwen3.5:4b']),
     'cloud': ModelProvider(['gpt-4o-mini'])},
    default='local')
assert providers.list_models() == ['local:qwen3.5:4b', 'cloud:gpt-4o-mini'], \
    providers.list_models()
print('provider model aggregation OK')

print('ALL HYBRID SMOKE TESTS PASSED')