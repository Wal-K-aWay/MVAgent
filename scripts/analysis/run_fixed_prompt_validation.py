"""Freeze B0/D/S prompt-only full rollouts; detach one sequential controller."""
from __future__ import annotations
import argparse,collections,copy,difflib,fcntl,hashlib,json,os,random,shutil,subprocess,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from run_overnight_watch import read,save,sha
REPO=Path(__file__).resolve().parents[2]
PYTHON='/home/kww/miniconda3/envs/MVAgent/bin/python'
DATA=Path('/home/kww/datasets/Multi-Video');SEED=20260922;ARMS=['B0','D','S']
GP='src/mvagent/agents/global_agent/prompts.py';VP='src/mvagent/agents/video_agent/prompts.py'
D_RULE='- Before answering, compare the most plausible alternatives against retained evidence while preserving the question\'s entity and video identities, relation direction, quantifiers, negation, and event order. Distinguish observations from inferences. When the question asks for an inferred missing event, use observed endpoints to choose the best-supported explanation without claiming the missing event was seen. Keep the answer label consistent with this conclusion; do not expand the reasoning merely to enumerate every option.'
S_RULE='- Preserve the entities, relations, direction, quantities, and event order needed by the active instruction. Distinguish what retained observations establish from any necessary inference or unresolved detail. Do not turn a detail that was not observed into evidence that it is absent, and do not resolve contradictory observations by silently discarding one. Mention only answer-relevant gaps; do not invent missing facts or mechanically fill a checklist.'
WEAK={'crossvid/CC','crossvid/PI','mvu_eval/KIR','mvu_eval/Comparison','cvbench/Joint-video Spatial Navigating','cvbench/Joint-video Summarization','cvbench/Video Difference Caption','cvbench/Multi-view Scene Understanding'}
PROTECT={'crossvid/PSS','crossvid/MSR','crossvid/NC','mvu_eval/Counting','mvu_eval/TR','cvbench/Joint-video Counting','cvbench/Temporal Ordering','cvbench/Temporal Grounding'}
def family(bucket):return 'weak' if bucket in WEAK else 'protection' if bucket in PROTECT or (bucket.startswith('cvbench/') and 'temporal' in bucket.lower()) else 'other'
def changed_source(text,arm):
 if arm=='B0':return text
 if arm=='D':
  anchors=['- Treat `reason` as a brief decision basis, not an open-ended reasoning transcript.','- Choose answer when the evidence resolves the answer-critical analysis.','- Give a concise evidence-based `reason`. State any material remaining gap instead of inventing unseen visual facts.'];rule=D_RULE
 else:
  anchors=['- Return exactly this one field.','- Include any answer-relevant uncertainty in the same summary.'];rule=S_RULE
 for anchor in anchors:
  if text.count(anchor)!=1:raise ValueError('Prompt anchor not unique: '+anchor)
  text=text.replace(anchor,anchor+'\n'+rule)
 return text

