"""Status-first versus IDs-first versus original empty-array selection."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys

ROOT=Path('/home/kww/projects/MVAgent_API')
PARENT=ROOT/'outputs/analysis/20261005_selector_integrated_confirmation_v2'
ARMS=('empty_array','status_first','ids_first')
def read(p):return json.loads(Path(p).read_text())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,v):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_suffix(p.suffix+'.tmp');tmp.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n');tmp.replace(p)
def schema_for(arm,original):
 if arm=='empty_array':return json.loads(json.dumps(original))
 ids=original['properties']['selected_skill_ids']['items']['enum'];branches=[]
 order=['status','selected_skill_ids'] if arm=='status_first' else ['selected_skill_ids','status']
 for status in ['skip','selected']:
  properties={'status':{'type':'string','const':status},'selected_skill_ids':{'type':'array','items':{'type':'string','enum':ids},'minItems':0 if status=='skip' else 1,'maxItems':0 if status=='skip' else 1}}
  branches.append(dict(type='object',properties={k:properties[k] for k in order},required=order,additionalProperties=False))
 return {'oneOf':branches}
def decode(arm,value):
 ids=value['selected_skill_ids']
 if arm!='empty_array':
  assert list(value)==(['status','selected_skill_ids'] if arm=='status_first' else ['selected_skill_ids','status']), 'Output field order differs'
  assert (value['status']=='skip' and not ids) or (value['status']=='selected' and len(ids)==1), 'Status/IDs conflict'
 return ids[0] if ids else None

def selfcheck():
 import xgrammar as x
 from models.vlm.api.providers.openai_compatible import _vllm_generation_schema,_compact_vllm_grammar
 from models.utils import validate_json_schema
 original={'type':'object','properties':{'selected_skill_ids':{'type':'array','items':{'type':'string','enum':['1','10']},'maxItems':1}},'required':['selected_skill_ids'],'additionalProperties':False}
 compiler=x.GrammarCompiler(x.TokenizerInfo([bytes([i]) for i in range(256)]))
 for arm in ARMS:
  schema=schema_for(arm,original);compiled=compiler.compile_grammar(_compact_vllm_grammar(json.dumps(_vllm_generation_schema(schema))))
  for chosen in [None,'1','10']:
   props={'status':'skip' if chosen is None else 'selected','selected_skill_ids':[] if chosen is None else [chosen]}
   value={'selected_skill_ids':props['selected_skill_ids']} if arm=='empty_array' else {k:props[k] for k in (['status','selected_skill_ids'] if arm=='status_first' else ['selected_skill_ids','status'])}
   validate_json_schema(value,schema);assert decode(arm,value)==chosen
   assert x.GrammarMatcher(compiled).accept_string(json.dumps(value,separators=(',',':')))
   if arm!='empty_array':
    reverse=dict(reversed(list(value.items())))
    assert not x.GrammarMatcher(compiled).accept_string(json.dumps(reverse,separators=(',',':')))
  invalids=[{'selected_skill_ids':['missing']}] if arm=='empty_array' else [{'status':'skip','selected_skill_ids':['1']},{'status':'selected','selected_skill_ids':[]},{'status':'selected','selected_skill_ids':['missing']}]
  for invalid in invalids:
   try:validate_json_schema(invalid,schema)
   except ValueError:pass
   else:raise AssertionError('Invalid output accepted')
 assert schema_for('empty_array',original)==original

def prepare(out):
 import runpy
 from skill_evolution.infra.store import tree_hash
 selfcheck()
 if out.exists() and any(out.iterdir()):raise ValueError('Fresh output required')
 out.mkdir(parents=True,exist_ok=True)
 rows=[]
 for path in sorted((PARENT/'results/previous').glob('*/0/*.json')):
  row=read(path);assert row['status']=='ok' and len(row['requests'])==1;req=row['requests'][0]
  rows.append({k:row[k] for k in ('sample_id','cohort','regime','expected','uncertain','candidates')} | dict(user=req['user'],schema=req['json_schema'],source=str(path)))
 assert len(rows)==788
 save(out/'inputs.json',rows)
 base=runpy.run_path(str(ROOT/'src/mvagent/skills/prompts.py'))['SYSTEM_TEMPLATE']
 assert base==read(ROOT/'outputs/analysis/20261005_selector_semantic_fit/systems.json')['coverage']
 prefix=base.split('# Output contract',1)[0]
 def contract(arm):
  fields=['status','selected_skill_ids'] if arm=='status_first' else ['selected_skill_ids','status']
  descriptions={'status':'- status: "skip" if no Skill is selected, otherwise "selected".', 'selected_skill_ids':'- selected_skill_ids: [] when status is "skip"; an array containing exactly one supplied reference when status is "selected".'}
  selected={'status':'selected','selected_skill_ids':['1']};skip={'status':'skip','selected_skill_ids':[]}
  return '# Output contract\nReturn exactly one JSON object with the following two fields, matching the supplied Schema. Write the fields in the order listed below:\n'+'\n'.join(descriptions[k] for k in fields)+'\nCopy references from the supplied candidates; never generate or renumber them. The two fields must agree. Return no reason or additional fields.\n\nExample (if candidate 1 is selected):\n'+json.dumps({k:selected[k] for k in fields})+'\n\nExample (select none):\n'+json.dumps({k:skip[k] for k in fields})+'\n'
 save(out/'systems.json',dict(empty_array=base,status_first=prefix+contract('status_first'),ids_first=prefix+contract('ids_first')))
 for name in ('runtime.yaml','execution.yaml','rrf8.json'):shutil.copy2(PARENT/name,out/name)
 shutil.copytree(ROOT/'src',out/'src',ignore=shutil.ignore_patterns('__pycache__','*.pyc'));shutil.copy2(__file__,out/'controller.py')
 save(out/'protocol.json',dict(arms=ARMS,repeats=2,first_calls=4728,workers=4,model='Qwen3.5-35B-A3B',temperature=0,thinking=False,comparison='Same coverage rules/examples and User/candidate order. Original single-array contract vs two-field status/IDs contract with status first or IDs first. oneOf enforces skip=>[] and selected=>one candidate. Actual xgrammar and decoder verify field order. No reason. IDs-first isolates field-order effect within added-status format.',limits='394 reused real questions, previous134/new200/confirmation60 separate; confirmation60 now reused, not fresh independent Test or human gold. Frozen labels unchanged, repeats not independent. Production stays exact coverage/empty array; experimental contracts only; no Actor/Judge/optimizer or service deployment.'))
 files=['inputs.json','systems.json','runtime.yaml','execution.yaml','rrf8.json','controller.py','protocol.json']
 save(out/'manifest.json',dict(commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),source_hash=tree_hash(out/'src'),files={n:sha(out/n) for n in files},parent_requests={r['source']:sha(r['source']) for r in rows}))
 save(out/'status.json',dict(state='prepared',jobs=4728))

def run(out):
 import fcntl
 from skill_evolution.infra.store import tree_hash
 from mvagent.batch import ExecutionConfig,prepare_model_pools
 from mvagent.configs import MVAgentConfig
 from models.factory import ModelFactory
 from models.embeddings import EmbeddingConfig
 from mvagent.skills.bank import SkillBank
 from mvagent.skills.selection import retrieve_candidates
 from mvagent.skills.prompts import selection_input
 from models.execution import execution_scope
 from skill_evolution.configs.model_config import EvolutionModelConfig
 from mvagent.skills.prompts import build_selector_system_prompt
 from mvagent.utils.tools import validate_json_schema
 selfcheck();lock=(out/'controller.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 manifest=read(out/'manifest.json');assert tree_hash(out/'src')==manifest['source_hash'];assert all(sha(out/n)==v for n,v in manifest['files'].items());assert all(sha(n)==v for n,v in manifest['parent_requests'].items())
 cfg=MVAgentConfig.from_yaml(out/'runtime.yaml');pools,failures=prepare_model_pools(cfg.to_dict(),ExecutionConfig.from_yaml(out/'execution.yaml'))
 save(out/'services.json',dict(unavailable=failures,pools={n:[r.to_dict() for r in p.replicas] for n,p in pools.items()}));assert not failures
 def invoke(model,system,user,schema,arm):
  events=[];v=dict(requests=[dict(system_prompt=system,user=user,json_schema=schema)])
  try:
   with execution_scope(emit=events.append):result=model.json_prompt(user,system_prompt=system,json_schema=schema,schema_name='skill_selection')
   v.update(status=result['status'],result=result,selected=None)
   if result['status']=='ok':
    validate_json_schema(result['value'],schema);v['selected']=decode(arm,result['value']);v['output_field_order']=list(result['value']);v['decision_status']=result['value'].get('status')
  except Exception as exc:v.update(status='error',error=repr(exc),selected=None)
  v['events']=events;return v
 def one(job):
  arm,n,row=job;path=out/'results'/arm/row['regime']/str(n)/(row['sample_id'].replace(':','_')+'.json')
  if path.exists():return read(path)['status']!='ok'
  user=row['user'];schema=schema_for(arm,row['schema']);candidates=row['candidates']
  model=ModelFactory.create_model(EvolutionModelConfig(model_type='qwen3_5_35b_a3b_local'),cfg)
  try:
   system=read(out/'systems.json')[arm]
   value=dict(row,arm=arm,repeat=n,**invoke(model,system,user,schema,arm));value['candidates']=candidates;save(path,value)
   return value['status']!='ok'
  finally:model.close()
 jobs=[(a,n,r) for n in range(2) for a in ARMS for r in read(out/'inputs.json')];random.Random(202610052).shuffle(jobs)
 errors=0
 with ThreadPoolExecutor(max_workers=4) as ex:
  for n,f in enumerate(as_completed([ex.submit(one,j) for j in jobs]),1):
   errors+=f.result();save(out/'status.json',dict(state='running',done=n,total=len(jobs),errors=errors,pid=os.getpid(),time=datetime.now(timezone.utc).isoformat()))
 summarize(out);save(out/'status.json',dict(state='completed',done=len(jobs),total=len(jobs),errors=errors))

def summarize(out):
 rows=[read(p) for p in (out/'results').glob('*/*/*/*.json')];metrics={}
 for a in ARMS:
  for g in ('full','missing'):
   for cohort in ('all','new','previous','confirmation'):
    rs=[r for r in rows if r['arm']==a and r['regime']==g and not r['uncertain'] and ((cohort=='all' and r['cohort']!='confirmation') or r['cohort']==cohort)];valid=[r for r in rs if r['status']=='ok'];pos=[r for r in valid if r['expected']];neg=[r for r in valid if not r['expected']]
    metrics[f'{a}/{g}/{cohort}']=dict(attempted=len(rs),errors=len(rs)-len(valid),positive=len(pos),match=sum(r['selected'] in r['expected'] for r in pos),false_abstention=sum(r['selected'] is None for r in pos),recalled_positive=sum(any(c['id'] in r['expected'] for c in r['candidates']) for r in pos),wrong_card=sum(r['selected'] is not None and r['selected'] not in r['expected'] for r in pos),negative=len(neg),refusal=sum(r['selected'] is None for r in neg))
  events=[e for r in rows if r['arm']==a for e in r['events']];metrics[a+'/requests']=sum(e['kind']=='model_request' for e in events)
 save(out/'summary.json',dict(metrics=metrics,limits=read(out/'protocol.json')['limits']))

if __name__=='__main__':
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('mode',choices=['prepare','run','summarize','check']);ap.add_argument('--output',type=Path);args=ap.parse_args()
 if args.mode=='check':selfcheck();print('candidate ordering checks passed');sys.exit()
 if args.output is None:ap.error('--output required')
 out=args.output.resolve();sys.path.insert(0,str(out/'src' if (out/'src').exists() else ROOT/'src'))
 for name in ('NO_PROXY','no_proxy'):os.environ[name]=os.environ.get(name,'')+',127.0.0.1,localhost'
 globals()[args.mode](out)
