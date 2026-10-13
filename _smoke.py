import os, sys, json, tempfile
sys.path.insert(0, '.')
from security import policy

checks = [
    ('pwd', 0), ('nvidia-smi', 0), ('ls -la /home', 0),
    ('journalctl -u ollama', 0), ('mkdir test && touch a.txt', 1),
    ('pip install requests', 2), ('systemctl restart ollama', 2),
    ('sudo apt install htop', 3), ('rm -rf /tmp/x', 4),
]
for cmd, want in checks:
    got, reason = policy.classify_shell_command(cmd)
    assert got == want, f'{cmd!r} -> {got} != {want}'
print('policy: ALL %d PASS' % len(checks))

from security.approval import Approval
from security.permissions import (PermissionDenied, PermissionEngine,
                                  ShellPermissionEngine)
eng = PermissionEngine(auto_approve_until=2, approval=Approval(confirm=False))
print('perm L0:', eng.authorize('read_file', {'path': 'x'}))
print('perm L1:', eng.authorize('write_file', {'path': 'x'}))
print('perm L2:', eng.authorize('kill_process', {'pid': 1}))
# Privileged commands require approval even when the configured threshold
# would otherwise auto-approve them.
sh = ShellPermissionEngine(eng)
try:
    sh.authorize_command('sudo apt install htop')
    raise AssertionError('privileged shell command should require approval')
except PermissionDenied:
    print('shell L3 blocked without approval: OK')
try:
    eng.authorize('delete_file', {'path': 'x'})
    raise AssertionError('destructive action should require approval')
except PermissionDenied:
    print('perm L4 blocked OK')

from tools.router import ToolRouter
router = ToolRouter(workspace=None, perm=eng)
print('registered tools:', len(router.names()))
res = router.dispatch('shell_run_command', {'command': 'echo hi'})
print('shell tool:', res['exit_code'], res['stdout'].strip())
res2 = router.dispatch('fs_list_directory', {'path': '.'})
print('fs tool entries:', len(res2['entries']))
res3 = router.dispatch('gpu_status', {})
print('gpu available:', res3.get('available'))

from memory.long_term import LongTermMemory
with tempfile.TemporaryDirectory() as d:
    m = LongTermMemory(db_path=d + '/ev.db')
    m.remember('user_name', 'Mahdi')
    assert m.recall('user_name') == 'Mahdi'
    m.remember_preference('preferred_language', 'Persian')
    m.remember_preference('desktop_style', 'local-first, minimal prompts')
    assert m.get_profile()['preferred_language'] == 'Persian'
    assert 'local-first' in m.get_profile()['desktop_style']
    m.remember_event('completed test', {'ok': True})
    assert len(m.episodes()) == 1
    print('memory: OK')

from tools.integrations import INTEGRATION_TOOLS, extract_tasks
assert any(t.name == 'telegram_get_messages' for t in INTEGRATION_TOOLS), 'telegram connector missing'
assert any(t.name == 'gmail_get_recent_messages' for t in INTEGRATION_TOOLS), 'gmail connector missing'
assert any(t.name == 'google_calendar_list_events' for t in INTEGRATION_TOOLS), 'calendar connector missing'
assert any(t.name == 'notion_list_pages' for t in INTEGRATION_TOOLS), 'notion connector missing'
assert any(t.name == 'slack_get_channels' for t in INTEGRATION_TOOLS), 'slack connector missing'
assert any(t.name == 'github_triage_tasks' for t in INTEGRATION_TOOLS), 'github triage connector missing'
assert any(t.name == 'jira_get_issues' for t in INTEGRATION_TOOLS), 'jira connector missing'
assert any(t.name == 'linear_get_issues' for t in INTEGRATION_TOOLS), 'linear connector missing'
assert any(t.name == 'outlook_calendar_events' for t in INTEGRATION_TOOLS), 'outlook connector missing'
assert any(t.name == 'daily_brief' for t in INTEGRATION_TOOLS), 'daily brief connector missing'
extracted = extract_tasks({
    'github': {'ok': True, 'tasks': [{
        'id': 17, 'title': 'Fix production login bug', 'state': 'open',
        'labels': ['critical'], 'html_url': 'https://example.test/17',
    }]},
    'gmail': {'ok': True, 'messages': [{
        'id': 'm1', 'subject': 'Please review the release plan',
        'from': 'team@example.test',
    }]},
})
assert extracted[0]['priority'] == 'urgent', extracted
assert extracted[0]['source'] == 'github' and extracted[0]['actionable'], extracted
assert any(item['source'] == 'gmail' for item in extracted), extracted
print('platform integrations: registry OK')

