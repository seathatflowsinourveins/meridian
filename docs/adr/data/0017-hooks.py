"""No-model protocol probes from runtime-owned schema/docs, then safe execution.

Codex input schema: openai/codex rust-v0.167.2, hooks/schema/generated/
pre-tool-use.command.input.schema.json; core/tests/suite/hooks.rs asserts Bash.
Claude input: https://code.claude.com/docs/en/hooks#common-input-fields.
Payload values below are synthetic; no private runtime transcript is read.
"""
import json, pathlib, shlex, subprocess
ROOT=pathlib.Path.cwd(); CACHE=pathlib.Path.home()/'.cache/meridian/adr-0017'
WT=CACHE/'hook-probe'; HOME=CACHE/'hook-home'; BINARY=CACHE/'binary/rtk'
HOME.mkdir(exist_ok=True)
env={'HOME':str(HOME),'PATH':str(CACHE/'binary')+':'+str(WT/'.venv/bin')+':'+str(pathlib.Path.home()/'.local/bin')+':/usr/bin:/bin','LANG':'C.UTF-8','NO_COLOR':'1','PYRIGHT_PYTHON_IGNORE_WARNINGS':'1','UV_CACHE_DIR':str(CACHE/'uv-cache')}
def run(args,input=None):
 return subprocess.run(args,input=input,cwd=WT,env=env,capture_output=True,text=True)
def clean(s): return s.replace(str(WT),'<TREE>').replace(str(HOME),'<SCRATCH_HOME>').replace(str(CACHE),'<CACHE>')
subprocess.run(['git','clone','-q','--no-hardlinks',str(ROOT),str(WT)],check=True,env=env)
assert run(['git','checkout','-q','--detach','61536fc']).returncode==0
(WT/'.venv').symlink_to(CACHE/'commands/.venv',target_is_directory=True)
(WT/'tests/test_adr0017_planted.py').write_text((CACHE/'commands/tests/test_adr0017_planted.py').read_text())
result={'kind':'Protocol-shaped synthetic inputs, grounded in runtime-owned schema/docs; standalone RTK processors and executed replacements, not a live session test.','model_calls':0,'init':{},'probes':[]}
for runtime,args in [('codex',['init','--codex']),('claude',['init','-g','--agent','claude','--hook-only','--auto-patch'])]:
 init=run([str(BINARY),*args]);assert init.returncode==0,init.stderr
 result['init'][runtime]={'argv':args,'stdout':clean(init.stdout),'stderr':clean(init.stderr)}
 for command in ['git status','uv run ruff check .','uv run pyright']:
  payload={'session_id':'adr0017-synthetic-session','transcript_path':str(HOME/'nonexistent-transcript.jsonl'),'cwd':str(WT),'permission_mode':'default','hook_event_name':'PreToolUse','tool_name':'Bash','tool_use_id':'adr0017-synthetic-tool','tool_input':{'command':command,'description':'Offline ADR command probe'}}
  if runtime=='codex':
   payload.update(model='gpt-6-astra',turn_id='adr0017-synthetic-turn')
   schema=json.loads((CACHE/'codex-pre-tool-use.command.input.schema.json').read_text())
   assert set(schema['required'])<=payload.keys()<=schema['properties'].keys()
  else:
   payload.update(prompt_id='adr0017-synthetic-prompt',scratchpad_dir=str(HOME/'scratchpad'))
  hook=run([str(BINARY),'hook',runtime],json.dumps(payload));assert hook.returncode==0,hook.stderr
  output=json.loads(hook.stdout); specific=output['hookSpecificOutput'];assert specific['hookEventName']=='PreToolUse'
  rewritten=specific['updatedInput']['command'];assert rewritten!=command
  executed=run(shlex.split(rewritten));want=1 if command=='uv run pyright' else 0;assert executed.returncode==want
  result['probes'].append({'runtime':runtime,'input':json.loads(clean(json.dumps(payload))),'hook_exit':hook.returncode,'hook_output':output,'execution_exit':executed.returncode,'execution_output':clean(executed.stdout+executed.stderr)})
result['settings']={str(p.relative_to(WT)):json.loads(p.read_text()) for p in [WT/'.codex/hooks.json']}
claude=HOME/'.claude/settings.json'
result['settings']['<SCRATCH_HOME>/.claude/settings.json']=json.loads(claude.read_text())
(ROOT/'docs/adr/data/0017-hooks.json').write_text(json.dumps(result,indent=2)+'\n')
print('Six protocol rewrites executed with expected exit codes; no model/session call.')
