"""Paired metadata-style replay through the current Global retrieval and selector."""
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

ROOT = Path('/home/kww/projects/MVAgent_API')
SOURCE = ROOT/'outputs/analysis/20261005_selector_applicability'
STYLES = {
 'global-order-by-state-transitions': ('Order shuffled segments from one continuous video.', 'Order all supplied segments of one process by matching start and end states; not missing-event inference or interval localization.'),
 'global-missing-event-bridge': ('Infer the missing story event between earlier and later segments.', 'Infer the missing event between the supplied beginning and ending of one story using their states and causal links; not sorting supplied clips.'),
 'global-direct-detail-watch': ('Compare fine visual differences between videos.', 'Compare specified fine visual details across videos through joint viewing; not event totals, synchronized event-time states, interval alignment or narrative interpretation.'),
 'global-independent-focused-analysis': ('Identify videos showing specified actions, ingredients or other observable facts.', 'Check specified visible facts independently in each video and combine the findings; not event totals, timing relations or causal interpretation.'),
 'global-context-supported-interpretation': ('Compare the purpose, causal role or meaning of events across videos.', 'Interpret a behavior’s purpose, an event’s plot role or a thematic contrast from observed context and consequences; not mere presence, missing-event inference or procedural errors.'),
 'global-interval-event-ledger': ('Count repeated events or trace an object’s trajectory over time.', 'Count cumulative events, overtakes or occurrences, or trace a trajectory through an interval; not snapshot counts or counting matching videos.'),
 'global-local-temporal-relations': ('Compare the order or overlap of named actions within videos.', 'Determine before/after, first occurrence or simultaneous overlap of named actions within each video; not ordering supplied segments or synchronized cross-view snapshots.'),
 'global-procedure-error-check': ('Identify incorrect steps or part placement in assembly demonstrations.', 'Identify procedural errors using the question’s definitions, including wrong placement, unnecessary removal or corrective rework; repeated actions or different orders alone do not prove error.'),
 'global-reference-step-localization': ('Locate a matching step in another video from a supplied reference interval.', 'Identify the operation in a supplied reference interval, then find its functional equivalent and time boundaries in another video; not generic method comparison.'),
 'global-survey-then-focus': ('Survey video content for a broad question without a specific evidence target.', 'Survey broad, multi-part video content before focusing on relevant evidence; not a default for long videos or questions already naming a specific criterion.'),
 'global-synchronized-event-check': ('Read a video’s state when an event occurs in another synchronized view.', 'Locate an event in synchronized views, then read position, visibility, separation or quantity at that exact time; not cumulative interval totals or unsynchronized videos.'),
}
PREFIX='global-'
def read(p): return json.loads(Path(p).read_text())
def save(p,v):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);temp=p.with_suffix(p.suffix+'.tmp');temp.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n');temp.replace(p)
def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def labels(rows):
 # Question-by-question Codex review, before inference, based on unchanged card bodies.
 mapping={
 'BU:717':(['context-supported-interpretation'],True,'Environment-specific interactions require contextual judgment; alternative fact collection may also help.'),
 'BU:41':(['independent-focused-analysis'],False,'Visible predator/prey success is checked separately per video.'),
 'BU:729':(['independent-focused-analysis','local-temporal-relations'],True,'While may require temporal overlap or simply a local conjunction.'),
 'BU:464':(['independent-focused-analysis'],False,'Intersect observed activities across videos.'),
 'BU:673':(['independent-focused-analysis'],False,'Per-video doorway action predicate.'),
 'BU:37':([],True,'Vocal signals may require unavailable audio; visual evidence alone may not establish the predicate.'),
 'BU:306':(['independent-focused-analysis'],False,'Intersect observed activities across videos.'),
 'BU:14':(['context-supported-interpretation'],False,'Infer ambush versus active tracking from contextual behavior.'),
 'CC:591':(['direct-detail-watch','independent-focused-analysis'],True,'Flour-use differences may be fine visual details or explicit local facts.'),
 'CC:621':(['independent-focused-analysis'],True,'Ingredient conjunction is appropriate if ingredient identities are observable; taste alone is not.'),
 'CC:134':(['independent-focused-analysis'],False,'Check carbonated-liquid ingredient presence.'),
 'CC:719':(['independent-focused-analysis'],False,'Check vinegar ingredient presence.'),
 'CC:539':(['direct-detail-watch','independent-focused-analysis'],True,'Decorative sauce may require handling details or presence checklist.'),
 'CC:94':(['independent-focused-analysis'],True,'Oil identity and non-traditional category may remain visually ambiguous.'),
 'CC:217':(['direct-detail-watch','independent-focused-analysis'],False,'Halving shrimp is an observable local action, with possible fine-detail comparison.'),
 'CC:185':(['independent-focused-analysis'],False,'Check flour-butter mixture in each preparation.'),
 'NC:1210':([],False,'Separate films are not supplied segments of one continuous process; no bank method establishes cross-film chronology.'),
 }
 result=[]
 for row in rows:
  key=row['sample_id'].removeprefix('crossvid:');task=key.split(':')[0]
  if key in mapping:accepted,uncertain,reason=mapping[key]
  else:
   target={'FSA':'reference-step-localization','MOC':'synchronized-event-check','MSR':'synchronized-event-check','NC':'context-supported-interpretation','PEA':'procedure-error-check','PI':'missing-event-bridge','PSS':'order-by-state-transitions'}[task]
   if key in ('MOC:132','MSR:46','MSR:292'):target='interval-event-ledger'
   accepted=[target];uncertain=False;reason={'FSA':'Supplied reference operation to target time interval.','MOC':'State quantity or separation at cross-view anchor time.','MSR':'Cross-view anchor state, except trajectory questions mapped to interval tracking.','NC':'Contextual or causal role in narrative.','PEA':'Explicit assembly error definition.','PI':'Missing middle between supplied beginning and ending.','PSS':'Shuffled segments of one process.'}[task]
  result.append(dict(sample_id=row['sample_id'],acceptable_ids=[PREFIX+x for x in accepted],uncertain=uncertain,reason=reason,reviewer='Codex question/body semantic review; not independent human gold'))
 return result