from tasks.manager import TaskManager
from tasks.scheduler import Scheduler
from tasks.workflow import WorkflowEngine
from core.briefing import build_brief
from sensors.event_bus import EventBus
from sensors.system_monitor import SystemMonitor
from main import due_task_notification
from memory.semantic import SemanticMemory
from tasks.queue import EventDrivenTaskQueue
from core.context import ContextBuilder
from core.workflow import DesktopWorkflow

bus = EventBus()
seen = []
bus.subscribe('CPU_HIGH', lambda payload: seen.append(payload.get('value')))
bus.publish('CPU_HIGH', {'value': 91})
assert seen == [91], seen
print('event bus: publish OK')

alert_bus = EventBus()
alerts = []
alert_bus.subscribe('CPU_HIGH', lambda payload: alerts.append(payload['value']))
monitor = SystemMonitor(alert_bus, cpu_high_threshold=2.0)
for load in (2.5, 3.0, 2.2, 1.8, 2.4):
    monitor._publish_cpu_alert(load)
assert alerts == [2.5], alerts
monitor._publish_cpu_alert(1.5)
monitor._publish_cpu_alert(2.4)
assert alerts == [2.5, 2.4], alerts
print('system monitor: one CPU alert per high-load episode')

cpu_reminder = type('Task', (), {
    'id': 'TASK-CPU', 'description': 'Check high CPU load alert (2.5 loadavg).',
    'due_count': 1,
})()
regular_reminder = type('Task', (), {
    'id': 'TASK-REGULAR', 'description': 'Check disk space', 'due_count': 2,
})()
assert due_task_notification(cpu_reminder) is None
assert '[task due] TASK-REGULAR' in due_task_notification(regular_reminder)
print('scheduler notifications: CPU alerts suppressed, user reminders kept')

with tempfile.TemporaryDirectory() as d:
    tm = TaskManager(store=d + '/q.json')
    scheduler = Scheduler(tm, poll_seconds=0.1)
    q = EventDrivenTaskQueue(task_manager=tm, scheduler=scheduler)
    q.subscribe(bus)
    bus.publish('CPU_HIGH', {'event': 'CPU_HIGH', 'value': 91})
    due = [t for t in tm.all() if 'CPU' in t.description]
    assert due, 'proactive queue should raise a reminder task from CPU_HIGH'
    print('proactive task queue: cpu alert -> reminder task OK')

sem = SemanticMemory()
sem.add('Mahdi prefers local-first Persian desktop assistant with GPU access')
sem.add('Project runs on Ubuntu with Ollama and local tasks')
results = sem.search('Persian local assistant for desktop', k=2)
assert results and any('Persian' in r['text'].lower()
                       or 'local-first' in r['text'].lower()
                       for r in results), results
class DummyMemory:
    def all_facts(self):
        return {'user_name': 'Mahdi'}
    def search_events(self, q, limit=3):
        return []
    def search_semantic(self, q, limit=3):
        return ['Mahdi prefers local-first Persian desktop assistant', 'Project runs on Ubuntu and local GPU tools']

ctx = ContextBuilder({'agent': {'name': 'E.V.', 'user_name': 'Mahdi', 'language': 'Persian'}}, DummyMemory(), ['shell_run_command'])
prompt = ctx.system_prompt('desktop Persian assistant')
assert 'Relevant semantic memories' in prompt and 'Persian desktop assistant' in prompt, prompt
assert 'User profile' in prompt or 'Profile' in prompt, prompt
print('semantic memory: retrieval OK')