def prepare(root):
 import yaml
 sys.path.insert(0,str(REPO/'src'))
 from skill_evolution.infra.benchmarks import load_multibench_records
 from skill_evolution.infra.data import group_by_media
 from skill_evolution.infra.store import tree_hash
 if (root/'protocol.json').exists():raise ValueError('Already frozen')
 root.mkdir(parents=True,exist_ok=True)
 feat_path=REPO/'outputs/analysis/20260919_crossvid_lite2500/all_features.json'
 feat={r['sample_id']:r for r in read(feat_path)}
 cv_meta=Path('eval/e2e_eval/CVBench/Video-R1/src/r1-v/Evaluation/CVBench.json')
 cv={f"cvbench:{r['id']}":r['task_type'] for r in read(REPO/cv_meta)}
 ids=list(feat)+['cvbench:'+str(r['id']) for r in read(DATA/'CVBench/QAs.json')]+['mvu_eval:'+r['task']+':'+str(r['id']) for r in read(DATA/'MVU-Eval/QAs.json')]
 rec=load_multibench_records(DATA,ids)
 media={s:feat[s]['source_keys'] if s in feat else ['path:'+p for p in r.sample.videos.values()] for s,r in rec.items()}
 groups=group_by_media(media)
 sources=[feat_path,REPO/cv_meta,REPO/'eval/crossvid_2500.json',DATA/'CrossVid/qa.jsonl',DATA/'CVBench/QAs.json',DATA/'MVU-Eval/QAs.json']
 blocked=set()
 def use(relative):
  p=REPO/relative;sources.append(p);return read(p)
 blocked|={r['sample_id'] for r in use('outputs/mvagent/skill/20260916_evolution_redesign/train130_gate300.json')['samples']}
 blocked|=set(use('outputs/analysis/20260921_expanded_mismatch/protocol.json')['ids'])
 blocked|={r['sample_id'] for r in use('outputs/analysis/20260921_e2e_mvagent_mismatch/cases.json')}
 blocked|={r['sample_id'] for r in use('outputs/analysis/20260921_full_baseline/outside_panel_cases.json')['cases']}
 blocked|={r['sample_id'] for r in use('outputs/analysis/20260921_systematic_bottlenecks/cap_complete_contract/cap_protocol.json')['selected']}
 blocked|=set(use('outputs/analysis/20260920_watch_diagnostic/sample_ids.json'))
 # Only actually executed night nodes; unused reserved IDs did not inform conclusions.
 night=use('outputs/analysis/20260920_overnight_watch/comparison.json');blocked|=set(night['arms']['N0'])
 cross_confirm=set(read(REPO/'eval/crossvid_2500.json'))
 excluded_groups={groups[s] for s in blocked if s in groups};confirm_groups={groups[s] for s in cross_confirm}
 eligible=[s for s in ids if rec[s].native_task not in {'CCQA','FSA'} and groups[s] not in excluded_groups|confirm_groups]
 by_group=collections.defaultdict(list)
 for s in sorted(eligible):by_group[groups[s]].append(s)
 rng=random.Random(SEED);gids=sorted(by_group);rng.shuffle(gids)
 # Reserve CV/MVU components before development sampling; Cross Lite already frozen.
 reserve=set(g for g in gids if any(not s.startswith('crossvid:') for s in by_group[g]))
 reserve_order=sorted(reserve);rng.shuffle(reserve_order);reserve=set(reserve_order[:len(reserve_order)//5])
 confirm_ids=sorted(cross_confirm|{s for g in reserve for s in by_group[g]})
 pools=collections.defaultdict(list);metadata={}
 for g in gids:
  if g in reserve:continue
  members=by_group[g];s=rng.choice(members);r=rec[s];bucket=r.dataset+'/'+(cv[s] if r.dataset=='cvbench' else r.native_task)
  row=dict(sample_id=s,group_id=g,bucket=bucket,family=family(bucket),video_count=len(r.sample.videos),component_questions=len(members),scope='source_isolated')
  metadata[s]=row;pools[(row['family'],bucket)].append(s)
 selected=[];allocation={}
 for f in ['weak','protection','other']:
  tasks=sorted(k for k in pools if k[0]==f);counts={k:0 for k in tasks}
  for k in tasks:rng.shuffle(pools[k])
  while sum(counts.values())<400:
   active=[k for k in tasks if counts[k]<len(pools[k])]
   if not active:break
   for k in active:
    if sum(counts.values())==400:break
    counts[k]+=1
  for k,n in counts.items():
   allocation['/'.join(k)]=dict(available_components=len(pools[k]),selected=n,conditional_probability=n/len(pools[k]))
   selected+=pools[k][:n]
 # Supplement separately marked question-level diagnostics, without confirmation IDs.
 supplement=collections.defaultdict(list)
 for s in sorted(ids):
  if s in blocked or s in cross_confirm or groups[s] in reserve or s in selected or rec[s].native_task in {'FSA','CCQA'}:continue
  r=rec[s];bucket=r.dataset+'/'+(cv[s] if r.dataset=='cvbench' else r.native_task);f=family(bucket)
  supplement[(f,bucket)].append(s)
 for f in ['weak','protection','other']:
  need=400-sum(metadata[s]['family']==f for s in selected)
  keys=sorted(k for k in supplement if k[0]==f)
  for k in keys:rng.shuffle(supplement[k])
  while need>0 and any(supplement[k] for k in keys):
   for k in keys:
    if not need:break
    if not supplement[k]:continue
    sid=supplement[k].pop();r=rec[sid]
    metadata[sid]=dict(sample_id=sid,group_id=groups[sid],bucket=k[1],family=f,video_count=len(r.sample.videos),scope='shared_source_diagnostic',component_questions=None)
    selected.append(sid);need-=1
 # Task round-robin scheduling prevents prefix dominated by a single family.
 queues=collections.defaultdict(list)
 for s in selected:queues[metadata[s]['bucket']].append(s)
 ordered=[]
 while any(queues.values()):
  for k in sorted(queues):
   if queues[k]:ordered.append(queues[k].pop())
 if len(ordered)<32:raise ValueError('Fewer than32 isolated development components')
 panel=[metadata[s] for s in ordered];selected_groups={groups[s] for s in ordered}
 isolated_groups={groups[r['sample_id']] for r in panel if r['scope']=='source_isolated'}
 assert not isolated_groups & (excluded_groups|confirm_groups|reserve)
 assert not set(ordered)&(blocked|cross_confirm) and not selected_groups&reserve
 save(root/'panel.json',dict(samples=panel,allocation=allocation,target_per_family=400,actual_families=dict(collections.Counter(r['family'] for r in panel)),selection='Outcome-blind isolated component representatives first, then separately marked task-stratified question supplement to400 per family. Probabilities shown only for isolated representative selection; no population weighting.'))
 save(root/'sample_ids.json',ordered);save(root/'confirmation_ids.json',confirm_ids)
 save(root/'source_audit.json',dict(excluded_ids=sorted(blocked),excluded_groups=sorted(excluded_groups),confirmation_groups=sorted(confirm_groups|reserve),development_groups=sorted(selected_groups),known_component_count=len(set(groups.values())),eligible_questions=len(eligible),eligible_components=len(by_group),limitations='Known source keys/path connectivity only, not whole-film/session isolation; confirmation previously seen in aggregate. Shared-source supplement is explicitly diagnostic; Cross confirmation IDs excluded but its sources overlap supplemental development. Confirmation is not source-independent of the combined panel.'))
 save(root/'preflight_ids.json',ordered[:32])
 paths=sorted({p for s in ordered for p in rec[s].sample.videos.values()})
 save(root/'media_identity.json',{'files':[dict(path=p,size=Path(p).stat().st_size,mtime_ns=Path(p).stat().st_mtime_ns) for p in paths]})
 # Freeze checkpoint exactly; snapshots also contain the normal evaluation entry.
 tracked=['src','eval/agent_eval/run.py',str(cv_meta)]
 base=root/'base';base.mkdir()
 archive=subprocess.run(['git','archive','9a2085b',*tracked],cwd=REPO,stdout=subprocess.PIPE,check=True).stdout
 import io,tarfile
 with tarfile.open(fileobj=io.BytesIO(archive)) as tar:tar.extractall(base,filter='data')
 arms={}
 for arm in ARMS:
  dest=root/'frozen'/arm;shutil.copytree(base,dest)
  rel=GP if arm=='D' else VP
  if arm!='B0':
   p=dest/rel;old=p.read_text();new=changed_source(old,arm);p.write_text(new)
   (root/f'{arm}.patch').write_text(''.join(difflib.unified_diff(old.splitlines(True),new.splitlines(True),fromfile=rel,tofile=rel)))
  arms[arm]={'source_sha256':tree_hash(dest/'src'),'skill_enabled':False}
 shutil.copy2(REPO/'configs/inference/local_qwen35_35b_a3b_historical_no_skill.yaml',root/'actor.yaml')
 shutil.copy2(REPO/'configs/inference/execution/gpu2_7_single.yaml',root/'execution.yaml')
 for name in ['run_fixed_prompt_validation.py','run_overnight_watch.py']:shutil.copy2(REPO/'scripts/analysis'/name,root/name)
 blocks=[]
 for i,start in enumerate(range(0,len(ordered),96)):
  members=ordered[start:start+96];p=root/'blocks'/f'{i:03}.json';save(p,members);blocks.append(dict(index=i,n=len(members),ids_file=str(p),order=['B0']+(['D','S'] if i%2==0 else ['S','D'])))
 cfg=yaml.safe_load((root/'actor.yaml').read_text());assert not any(cfg['agents'][r]['skill']['enabled'] for r in ['global_agent','video_agent'])
 immutable=[p for p in root.rglob('*') if p.is_file() and 'base' not in p.relative_to(root).parts]
 protocol=dict(repo=str(REPO),checkpoint='9a2085b',controller_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip(),seed=SEED,arms=arms,blocks=blocks,n=len(ordered),api_judge=False,optimizer=False,primary='Equal weight across selected task buckets; diagnostic only. Also report family and individual task results. No automatic promotion.',stage_order='32-question operational preflight for each arm, then all paired full-trajectory blocks. No score-based stopping.',mechanism_note='Fixed-evidence node diagnostics deferred until these fresh matched trajectories are available; no assertion of fixed observations in full runs.',source_sha256={str(p):sha(p) for p in sources},immutable_sha256={str(p.relative_to(root)):sha(p) for p in immutable})
 save(root/'protocol.json',protocol)
 print(json.dumps(dict(n=len(ordered),families=read(root/'panel.json')['actual_families'],tasks=allocation,confirmation=len(confirm_ids)),ensure_ascii=False),flush=True)

def verify(root):
 p=read(root/'protocol.json')
 for name,h in p['immutable_sha256'].items():
  if sha(root/name)!=h:raise ValueError('Frozen file changed: '+name)
 for name,h in p['source_sha256'].items():
  if sha(name)!=h:raise ValueError('Source dataset changed: '+name)
 for row in read(root/'media_identity.json')['files']:
  st=Path(row['path']).stat()
  if (st.st_size,st.st_mtime_ns)!=(row['size'],row['mtime_ns']):raise ValueError('Media changed')
 return p

def paired(parent,candidate,ids,groups):
 import numpy as np
 scored=[s for s in ids if s in parent and s in candidate and parent[s]['score'] is not None and candidate[s]['score'] is not None]
 ds={s:candidate[s]['score']-parent[s]['score'] for s in scored};components=collections.defaultdict(list)
 for sid,d in ds.items():components[groups[sid]].append(d)
 interval=None
 if components:
  sums=np.array([sum(v) for v in components.values()]);sizes=np.array([len(v) for v in components.values()]);n=len(sizes)
  weights=np.random.default_rng(SEED).multinomial(n,np.ones(n)/n,size=4000);draws=100*(weights@sums)/(weights@sizes);interval=[float(v) for v in np.quantile(draws,[.0125,.9875])]
 return dict(expected=len(ids),scored=len(scored),missing_or_unscored=len(ids)-len(scored),repairs=[s for s,d in ds.items() if d>0],regressions=[s for s,d in ds.items() if d<0],delta_pp=100*sum(ds.values())/len(ds) if ds else None,source_groups=len(components),cluster_bonferroni_97_5_pp=interval)

def summarize(root):
 sys.path.insert(0,str(root/'frozen/B0/src'))
 from skill_evolution.infra.evaluation import execution_metrics
 from types import SimpleNamespace
 p=read(root/'protocol.json');meta={r['sample_id']:r for r in read(root/'panel.json')['samples']};rows={a:{} for a in ARMS};partial={};complete=[]
 for block in p['blocks']:
  raw={a:{} for a in ARMS}
  for a in ARMS:
   base=root/'runs'/f"b{block['index']:03}_{a}"
   for path in (base/'records').glob('*/*/result.json'):
    r=read(path);sid=r['sample_id'];v=r.get('result') or {};acts=[x['action'] for x in v.get('action_history',[]) if x['action'] in {'analyze_videos','watch_videos'}]
    raw[a][sid]=dict(score=float(r['correct']) if r['status']==r['scoring_status']=='ok' and r['correct'] is not None else None,prediction=r['prediction'],first=acts[0] if acts else None,actions=acts,metrics=execution_metrics(SimpleNamespace(artifact=r,status=r['status'])),artifact=str(path))
  if all(len(raw[a])==block['n'] and (root/'runs'/f"b{block['index']:03}_{a}"/'summary.json').exists() for a in ARMS):
   complete.append(block['index'])
   for a in ARMS:rows[a].update(raw[a])
  elif any(raw.values()):partial[str(block['index'])]={a:len(raw[a]) for a in ARMS}
 ids=list(rows['B0']);strata={'all':ids}
 for field in ['family','bucket','scope']:
  for k in sorted({meta[s][field] for s in ids}):strata[k]=[s for s in ids if meta[s][field]==k]
 comparisons={a:{k:paired(rows['B0'],rows[a],members,{s:meta[s]['group_id'] for s in members}) for k,members in strata.items()} for a in ['D','S']}
 for a in ['D','S']:
  task_values=[c['delta_pp'] for k,c in comparisons[a].items() if '/' in k and c['delta_pp'] is not None]
  comparisons[a]['equal_task_macro']=dict(delta_pp=sum(task_values)/len(task_values) if task_values else None,n_tasks=len(task_values),note='Descriptive equal-task development metric; no independent confirmation or automatic promotion. Cluster intervals separately reported for paired strata.')
 save(root/'comparison.json',dict(complete_blocks=complete,partial_blocks=partial,questions_per_arm=len(ids),arms=rows,paired=comparisons))
 lines=['# 固定Prompt完整轨迹对照',f'完成配对题数：{len(ids)}/{p["n"]}。部分块单列，缺失/失败不记零。','', '|组别|已评分|正确|首次watch|','|---|---:|---:|---:|']
 for a in ARMS:lines.append(f"|{a}|{sum(r['score'] is not None for r in rows[a].values())}|{sum(r['score']==1 for r in rows[a].values())}|{sum(r['first']=='watch_videos' for r in rows[a].values())}|")
 lines+=['','|组别/范围|配对数|修复|损失|差值pp|','|---|---:|---:|---:|---:|']
 for a in ['D','S']:
  for k in ['all','weak','protection','other','source_isolated','shared_source_diagnostic']:
   if k in comparisons[a]:
    c=comparisons[a][k];lines.append(f"|{a}/{k}|{c['scored']}|{len(c['repairs'])}|{len(c['regressions'])}|{c['delta_pp']}|")
 lines+=['','各任务、action与执行指标见comparison.json。来源隔离后的类别覆盖有限，不是完整benchmark得分。固定证据机制诊断尚未运行。']
 (root/'report.md').write_text('\n'.join(lines)+'\n')

def run(root):
 global REPO
 REPO=Path(read(root/'protocol.json')['repo'])
 lock=(root/'controller.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 import psutil,yaml
 for proc in psutil.process_iter(['pid','cmdline']):
  cmd=proc.info['cmdline'] or []
  if proc.pid!=os.getpid() and any(str(root) in arg for arg in cmd) and any(arg.endswith('/run.py') for arg in cmd):raise RuntimeError('Runner already alive')
 p=verify(root);sys.path.insert(0,str(root/'frozen/B0/src'))
 from mvagent.batch import BatchExecutor,ExecutionConfig
 os.environ['NO_PROXY']=os.environ['no_proxy']='localhost,127.0.0.1';events=[]
 pool=BatchExecutor(ExecutionConfig.from_yaml(root/'execution.yaml'),on_event=events.append)
 try:
  pool.prepare(yaml.safe_load((root/'actor.yaml').read_text()));e=next(e for e in events if e['kind']=='batch_prepared');assert e['question_workers']==6 and not e['unavailable']
 finally:pool.close();save(root/'pool_verification.json',events)
 start=time.time();done=[]
 def status(stage,**kw):save(root/'status.json',dict(stage=stage,pid=os.getpid(),started_at=start,updated_at=time.time(),completed=done,**kw))
 def execute(stage,arm,file,preflight=False):
  out=root/'runs'/stage;manifest=out/'run_manifest.json'
  if manifest.exists() and read(manifest).get('status')=='completed' and (out/'summary.json').exists() and (root/'timings'/f'{stage}.json').exists() and (not preflight or (root/'preflight_checks'/f'{arm}.json').exists()):done.append(stage);return
  frozen=root/'frozen'/arm;env=dict(os.environ,PYTHONPATH=str(frozen/'src'),MVAGENT_PROJECT_ROOT=str(frozen))
  cmd=[PYTHON,str(frozen/'eval/agent_eval/run.py'),'--config',str(root/'actor.yaml'),'--execution-config',str(root/'execution.yaml'),'--sample-ids-file',str(file),'--output',str(out),'--benchmarks','crossvid','cvbench','mvu_eval']
  if manifest.exists():cmd+=['--resume']
  begin=time.time()
  with (root/f'{stage}.log').open('ab') as log:
   child=subprocess.Popen(cmd,cwd=REPO,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT);status(stage,child_pid=child.pid);code=child.wait()
  if code:raise RuntimeError(f'{stage} exited {code}; saved partial records, explicit resume supported')
  summary=read(out/'summary.json');assert summary['total_expected']==len(read(file)) and summary['total_pending']==0
  ev=[json.loads(l) for l in (out/'execution_events.jsonl').read_text().splitlines()];prepared=[e for e in ev if e['kind']=='batch_prepared'];assert prepared and all(e['question_workers']==6 and not e['unavailable'] for e in prepared)
  if preflight and (summary.get('total_errors',0) or not summary.get('score_complete')):raise RuntimeError('Preflight health/scoring failure: '+stage)
  if preflight:
   schemas=collections.Counter();verified_nodes=0;old_matches=0
   for path in (out/'records').glob('*/*/result.json'):
    raw=read(path)
    for e in raw.get('events',[]):
     if e.get('kind')!='structured_request':continue
     schemas[e.get('schema')]+=1;text='\n'.join(m.get('content','') for m in e.get('messages',[]) if isinstance(m.get('content'),str))
     if arm=='D' and e.get('agent')=='GlobalAgent':
      assert D_RULE in text;verified_nodes+=1
     if arm=='S' and e.get('agent')=='VideoAgent' and ('### Action: finish' in text or '# Final video summary' in text):
      assert S_RULE in text;verified_nodes+=1
   if arm!='B0' and not verified_nodes:raise RuntimeError('No exercised candidate prompt nodes: '+arm)
   save(root/'preflight_checks'/f'{arm}.json',dict(schemas=dict(schemas),verified_candidate_nodes=verified_nodes,errors=summary.get('total_errors'),score_complete=summary.get('score_complete'),note='Terminal wrappers covered by CPU rendering tests; only actually observed schemas listed here.'))
  done.append(stage);save(root/'timings'/f'{stage}.json',dict(seconds=time.time()-begin,n=len(read(file))))
 for arm in ARMS:execute('preflight_'+arm,arm,root/'preflight_ids.json',True)
 times=[read(root/'timings'/f'preflight_{a}.json')['seconds'] for a in ARMS]
 save(root/'estimate.json',dict(main_estimated_hours=sum(times)*p['n']/32/3600,n=p['n'],note='32-question per-arm measured throughput; dataset duration mixture may differ. Not a deadline.'))
 for block in p['blocks']:
  for arm in block['order']:execute(f"b{block['index']:03}_{arm}",arm,Path(block['ids_file']))
  summarize(root);status('paired_block_completed',block=block['index'])
 summarize(root);status('completed')

def launch(root):
 if not (root/'protocol.json').exists():prepare(root)
 import psutil
 if (root/'process.json').exists():
  previous=read(root/'process.json')
  if psutil.pid_exists(previous['pid']) and any(str(root) in a for a in psutil.Process(previous['pid']).cmdline()):raise RuntimeError('Controller already running')
 verify(root)
 with (root/'controller.log').open('ab') as log:
  proc=subprocess.Popen([PYTHON,str(root/'run_fixed_prompt_validation.py'),'run','--output',str(root)],cwd=REPO,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
 save(root/'process.json',dict(pid=proc.pid,launched_at=time.time()));print('launched',proc.pid,root,flush=True)

if __name__=='__main__':
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('mode',choices=['prepare','launch','run','summarize']);parser.add_argument('--output',type=Path,default=REPO/'outputs/analysis/20260922_fixed_prompt_validation');args=parser.parse_args();root=args.output.resolve()
 try:globals()[args.mode](root)
 except BaseException as e:
  if args.mode=='run':save(root/'status.json',dict(stage='failed',error=str(e),pid=os.getpid(),updated_at=time.time()))
  raise
