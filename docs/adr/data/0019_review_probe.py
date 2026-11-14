"""ADR 0019 review probe: python3 docs/adr/data/0019_review_probe.py CACHE_ROOT.

CACHE_ROOT/vocab/o200k_base.tiktoken must hold ADR 0001's checked vocabulary.
Uses a new CACHE_ROOT/home, public npm, synthetic tools/transcript, and only the
real settings' Orca hooks/statusLine; no authentication file is read or copied.
The HOME passed to setup.sh is always the unsigned scratch home. Runtime version
checks can contact the public npm registry; no tool payload command is executed.
"""
from pathlib import Path
import hashlib,json,os,re,runpy,shutil,statistics,subprocess,sys,time
root=Path(sys.argv[1]).resolve()
repo=Path(__file__).resolve().parents[3]; home=root/'home'; claude=home/'.claude'; local=home/'.local/bin'
assert not home.exists(), 'Use a fresh scratch home'
local.mkdir(parents=True); claude.mkdir()
api=runpy.run_path(str(repo/'deploy/wsl/meridian-omc.py'))
script=(repo/'deploy/wsl/setup.sh').read_text()
def body(name): return script.split(name+'() {\n',1)[1].split('\n}',1)[0]
def run(cmd,**kw):
 result=subprocess.run(cmd,text=True,capture_output=True,**kw)
 if result.returncode:
  print(result.stdout, result.stderr, file=sys.stderr)
 result.check_returncode()
 return result
def write(path,obj): api['write'](path,obj)
# Only the explicitly authorized real settings fields; no other values copied.
real=json.loads((Path.home()/'.claude/settings.json').read_text())
settings=api['foreign_settings']({'statusLine':real.get('statusLine'),'hooks':{event:[g for g in groups if any('.orca/agent-hooks/' in h.get('command','') for h in g['hooks'])] for event,groups in real.get('hooks',{}).items()}},Path('/home/apoth/.claude'))
write(claude/'settings.json',settings); (claude/'CLAUDE.md').write_text('Synthetic owner instructions without trailing newline')
# Seed settings using the same jq expression as the repository's offline tests.
expression=re.search(r"jq [^\n]* '\n(.*?)\n  '",body('claude_settings'),re.S)[1]
settings=json.loads(run(['jq','-e','--arg','model','model','--arg','floor','floor',expression],input=json.dumps(settings)).stdout)
write(claude/'settings.json',settings)
user=home/'.config/claude-omc/config.jsonc'
write(user,{'keywordDetector':{'disabled':['ralph'],'keep':True}})
write(claude/'.omc-config.json',{'hudEnabled':True,'keep':True})
other=claude/'skills/code-review/SKILL.md';other.parent.mkdir(parents=True);other.write_text('Synthetic existing review skill')
(root/'empty.npmrc').touch()
env=dict(os.environ,HOME=str(home),NPM_CONFIG_PREFIX=str(home/'.local'),NPM_CONFIG_CACHE=str(root/'npm-cache'),NPM_CONFIG_USERCONFIG=str(root/'empty.npmrc'),CLAUDE_CONFIG_DIR=str(claude),XDG_CONFIG_HOME=str(home/'.config'),OMC_HOME=str(root/'runtime'),OMC_STATE_DIR=str(root/'state'))
def files(): return {str(p.relative_to(home)):hashlib.sha256(p.read_bytes()).hexdigest() for p in home.rglob('*') if p.is_file()}
before=files(); before_settings=json.loads((claude/'settings.json').read_text())
log=run([str(repo/'deploy/wsl/setup.sh'),'omc'],env=env)
(root/'install.log').write_text(log.stdout+log.stderr)
# Idempotence of actual setup, projected assets and user settings.
first=files();run([str(repo/'deploy/wsl/setup.sh'),'omc'],env=env);second=files()
assert first==second, sorted(k for k in first.keys()|second.keys() if first.get(k)!=second.get(k))
assert all((claude/'skills'/n/'SKILL.md').exists() for n in api['SKILLS'])
assert not (claude/'skills/tdd').exists()
results={'actual_setup_twice_identical':True,'skills':sorted(api['SKILLS']),'agents':sorted(api['AGENTS'])}
# Static estimates follow ADR 0001 with complete frontmatter, not provider tokens.
mod=runpy.run_path(str(repo/'docs/adr/data/0001_count_tokens.py'))
encoder=mod['Encoder']('o200k_base',root/'vocab')
pkg=home/'.local/lib/node_modules/oh-my-claude-sisyphus'
def listing(paths):
 return '\n'.join(p.parent.name+'\n'+p.read_text().split('---',2)[1] for p in sorted(paths))