with tempfile.TemporaryDirectory() as d:
    log_path = d + '/desktop.jsonl'
    wf = DesktopWorkflow(audit_path=log_path)
    wf.register_tool('capture_screen', lambda path='data/screenshots/test.png', **_: {'ok': True, 'path': path})
    wf.register_tool('browser_read', lambda url='https://example.com', **_: {'ok': True, 'text': 'Example Domain'})
    assert wf.run('capture_screen', {'path': 'data/screenshots/test.png'})['ok']
    assert wf.run('browser_read', {'url': 'https://example.com'})['ok']
    try:
        wf.run('shell_run_command', {'command': 'echo hi'})
        raise AssertionError('unsafe shell command should be blocked by workflow allowlist')
    except ValueError:
        pass
    assert os.path.exists(log_path), 'desktop workflow audit log missing'
    print('desktop workflow: safe audit + allowlist OK')

    class RecoveryLLM:
        def __init__(self):
            self.calls = 0
        def chat(self, messages, tools=None, model=None, **kw):
            self.calls += 1
            if self.calls == 1:
                return {"message": {"content": "بررسی می‌کنم.",
                                    "tool_calls": [{"function": {"name": "missing_tool", "arguments": {}}}]}}
            if any("شکست خورد" in (m.get('content') or '') for m in messages):
                return {"message": {"content": "بازیابی فعال شد.",
                                    "tool_calls": [{"function": {"name": "gpu_status", "arguments": {}}}]}}
            return {"message": {"content": "وضعیت GPU بررسی شد.", "tool_calls": []}}

    class RecoveryRouter:
        def schemas(self):
            return [{"type": "function", "function": {"name": "gpu_status", "parameters": {"type":"object","properties":{}}}}]
        def dispatch(self, name, args):
            if name == 'gpu_status':
                return {'ok': True, 'available': True}
            return {'error': f'unknown tool: {name}', 'blocked': False}
        def names(self):
            return ['gpu_status']

    recovery_llm = RecoveryLLM()
    recovery_agent = __import__('core.agent', fromlist=['Agent']).Agent(
        recovery_llm, RecoveryRouter(), ctx, __import__('memory.short_term').short_term.ShortTermMemory(10), __import__('memory.episodic').episodic.EpisodicMemory(__import__('memory.long_term').long_term.LongTermMemory(db_path=d + '/recovery.db')),
        __import__('core.router').router.ModelRouter(preferred={'main': 'qwen3.5:4b'}, available=['qwen3.5:4b']), max_iterations=4)
    recovery_out = recovery_agent.run('وضعیت GPU را بررسی کن')
    assert recovery_llm.calls >= 2, recovery_llm.calls
    assert 'GPU' in recovery_out or 'بازیابی' in recovery_out or 'بررسی' in recovery_out, recovery_out
    print('agent recovery: failed tool -> safe retry OK')

