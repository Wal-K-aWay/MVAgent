"""Case-driven semantic boundary improvements within the four-rule Selector framework."""
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
ARMS=('baseline','operation','coverage','combined')
def read(p):return json.loads(Path(p).read_text())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,v):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_suffix(p.suffix+'.tmp');tmp.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n');tmp.replace(p)
def selfcheck():
 import runpy
 new=runpy.run_path(str(ROOT/'src/mvagent/skills/prompts.py'))['SYSTEM_TEMPLATE']
 assert new.count('# Selection rules')==1 and '# Applicability examples' not in new and '# Task-scope alignment' not in new
 assert all(f'{i}. ' in new for i in range(1,5))
 assert 'selected_skill_ids' in new and 'Unknown facts to be observed are not missing prerequisites' in new

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
 operation=base.replace('Identify the result to establish and the main operation needed.', 'Identify what must be established about the inputs, using the substantive question and options rather than its answer format or introductory wrapper. A video ID, option letter or number can be the output of many different reasoning tasks; it does not by itself make the task fact identification. Distinguish finding an observed fact from establishing its significance, correspondence, correctness or temporal relation.')
 coverage=base.replace('Do not make a card fit by changing the question, inventing capabilities or treating a useful preliminary observation as the missing method.', 'Check whether the declared method addresses the specific relation or judgment the question requires. A card that can collect relevant observations is not automatically a method for interpreting, matching, ordering or evaluating those observations. Do not make a card fit by changing the question or inventing the missing main operation. A short task scope may omit execution details without omitting the task itself.')
 operation=operation.replace('Example: a card checking specified observable facts in each video can identify which videos show a requested action across different scene topics.', 'Example: "Which video shows a worker holding a tool?" can use observable-fact checks; "Which video shows that action resolving a conflict?" also requires the contextual role of the action. The shared video-selection format does not make these the same task.')
 combined=coverage.replace('Identify the result to establish and the main operation needed.', 'Identify what must be established about the inputs, using the substantive question and options rather than its answer format or introductory wrapper. A video ID, option letter or number can be the output of many different reasoning tasks; it does not by itself make the task fact identification. Distinguish finding an observed fact from establishing its significance, correspondence, correctness or temporal relation.')
 combined=combined.replace('Example: a card checking specified observable facts in each video can identify which videos show a requested action across different scene topics.', 'Example: "Which video shows a worker holding a tool?" can use observable-fact checks; "Which video shows that action resolving a conflict?" also requires the contextual role of the action. The shared video-selection format does not make these the same task.')
 systems=dict(baseline=base,operation=operation,coverage=coverage,combined=combined)
 assert len(set(systems.values()))==4
 assert all(v.split('# Output contract',1)[1]==base.split('# Output contract',1)[1] for v in systems.values())
 assert all(v.count('# Selection rules')==1 for v in systems.values())
 save(out/'systems.json',systems)
 for name in ('runtime.yaml','execution.yaml','rrf8.json'):shutil.copy2(PARENT/name,out/name)
 shutil.copytree(ROOT/'src',out/'src',ignore=shutil.ignore_patterns('__pycache__','*.pyc'));shutil.copy2(__file__,out/'controller.py')
 save(out/'protocol.json',dict(arms=ARMS,repeats=2,first_calls=6304,workers=4,model='Qwen3.5-35B-A3B',temperature=0,thinking=False,comparison='Four-rule baseline versus main-operation parsing, direct-method coverage and combined improvements. Same User/candidate order/Schema, no retrieval/card changes. Contrasting predicates replace positive example only in operation/combined. Scope/evidence/output contracts unchanged.',limits='394 reused real questions, previous134/new200/confirmation60 separate; confirmation60 now reused, not fresh independent Test or human gold. Frozen labels unchanged, repeats not independent. Experimental semantic variants; production stays four-rule baseline pending evidence; no Actor/Judge/optimizer or service deployment.'))
 files=['inputs.json','systems.json','runtime.yaml','execution.yaml','rrf8.json','controller.py','protocol.json']
 save(out/'manifest.json',dict(commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),source_hash=tree_hash(out/'src'),files={n:sha(out/n) for n in files},parent_requests={r['source']:sha(r['source']) for r in rows}))
 save(out/'status.json',dict(state='prepared',jobs=6304))

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
  model=ModelFactory.create_model(EvolutionModelConfig(model_type='qwen3_5_35b_a3b_local'),cfg)
  try:
   system=read(out/'systems.json')[arm]
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
