"""Cluster-grounded input/task/answer Skill scopes with fixed Selector."""
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
PARENT=ROOT/'outputs/analysis/20261005_selector_card_ablation'
ARMS=('original','cluster_all','cluster_specialized')
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
 for path in sorted((PARENT/'results/original').glob('*/0/*.json')):
  row=read(path);assert row['status']=='ok' and len(row['requests'])==1;req=row['requests'][0]
  rows.append({k:row[k] for k in ('sample_id','cohort','regime','expected','uncertain','candidates')} | dict(user=req['user'],schema=req['json_schema'],source=str(path)))
 assert len(rows)==1028
 save(out/'inputs.json',rows)
 base=read(ROOT/'outputs/analysis/20261005_selector_semantic_fit/systems.json')['coverage']
 save(out/'systems.json',{arm:base for arm in ARMS})
 edits={
 '1':'Given multiple videos, interpret the roles, motives or causal consequences of depicted events to identify the video or explanation matching the question’s narrative or behavioral meaning.',
 '2':'Given videos with comparable subjects or activities, inspect the specified visual details to answer how their appearance, actions or execution differ.',
 '3':'Given multiple videos and explicit observable criteria, check the presence or absence of the named actions, objects or attributes and return the matching videos, shared facts or number of matching videos.',
 '4':'Given a tracked object and a time span in the videos, accumulate specified repeated events or follow its path to return an event total or the object’s trajectory/final state.',
 '5':'Given named actions within each video, compare their occurrence times to identify which videos show the requested before/after order or simultaneous overlap.',
 '6':'Given beginning and ending segments of the same story, infer the missing transition from their states and select the event most likely to occur in the unseen middle.',
 '7':'Given shuffled segments of one continuous video, connect their progress and transitions to return a chronological sequence containing each supplied segment ID.',
 '8':'Given assembly demonstrations and defined error types, classify candidate operations or attachments against those criteria and return the incorrect step, part or matching video combination.',
 '9':'Given two videos and a stated start/end interval in the reference video, find the functionally corresponding operation in the target video and return its start/end times.',
 '10':'Given videos and an open-ended request to summarize their overall content without a specified local evidence target, survey the relevant content and return a concise overview addressing the question.',
 '11':'Given synchronized views and a trigger event in one view, locate that event time and read the other view at the same time to return the requested position, spatial relation or snapshot count.'}
 save(out/'scope_edits.json',edits)
 bank=read(PARENT/'rrf8.json')
 for card in bank['skills']:card['when_to_use']=edits[card['meta']['id']]
 save(out/'input_scopes_bank.json',bank)
 for name in ('runtime.yaml','execution.yaml','rrf8.json'):shutil.copy2(PARENT/name,out/name)
 shutil.copytree(ROOT/'src',out/'src',ignore=shutil.ignore_patterns('__pycache__','*.pyc'));shutil.copy2(__file__,out/'controller.py')
 save(out/'protocol.json',dict(arms=ARMS,repeats=2,first_calls=6168,workers=4,model='Qwen3.5-35B-A3B',temperature=0,thinking=False,comparison='Cluster-grounded scopes: original vs all11 vs specialized edits preserving2/3/10. Inputs/types/tasks/answer content distilled from saved actual843 clustering original question/options/IDs/durations; mixed groups reviewed rather than blindly unified. Exact coverage/frozen candidate order/Schema/strategy/meta;514 reused questions,two regimes,two repeats. No fresh Test/retrieval/QA claim.',limits='All514 questions now reused development data, not independent Test or human gold. Clear401 positive and425 total clear; uncertain separate; two repeats not independent. Fixed saved original-arm repeat0 candidates across every arm/repeat. No retrieval/Embedding/Actor/Judge/optimizer/service deployment; production remains unchanged.'))
 cluster_root=ROOT/'outputs/analysis/20261002_cross_benchmark_clusters843'
 groups=read(cluster_root/'clusters.json');raw=read(cluster_root/'inputs.json')
 mapping={'1':[1,9],'2':[4,15],'3':[2,3,17],'4':[6,8],'5':[3],'6':[13],'7':[14],'8':[12],'9':[5],'10':[11],'11':[6,7]}
 used={n for ns in mapping.values() for n in ns}
 materials=[dict(cluster=g['cluster'],cases=[dict(sample_id=sid,**raw[sid]) for sid in g['ids']]) for g in groups if g['cluster'] in used]
 save(out/'cluster_materials.json',materials)
 save(out/'cluster_review.json',dict(mapping=mapping,source_files={str(cluster_root/n):sha(cluster_root/n) for n in ('clusters.json','inputs.json')},note='Codex pre-inference authoring from saved raw grouped inputs; clustering is not an applicability label. Pure5/12/13/14 support main9/8/6/7 types. Groups6/7 need separate snapshot vs temporal-total subtypes. Mixed1/3/11/15/17 cannot all be covered by one method; only supported subtype informs the corresponding existing strategy. Per-case relevance review in report; no answers or traces used. Source groups and selector panel overlap, so no new independent evidence.'))
 files=['inputs.json','systems.json','runtime.yaml','execution.yaml','rrf8.json','controller.py','protocol.json','scope_edits.json','input_scopes_bank.json','cluster_materials.json','cluster_review.json']
 save(out/'manifest.json',dict(commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),source_hash=tree_hash(out/'src'),files={n:sha(out/n) for n in files},parent_requests={r['source']:sha(r['source']) for r in rows}))
 save(out/'status.json',dict(state='prepared',jobs=6168))

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
  if arm!='original':
   original={c['meta']['id']:c['when_to_use'] for c in read(out/'rrf8.json')['skills']}
   for cid,text in read(out/'scope_edits.json').items():
    if (arm=='cluster_all' or cid not in ('2','3','10')) and any(c['id']==cid for c in candidates):
     before=f"## Skill ID: {cid}\nWhen to use: {original[cid]}"
     assert user.count(before)==1
     user=user.replace(before,f"## Skill ID: {cid}\nWhen to use: {text}")
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
   for cohort in ('combined','old','new','previous','confirmation','expanded'):
    rs=[r for r in rows if r['arm']==a and r['regime']==g and not r['uncertain'] and (cohort=='combined' or (cohort=='old' and r['cohort']!='expanded') or r['cohort']==cohort)];valid=[r for r in rs if r['status']=='ok'];pos=[r for r in valid if r['expected']];neg=[r for r in valid if not r['expected']]
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