def prepare(out):
 if out.exists() and any(out.iterdir()):raise ValueError('Fresh output directory required')
 out.mkdir(parents=True,exist_ok=True)
 from skill_evolution.infra.store import tree_hash
 rows=read(SOURCE/'train_inputs.json');save(out/'inputs.json',rows);save(out/'labels.json',labels(rows))
 cards=[read(p) for p in sorted((ROOT/'src/mvagent/skills/authored/acquisition-v002').glob('global*.json'))]
 assert {c['meta']['id'] for c in cards}==set(STYLES) and len(cards)==11
 banks={}
 for arm in ('short','compact','detailed'):
  values=[]
  for card in cards:
   value=dict(card)
   if arm!='detailed':value['when_to_use']=STYLES[card['meta']['id']][0 if arm=='short' else 1]
   values.append(value)
  banks[arm]=dict(schema_version=3,skills=values);save(out/(arm+'.json'),banks[arm])
 shutil.copytree(ROOT/'src',out/'src',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
 shutil.copy2(__file__,out/'controller.py')
 shutil.copy2(SOURCE/'runtime.yaml',out/'runtime.yaml');shutil.copy2(SOURCE/'execution.yaml',out/'execution.yaml')
 save(out/'protocol.json',dict(arms=list(banks),questions=len(rows),cards=11,repeats=2,workers=4,seed=20261005,actor_inference=False,optimizer_calls=0,judge_calls=0,
  input='Exact original question and options; videos IDs/durations passed to Selector. Current retrieval query is question[:3000] plus empty recent history, and does not contain video metadata.',
  limits='Reused CrossVid development questions, not independent Test. Codex semantic applicability labels are provisional, not human gold. Shorter descriptions omit detail, so this compares actual writing styles rather than isolating token count. No full QA or accuracy-gain claim. No service deployment or runtime changes.'))
 files=['inputs.json','labels.json','short.json','compact.json','detailed.json','runtime.yaml','execution.yaml','protocol.json','controller.py']
 save(out/'manifest.json',dict(commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),source_hash=tree_hash(out/'src'),files={p:digest(out/p) for p in files},original_input_hash=digest(SOURCE/'train_inputs.json')))
 save(out/'status.json',dict(state='prepared',planned=len(rows)*6))

