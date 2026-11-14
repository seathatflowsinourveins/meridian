"""Project-scoped Codex route proof; does not read sign-in files."""
import json, pathlib, subprocess, time, shutil
ROOT = pathlib.Path.cwd()
CACHE = pathlib.Path.home() / '.cache/meridian/adr-0017'
OUT = pathlib.Path.home() / 'src/meridian-ab/0017'
OUT.mkdir(parents=True, exist_ok=True)
WT = CACHE / 'probe'
HOME = CACHE / 'home'
BINARY = CACHE / 'binary/rtk'
OWNER = pathlib.Path.home()
EVENTS = 'session_start user_prompt_submit pre_tool_use permission_request post_tool_use subagent_start subagent_stop stop interrupt'.split()
OFF = 'hooks.state={' + ','.join(json.dumps(str(OWNER / '.codex/hooks.json') + ':' + e + ':0:0') + '={enabled=false}' for e in EVENTS) + '}'
def flags(wt):
 return ['--json','--color','never','-m','gpt-6-astra','-c','model_reasoning_effort="high"','--dangerously-bypass-approvals-and-sandbox','--dangerously-bypass-hook-trust','-C',str(wt),'-c','projects={'+json.dumps(str(wt))+'={trust_level="trusted"}}','-c',OFF,'--disable','multi_agent']
def env(home):
 return {'HOME':str(home),'CODEX_HOME':str(OWNER/'.codex'),'PATH':str(CACHE/'binary')+':'+str(OWNER/'.local/bin')+':'+str(pathlib.Path(shutil.which('node')).parent)+':/usr/local/bin:/usr/bin:/bin','PYRIGHT_PYTHON_IGNORE_WARNINGS':'1','UV_CACHE_DIR':str(CACHE/'uv-cache'),'TMPDIR':str(CACHE),'LANG':'C.UTF-8'}
if __name__=='__main__':
 subprocess.run(['git','init','-q',str(WT)],check=True)
 subprocess.run(['bash',str(ROOT/'docs/adr/data/0003_gateway_guard.sh')],check=True)
 prompt='Run exactly git status once with the shell tool in this directory, report its output, then stop. Do not call other tools or agents.'
 start=time.monotonic()
 with (OUT/'probe.jsonl').open('w') as out,(OUT/'probe.stderr').open('w') as err:
  p=subprocess.run([str(OWNER/'.local/bin/codex'),'exec',*flags(WT),prompt],env=env(HOME),stdin=subprocess.DEVNULL,stdout=out,stderr=err,timeout=180)
 print('probe',p.returncode,round(time.monotonic()-start,2))
 for line in (OUT/'probe.jsonl').read_text().splitlines():
  x=json.loads(line)
  if x['type'] in ('turn.completed','item.completed'): print(json.dumps(x))
