"""Fixed-candidate real-input comparison: direct selection versus reason before selection."""
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
PARENT=ROOT/'outputs/analysis/20261005_selector_prompt_revision'
ARMS=('direct','reason')

def read(p):return json.loads(Path(p).read_text())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,value):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_suffix(p.suffix+'.tmp');tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n');tmp.replace(p)

def prepare(out):
 from skill_evolution.infra.store import tree_hash
 if out.exists() and any(out.iterdir()):raise ValueError('Fresh output required')
 out.mkdir(parents=True,exist_ok=True)
 rows=[read(p) for p in sorted((PARENT/'results/previous').glob('*/0/*.json'))]
 assert len(rows)==268
 inputs=[{k:r[k] for k in ('sample_id','regime','expected','uncertain','candidates')} | dict(user=r['requests'][0]['user'],schema=r['requests'][0]['json_schema'],source=str(p)) for r,p in zip(rows,sorted((PARENT/'results/previous').glob('*/0/*.json')))]
 for r in inputs:
  r['schema']['required']=['selected_skill_ids'];r['schema']['properties']={k:v for k,v in r['schema']['properties'].items() if k=='selected_skill_ids'}
 save(out/'inputs.json',inputs)
 for name in ('runtime.yaml','execution.yaml','id_mapping.json'):shutil.copy2(PARENT/name,out/name)
 shutil.copytree(ROOT/'src',out/'src',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
 shutil.copy2(__file__,out/'controller.py')
 shutil.copy2(ROOT/'outputs/analysis/20261005_selector_explicit_applicability/src/mvagent/skills/prompts.py',out/'direct_prompts.py')
 save(out/'protocol.json',dict(arms=list(ARMS),repeats=2,planned=1072,model='Qwen3.5-35B-A3B',temperature=0,thinking=False,max_tokens=2048,workers=4,
  comparison='One call per arm. Same current applicability rules, task, numeric references, metadata and exact candidate order. Reason arm outputs one concise reason before selected_skill_ids; selection rules identical. No new retrieval.',
  limits='Reused134 real development questions,115 clear19 uncertain frozen Codex labels, not independent human gold/Test. Full/missing-primary conditions are paired. Auxiliary usefulness is semantically debatable. No Actor QA/Judge/optimizer. Current source adds reason; direct loads frozen preceding Prompt.'))
 files=['inputs.json','runtime.yaml','execution.yaml','id_mapping.json','controller.py','protocol.json','direct_prompts.py']
 save(out/'manifest.json',dict(commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),source_hash=tree_hash(out/'src'),files={n:sha(out/n) for n in files},parent_requests={r['source']:sha(r['source']) for r in inputs}))
 save(out/'status.json',dict(state='prepared',planned=1072))

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
 import importlib.util
 spec=importlib.util.spec_from_file_location("direct_prompts",out/"direct_prompts.py");direct_prompts=importlib.util.module_from_spec(spec);spec.loader.exec_module(direct_prompts)
 lock=(out/'controller.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 manifest=read(out/'manifest.json');assert tree_hash(out/'src')==manifest['source_hash'];assert all(sha(out/n)==v for n,v in manifest['files'].items())
 cfg=MVAgentConfig.from_yaml(out/'runtime.yaml');pools,failures=prepare_model_pools(cfg.to_dict(),ExecutionConfig.from_yaml(out/'execution.yaml'))
 save(out/'services.json',dict(unavailable=failures,pools={n:[r.to_dict() for r in p.replicas] for n,p in pools.items()}));assert not failures
 def one(job):
  arm,repeat,row=job;path=out/'results'/arm/row['regime']/str(repeat)/(row['sample_id'].replace(':','_')+'.json')
  if path.exists():return read(path)
  schema=json.loads(json.dumps(row['schema']));system=direct_prompts.build_selector_system_prompt('global')
  if arm=='reason':
   system=build_selector_system_prompt('global')
   schema['required']=['reason','selected_skill_ids'];schema['properties']={'reason':dict(type='string',minLength=1,pattern=r'[\s\S]*\S[\s\S]*'),**schema['properties']}
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
 jobs=[(arm,n,row) for n in range(2) for arm in ARMS for row in read(out/'inputs.json')];random.Random(20261005).shuffle(jobs)
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