def run(out):
 import fcntl
 from mvagent.batch import ExecutionConfig,prepare_model_pools
 from mvagent.configs import MVAgentConfig
 from models.factory import ModelFactory
 from skill_evolution.configs.model_config import EvolutionModelConfig
 from skill_evolution.infra.store import tree_hash
 from models.embeddings import EmbeddingConfig
 from models.execution import execution_scope
 from mvagent.skills.bank import SkillBank
 from mvagent.skills.selection import select_skills,retrieve,retrieve_embedding
 lock=(out/'controller.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 manifest=read(out/'manifest.json');assert tree_hash(out/'src')==manifest['source_hash'];assert all(digest(out/p)==h for p,h in manifest['files'].items())
 config=MVAgentConfig.from_yaml(out/'runtime.yaml');pools,failures=prepare_model_pools(config.to_dict(),ExecutionConfig.from_yaml(out/'execution.yaml'))
 save(out/'services.json',dict(unavailable=failures,pools={k:[r.to_dict() for r in p.replicas] for k,p in pools.items()}))
 if failures:raise RuntimeError('Unavailable services; no replacement attempted')
 embedding=EmbeddingConfig('http://127.0.0.1:8110/v1','qwen3_embedding_8b')
 banks={a:replace(SkillBank.from_dict(read(out/(a+'.json')),sha256=digest(out/(a+'.json'))),embedding=embedding) for a in ('short','compact','detailed')}
 jobs=[(a,n,row) for n in range(2) for a in banks for row in read(out/'inputs.json')];random.Random(20261005).shuffle(jobs)
 def one(job):
  arm,repeat,row=job;path=out/'results'/arm/str(repeat)/(row['sample_id'].replace(':','_')+'.json')
  if path.exists():return read(path)
  model=ModelFactory.create_model(EvolutionModelConfig(model_type='qwen3_5_35b_a3b_local'),config);events=[];calls=[]
  def decide(prompt,**kw):
   calls.append(dict(user=prompt,**kw));return model.json_prompt(prompt,**kw)
  try:
   bank=banks[arm];state=dict(videos=row['videos'],history='(none)');cache={}
   with execution_scope(emit=events.append):
    result=select_skills(bank,role='global',has_evidence=False,task=row['question'],state=state,selection_cache=cache,decide=decide)
    retrieval=next(e for e in events if e.get('type',e.get('kind'))=='skill_retrieval')
    lexical=retrieve(bank.cards,retrieval['query'],11);semantic=retrieve_embedding(bank.cards,retrieval['query'],11,embedding)
   selected=cache.get('selected',[])
   value=dict(sample_id=row['sample_id'],arm=arm,repeat=repeat,status=result['status'],selected=selected[0]['id'] if selected else None,
    candidates=retrieval['candidates'],lexical=[c.id for c,_ in lexical],semantic=[c.id for c,_ in semantic],requests=calls,events=events,error=result.get('error'))
  except Exception as exc:
   value=dict(sample_id=row['sample_id'],arm=arm,repeat=repeat,status='error',error=repr(exc),requests=calls,events=events)
  finally:model.close()
  save(path,value);return value
 done=0;errors=0
 with ThreadPoolExecutor(max_workers=4) as pool:
  for future in as_completed([pool.submit(one,j) for j in jobs]):
   value=future.result();done+=1;errors+=value['status']!='ok'
   save(out/'status.json',dict(state='running',done=done,total=len(jobs),errors=errors,time=datetime.now(timezone.utc).isoformat(),pid=os.getpid()))
 summarize(out);save(out/'status.json',dict(state='completed',done=done,total=len(jobs),errors=errors))

def summarize(out):
 from mvagent.skills.bank import count_words
 labels_by_id={r['sample_id']:r for r in read(out/'labels.json')};metrics={};all_results={}
 for arm in ('short','compact','detailed'):
  rs=[read(p) for p in sorted((out/'results'/arm).glob('*/*.json'))];all_results[arm]=rs
  for group in ('clear','all'):
   rows=[r for r in rs if group=='all' or not labels_by_id[r['sample_id']]['uncertain']];valid=[r for r in rows if r['status']=='ok'];positive=[r for r in valid if labels_by_id[r['sample_id']]['acceptable_ids']]
   def ok(r):return r['selected'] in labels_by_id[r['sample_id']]['acceptable_ids'] if labels_by_id[r['sample_id']]['acceptable_ids'] else r['selected'] is None
   def rank(r,field):
    ids=r[field] if field!='candidates' else [c['id'] for c in r[field]];wanted=labels_by_id[r['sample_id']]['acceptable_ids'];return next((i+1 for i,c in enumerate(ids) if c in wanted),None)
   recalled=[r for r in positive if rank(r,'candidates')]
   metrics[arm+'/'+group]=dict(attempted=len(rows),valid=len(valid),errors=len(rows)-len(valid),agreement=sum(ok(r) for r in valid),positive=len(positive),recall_at8=sum(bool(rank(r,'candidates')) for r in positive),mrr=sum(1/rank(r,'candidates') if rank(r,'candidates') else 0 for r in positive)/len(positive) if positive else None,
    lexical_recall_at8=sum(bool(rank(r,'lexical') and rank(r,'lexical')<=8) for r in positive),semantic_recall_at8=sum(bool(rank(r,'semantic') and rank(r,'semantic')<=8) for r in positive),correct_given_recall=sum(ok(r) for r in recalled),recalled=len(recalled),false_positive=sum(bool(r['selected']) for r in valid if not labels_by_id[r['sample_id']]['acceptable_ids']),abstained_positive=sum(r['selected'] is None for r in positive))
 paired=[]
 maps={a:{(r['sample_id'],r['repeat']):r for r in rs} for a,rs in all_results.items()}
 for key in sorted(set.intersection(*(set(m) for m in maps.values()))):
  lab=labels_by_id[key[0]];outcomes={a:maps[a][key] for a in maps};paired.append(dict(sample_id=key[0],repeat=key[1],label=lab,arms={a:dict(status=r['status'],selected=r.get('selected'),candidates=r.get('candidates'),correct=(r['selected'] in lab['acceptable_ids'] if lab['acceptable_ids'] else r['selected'] is None) if r['status']=='ok' else None) for a,r in outcomes.items()}))
 save(out/'paired.json',paired)
 lengths={a:[count_words(c['when_to_use']) for c in read(out/(a+'.json'))['skills']] for a in all_results}
 stability={a:dict(pairs=sum((s,0) in m and (s,1) in m for s in labels_by_id),changed=[s for s in labels_by_id if (s,0) in m and (s,1) in m and m[(s,0)].get('selected')!=m[(s,1)].get('selected')]) for a,m in maps.items()}
 save(out/'summary.json',dict(metrics=metrics,metadata_words=lengths,repeat_consistency=stability,limits=read(out/'protocol.json')['limits']))

if __name__=='__main__':
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('mode',choices=['prepare','run','summarize']);ap.add_argument('--output',type=Path,required=True);args=ap.parse_args();out=args.output.resolve()
 frozen=out/'src';sys.path.insert(0,str(frozen if frozen.exists() else ROOT/'src'))
 for name in ('NO_PROXY','no_proxy'):
  current=os.environ.get(name,'');os.environ[name]=current+(', ' if current else '')+'127.0.0.1,localhost'
 if args.mode=='prepare':prepare(out)
 elif args.mode=='run':run(out)
 else:summarize(out)
