"""Fixed-selector comparison of original and task-precise short Skill scopes."""
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
ARMS=('original','card4','card5','card4_5')
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
 for r in read(ROOT/'outputs/analysis/20261005_selector_scope_expanded_panel/inputs.json'):
  for regime in ('full','missing'):
   rows.append(dict(sample_id=r['sample_id'],cohort='expanded',regime=regime,expected=r['label']['acceptable_ids'] if regime=='full' else [],uncertain=r['label']['uncertain'],candidates=[],user=None,schema=None,source=None,task=r['question'],videos=r['videos'],accepted_full=r['label']['acceptable_ids']))
 assert len(rows)==1028
 save(out/'inputs.json',rows)
 base=read(ROOT/'outputs/analysis/20261005_selector_semantic_fit/systems.json')['coverage']
 save(out/'systems.json',{a:base for a in ARMS})
 bank=read(PARENT/'rrf8.json')
 edits={
 '1':'Interpret and compare the purpose, causal role or meaning of observed events across videos.',
 '2':'Distinguish fine visual details of corresponding objects or actions across videos.',
 '3':'Identify which videos satisfy specified directly observable facts or actions.',
 '4':'Count repeated event occurrences over an interval or reconstruct an object’s path through time.',
 '5':'Determine the temporal order or overlap of named actions within each video.',
 '10':'Build an overview of video content when the question leaves the relevant evidence target unspecified.'}
 for card in bank['skills']:
  if card['meta']['id'] in edits:card['when_to_use']=edits[card['meta']['id']]
 save(out/'task_precise_bank.json',bank)
 save(out/'scope_edits.json',edits)
 for name in ('runtime.yaml','execution.yaml','rrf8.json'):shutil.copy2(PARENT/name,out/name)
 shutil.copytree(ROOT/'src',out/'src',ignore=shutil.ignore_patterns('__pycache__','*.pyc'));shutil.copy2(__file__,out/'controller.py')
 save(out/'protocol.json',dict(arms=ARMS,repeats=2,first_calls=8224,workers=4,model='Qwen3.5-35B-A3B',temperature=0,thinking=False,comparison='Original vs only card4 vs only card5 vs both, fixed production System/strategy/output. Reused394 plus fresh120 exact-path excluded questions. Fresh candidates obtained with original RRF8 and shared across card variants; no edited retrieval effect.',limits='394 reused real questions, previous134/new200/confirmation60 separate; confirmation60 now reused, not fresh independent Test or human gold. Frozen labels unchanged, repeats not independent. Experimental semantic variants; production is user-chosen coverage; further variants isolated pending evidence; no Actor/Judge/optimizer or service deployment.'))
 for n in ('inputs.json','sampling.json','sampler.py','reviewer.py'):shutil.copy2(ROOT/'outputs/analysis/20261005_selector_scope_expanded_panel'/n,out/('expanded_'+n))
 files=['expanded_inputs.json','expanded_sampling.json','expanded_sampler.py','expanded_reviewer.py','inputs.json','systems.json','runtime.yaml','execution.yaml','rrf8.json','controller.py','protocol.json','task_precise_bank.json','scope_edits.json']
 save(out/'manifest.json',dict(commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),source_hash=tree_hash(out/'src'),files={n:sha(out/n) for n in files},parent_requests={r['source']:sha(r['source']) for r in rows if r['source']}))
 save(out/'status.json',dict(state='prepared',jobs=8224))

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
  if row['cohort']=='expanded':
   bank=SkillBank.from_dict(read(out/'rrf8.json'),sha256=sha(out/'rrf8.json'))
   cards=tuple(c for c in bank.cards if row['regime']=='full' or c.id not in row['accepted_full'])
   ranking,_=retrieve_candidates(cards,row['task'][:3000]+'\nRecent evidence/history:\n(none)',EmbeddingConfig('http://127.0.0.1:8110/v1','qwen3_embedding_8b'))
   candidates=[dict(id=c.id,score=v) for c,v in ranking]
   user=selection_input(row['task'],dict(videos=row['videos']),[c for c,v in ranking],role='global')
   schema={'type':'object','properties':{'selected_skill_ids':{'type':'array','items':{'type':'string','enum':[c.id for c,v in ranking]},'maxItems':1}},'required':['selected_skill_ids'],'additionalProperties':False}
  original={c['meta']['id']:c['when_to_use'] for c in read(out/'rrf8.json')['skills']}
  edited=read(out/'scope_edits.json')
  changed={'original':[], 'card4':['4'],'card5':['5'],'card4_5':['4','5']}[arm]
  for cid in changed:
   if any(c['id']==cid for c in candidates):
    old=f"## Skill ID: {cid}\nWhen to use: {original[cid]}";new=f"## Skill ID: {cid}\nWhen to use: {edited[cid]}"
    assert user.count(old)==1;user=user.replace(old,new)
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
   for cohort in ('all','new','previous','confirmation','expanded'):
    rs=[r for r in rows if r['arm']==a and r['regime']==g and not r['uncertain'] and ((cohort=='all' and r['cohort'] in ('previous','new')) or r['cohort']==cohort)];valid=[r for r in rs if r['status']=='ok'];pos=[r for r in valid if r['expected']];neg=[r for r in valid if not r['expected']]
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