def agents(paths):
 return '\n'.join(p.stem+'\n'+p.read_text().split('---',2)[1] for p in sorted(paths))
def count(text): return {'characters':len(text),'bytes':len(text.encode()),'tokens':len(encoder.encode(text))}
# upstream source has entitlement-only directories; compare original 84 emitted skill set
# by another isolated upstream setup, avoiding accidentally counting uninstalled packages.
full=root/'full'; write(full/'.omc-config.json',{'hudEnabled':False}); write(root/'empty.json',{})
fullenv=dict(env,CLAUDE_CONFIG_DIR=str(full),XDG_CONFIG_HOME=str(root/'full-config'),OMC_HOME=str(root/'full-omc'),OMC_STATE_DIR=str(root/'full-state'),CODEX_HOME=str(root/'full-codex'),CLAUDE_MCP_CONFIG_PATH=str(root/'empty.json'),OMC_MCP_REGISTRY_PATH=str(root/'empty.json'))
run(['node',str(pkg/'bin/oh-my-claudecode.js'),'setup','--no-plugin','--force','--quiet'],cwd=root,env=fullenv,input='')
results['listing']={'before_skills':count(listing((full/'skills').glob('*/SKILL.md'))),'after_skills':count(listing((claude/'skills'/n/'SKILL.md' for n in api['SKILLS']))),'before_agents':count(agents((full/'agents').glob('*.md'))),'after_agents':count(agents((claude/'agents').glob('*.md')))}
results['instructions']=count((claude/'CLAUDE.md').read_text().removeprefix('Synthetic owner instructions without trailing newline'))
# Every timed sample starts a fresh interpreter and node process. No command is executed.
work=root/'bench';work.mkdir(exist_ok=True);transcript=claude/'projects/bench/bench.jsonl';transcript.parent.mkdir(parents=True,exist_ok=True);transcript.touch()
payload=json.dumps({'session_id':'bench','cwd':str(work),'transcript_path':str(transcript),'hook_event_name':'PostToolUse','tool_name':'Bash','tool_input':{'command':'uv run pytest tests/test_agent_config.py -q','description':'Run focused offline configuration checks'},'tool_response':{'stdout':'synthetic check passed\n'*60,'stderr':'','exit_code':0},'prompt':'Continue the authorized fixture task','last_assistant_message':'Implementation is in progress.'})
bench={}
for event,names in api['HOOKS'].items():
 for name in names:
  sample={}
  for mode in ['wrapped','direct']:
   cmd=['python3',str(local/'meridian-omc'),'hook',event,str(claude/'hooks'/name)] if mode=='wrapped' else ['node',str(claude/'hooks'/name)]
   run(cmd,env=env,cwd=work,input=payload)
   times=[]
   for _ in range(32):
    start=time.perf_counter();run(cmd,env=env,cwd=work,input=payload);times.append((time.perf_counter()-start)*1000)
   sample[mode]={'median_ms':round(statistics.median(times),2),'p95_ms':round(sorted(times)[30],2),'max_ms':round(max(times),2),'samples':32}
  bench[event+'/'+name]=sample
results['hook_timing']=bench
# Retain actual selected-hook projection for the existing synthetic stage probe.
probe=root/'profile';probe.mkdir(exist_ok=True);shutil.copytree(claude,probe/'claude');shutil.copytree(home/'.config',probe/'config')
probe_result=run(['python3',str(repo/'docs/adr/data/0019_probe.py'),str(probe)],env=env)
results['profile']=json.loads(probe_result.stdout)
# Removal helper exercised against real upstream assets; npm removal remains isolated.
run(['python3',str(repo/'deploy/wsl/meridian-omc.py'),'remove',str(claude),str(user),str(local/'meridian-omc')],env=env)
run(['npm','uninstall','-g','--ignore-scripts','--no-audit','--no-fund','oh-my-claude-sisyphus'],env=env)
assert not pkg.exists()
assert json.loads((claude/'settings.json').read_text())==before_settings
# Runtime hook samples created their own cache/latches outside payload ownership; compare
# files that setup/removal owns, separately list intentional synthetic runtime leftovers.
after=files();added=sorted(set(after)-set(before))
assert all(after.get(k)==v for k,v in before.items()), [k for k in before if after.get(k)!=before[k]]
assert not any(k.startswith(('.claude/skills/','.claude/agents/','.claude/hooks/','.local/bin/')) for k in added),added
results['remove_restores_before_files']=True;results['npm_removed']=True;results['runtime_sample_files_after_remove']=added
results['python']=sys.version.split()[0]
results['node']=run(['node','--version']).stdout.strip()
(root/'review-results.json').write_text(json.dumps(results,indent=2)+'\n')
print(json.dumps(results,indent=2))
