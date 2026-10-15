"""Fixed candidate prompt and numeric-ID ordering factorial audit."""
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
ARMS=tuple(f'{rule}_{order}' for rule in ('current','strict','balanced','scope') for order in ('rank','id'))
STRICT='''\n# Final applicability check
Before selecting, check whether the declared task covers the question's requested result, its main reasoning operation, and any essential relationship between inputs. Shared observable content or a useful preliminary observation alone does not establish applicability.
For a reasoning, correspondence, temporal reconstruction or causal question, a generic fact-checking or comparison card is eligible only when that declared task directly establishes the requested result. Do not assume unstated capabilities or an extra reasoning stage to bridge a mismatch. For simple identification or attribute comparison, generic fact-checking remains eligible.
If the best candidate is merely related, partially useful, or requires an unsupported essential relationship, return {"selected_skill_ids": []}. Do not choose a substitute just because the exact method is absent. Prefer baseline execution over a speculative method.\n'''

BALANCED="""
# Scope check before selection
Select a card whose stated task directly matches the main requested operation, allowing ordinary paraphrases and generalization across scene topics. A short when_to_use need not describe execution or guarantee the final answer. Simple identification and attribute comparison can use general fact-checking.
Reject clear operation or input-relation mismatches: facts or interpretation do not substitute for locating a matching interval; within-video action ordering does not substitute for ordering supplied clips; a momentary state does not substitute for cumulative counting. If only such substitutes remain, select none. Do not infer a mismatch merely because execution details are omitted.
"""
SCOPE="""
# Decision criterion
First decide whether any candidate declares the same main task as the question. Choose only among those cards; if none does, return an empty selected_skill_ids array. Sharing topic, objects or temporal words does not establish a task match, and the most similar card may still be unsuitable.
Treat ordinary paraphrases and different scene domains as equivalent. General observable-fact checking may directly support identification and factual comparison. Execution details and the answer need not be present in when_to_use. Preserve essential input relationships and do not substitute a different operation for the requested one.
"""
def ordered_input(user,schema,order):
 schema=json.loads(json.dumps(schema))
 if order=='rank':return user,schema
 head,body=user.split('# Candidate skills',1)
 blocks=body.strip().split('## Skill ID: ')[1:]
 blocks.sort(key=lambda b:int(b.split('\n',1)[0].strip()))
 return head+'# Candidate skills\n\n'+'\n\n'.join('## Skill ID: '+b.strip() for b in blocks),schema

def read(p):return json.loads(Path(p).read_text())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,v):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_suffix(p.suffix+'.tmp');tmp.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n');tmp.replace(p)
def selfcheck():
 u='# Input\nQ\n# Candidate skills\n\n## Skill ID: 10\nWhen to use: ten\n\n## Skill ID: 2\nWhen to use: two\n\n## Skill ID: 1\nWhen to use: one'
 schema={'properties':{'selected_skill_ids':{'items':{'enum':['10','2','1']}}}}
 v,z=ordered_input(u,schema,'id')
 assert v.index('Skill ID: 1\n')<v.index('Skill ID: 2\n')<v.index('Skill ID: 10\n')
 assert z==schema
 assert schema['properties']['selected_skill_ids']['items']['enum']==['10','2','1']
 assert ordered_input(u,schema,'rank')[0]==u
 assert {b.strip() for b in v.split('## Skill ID: ')[1:]}=={b.strip() for b in u.split('## Skill ID: ')[1:]}

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
 save(out/'inputs.json',inputs)
 for name in ('runtime.yaml','execution.yaml','rrf8.json'):shutil.copy2(PARENT/name,out/name)
 shutil.copytree(ROOT/'src',out/'src',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
 shutil.copy2(__file__,out/'controller.py')
 save(out/'protocol.json',dict(arms=ARMS,repeats=2,first_calls=10688,max_review_calls=0,model='Qwen3.5-35B-A3B',temperature=0,thinking=False,workers=4,
  comparison='Four rules (current, prior strict, balanced mismatch veto, task-scope check) crossed with rank/numeric-ID ascending. Same candidate set and single-field output. Schema enum order unchanged to isolate displayed order. No review calls.',
  target='Correct selection approximately90%, missing-card correct rejection>=70%, aspirational75%; no relabeling after inference.',
  limits='Reused334 development questions;200 previously new are now reused, not held-out Test. Frozen Codex labels not independent human gold. New/previous and uncertain cohorts separate; two repeats not independent. No Actor QA/Judge/optimizer or production changes.'))
 files=['inputs.json','runtime.yaml','execution.yaml','rrf8.json','protocol.json','controller.py']
 save(out/'manifest.json',dict(commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),source_hash=tree_hash(out/'src'),files={p:sha(out/p) for p in files},parent_requests={r['source']:sha(r['source']) for r in inputs}))
 save(out/'status.json',dict(state='prepared',jobs=10688))

