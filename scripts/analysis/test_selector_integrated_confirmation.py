"""Production integrated task-scope rules versus previous System, reused334 and fresh60 paired audit."""
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
PARENT=ROOT/'outputs/analysis/20261005_expanded_selector_retrieval'
ARMS=('previous','updated')
def read(p):return json.loads(Path(p).read_text())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,v):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_suffix(p.suffix+'.tmp');tmp.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n');tmp.replace(p)
def selfcheck():
 import runpy
 old=runpy.run_path(str(ROOT/'outputs/analysis/20261005_selector_prompt_order/src/mvagent/skills/prompts.py'))['SYSTEM_TEMPLATE']
 new=runpy.run_path(str(ROOT/'src/mvagent/skills/prompts.py'))['SYSTEM_TEMPLATE']
 old_output=old.split('# Output contract',1)[1].strip()
 new_output=new.split('# Output contract',1)[1].split('# Task-scope alignment',1)[0].strip()
 assert old_output==new_output
 assert new.count('# Selection rules')==1 and '# Decision criterion' not in new
 assert old!=new and 'main' in new

def prepare(out):
 from skill_evolution.infra.store import tree_hash
 selfcheck()
 if out.exists() and any(out.iterdir()):raise ValueError('Fresh output required')
 out.mkdir(parents=True,exist_ok=True)
 inputs=[]
 for path in sorted((PARENT/'results/rrf8').glob('*/0/*.json')):
  row=read(path);assert row['status']=='ok' and len(row['requests'])==1;req=row['requests'][0]
  inputs.append({k:row[k] for k in ('sample_id','cohort','regime','expected','uncertain','candidates')} | dict(user=req['user'],schema=req['json_schema'],source=str(path)))
 assert len(inputs)==668
 original={r['sample_id']:r for r in read(PARENT/'inputs.json')}
 for r in inputs:
  r['task']=original[r['sample_id']]['question'];r['videos']=original[r['sample_id']]['videos'];r['accepted_full']=original[r['sample_id']]['label']['acceptable_ids']
 for r in read(ROOT/'outputs/analysis/20261005_selector_confirmation_panel/inputs.json'):
  for regime in ('full','missing'):
   inputs.append(dict(sample_id=r['sample_id'],cohort='confirmation',regime=regime,expected=r['label']['acceptable_ids'] if regime=='full' else [],uncertain=r['label']['uncertain'],candidates=[],source=None,user=None,schema=None,task=r['question'],videos=r['videos'],accepted_full=r['label']['acceptable_ids']))
 assert len(inputs)==788
 import runpy
 previous=runpy.run_path(str(ROOT/'outputs/analysis/20261005_selector_prompt_order/src/mvagent/skills/prompts.py'))['SYSTEM_TEMPLATE']
 save(out/'previous_system.json',previous)
 for name in ('inputs.json','sampling.json','sampler.py','reviewer.py'):
  shutil.copy2(ROOT/'outputs/analysis/20261005_selector_confirmation_panel'/name,out/('confirmation_'+name))
 save(out/'inputs.json',inputs)
 for name in ('runtime.yaml','execution.yaml','rrf8.json'):shutil.copy2(PARENT/name,out/name)
 shutil.copytree(ROOT/'src',out/'src',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
 shutil.copy2(__file__,out/'controller.py')
 save(out/'protocol.json',dict(arms=ARMS,repeats=2,first_calls=3152,max_review_calls=0,model='Qwen3.5-35B-A3B',temperature=0,thinking=False,workers=4,
  comparison='Four rules (current, prior strict, balanced mismatch veto, task-scope check) crossed with rank/numeric-ID ascending. Same candidate set and single-field output. Schema enum order unchanged to isolate displayed order. No review calls.',
  target='Correct selection approximately90%, missing-card correct rejection>=70%, aspirational75%; no relabeling after inference.',
  limits='Reused334 development questions plus60 fresh stratified real questions excluding all previous exact video paths. Fresh panel not seen during prompt tuning; not independent human gold or whole-film/session isolated benchmark Test. New/previous/confirmation and uncertain separate; repeats not independent. User authorized production System edit. No Actor QA/Judge/optimizer or service deployment.'))
 files=['inputs.json','runtime.yaml','execution.yaml','rrf8.json','protocol.json','controller.py','previous_system.json','confirmation_inputs.json','confirmation_sampling.json','confirmation_sampler.py','confirmation_reviewer.py']
 save(out/'manifest.json',dict(commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),source_hash=tree_hash(out/'src'),files={p:sha(out/p) for p in files},parent_requests={r['source']:sha(r['source']) for r in inputs if r['source']}))
 save(out/'status.json',dict(state='prepared',jobs=3152))

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
 banks={'original':SkillBank.from_dict(read(out/'rrf8.json'),sha256=sha(out/'rrf8.json'))}
 embedding=EmbeddingConfig('http://127.0.0.1:8110/v1','qwen3_embedding_8b')
 def invoke(model,system,user,schema):
  events=[];v=dict(requests=[dict(system_prompt=system,user=user,json_schema=schema)])
  try:
   with execution_scope(emit=events.append):result=model.json_prompt(user,system_prompt=system,json_schema=schema,schema_name='skill_selection')
   v.update(status=result['status'],result=result,selected=None)
   if result['status']=='ok':
    validate_json_schema(result['value'],schema);ids=result['value']['selected_skill_ids'];v['selected']=ids[0] if ids else None
  except Exception as exc:v.update(status='error',error=repr(exc),selected=None)
  v['events']=events;return v
 def one(job):
  arm,n,row=job;path=out/'results'/arm/row['regime']/str(n)/(row['sample_id'].replace(':','_')+'.json')
  if path.exists():return read(path)['status']!='ok'
  user=row['user'];schema=row['schema'];candidates=row['candidates']
  if row['cohort']=='confirmation':
   cards=tuple(c for c in banks['original'].cards if row['regime']=='full' or c.id not in row['accepted_full'])
   ranking,retriever=retrieve_candidates(cards,row['task'][:3000]+'\nRecent evidence/history:\n(none)',embedding)
   user=selection_input(row['task'],dict(videos=row['videos']),[c for c,v in ranking],role='global')
   schema={'type':'object','properties':{'selected_skill_ids':{'type':'array','items':{'type':'string','enum':[c.id for c,v in ranking]},'maxItems':1}},'required':['selected_skill_ids'],'additionalProperties':False}
   candidates=[dict(id=c.id,score=v) for c,v in ranking]
  model=ModelFactory.create_model(EvolutionModelConfig(model_type='qwen3_5_35b_a3b_local'),cfg)
  try:
   system=read(out/'previous_system.json') if arm=='previous' else build_selector_system_prompt('global')
   value=dict(row,arm=arm,repeat=n,**invoke(model,system,user,schema));value['candidates']=candidates;save(path,value)
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
