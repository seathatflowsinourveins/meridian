"""Record the eight repository commands raw and through the pinned RTK routing."""
import importlib.util, json, pathlib, re, shlex, subprocess, sys
ROOT = pathlib.Path.cwd()
CACHE = pathlib.Path.home()/'.cache/meridian/adr-0017'
WT = CACHE/'commands'
HOME = CACHE/'command-home'
DATA = ROOT/'docs/adr/data'
RTK = CACHE/'binary/rtk'
HOME.mkdir(exist_ok=True)
ENV = {'HOME':str(HOME),'PATH':str(CACHE/'replay')+':'+str(CACHE/'binary')+':'+str(WT/'.venv/bin')+':'+str(pathlib.Path.home()/'.local/bin')+':/usr/bin:/bin','LANG':'C.UTF-8','NO_COLOR':'1','PYRIGHT_PYTHON_IGNORE_WARNINGS':'1','UV_CACHE_DIR':str(CACHE/'uv-cache')}
def run(args,cwd=WT,env=ENV):
 return subprocess.run(args,cwd=cwd,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
def normalize(s):
 return s.replace(str(WT),'<TREE>').replace(str(HOME),'<SCRATCH_HOME>').replace(str(CACHE),'<CACHE>')
def diagnostics(s):
 ids=re.findall(r'^FAILED (\S+)',s,re.M)
 locations=re.findall(r'(?:[\w./<>-]+\.py):\d+(?::\d+)?',s)
 messages=re.findall(r'^E\s+(.+)$',s,re.M)
 for m in re.finditer(r'^\s*.*?\.py:\d+:\d+ - (?:error|warning): (.+(?:\n {4,}[^\n]+)*)',s,re.M):
  messages.extend(t.strip() for t in m.group(1).splitlines())
 messages.extend(line.strip() for line in s.splitlines() if re.search(r'\(report[A-Za-z]+\)$',line) and ' - error: ' not in line)
 return sorted(set(ids+locations+messages))
if __name__=='__main__':
 spec=importlib.util.spec_from_file_location('counter',DATA/'0001_count_tokens.py'); mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
 enc=mod.Encoder('o200k_base',CACHE/'vocab')
 resume='--resume-failing' in sys.argv
 if not resume:
  subprocess.run(['git','clone','-q','--no-hardlinks',str(ROOT),str(WT)],check=True,env=ENV)
  subprocess.run(['git','checkout','-q','--detach','61536fc'],cwd=WT,check=True,env=ENV)
  # The scratch clone has only committed public content; no ignored owner files.
  sync=run(['uv','sync','--locked']); print('sync',sync.returncode,flush=True); assert sync.returncode==0,sync.stdout
  recorded=subprocess.run(['gh','pr','checks','31','--repo','seathatflowsinourveins/meridian'],capture_output=True,text=True,check=True).stdout
  (DATA/'0017-gh-pr-checks.json').write_text(json.dumps({'command':'gh pr checks 31 --repo seathatflowsinourveins/meridian','output':recorded},indent=2)+'\n')
  replay=CACHE/'replay'; replay.mkdir(exist_ok=True)
  stub=replay/'gh'; stub.write_text('#!/usr/bin/python3\nimport json,sys\nsys.stdout.write(json.load(open('+repr(str(DATA/'0017-gh-pr-checks.json'))+'))["output"])\n'); stub.chmod(0o755)
 commands=['uv run ruff check .','uv run ruff format --check .','uv run pyright','uv run pytest','git status','git log -5','git diff 4fdaff6^ 4fdaff6','gh pr checks 31']
 results=json.loads((DATA/'0017-compression.json').read_text()) if resume else []
 transcripts=json.loads((DATA/'0017-outputs.json').read_text()) if resume else {}
 for arm in (['failing'] if resume else ['passing','failing']):
  if arm=='failing':
   (WT/'tests/test_adr0017_planted.py').write_text('"""One deliberately failing test and one type error for ADR 0017."""\n\nPLANTED_NUMBER: int = "adr0017-type-marker"\n\n\ndef test_adr0017_planted_failure() -> None:\n    assert 2 + 2 == 5, "adr0017-assertion-marker"\n')
  for command in commands:
   raw=run(shlex.split(command)); rewrite=run([str(RTK),'rewrite',command]); rewritten=rewrite.stdout.strip()
   assert rewrite.returncode in (0,3),(command,rewrite.stdout)
   compressed=run(shlex.split(rewritten)) if rewritten else raw
   a,b=normalize(raw.stdout),normalize(compressed.stdout)
   key=arm+':'+command
   need=diagnostics(a) if command.startswith('uv run ') else []; missing=[x for x in need if x not in b]
   row={'tree':arm,'command':command,'rewrite':rewritten,'raw_exit':raw.returncode,'rtk_exit':compressed.returncode,'raw_tokens':len(enc.encode(a)),'rtk_tokens':len(enc.encode(b)),'required_diagnostics':need,'missing_diagnostics':missing}
   results.append(row); transcripts[key]={'raw':a,'rtk':b}
   print(json.dumps(row),flush=True)
   (DATA/'0017-compression.json').write_text(json.dumps(results,indent=2)+'\n')
   (DATA/'0017-outputs.json').write_text(json.dumps(transcripts,indent=2)+'\n')
