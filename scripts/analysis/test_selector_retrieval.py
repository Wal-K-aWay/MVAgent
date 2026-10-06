"""Compare retrieval methods and shortlist sizes with the unchanged real Global Selector."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
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
PARENT=ROOT/'outputs/analysis/20261005_when_to_use_styles'
REGIMES=('full','missing')
ARMS=tuple(f'{method}{k}' for method in ('rrf','embedding','bm25') for k in (4,8))

def read(p):return json.loads(Path(p).read_text())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,v):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_suffix(p.suffix+'.tmp');tmp.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n');tmp.replace(p)
def prepare(out):
 from skill_evolution.infra.store import tree_hash
 parent=ROOT/'outputs/analysis/20261005_selector_rejection_coverage'
 if out.exists() and any(out.iterdir()):raise ValueError('Fresh output required')
 out.mkdir(parents=True,exist_ok=True)
 for name in ('inputs.json','runtime.yaml','execution.yaml'):
  shutil.copy2(parent/name,out/name)
 for arm in ARMS:shutil.copy2(parent/'detailed.json',out/(arm+'.json'))
 shutil.copytree(ROOT/'src',out/'src',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
 shutil.copy2(__file__,out/'controller.py')
 inputs=read(out/'inputs.json')
 save(out/'protocol.json',dict(arms=list(ARMS),regimes=list(REGIMES),repeats=2,planned=len(inputs)*24,
  catalog='Existing11 cards, unchanged detailed when_to_use and strategy; missing removes accepted primary cards.',
  retrieval='RRF branch depth remains8 for both k4/k8; only final shortlist changes. Embedding/BM25 use k4/k8. BM25 admits positive-score matches only when catalog exceeds k. No score threshold or fallback.',
  telemetry='Runtime fixed retrieval_top_k=8 field is inherited; actual experimental k is in retriever name and experiment_arm. No production runtime/config changes.',
  limits='134 reused real development questions, frozen Codex labels (115 clear,19 uncertain), not human gold or independent Test. Controlled removal is not natural frequency. No Actor QA, Judge or optimization. Query uses question plus empty history; video metadata enters Selector only. Paired repeats are not independent samples.'))
 files=['inputs.json','runtime.yaml','execution.yaml','protocol.json','controller.py']+[a+'.json' for a in ARMS]
 save(out/'manifest.json',dict(commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),source_hash=tree_hash(out/'src'),files={p:sha(out/p) for p in files},parent_inputs_sha256=sha(parent/'inputs.json')))
 save(out/'status.json',dict(state='prepared',planned=len(inputs)*24))
 print(json.dumps(dict(questions=len(inputs),planned=len(inputs)*24)))


def run(out):
 import fcntl
 from skill_evolution.infra.store import tree_hash
 from mvagent.batch import ExecutionConfig,prepare_model_pools
 from mvagent.configs import MVAgentConfig
 from models.factory import ModelFactory
 from models.execution import execution_scope
 from models.embeddings import EmbeddingConfig
 from skill_evolution.configs.model_config import EvolutionModelConfig
 from mvagent.skills.bank import SkillBank
 from mvagent.skills.selection import select_skills
 import mvagent.skills.selection as selection
 from threading import local
 context=local()
 def experimental_retrieve(cards,query,embedding):
  arm=context.arm;k=int(arm[-1]);method=arm[:-1]
  if len(cards)<=k:return [(c,None) for c in sorted(cards,key=lambda c:c.id)],'experiment-full-'+arm
  if method=='embedding':ranking=selection.retrieve_embedding(cards,query,k,embedding)
  elif method=='bm25':ranking=selection.retrieve(cards,query,k)
  else:
   lexical=selection.retrieve(cards,query,8);semantic=selection.retrieve_embedding(cards,query,8,embedding);scores={};by_id={c.id:c for c in cards}
   for branch in (lexical,semantic):
    for rank,(card,_) in enumerate(branch,1):scores[card.id]=scores.get(card.id,0)+1/(60+rank)
   ranking=[(by_id[sid],scores[sid]) for sid in sorted(scores,key=lambda sid:(-scores[sid],sid))[:k]]
  assert len(ranking)<=k
  return ranking,'experiment-'+arm
 selection.retrieve_candidates=experimental_retrieve
 lock=(out/'controller.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 manifest=read(out/'manifest.json');assert tree_hash(out/'src')==manifest['source_hash'];assert all(sha(out/p)==v for p,v in manifest['files'].items())
 cfg=MVAgentConfig.from_yaml(out/'runtime.yaml');pools,failures=prepare_model_pools(cfg.to_dict(),ExecutionConfig.from_yaml(out/'execution.yaml'))
 save(out/'services.json',dict(unavailable=failures,pools={n:[r.to_dict() for r in p.replicas] for n,p in pools.items()}))
 if failures:raise RuntimeError('Unavailable pool; services not replaced')
 embedding=EmbeddingConfig('http://127.0.0.1:8110/v1','qwen3_embedding_8b')
 banks={a:SkillBank.from_dict(read(out/(a+'.json')),sha256=sha(out/(a+'.json'))) for a in ARMS}
 inputs=read(out/'inputs.json')
 def one(job):
  arm,regime,repeat,row=job;context.arm=arm;path=out/'results'/arm/regime/str(repeat)/(row['sample_id'].replace(':','_')+'.json')
  if path.exists():return read(path)
  bank=banks[arm];accepted=set(row['label']['acceptable_ids'])
  if regime=='missing':cards=tuple(c for c in bank.cards if c.id not in accepted)
  else:cards=bank.cards
  bank=SkillBank(cards,embedding=embedding);bank=replace(bank,sha256=hashlib.sha256(json.dumps(bank.to_dict(),sort_keys=True).encode()).hexdigest())
  expected=list(accepted) if regime=='full' else []
  events=[];requests=[];cache={};model=ModelFactory.create_model(EvolutionModelConfig(model_type='qwen3_5_35b_a3b_local'),cfg)
  def decide(prompt,**kw):requests.append(dict(user=prompt,**kw));return model.json_prompt(prompt,**kw)
  try:
   with execution_scope(emit=events.append):result=select_skills(bank,role='global',has_evidence=False,task=row['question'],state=dict(videos=row['videos'],history='(none)'),selection_cache=cache,decide=decide)
   retrieval=next(e for e in events if e['kind']=='skill_retrieval');selected=cache.get('selected',[])
   value=dict(sample_id=row['sample_id'],arm=arm,regime=regime,repeat=repeat,status=result['status'],selected=selected[0]['id'] if selected else None,expected=expected,uncertain=row['label']['uncertain'],bank_sha256=bank.sha256,catalog_ids=[c.id for c in cards],candidates=retrieval['candidates'],retriever=retrieval['retriever'],experiment_arm=arm,requests=requests,events=events,error=result.get('error'))
  except Exception as exc:value=dict(sample_id=row['sample_id'],arm=arm,regime=regime,repeat=repeat,status='error',error=repr(exc),expected=expected,uncertain=row['label']['uncertain'],requests=requests,events=events)
  finally:model.close()
  save(path,value);return value
 jobs=[(a,g,n,r) for n in range(2) for a in banks for g in REGIMES for r in inputs];random.Random(20261005).shuffle(jobs)
 done=0;errors=0
 with ThreadPoolExecutor(max_workers=4) as executor:
  for f in as_completed([executor.submit(one,j) for j in jobs]):
   result=f.result();done+=1;errors+=result['status']!='ok'
   save(out/'status.json',dict(state='running',done=done,total=len(jobs),errors=errors,pid=os.getpid(),time=datetime.now(timezone.utc).isoformat()))
 summarize(out);save(out/'status.json',dict(state='completed',done=done,total=len(jobs),errors=errors))

def summarize(out):
 from collections import Counter
 inputs={r['sample_id']:r for r in read(out/'inputs.json')};metrics={};rows=[]
 for a in ARMS:
  for g in REGIMES:
   rs=[read(p) for p in (out/'results'/a/g).glob('*/*.json')];rows+=rs
   for group in ('clear','all'):
    selected=[r for r in rs if group=='all' or not r['uncertain']];valid=[r for r in selected if r['status']=='ok'];positive=[r for r in valid if r['expected']];negative=[r for r in valid if not r['expected']]
    m=dict(attempted=len(selected),valid=len(valid),errors=len(selected)-len(valid),positive=len(positive),negative=len(negative),positive_match=sum(r['selected'] in r['expected'] for r in positive),wrong_card=sum(bool(r['selected']) and r['selected'] not in r['expected'] for r in positive),false_abstention=sum(r['selected'] is None for r in positive),correct_abstention=sum(r['selected'] is None for r in negative),false_selection=sum(bool(r['selected']) for r in negative),recalled_positive=sum(any(c['id'] in r['expected'] for c in r['candidates']) for r in positive),selected_cards=dict(Counter(r['selected'] for r in valid if r['selected'])))
    metrics[a+'/'+g+'/'+group]=m
 pairs=[]
 for a in ARMS:
  index={(r['sample_id'],r['regime'],r['repeat']):r for r in rows if r['arm']==a}
  for sid in sorted(inputs):
   for n in range(2):
    key=(sid,'full',n)
    if key not in index:continue
    choices={g:index[(sid,g,n)].get('selected') for g in REGIMES if (sid,g,n) in index}
    pairs.append(dict(sample_id=sid,arm=a,repeat=n,uncertain=inputs[sid]['label']['uncertain'],expected_full=inputs[sid]['label']['acceptable_ids'],choices=choices,full_primary_selected=choices.get('full') in inputs[sid]['label']['acceptable_ids'],stopped_when_primary_removed=choices.get('missing') is None if 'missing' in choices else None))
 # Keep compact results without multi-MB request payloads for analysis.
 save(out/'paired.json',pairs)
 save(out/'summary.json',dict(metrics=metrics,questions=len(inputs),review_uncertain=sum(r['label']['uncertain'] for r in inputs.values()),limits=read(out/'protocol.json')['limits']))

if __name__=='__main__':
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('mode',choices=['prepare','run','summarize']);ap.add_argument('--output',type=Path,required=True);args=ap.parse_args();out=args.output.resolve();sys.path.insert(0,str(out/'src' if (out/'src').exists() else ROOT/'src'))
 for name in ('NO_PROXY','no_proxy'):os.environ[name]=os.environ.get(name,'')+',127.0.0.1,localhost'
 if args.mode=='prepare':prepare(out)
 elif args.mode=='run':run(out)
 else:summarize(out)