with tempfile.TemporaryDirectory() as d:
    tm = TaskManager(store=d + '/t.json')
    t = tm.new('install qwen')
    tm.add_step(t.id, 'check', 'done'); tm.update(t.id, status='done')
    print('task:', t.id, tm.get(t.id).status, len(tm.get(t.id).steps))

    clock = [1000.0]
    due_events = []
    scheduler = Scheduler(tm, on_due=due_events.append,
                          poll_seconds=0.1, clock=lambda: clock[0])
    one_shot = tm.new('check disk')
    scheduler.schedule(one_shot.id, delay_seconds=10)
    assert not scheduler.run_due(now=1009)
    assert len(scheduler.run_due(now=1010)) == 1
    assert tm.get(one_shot.id).status == 'due'
    assert tm.get(one_shot.id).next_run_at is None

    recurring = tm.new('check GPU')
    scheduler.schedule(recurring.id, delay_seconds=5, interval_seconds=60)
    overdue = scheduler.run_due(now=1185)
    assert len(overdue) == 1 and overdue[0].due_count == 4, overdue
    assert tm.get(recurring.id).next_run_at == 1245
    assert scheduler.cancel(recurring.id)

    restored = TaskManager(store=d + '/t.json')
    assert restored.get(one_shot.id).status == 'due'
    assert restored.get(recurring.id).next_run_at is None
    assert len(due_events) == 2
    print('scheduler: one-shot, recurring catch-up, cancel, persistence OK')

    workflow = tm.new('release workflow')
    attempts = {'verify': 0}

    def execute(step, task):
        if step['name'] == 'verify':
            attempts['verify'] += 1
            if attempts['verify'] == 1:
                raise RuntimeError('temporary failure')
        return {'step': step['name'], 'ok': True}

    engine = WorkflowEngine(tm, max_retries=1)
    result = engine.run(workflow.id, [
        {'name': 'prepare'}, {'name': 'verify'}, {'name': 'deploy'}
    ], execute)
    assert result['ok'] and result['completed'] == 3, result
    restored_workflow = tm.get(workflow.id)
    assert restored_workflow.status == 'done'
    assert len(restored_workflow.steps) >= 4, restored_workflow.steps
    print('workflow: checkpoints, retry, completion OK')

    from ui.cli.repl import CLI
    fake_agent = type('FakeAgent', (), {
        'memory': type('Memory', (), {'clear': lambda self: None})(),
        'run': lambda self, prompt: 'completed: ' + prompt,
    })()
    cli = CLI(fake_agent, {}, on_tasks=tm.all,
              on_task_new=tm.new,
              on_brief=lambda: {'summary': 'Local briefing: 1 local task',
                                'tasks': [{'title': 'check disk', 'priority': 'medium'}]},
              on_schedule=lambda tid, delay, interval=None:
                  scheduler.schedule(tid, delay, interval),
              on_cancel_schedule=scheduler.cancel,
              on_run_task=lambda tid: 'completed: ' + tm.get(tid).description,
              on_integrations=lambda: ['telegram_get_messages', 'gmail_get_recent_messages', 'google_calendar_list_events'])
    assert cli._dispatch_slash('/schedule in 10m check disk')
    assert cli._dispatch_slash('/integrations')
    assert cli._dispatch_slash('/brief')
    scheduled = [task for task in tm.all()
                 if task.description == 'check disk'
                 and task.next_run_at is not None]
    assert scheduled
    assert cli._dispatch_slash('/cancel ' + scheduled[0].id)
    assert tm.get(scheduled[0].id).next_run_at is None
    assert cli._dispatch_slash('/run ' + one_shot.id)
    print('scheduler CLI: schedule, cancel, explicit run OK')

class BriefMCP:
    def call(self, name, arguments):
        if name == 'messaging_list_channels':
            return {'content': [{'type': 'text', 'text': json.dumps({
                'ok': True, 'channels': [{'id': 'chat-1'}]})}]}
        if name == 'messaging_recent_messages':
            return {'content': [{'type': 'text', 'text': json.dumps({
                'ok': True, 'messages': [{'id': 'msg-1',
                    'text': 'URGENT: review deployment'}]})}]}
        assert name == 'messaging_extract_tasks'
        return {'content': [{'type': 'text', 'text': json.dumps({
            'ok': True,
            'tasks': [{'id': 'msg-1', 'title': 'URGENT: review deployment',
                       'priority': 'urgent', 'source': 'telegram'}],
        })}]}

    os.environ.setdefault('TELEGRAM_BOT_TOKEN', 'smoke-only-token')
brief = build_brief([], mcp=BriefMCP(), include_external=False)
assert brief['tasks'][0]['title'] == 'URGENT: review deployment', brief
assert brief['tasks'][0]['priority'] == 'urgent', brief
print('local briefing: messaging MCP task merge OK')

cfg = json.load(open('config.json'))
from core.router import ModelRouter
mr = ModelRouter(preferred=cfg['ollama']['models'], available=[])
print('route simple ->', mr.choose('سلام') or '(empty)')
mr2 = ModelRouter(preferred=cfg['ollama']['models'], available=[])
print('route task   ->', mr2.choose('Ollama رو تعمیر کن و سرویسش رو بازنشانی کن') or '(empty)')

# --- regression: every registered tool must have an explicit permission
# level, otherwise action_level() escalates it to L3 and the user gets
# spammed with approval prompts (the "camera asks 4 times" bug).
from tools.router import ToolRouter as _TR
from security.policy import ACTION_LEVELS as _AL
_tr = _TR(workspace='.')
_missing = [n for n in _tr.names() if n not in _AL]
assert not _missing, f"tools missing from ACTION_LEVELS: {_missing}"
print('permission levels: all %d registered tools classified' % len(_tr.names()))
print('ALL SMOKE TESTS PASSED')
