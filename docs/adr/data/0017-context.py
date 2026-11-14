"""No-model M2 prompt attribution in an empty Codex home, same project path."""
import hashlib, importlib.util, json, pathlib, subprocess, shutil
ROOT=pathlib.Path.cwd(); CACHE=pathlib.Path.home()/'.cache/meridian/adr-0017'
WT=CACHE/'context'; HOME=CACHE/'context-home'; CODEX=pathlib.Path.home()/'.local/bin/codex'
for p in (WT,HOME,HOME/".codex"): p.mkdir(exist_ok=True)
env={'HOME':str(HOME),'CODEX_HOME':str(HOME/'.codex'),'PATH':str(pathlib.Path(shutil.which('node')).parent)+':'+str(pathlib.Path.home()/'.local/bin')+':/usr/bin:/bin','LANG':'C.UTF-8'}
def run(args):
 p=subprocess.run(args,cwd=WT,env=env,capture_output=True,text=True)
 if p.returncode: print(p.stderr)
 p.check_returncode()
 return p
if not (WT/'.git').exists():
 subprocess.run(['git','clone','-q','--no-hardlinks',str(ROOT),str(WT)],check=True)
run(['git','checkout','-q','--detach','61536fc'])
spec=importlib.util.spec_from_file_location('counter',ROOT/'docs/adr/data/0001_count_tokens.py'); mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
enc=mod.Encoder('o200k_base',CACHE/'vocab')
result={}
def render():
 p=run([str(CODEX),'--dangerously-bypass-approvals-and-sandbox','--disable','hooks','-C',str(WT),'-m','gpt-6-astra','-c','model_reasoning_effort="high"','debug','prompt-input','Reply with exactly the word OK. Do not run any command or call any tool.'])
 items=json.loads(p.stdout); texts=[c['text'] for x in items if x.get('type')=='message' for c in x['content']]
 text='\n'.join(texts)
 return {'message_bytes':sum(len(t.encode()) for t in texts),'message_tokens_o200k':sum(len(enc.encode(t)) for t in texts),'rtk_reference_present':'@RTK.md' in text,'awareness_body_present':'Command output here is condensed' in text}
result['without']=render()
result['init_stdout']=run([str(CACHE/'binary/rtk'),'init','--codex']).stdout.replace(str(HOME),'<SCRATCH_HOME>').replace(str(WT),'<TREE>')
result['with']=render()
result['awareness']={}
for name in ['AGENTS.md','RTK.md','.codex/hooks.json']:
 t=(WT/name).read_text(); result['awareness'][name]={'bytes':len(t.encode()),'tokens_o200k':len(enc.encode(t)),'sha256':hashlib.sha256(t.encode()).hexdigest()}
result['added_reference']={'bytes':len('\n@RTK.md\n'.encode()),'tokens_o200k':len(enc.encode('\n@RTK.md\n'))}
result['M1']=None; result['reason']='Gateway guard refused; no signed-in model sessions started. M2 excludes hook context and extension tools.'
(ROOT/'docs/adr/data/0017-context.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
