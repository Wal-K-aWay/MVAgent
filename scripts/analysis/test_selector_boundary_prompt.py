"""Fixed-candidate short/detailed applicability boundary prompt experiment."""
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
PARENT=ROOT/'outputs/analysis/20261005_current_when_to_use'
ARMS=('short_current','short_boundary','detailed_current','detailed_boundary')
BOUNDARY_RULES='''# Selection rules
1. Identify exactly what the question asks to establish and the relationship between the supplied videos. Judge a candidate against this target and input relationship, not just shared objects, topic or words.
2. A candidate is eligible only if its when_to_use directly supports establishing that target using the supplied inputs. Do not expand or reinterpret its task to make it fit. Ordering actions within a video does not establish the order of supplied clips; reading a state at one event time does not count occurrences over an interval; interpreting event meaning does not locate a corresponding interval.
3. A conflicting stated prerequisite or exclusion disqualifies the candidate. This is a veto, not a disadvantage that similarity or usefulness can outweigh. Apply the same check even if it is the only candidate. Necessary input relationships must be present; facts the method is intended to observe need not already be known.
4. Keep general methods eligible when they directly cover the requested task. A special-purpose card is not required for every question: independent fact collection can support straightforward per-video predicates and comparisons. But a method that only supplies an auxiliary clue is not a substitute for a different reasoning or correspondence task. Do not require incidental domain details or identical wording.
5. If no candidate has a clear supported fit, return an empty selected_skill_ids array. Candidate retrieval and ranking do not establish fit. Otherwise select the most direct eligible method and copy its supplied reference exactly. Select at most one Skill.

'''

def read(p):return json.loads(Path(p).read_text())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,value):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_suffix(p.suffix+'.tmp');tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n');tmp.replace(p)

