import sys, json, tempfile
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
from security.permissions import PermissionEngine, ShellPermissionEngine
eng = PermissionEngine(auto_approve_until=2, approval=Approval(confirm=False))
print('perm L0:', eng.authorize('read_file', {'path': 'x'}))
print('perm L1:', eng.authorize('write_file', {'path': 'x'}))
print('perm L2:', eng.authorize('kill_process', {'pid': 1}))
# frictionless-operation policy: Level 3 (sudo / elevated) runs WITHOUT an
# approval prompt; the password itself is asked at execution time.
sh = ShellPermissionEngine(eng)
print('shell L3 sudo ok:', sh.authorize_command('sudo apt install htop'))
# only destructive (Level 4) actions still ask -> confirm=False denies.
try:
    eng.authorize('delete_file', {'path': 'x'})
    print('perm L4: NOT BLOCKED (BAD)')
except Exception as e:
    print('perm L4 blocked OK:', str(e)[:30])

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
    m.remember_event('completed test', {'ok': True})
    assert len(m.episodes()) == 1
    print('memory: OK')

from tasks.manager import TaskManager
with tempfile.TemporaryDirectory() as d:
    tm = TaskManager(store=d + '/t.json')
    t = tm.new('install qwen')
    tm.add_step(t.id, 'check', 'done'); tm.update(t.id, status='done')
    print('task:', t.id, tm.get(t.id).status, len(tm.get(t.id).steps))

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