def run(out):
 import fcntl
 from skill_evolution.infra.store import tree_hash
 from mvagent.batch import ExecutionConfig,prepare_model_pools
 from mvagent.configs import MVAgentConfig
 from models.factory import ModelFactory
 from models.execution import execution_scope
 from skill_evolution.configs.model_config import EvolutionModelConfig
 from mvagent.skills.prompts import build_selector_system_prompt
 from mvagent.utils.tools import validate_json_schema
 selfcheck();lock=(out/'controller.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 manifest=read(out/'manifest.json');assert tree_hash(out/'src')==manifest['source_hash'];assert all(sha(out/n)==v for n,v in manifest['files'].items());assert all(sha(n)==v for n,v in manifest['parent_requests'].items())
 cfg=MVAgentConfig.from_yaml(out/'runtime.yaml');pools,failures=prepare_model_pools(cfg.to_dict(),ExecutionConfig.from_yaml(out/'execution.yaml'))
 save(out/'services.json',dict(unavailable=failures,pools={n:[r.to_dict() for r in p.replicas] for n,p in pools.items()}));assert not failures
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
  rule,order=arm.split('_');user,schema=ordered_input(row['user'],row['schema'],order)
  model=ModelFactory.create_model(EvolutionModelConfig(model_type='qwen3_5_35b_a3b_local'),cfg)
  try:
   system=build_selector_system_prompt('global')+{'current':'','strict':STRICT,'balanced':BALANCED,'scope':SCOPE}[rule]
   value=dict(row,arm=arm,repeat=n,**invoke(model,system,user,schema));save(path,value)
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
   for cohort in ('all','new','previous'):
    rs=[r for r in rows if r['arm']==a and r['regime']==g and not r['uncertain'] and (cohort=='all' or r['cohort']==cohort)];valid=[r for r in rs if r['status']=='ok'];pos=[r for r in valid if r['expected']];neg=[r for r in valid if not r['expected']]
    metrics[f'{a}/{g}/{cohort}']=dict(attempted=len(rs),errors=len(rs)-len(valid),positive=len(pos),match=sum(r['selected'] in r['expected'] for r in pos),false_abstention=sum(r['selected'] is None for r in pos),wrong_card=sum(r['selected'] is not None and r['selected'] not in r['expected'] for r in pos),negative=len(neg),refusal=sum(r['selected'] is None for r in neg))
  events=[e for r in rows if r['arm']==a for e in r['events']];metrics[a+'/requests']=sum(e['kind']=='model_request' for e in events)
 save(out/'summary.json',dict(metrics=metrics,limits=read(out/'protocol.json')['limits']))

if __name__=='__main__':
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('mode',choices=['prepare','run','summarize','check']);ap.add_argument('--output',type=Path);args=ap.parse_args()
 if args.mode=='check':selfcheck();print('candidate ordering checks passed');sys.exit()
 if args.output is None:ap.error('--output required')
 out=args.output.resolve();sys.path.insert(0,str(out/'src' if (out/'src').exists() else ROOT/'src'))
 for name in ('NO_PROXY','no_proxy'):os.environ[name]=os.environ.get(name,'')+',127.0.0.1,localhost'
 globals()[args.mode](out)