def prepare(out):
 from skill_evolution.infra.store import tree_hash
 if out.exists() and any(out.iterdir()):raise ValueError('Fresh output required')
 out.mkdir(parents=True,exist_ok=True)
 paths=sorted((PARENT/'results').glob('*/*/0/*.json'))
 inputs=[]
 for path in paths:
  row=read(path);req=row['requests'][0]
  inputs.append({k:row[k] for k in ('sample_id','regime','expected','uncertain','candidates')} | dict(style=row['arm'],user=req['user'],schema=req['json_schema'],source=str(path)))
 assert len(inputs)==536
 save(out/'inputs.json',inputs)
 for name in ('runtime.yaml','execution.yaml','id_mapping.json'):shutil.copy2(PARENT/name,out/name)
 shutil.copytree(ROOT/'src',out/'src',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
 shutil.copy2(__file__,out/'controller.py')

 save(out/'protocol.json',dict(arms=list(ARMS),repeats=2,planned=2144,model='Qwen3.5-35B-A3B',temperature=0,thinking=False,max_tokens=2048,workers=4,
  comparison='Current versus boundary-veto rules, on frozen short and detailed User inputs. Same candidates/order within style and same one-field output. No new retrieval.',
  limits='Reused134 real development questions,115 clear19 uncertain frozen Codex labels, not independent human gold/Test. Full/missing-primary conditions are paired. Auxiliary usefulness is semantically debatable. No Actor QA/Judge/optimizer. No production Prompt changes; labels are historical main-method reviews and some generic-helper negatives are disputed.'))
 files=['inputs.json','runtime.yaml','execution.yaml','id_mapping.json','controller.py','protocol.json']
 save(out/'manifest.json',dict(commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),source_hash=tree_hash(out/'src'),files={n:sha(out/n) for n in files},parent_requests={r['source']:sha(r['source']) for r in inputs}))
 save(out/'status.json',dict(state='prepared',planned=2144))

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
 lock=(out/'controller.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 manifest=read(out/'manifest.json');assert tree_hash(out/'src')==manifest['source_hash'];assert all(sha(out/n)==v for n,v in manifest['files'].items())
 cfg=MVAgentConfig.from_yaml(out/'runtime.yaml');pools,failures=prepare_model_pools(cfg.to_dict(),ExecutionConfig.from_yaml(out/'execution.yaml'))
 save(out/'services.json',dict(unavailable=failures,pools={n:[r.to_dict() for r in p.replicas] for n,p in pools.items()}));assert not failures
 def one(job):
  arm,repeat,row=job;path=out/'results'/arm/row['regime']/str(repeat)/(row['sample_id'].replace(':','_')+'.json')
  if path.exists():return read(path)
  schema=json.loads(json.dumps(row['schema']));system=build_selector_system_prompt('global')
  if arm.endswith('_boundary'):
   system=system.split('# Selection rules')[0]+BOUNDARY_RULES+'# Output contract'+system.split('# Output contract',1)[1]
  events=[];model=ModelFactory.create_model(EvolutionModelConfig(model_type='qwen3_5_35b_a3b_local'),cfg)
  value=dict(arm=arm,repeat=repeat,**row,requests=[dict(user=row['user'],system_prompt=system,json_schema=schema)])
  try:
   with execution_scope(emit=events.append):result=model.json_prompt(row['user'],system_prompt=system,json_schema=schema,schema_name='skill_selection')
   value.update(status=result['status'],result=result,selected=None,assessment_consistent=None)
   if result['status']=='ok':
    validate_json_schema(result['value'],schema);selected=result['value']['selected_skill_ids'];value['selected']=selected[0] if selected else None
  except Exception as exc:value.update(status='error',error=repr(exc))
  finally:model.close()
  value['events']=events;save(path,value);return value
 jobs=[(arm,n,row) for n in range(2) for arm in ARMS for row in read(out/'inputs.json') if row['style']==arm.split('_')[0]];random.Random(20261005).shuffle(jobs)
 errors=0
 with ThreadPoolExecutor(max_workers=4) as ex:
  for n,f in enumerate(as_completed([ex.submit(one,j) for j in jobs]),1):
   r=f.result();errors+=r['status']!='ok';save(out/'status.json',dict(state='running',done=n,total=len(jobs),errors=errors,pid=os.getpid(),time=datetime.now(timezone.utc).isoformat()))
 summarize(out);save(out/'status.json',dict(state='completed',done=len(jobs),total=len(jobs),errors=errors))

def summarize(out):
 from collections import Counter
 from statistics import mean
 rows=[read(p) for p in (out/'results').glob('*/*/*/*.json')];metrics={}
 for arm in ARMS:
  for regime in ('full','missing'):
   rs=[r for r in rows if r['arm']==arm and r['regime']==regime and not r['uncertain']];valid=[r for r in rs if r['status']=='ok'];pos=[r for r in valid if r['expected']];neg=[r for r in valid if not r['expected']]
   metrics[arm+'/'+regime]=dict(attempted=len(rs),errors=len(rs)-len(valid),positive=len(pos),match=sum(r['selected'] in r['expected'] for r in pos),false_abstention=sum(r['selected'] is None for r in pos),negative=len(neg),refusal=sum(r['selected'] is None for r in neg),inconsistent=sum(r.get('assessment_consistent') is False for r in valid))
  rs=[r for r in rows if r['arm']==arm];events=[e for r in rs for e in r['events']];usage=[e['usage'] for e in events if e['kind']=='model_response' and e.get('usage')];index={(r['sample_id'],r['regime'],r['repeat']):r for r in rs}
  metrics[arm+'/engineering']=dict(attempted=len(rs),errors=sum(r['status']!='ok' for r in rs),model_requests=sum(e['kind']=='model_request' for e in events),mean_input_tokens=mean(u['prompt_tokens'] for u in usage) if usage else None,mean_output_tokens=mean(u['completion_tokens'] for u in usage) if usage else None,repeat_changes=sum(index[(sid,g,1)]['selected']!=r['selected'] for (sid,g,n),r in index.items() if n==0 and (sid,g,1) in index))
 save(out/'summary.json',dict(metrics=metrics,limits=read(out/'protocol.json')['limits']))

if __name__=='__main__':
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('mode',choices=['prepare','run','summarize']);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args();out=args.output.resolve();sys.path.insert(0,str(out/'src' if (out/'src').exists() else ROOT/'src'))
 for name in ('NO_PROXY','no_proxy'):os.environ[name]=os.environ.get(name,'')+',127.0.0.1,localhost'
 globals()[args.mode](out)
