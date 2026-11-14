"""Pinned-package scratch proof; python3 docs/adr/data/0019_delegation_probe.py.

Only public npm/GitHub downloads; everything installed is inside a new cache
folder removed on exit. Hook payloads are data, never executed. No model runs.
"""
import base64, hashlib, json, os, runpy, shlex, statistics, subprocess, sys, tarfile, tempfile, time
from pathlib import Path
from urllib.request import urlopen

repo = Path(__file__).resolve().parents[3]
api = runpy.run_path(str(repo / 'deploy/wsl/meridian-omc.py'))
cache = Path.home() / '.cache/meridian'
cache.mkdir(parents=True, exist_ok=True)
results = {}

def run(cmd, **kw):
    result = subprocess.run(cmd, text=True, capture_output=True, **kw)
    if result.returncode:
        print(result.stdout, result.stderr, file=sys.stderr)
    result.check_returncode()
    return result

with tempfile.TemporaryDirectory(prefix='omc-delegation-', dir=cache) as folder:
    root = Path(folder)
    archive = root / 'package.tgz'
    with urlopen('https://registry.npmjs.org/oh-my-claude-sisyphus/-/oh-my-claude-sisyphus-5.8.4.tgz') as response:
        archive.write_bytes(response.read())
    integrity = 'sha512-' + base64.b64encode(hashlib.sha512(archive.read_bytes()).digest()).decode()
    assert integrity == 'sha512-6J2v4YomI8vK4mmhDTMV8SqS2Bj4dUvPz3ApapKsYVN6P04rGs0/L78p3/Rda0mq1UuHOYII8ubj+ehlgmxxwA=='
    with tarfile.open(archive) as package:
        package.extractall(root, filter='data')
    pinned = root / 'pinned-pre-tool-use.mjs'
    with urlopen('https://raw.githubusercontent.com/Yeachan-Heo/oh-my-claudecode/b93059fb7c10ae28934a0bc950e26c9a17437a94/templates/hooks/pre-tool-use.mjs') as response:
        pinned.write_bytes(response.read())
    assert pinned.read_bytes() == (root / 'package/templates/hooks/pre-tool-use.mjs').read_bytes()
    results['pin'] = {'version': api['VERSION'], 'npm_integrity_verified': True,
                      'hook_matches_git_pin': True, 'hook_sha256': api['digest'](pinned)}
    home = root / 'home'; home.mkdir()
    claude = home / '.claude'
    user = home / '.config/claude-omc/config.jsonc'
    staging = root / 'staging'
    adapter = home / 'bin/meridian-omc'; adapter.parent.mkdir()
    adapter.write_bytes((repo / 'deploy/wsl/meridian-omc.py').read_bytes())
    api['write'](claude / 'settings.json', {'hooks': {
        event: [{'hooks': [{'type': 'command', 'command': 'sh /fixture/.orca/agent-hooks/claude-hook.sh'}]}]
        for event in api['HOOKS']}})
    api['stage'](claude, staging)
    api['write'](root / 'empty.json', {})
    # Whitelist environment: never inherit real credential or provider configuration.
    env = dict(PATH=os.environ['PATH'], HOME=str(home), CLAUDE_CONFIG_DIR=str(claude),
               XDG_CONFIG_HOME=str(home / '.config'), OMC_HOME=str(root / 'runtime'),
               OMC_STATE_DIR=str(root / 'state'), CODEX_HOME=str(root / 'codex'),
               CLAUDE_MCP_CONFIG_PATH=str(root / 'empty.json'),
               OMC_MCP_REGISTRY_PATH=str(root / 'empty.json'), OMC_NOTIFY='0', OMC_OPENCLAW='0')
    (root / 'empty.npmrc').touch()
    npmenv = dict(env, NPM_CONFIG_CACHE=str(root / 'npm-cache'),
                  NPM_CONFIG_USERCONFIG=str(root / 'empty.npmrc'))
    run(['npm', 'install', '--prefix', str(root / 'npm'), '--ignore-scripts', '--no-audit',
         '--no-fund', str(archive)], env=npmenv, cwd=root)
    installed = root / 'npm/node_modules/oh-my-claude-sisyphus'
    setupenv = dict(env, CLAUDE_CONFIG_DIR=str(staging), XDG_CONFIG_HOME=str(root / 'config'))
    run(['node', str(installed / 'bin/oh-my-claudecode.js'), 'setup', '--no-plugin', '--force', '--quiet'],
        env=setupenv, cwd=root, input='')
    api['install'](claude, user, adapter, staging)
    api['check'](claude, user, adapter)
    script = claude / 'hooks/pre-tool-use.mjs'
    assert script.read_bytes() == pinned.read_bytes()
    direct = ['node', str(script)]
    filtered = shlex.split(api['hook_command'](claude, adapter, 'PreToolUse', script.name))
    # Simulate the previous installed layout, then exercise upgrade through install().
    settings = api['read'](claude / 'settings.json')
    settings['hooks']['PreToolUse'][-1]['hooks'][0]['command'] = shlex.join(direct)
    api['write'](claude / 'settings.json', settings)
    record = api['read'](claude / api['INSTALL'])
    del record['files']['hooks/' + api['PRE_FILTER']]
    api['write'](claude / api['INSTALL'], record)
    (claude / 'hooks' / api['PRE_FILTER']).unlink()
    api['install'](claude, user, adapter, staging)
    api['check'](claude, user, adapter)
    once = (claude / 'settings.json').read_bytes()
    api['install'](claude, user, adapter, staging)
    assert once == (claude / 'settings.json').read_bytes()
    results['install'] = {'upgrade_from_direct': True, 'repeat_settings_identical': True,
                          'check_passed': True, 'upstream_unchanged': True}
    work = root / 'work'; work.mkdir()
    base = {'session_id': 'delegation-probe', 'cwd': str(work), 'hook_event_name': 'PreToolUse',
            'tool_response': {'stdout': 'synthetic check passed\n' * 60, 'stderr': '', 'exit_code': 0},
            'prompt': 'Continue the authorized fixture task', 'last_assistant_message': 'Implementation is in progress.'}
    def payload(tool, args):
        return base | {'tool_name': tool, 'tool_input': args}
    def invoke(cmd, data, extra=None):
        return run(cmd, input=data if isinstance(data, str) else json.dumps(data),
                   cwd=work, env=env | (extra or {}))
    silent = {'continue': True, 'suppressOutput': True}
    cases = {}
    for tool, args in [('Bash', {'command': 'echo fixture > app.py'}),
                       ('Edit', {'file_path': 'app.py', 'old_string': 'a', 'new_string': 'b'}),
                       ('Write', {'file_path': 'app.py', 'content': 'fixture'})]:
        data = payload(tool, args)
        old = json.loads(invoke(direct, data).stdout)
        assert old['hookSpecificOutput']['additionalContext'].startswith('[DELEGATION NOTICE]')
        assert json.loads(invoke(filtered, data).stdout) == silent
        cases[tool + '_notice_removed'] = True
    skill = payload('Skill', {'skill': 'ralplan'})
    assert json.loads(invoke(filtered, skill).stdout) == silent
    state = root / 'state/non-git/state/sessions/delegation-probe/skill-active-state.json'
    active = json.loads(state.read_text())
    assert active['active'] is True and active['skill_name'] == 'ralplan'
    cases['Skill_active_state_written'] = True
    for tool in ['Task', 'Agent']:
        data = payload(tool, {'subagent_type': 'oh-my-claudecode:autopilot'})
        before = invoke(direct, data).stdout
        assert json.loads(before)['hookSpecificOutput']['permissionDecision'] == 'deny'
        assert invoke(filtered, data).stdout == before
        cases[tool + '_skill_deny_unchanged'] = True
    for worker_key in ['OMC_TEAM_WORKER', 'OMX_TEAM_WORKER']:
        for tool, args in [('Task', {'subagent_type': 'executor'}), ('Skill', {'skill': 'ralplan'}),
                           *[('Bash', {'command': cmd}) for cmd in
                             ['tmux split-window', 'omc team 2:executor', 'echo $ralph']]]:
            data = payload(tool, args); extra = {worker_key: 'fixture/worker-1'}
            before = invoke(direct, data, extra).stdout
            assert json.loads(before)['continue'] is False
            assert invoke(filtered, data, extra).stdout == before
        cases[worker_key + '_five_restrictions_unchanged'] = True
    for tool, args in [('Read', {'file_path': 'app.py'}), ('Bash', {'command': 'uv run pytest -q'}),
                       ('Edit', {'file_path': '.omc/notes.py'}), ('Edit', {'file_path': 'notes.md'}),
                       ('Agent', {'subagent_type': 'executor'})]:
        data = payload(tool, args)
        assert invoke(filtered, data).stdout == invoke(direct, data).stdout
    cases['other_tools_and_allowed_paths_unchanged'] = True
    for data in ['not json', payload('Bash', {'command': 'echo x > app.py'}) | {'turn_id': 'codex-fixture'}]:
        assert invoke(filtered, data).stdout == invoke(direct, data).stdout
    cases['malformed_input_and_codex_shape_unchanged'] = True
    assert not (work / 'app.py').exists()
    results['offline_cases'] = cases
    # Prototype the existing Python-adapter architecture with captured stdout.
    prototype = root / 'python-filter.py'
    prototype.write_text('''import json, runpy, subprocess, sys
api = runpy.run_path(sys.argv[1])
r = subprocess.run(['node', sys.argv[2]], input=sys.stdin.buffer.read(), stdout=subprocess.PIPE)
try:
 v = json.loads(r.stdout); h = v.get('hookSpecificOutput', {}); c = h.get('additionalContext', '')
 suffix = '\\n\\nRecommended: Delegate to executor agent instead:\\n  Task(subagent_type="oh-my-claudecode:executor", model="sonnet", prompt="...")\\n\\nThis is a soft warning. Operation will proceed.'
 prefixes = ['[DELEGATION NOTICE] Bash command may modify source files: '] + ['[DELEGATION NOTICE] Direct ' + t + ' on source file: ' for t in ['Edit','Write','edit','write']]
 if set(v) == {'continue','hookSpecificOutput'} and v['continue'] is True and set(h) == {'hookEventName','additionalContext'} and h['hookEventName'] == 'PreToolUse' and isinstance(c, str) and any(c.startswith(p) for p in prefixes) and c.endswith(suffix):
  r.stdout = b'{"continue":true,"suppressOutput":true}\\n'
except (ValueError, TypeError, AttributeError): pass
sys.stdout.buffer.write(r.stdout)
sys.exit(r.returncode)
''')
    python = ['python3', str(prototype), str(adapter), str(script)]
    samples = {
        'ordinary_shell': payload('Bash', {'command': 'uv run pytest tests/test_agent_config.py -q',
                                         'description': 'Run focused offline configuration checks'}),
        'source_shell': payload('Bash', {'command': 'echo fixture > app.py'}),
        'source_edit': payload('Edit', {'file_path': 'app.py'}),
        'long_shell': payload('Bash', {'command': ('echo fixture; ' * 1000) + 'echo fixture > app.py'}),
    }
    timings = {}
    for name, data in samples.items():
        modes = {'direct': direct, 'node_preload': filtered, 'python_capture': python}
        for cmd in modes.values(): invoke(cmd, data)
        assert invoke(python, data).stdout == invoke(filtered, data).stdout
        durations = {mode: [] for mode in modes}
        # Interleave modes to reduce shared-host drift, one warm-up plus 32 fresh calls.
        for _ in range(32):
            for mode, cmd in modes.items():
                start = time.perf_counter(); invoke(cmd, data)
                durations[mode].append((time.perf_counter() - start) * 1000)
        timings[name] = {mode: {'median_ms': round(statistics.median(values), 2),
                               'p95_ms': round(sorted(values)[30], 2), 'max_ms': round(max(values), 2),
                               'samples': len(values)} for mode, values in durations.items()}
    results['timing'] = timings
    results['node'] = run(['node', '--version']).stdout.strip()
    results['python'] = sys.version.split()[0]
    api['remove'](claude, user, adapter)
    assert not (claude / 'hooks' / api['PRE_FILTER']).exists()
    assert not script.exists()
    results['owned_filter_removed'] = True

out = repo / 'docs/adr/data/0019-delegation-results.json'
out.write_text(json.dumps(results, indent=2) + '\n')
print(json.dumps(results, indent=2))
