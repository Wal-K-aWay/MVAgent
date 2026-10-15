"""Global Selector abstention audit using real questions and controlled bank coverage."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys

ROOT=Path('/home/kww/projects/MVAgent_API')
PARENT=ROOT/'outputs/analysis/20261005_when_to_use_styles'
PREFIX='global-'
REGIMES=('full','missing','near_only','single_near')
# Alternatives share task words, domain or an auxiliary action, but not the primary workflow.
NEIGHBORS={
 'order-by-state-transitions':['missing-event-bridge','local-temporal-relations','reference-step-localization','survey-then-focus'],
 'missing-event-bridge':['order-by-state-transitions','context-supported-interpretation','direct-detail-watch','survey-then-focus'],
 'reference-step-localization':['direct-detail-watch','local-temporal-relations','order-by-state-transitions','independent-focused-analysis'],
 'synchronized-event-check':['interval-event-ledger','direct-detail-watch','local-temporal-relations','independent-focused-analysis'],
 'interval-event-ledger':['synchronized-event-check','independent-focused-analysis','local-temporal-relations','survey-then-focus'],
 'procedure-error-check':['direct-detail-watch','order-by-state-transitions','independent-focused-analysis','local-temporal-relations'],
 'context-supported-interpretation':['independent-focused-analysis','direct-detail-watch','missing-event-bridge','survey-then-focus'],
 'independent-focused-analysis':['direct-detail-watch','survey-then-focus','context-supported-interpretation','local-temporal-relations'],
 'direct-detail-watch':['independent-focused-analysis','survey-then-focus','context-supported-interpretation','order-by-state-transitions'],
}
STATIC=['mvu_eval:Counting:1','mvu_eval:Counting:1017','mvu_eval:Counting:1029','mvu_eval:Counting:117','mvu_eval:Counting:38','mvu_eval:Counting:445','mvu_eval:Counting:580']

def read(p):return json.loads(Path(p).read_text())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,v):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_suffix(p.suffix+'.tmp');tmp.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n');tmp.replace(p)
def classify(row):
 sid=row['sample_id']
 if sid.startswith('crossvid:'):
  task=sid.split(':')[1]
  if task in ('FSA','PI','PSS'):
   target={'FSA':'reference-step-localization','PI':'missing-event-bridge','PSS':'order-by-state-transitions'}[task];return [PREFIX+target],False,'Same explicit task as prior reviewed card body.'
  return [PREFIX+'independent-focused-analysis'],False,'Per-video ingredient/action facts and conjunctions.'
 if sid.startswith('cvbench:'):
  uncertain=sid not in ('cvbench:542','cvbench:576','cvbench:598')
  return [],uncertain,'No general spatial navigation/reference-frame workflow in this bank; placement comparisons are auxiliary. Simple-location cases marked uncertain.'
 if sid in STATIC:return [],False,'Static object counts are neither cumulative action occurrences nor synchronized event-time snapshots; predicate-video counting is not object counting.'
 if sid.startswith('mvu_eval:Comparison:'):
  if sid.endswith(':813'):return [PREFIX+'independent-focused-analysis'],False,'Shared signs/markings are independently observable predicates.'
  return [PREFIX+'direct-detail-watch',PREFIX+'independent-focused-analysis'],True,'Edit operation or vehicle-turn comparison may require detailed inspection versus explicit facts; insufficient task text to choose uniquely.'
 if sid=='mvu_eval:Counting:1212':return [PREFIX+'independent-focused-analysis'],False,'Identify vehicles showing turns, not the number of turn occurrences.'
 if sid.startswith('mvu_eval:TR:'):
  if sid.split(':')[-1] in ('1415','1438','1450','1481','261'):return [PREFIX+'order-by-state-transitions'],False,'Order supplied clips; positive control for same workflow across dataset wording.'
  return [PREFIX+'independent-focused-analysis'],False,'Find a clip matching a supplied visible description, not reorder clips.'
 raise ValueError('Unreviewed input '+sid)

def prepare(out):
 from skill_evolution.infra.store import tree_hash
 if out.exists() and any(out.iterdir()):raise ValueError('Fresh output required')
 out.mkdir(parents=True,exist_ok=True)
 rows={r['sample_id']:dict(r,origin='previous_real_panel') for r in read(PARENT/'inputs.json')}
 labels={r['sample_id']:dict(r) for r in read(PARENT/'labels.json')}
 # Correct explanatory prose only; accepted IDs remain identical to the prior prelabel.
 labels['crossvid:MOC:132']['reason']='Whole-interval cumulative overtakes, not an event-time snapshot.'
 hashes={}
 fixtures=ROOT/'tests/fixtures/skill_selector_cases.json'
 for c in read(fixtures)['cases']:
  if c['role']!='global' or c['origin']!='real':continue
  source=Path(c['source']['source']);assert source.exists() and sha(source)==c['source_sha256'];hashes[str(source)]=sha(source)
  sid=c['source']['id']
  if sid in rows:
   assert rows[sid]['question']==c['task'];continue
  rows[sid]=dict(sample_id=sid,question=c['task'],videos=c['state'].get('videos',{}),origin='historical_real_trajectory',source=c['source'],source_sha256=c['source_sha256'])
  accepted,uncertain,reason=classify(rows[sid]);labels[sid]=dict(sample_id=sid,acceptable_ids=accepted,uncertain=uncertain,reason=reason,reviewer='Codex question/body review, not independent human gold')
 inputs=[]
 for sid,row in sorted(rows.items()):
  label=labels[sid];accepted=label['acceptable_ids']
  if accepted:neighbors=[PREFIX+x for x in NEIGHBORS[accepted[0].removeprefix(PREFIX)]]
  elif sid in STATIC:neighbors=[PREFIX+x for x in ('interval-event-ledger','synchronized-event-check','independent-focused-analysis','direct-detail-watch')]
  elif sid.startswith('cvbench:'):neighbors=[PREFIX+x for x in ('direct-detail-watch','synchronized-event-check','independent-focused-analysis','survey-then-focus')]
  else:neighbors=[PREFIX+x for x in ('order-by-state-transitions','context-supported-interpretation','independent-focused-analysis','survey-then-focus')]
  neighbors=[x for x in neighbors if x not in accepted]
  assert neighbors
  inputs.append(dict(**row,label=label,neighbors=neighbors))
 save(out/'inputs.json',inputs);save(out/'source_records.json',hashes)
 for arm in ('short','compact','detailed'):shutil.copy2(PARENT/(arm+'.json'),out/(arm+'.json'))
 shutil.copy2(PARENT/'runtime.yaml',out/'runtime.yaml');shutil.copy2(PARENT/'execution.yaml',out/'execution.yaml')
 shutil.copytree(ROOT/'src',out/'src',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
 shutil.copy2(__file__,out/'controller.py')
 save(out/'protocol.json',dict(real_questions=len(inputs),arms=['short','compact','detailed'],regimes=list(REGIMES),repeats=2,workers=4,planned=len(inputs)*24,
  conditions={'full':'Unchanged full11 bank; expected IDs according to body review.', 'missing':'Remove all pre-reviewed primary methods; keep remaining competing cards.', 'near_only':'Only up to4 pre-reviewed superficially related/auxiliary cards, no primary method.', 'single_near':'Only first neighboring card, to test forced-nearest-choice pressure.'},
  engineering_controls='Two questions per dataset, full bank with stages=evidence at initial activation; expected eligible catalog empty. These are Runtime controls, not LLM abstention evidence.',
  labels='Frozen before inference. Codex semantic review, no video GT or independent human gold. Ambiguous inputs excluded from primary rates. An unavailable primary method does not mean auxiliary guidance has zero possible value.',
  limits='Reused development trajectories. Real questions unchanged; missing/near/single bank coverage is controlled, not a naturally occurring catalog distribution. Same-question regimes and repeats are paired, not independent observations. No optimization, Actor QA or Judge; no deployment. Runtime query includes question plus empty history; videos metadata enters Selector only.'))
 files=['inputs.json','source_records.json','short.json','compact.json','detailed.json','runtime.yaml','execution.yaml','protocol.json','controller.py']
 save(out/'manifest.json',dict(commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),source_hash=tree_hash(out/'src'),files={p:sha(out/p) for p in files},input_source_hashes={str(PARENT/'inputs.json'):sha(PARENT/'inputs.json'),str(PARENT/'labels.json'):sha(PARENT/'labels.json'),str(fixtures):sha(fixtures)}))
 save(out/'status.json',dict(state='prepared',planned=len(inputs)*24))
 print(json.dumps(dict(real_questions=len(inputs),clear=sum(not r['label']['uncertain'] for r in inputs),natural_no_primary=sum(not r['label']['uncertain'] and not r['label']['acceptable_ids'] for r in inputs),planned=len(inputs)*24)))

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
 lock=(out/'controller.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 manifest=read(out/'manifest.json');assert tree_hash(out/'src')==manifest['source_hash'];assert all(sha(out/p)==v for p,v in manifest['files'].items())
 cfg=MVAgentConfig.from_yaml(out/'runtime.yaml');pools,failures=prepare_model_pools(cfg.to_dict(),ExecutionConfig.from_yaml(out/'execution.yaml'))
 save(out/'services.json',dict(unavailable=failures,pools={n:[r.to_dict() for r in p.replicas] for n,p in pools.items()}))
 if failures:raise RuntimeError('Unavailable pool; services not replaced')
 embedding=EmbeddingConfig('http://127.0.0.1:8110/v1','qwen3_embedding_8b')
 banks={a:SkillBank.from_dict(read(out/(a+'.json')),sha256=sha(out/(a+'.json'))) for a in ('short','compact','detailed')}
 inputs=read(out/'inputs.json')
 def one(job):
  arm,regime,repeat,row=job;path=out/'results'/arm/regime/str(repeat)/(row['sample_id'].replace(':','_')+'.json')
  if path.exists():return read(path)
  bank=banks[arm];accepted=set(row['label']['acceptable_ids'])
  if regime=='missing':cards=tuple(c for c in bank.cards if c.id not in accepted)
  elif regime in ('near_only','single_near'):cards=tuple(c for c in bank.cards if c.id in row['neighbors'][:1 if regime=='single_near' else None])
  elif regime=='ineligible':cards=tuple(replace(c,stages=('evidence',)) for c in bank.cards)
  else:cards=bank.cards
  bank=SkillBank(cards,embedding=embedding);bank=replace(bank,sha256=hashlib.sha256(json.dumps(bank.to_dict(),sort_keys=True).encode()).hexdigest())
  expected=list(accepted) if regime=='full' else []
  events=[];requests=[];cache={};model=ModelFactory.create_model(EvolutionModelConfig(model_type='qwen3_5_35b_a3b_local'),cfg)
  def decide(prompt,**kw):requests.append(dict(user=prompt,**kw));return model.json_prompt(prompt,**kw)
  try:
   with execution_scope(emit=events.append):result=select_skills(bank,role='global',has_evidence=False,task=row['question'],state=dict(videos=row['videos'],history='(none)'),selection_cache=cache,decide=decide)
   retrieval=next(e for e in events if e['kind']=='skill_retrieval');selected=cache.get('selected',[])
   value=dict(sample_id=row['sample_id'],arm=arm,regime=regime,repeat=repeat,status=result['status'],selected=selected[0]['id'] if selected else None,expected=expected,uncertain=row['label']['uncertain'],bank_sha256=bank.sha256,catalog_ids=[c.id for c in cards],candidates=retrieval['candidates'],retriever=retrieval['retriever'],requests=requests,events=events,error=result.get('error'))
  except Exception as exc:value=dict(sample_id=row['sample_id'],arm=arm,regime=regime,repeat=repeat,status='error',error=repr(exc),expected=expected,uncertain=row['label']['uncertain'],requests=requests,events=events)
  finally:model.close()
  save(path,value);return value
 controls=[]
 for dataset in ('crossvid','cvbench','mvu_eval'):
  controls.extend([r for r in inputs if r['sample_id'].startswith(dataset+':')][:2])
 for row in controls:one(('detailed','ineligible',0,row))
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
 for a in ('short','compact','detailed'):
  for g in REGIMES:
   rs=[read(p) for p in (out/'results'/a/g).glob('*/*.json')];rows+=rs
   for group in ('clear','all'):
    selected=[r for r in rs if group=='all' or not r['uncertain']];valid=[r for r in selected if r['status']=='ok'];positive=[r for r in valid if r['expected']];negative=[r for r in valid if not r['expected']]
    m=dict(attempted=len(selected),valid=len(valid),errors=len(selected)-len(valid),positive=len(positive),negative=len(negative),positive_match=sum(r['selected'] in r['expected'] for r in positive),wrong_card=sum(bool(r['selected']) and r['selected'] not in r['expected'] for r in positive),false_abstention=sum(r['selected'] is None for r in positive),correct_abstention=sum(r['selected'] is None for r in negative),false_selection=sum(bool(r['selected']) for r in negative),recalled_positive=sum(any(c['id'] in r['expected'] for c in r['candidates']) for r in positive),selected_cards=dict(Counter(r['selected'] for r in valid if r['selected'])))
    metrics[a+'/'+g+'/'+group]=m
 pairs=[]
 for a in ('short','compact','detailed'):
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
