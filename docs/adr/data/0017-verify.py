"""Recount public captures and independently verify registered diagnostic fidelity."""
import importlib.util, json, pathlib, sys
DATA=pathlib.Path(__file__).resolve().parent

def load(name,path):
 spec=importlib.util.spec_from_file_location(name,path);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod

if __name__=='__main__':
 counter=load('counter',DATA/'0001_count_tokens.py')
 measure=load('measure',DATA/'0017-measure.py')
 vocab=pathlib.Path(sys.argv[1]) if len(sys.argv)>1 else pathlib.Path.home()/'.cache/meridian/adr-0017/vocab'
 enc=counter.Encoder('o200k_base',vocab)
 rows=json.loads((DATA/'0017-compression.json').read_text());outputs=json.loads((DATA/'0017-outputs.json').read_text())
 assert len(rows)==16
 for row in rows:
  output=outputs[row['tree']+':'+row['command']]
  for arm in ('raw','rtk'): assert len(enc.encode(output[arm]))==row[arm+'_tokens']
  required=measure.diagnostics(output['raw']) if row['command'].startswith('uv run ') else []
  missing=[s for s in required if s not in output['rtk']]
  if '--refresh-diagnostics' in sys.argv:
   row['required_diagnostics']=required; row['missing_diagnostics']=missing
  assert required==row['required_diagnostics']
  assert missing==row['missing_diagnostics']
 for state in ('passing','failing'):
  for row in (r for r in rows if r['tree']==state):
   want=1 if state=='failing' and row['command'] in ('uv run pyright','uv run pytest') else 0
   assert row['raw_exit']==want,(state,row['command'],row['raw_exit'])
 if '--refresh-diagnostics' in sys.argv: (DATA/'0017-compression.json').write_text(json.dumps(rows,indent=2)+'\n')
 needed=sum(len(r['required_diagnostics']) for r in rows)
 lost=sum(len(r['missing_diagnostics']) for r in rows)
 raw=sum(r['raw_tokens'] for r in rows); compressed=sum(r['rtk_tokens'] for r in rows)
 summary={'cells':16,'raw_tokens':raw,'rtk_tokens':compressed,'saving_percent':round(100*(1-compressed/raw),3),'diagnostic_strings_required':needed,'diagnostic_strings_missing':lost,'diagnostic_fidelity_percent':round(100*(needed-lost)/needed,3) if needed else None,'exit_codes_preserved':all(r['raw_exit']==r['rtk_exit'] for r in rows),'model_runs':0,'decision':'not adopted' if lost or any(r['raw_exit']!=r['rtk_exit'] for r in rows) else 'requires quality/runtime assessment'}
 (DATA/'0017-summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary,indent=2))
