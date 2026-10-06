"""Read all retained B0/D/S traces; decompose paired outcomes and first divergence."""
from __future__ import annotations
import argparse,collections,difflib,hashlib,json,re,statistics
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def read(p):return json.loads(p.read_text())
def save(p,x):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')
def digest(x):return hashlib.sha256(json.dumps(x,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
def prefix(p):
 lines=[]
 for line in p.open():
  if line.startswith('  "events":'):return json.loads(''.join(lines).rstrip().rstrip(',')+'\n}')
  lines.append(line)
 return json.loads(''.join(lines))
def features(raw):
 v=raw['result'];tr=v['trajectory'];g=[t['output'] for t in tr if t.get('agent')=='GlobalAgent' and t['action']=='decide' and t['output'].get('action') in {'analyze_videos','watch_videos','answer'}];vr=[t for t in tr if t.get('agent')=='VideoAgent'];actions=v.get('action_history',[])
 observations=[];reports=[];requests=[]
 for t in vr:
  rnd=t['input']['global_round'];vid=t['video_id'];st=t['output'].get('steps',[]);obs=[]
  for step in st:
   if step['action']=='observe':obs.append(dict(parameters=step['parameters'],observations=step['result'].get('observations',[]),status=step['result'].get('status')))
  observations.append(dict(round=rnd,video_id=vid,instruction=t['input']['instruction'],observations=obs))
  texts=[x['text'] for st in obs for x in st['observations']];summaries=[s['parameters']['summary'] for s in st if s['action']=='finish']
  summary=summaries[-1] if summaries else t['output'].get('report','').split('Summary:')[-1]
  reports.append(dict(round=rnd,video_id=vid,summary=summary))
  requests.append(dict(round=rnd,video_id=vid,observes=len(obs),observer_chars=sum(map(len,texts)),summary_chars=len(summary),summary=summary))
 observations.sort(key=lambda x:(x['round'],x['video_id']));reports.sort(key=lambda x:(x['round'],x['video_id']))
 final=[t['output'] for t in tr if t.get('agent')=='GlobalAgent' and (t['action']=='terminal_answer' or (t['action']=='decide' and t['output'].get('action')=='answer'))]
 reason=final[-1].get('reason','') if final else ''
 choices=[dict(action=x.get('action'),parameters=x.get('parameters')) for x in g]
 watch=v.get('watch_results',[])
 return dict(first_action=g[0]['action'],first_choice=digest(choices[0]),first_full_decision=digest(g[0]),global_steps=len(g),first_instruction_chars=sum(len(x.get('instruction','')) for x in choices[0]['parameters'].get('videoagent_request',[]))+len(choices[0]['parameters'].get('instruction','')),action_sequence=[x['action'] for x in actions if x['action'] in ['analyze_videos','watch_videos']],action_parameters=digest([dict(action=x['action'],parameters=x.get('parameters',{})) for x in actions]),history=digest(actions),all_observations=digest(observations),first_round_observations=digest([x for x in observations if x['round']==1]),first_round_reports=digest([x for x in reports if x['round']==1]),watch_evidence=digest(watch),observes=sum(r['observes'] for r in requests),video_requests=len(requests),multiobserve_requests=sum(r['observes']>1 for r in requests),observer_chars=sum(r['observer_chars'] for r in requests),summary_chars=sum(r['summary_chars'] for r in requests),reason_chars=len(reason),reason_at_cap=len(reason)>=1180,requests=requests,prefix_sha256=digest(raw))
def sensitivity(rows,results):
 out={};unc=re.compile(r'\b(?:uncertain|unclear|not observed|not visible|cannot (?:confirm|determine)|not (?:explicitly|clearly)|inferred|inference)\b',re.I)
 for a,rs in rows.items():
  req=[q for r in rs.values() for q in r['requests']];out[a]=dict(requests=len(req),mean_summary_chars_per_request=statistics.mean(q['summary_chars'] for q in req),uncertainty_lexical_requests=sum(bool(unc.search(q['summary'])) for q in req))
 ps=[]
 for sid,p in results['S']['pairs'].items():
  if p['path']!='same_all_observations_and_watch':continue
  b={(q['round'],q['video_id']):q for q in rows['B0'][sid]['requests']};c={(q['round'],q['video_id']):q for q in rows['S'][sid]['requests']};assert b.keys()==c.keys()
  ratios=[difflib.SequenceMatcher(None,b[k]['summary'].split(),c[k]['summary'].split(),autojunk=False).ratio() for k in b]
  ps.append(dict(delta=p['delta'],similarity=statistics.mean(ratios) if ratios else 1))
 out['matched_observation_summary_similarity']={label:dict(n=len(rs),mean=statistics.mean(r['similarity'] for r in rs),at_least80pct=sum(r['similarity']>=.8 for r in rs)) for label,rs in [('all',ps),('flips',[r for r in ps if r['delta']]),('repair',[r for r in ps if r['delta']>0]),('loss',[r for r in ps if r['delta']<0])]}
 out['task_scope']={}
 for task in sorted({r['task'] for r in rows['B0'].values()}):
  for scope in ['source_isolated','shared_source_diagnostic']:
   ids=[s for s,r in rows['B0'].items() if r['task']==task and r['scope']==scope];out['task_scope'][task+'/'+scope]=dict(n=len(ids),net_S=sum(rows['S'][s]['score']-rows['B0'][s]['score'] for s in ids),groups=len({rows['B0'][s]['group_id'] for s in ids}))
 return out
def run(root,out):
 c=read(root/'comparison.json');panel=read(root/'panel.json')['samples'];meta={r['sample_id']:r for r in panel};ids=[r['sample_id'] for r in panel]
 assert c['questions_per_arm']==len(ids)==1200 and len(set(ids))==1200
 hist=read(ROOT/'outputs/analysis/20260920_watch_diagnostic/historical_rows.json');rows={a:{} for a in ['B0','D','S']};totals={}
 for arm in rows:
  for sid in ids:
   rec=c['arms'][arm][sid];raw=prefix(Path(rec['artifact']));assert raw['sample_id']==sid and raw['prediction']==rec['prediction'] and float(raw['correct'])==rec['score'];assert raw['status']==raw['scoring_status']=='ok'
   r=features(raw);r.update(score=rec['score'],prediction=rec['prediction'],task=meta[sid]['bucket'],scope=meta[sid]['scope'],family=meta[sid]['family'],group_id=meta[sid]['group_id'],metrics=rec['metrics'],artifact=rec['artifact']);rows[arm][sid]=r
  totals[arm]=dict(correct=sum(r['score'] for r in rows[arm].values()),first_actions=dict(collections.Counter(r['first_action'] for r in rows[arm].values())),all_evidence_actions=dict(collections.Counter(a for r in rows[arm].values() for a in r['action_sequence'])),means={k:statistics.mean(r[k] for r in rows[arm].values()) for k in ['global_steps','observes','video_requests','summary_chars','observer_chars','reason_chars','first_instruction_chars']},reason_at_cap=sum(r['reason_at_cap'] for r in rows[arm].values()),multiobserve_requests=sum(r['multiobserve_requests'] for r in rows[arm].values()),health={k:sum(r['metrics'].get(k,0) for r in rows[arm].values()) for k in ['fatal','invalid','model_errors','failed_video_requests','structured_repairs','length_responses','terminal_answer','model_calls','total_tokens']})
  print(arm,'scanned',len(rows[arm]),flush=True)
 results={}
 for arm in ['D','S']:
  pairs={}
  for sid in ids:
   b,r=rows['B0'][sid],rows[arm][sid];d=r['score']-b['score'];h=hist['e2e_35b_a3b'].get(sid);old=hist['agent_35b_a3b'][sid]
   cell='unpaired' if h is None or h['score'] is None else (('both_correct' if b['score'] else 'e2e_only') if h['score'] else ('agent_only' if b['score'] else 'both_wrong'))
   eq={k:b[k]==r[k] for k in ['first_action','first_choice','first_full_decision','action_sequence','action_parameters','history','all_observations','first_round_observations','first_round_reports','watch_evidence']}
   path='same_public_history' if eq['history'] else 'same_all_observations_and_watch' if eq['all_observations'] and eq['watch_evidence'] else 'same_first_round_observations' if eq['first_round_observations'] and b['first_action']=='analyze_videos' and eq['first_choice'] else 'different_first_request' if not eq['first_choice'] else 'other_evidence_change'
   pairs[sid]=dict(delta=d,cell=cell,old_agent_prediction_match=old['prediction']==b['prediction'],outcome='repair' if d>0 else 'loss' if d<0 else 'both_correct' if b['score'] else 'both_wrong',same=eq,first_transition=b['first_action']+' -> '+r['first_action'],path=path,observe_delta=r['observes']-b['observes'],step_delta=r['global_steps']-b['global_steps'],task=b['task'],scope=b['scope'],group=b['group_id'])
  def group_by(field):
   ans={}
   for value in sorted({p[field] for p in pairs.values()}):
    selected=[s for s in ids if pairs[s][field]==value];ps=[pairs[s] for s in selected]
    ans[value]=dict(n=len(ps),repairs=sum(p['delta']>0 for p in ps),losses=sum(p['delta']<0 for p in ps),net=sum(p['delta'] for p in ps),b0_correct=sum(rows['B0'][s]['score'] for s in selected),candidate_correct=sum(rows[arm][s]['score'] for s in selected),groups=len({p['group'] for p in ps}),mean_observe_delta=statistics.mean(p['observe_delta'] for p in ps),mean_step_delta=statistics.mean(p['step_delta'] for p in ps))
   return ans
  results[arm]=dict(by_task=group_by('task'),by_cell=group_by('cell'),by_path=group_by('path'),by_outcome=group_by('outcome'),by_first_transition=group_by('first_transition'),by_source_group=group_by('group'),same_counts={k:sum(p['same'][k] for p in pairs.values()) for k in next(iter(pairs.values()))['same']},pairs=pairs)
  results[arm]['macro_sensitivity']={str(n):dict(tasks=sum(v['n']>=n for v in results[arm]['by_task'].values()),delta_pp=statistics.mean(100*v['net']/v['n'] for v in results[arm]['by_task'].values() if v['n']>=n)) for n in [1,10,20,50]}
  assert sum(x['net'] for x in results[arm]['by_task'].values())==totals[arm]['correct']-totals['B0']['correct']
 save(out/'sensitivity.json',sensitivity(rows,results))
 save(out/'trajectory_features.json',rows);save(out/'diagnosis.json',dict(n=1200,raw_records_reconciled=3600,totals=totals,comparisons=results,baseline_historical_prediction_matches=sum(p['old_agent_prediction_match'] for p in results['S']['pairs'].values()),input_hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [root/'protocol.json',root/'comparison.json',root/'panel.json',Path(__file__)]}))
 print(json.dumps({'totals':totals,'comparisons':{a:{k:v for k,v in r.items() if k not in ['pairs','by_source_group','by_task']} for a,r in results.items()}},indent=2))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=ROOT/'outputs/analysis/20260922_fixed_prompt_validation');p.add_argument('--output',type=Path,default=ROOT/'outputs/analysis/20260921_fixed_prompt_diagnosis');args=p.parse_args();run(args.root,args.output)
