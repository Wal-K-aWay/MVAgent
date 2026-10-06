"""Replay all B0 final nodes with original evidence; isolate D from early routing."""
import argparse,concurrent.futures as cf,copy,fcntl,hashlib,json,os,shutil,subprocess,sys,threading,time
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];PYTHON='/home/kww/miniconda3/envs/MVAgent/bin/python'
def read(p):return json.loads(p.read_text())
def save(p,x):
 p.parent.mkdir(parents=True,exist_ok=True);t=p.with_suffix('.tmp');t.write_text(json.dumps(x,ensure_ascii=False,indent=2));t.replace(p)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def final_request(raw):
 return [e for e in raw['events'] if e.get('kind')=='structured_request' and e.get('schema') in {'global_decision','global_answer'}][-1]
def prepare(out,source):
 assert not (out/'protocol.json').exists();sys.path.insert(0,str(source));from run_fixed_prompt_validation import D_RULE,verify
 verify(source);c=read(source/'comparison.json');meta=[]
 anchors=['- Treat `reason` as a brief decision basis, not an open-ended reasoning transcript.','- Do not claim unseen visual facts or use this action merely because some evidence exists; the evidence must resolve the answer-critical analysis.','- Give a concise evidence-based `reason`. State any material remaining gap instead of inventing unseen visual facts.']
 for sid,r in c['arms']['B0'].items():
  raw=read(Path(r['artifact']));req=final_request(raw);is_terminal=any(t.get('agent')=='GlobalAgent' and t.get('action')=='terminal_answer' for t in raw['result']['trajectory']);assert (req['schema']=='global_answer')==is_terminal;inp={k:req[k] for k in ['schema','messages','json_schema']};changed=copy.deepcopy(inp);n=0
  for msg in changed['messages']:
   for anchor in anchors:
    count=msg['content'].count(anchor);n+=count;msg['content']=msg['content'].replace(anchor,anchor+'\n'+D_RULE)
  assert n==(2 if inp['schema']=='global_decision' else 1),(sid,inp['schema'],n)
  path=out/'inputs'/f'{sid}.json';save(path,dict(B0=inp,D=changed));meta.append(dict(sample_id=sid,original_prediction=raw['prediction'],original_correct=raw['correct'],source_artifact=r['artifact'],source_sha256=sha(Path(r['artifact'])),input_sha256=sha(path)))
 assert len(meta)==1200
 shutil.copy2(Path(__file__),out/'probe.py');save(out/'protocol.json',dict(source=str(source),samples=meta,script_sha256=sha(out/'probe.py'),max_tokens=2048,temperature=0,top_p=1,thinking=False,description='All1200 ordinary/terminal final Global nodes. Original messages/schema versus only D rule insertions. No new tools executed; non-answer outputs remain unresolved. Original answers/GT never added to messages.'))
 print('prepared',len(meta),flush=True)
def score(out):
 p=read(out/'protocol.json');source=Path(p['source']);sys.path.insert(0,str(source/'frozen/B0/src'))
 from skill_evolution.infra.benchmarks import load_multibench_records
 from skill_evolution.infra.benchmarks.scoring import ChoiceScorer,OrderingScorer
 from skill_evolution.infra.benchmarks.contracts import SampleTask
 rec=load_multibench_records('/home/kww/datasets/Multi-Video',[r['sample_id'] for r in p['samples']]);meta={r['sample_id']:r for r in read(source/'panel.json')['samples']};rows=[]
 for r in p['samples']:
  sid=r['sample_id'];sample=rec[sid].sample;scorer=OrderingScorer() if sample.task==SampleTask.ORDERING else ChoiceScorer(strict_format=True)
  assert bool(scorer.score(prediction=r['original_prediction'],sample=sample).score)==r['original_correct']
  row=dict(sample_id=sid,task=meta[sid]['bucket'],scope=meta[sid]['scope'],family=meta[sid]['family'])
  for arm in ['B0','D']:
   f=out/'results'/arm/f'{sid}.json'
   if not f.exists():row[arm]={'status':'missing'};continue
   res=read(f);v=res.get('response',{}).get('value',{});answer=v.get('parameters',{}).get('answer') if v.get('action')=='answer' else v.get('answer') if 'action' not in v else None
   row[arm]=dict(status=res['status'],action=v.get('action','answer' if answer is not None else None),answer=answer,correct=bool(scorer.score(prediction=answer,sample=sample).score) if answer is not None else None,historical_match=answer==r['original_prediction'])
  rows.append(row)
 summary={}
 for k in ['all']+sorted({r['task'] for r in rows}):
  rs=[r for r in rows if k=='all' or r['task']==k];both=[r for r in rs if all(r[a].get('correct') is not None for a in ['B0','D'])]
  summary[k]=dict(n=len(rs),arms={a:dict(statuses=dict(Counter(r[a]['status'] for r in rs)),actions=dict(Counter(r[a].get('action') for r in rs)),correct=sum(r[a].get('correct') is True for r in rs)) for a in ['B0','D']},baseline_matches=sum(r['B0'].get('historical_match',False) for r in rs),both_direct=len(both),repairs=sum(not r['B0']['correct'] and r['D']['correct'] for r in both),losses=sum(r['B0']['correct'] and not r['D']['correct'] for r in both))
 save(out/'scored_rows.json',rows);save(out/'summary.json',summary)
def run(out):
 lock=(out/'probe.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);p=read(out/'protocol.json');source=Path(p['source']);assert sha(out/'probe.py')==p['script_sha256'];sys.path.insert(0,str(source));from run_fixed_prompt_validation import verify
 verify(source);sys.path.insert(0,str(source/'frozen/B0/src'))
 import yaml
 from models.pool import install_pools
 from models.factory import ModelFactory
 from models.execution import execution_scope
 from mvagent.configs import MVAgentConfig
 from mvagent.batch import BatchExecutor,ExecutionConfig
 for r in p['samples']:assert sha(out/'inputs'/f"{r['sample_id']}.json")==r['input_sha256']
 os.environ['NO_PROXY']=os.environ['no_proxy']='localhost,127.0.0.1';ev=[];cfgdata=yaml.safe_load((source/'actor.yaml').read_text());cfg=MVAgentConfig.from_dict(cfgdata);pool=BatchExecutor(ExecutionConfig.from_yaml(source/'execution.yaml'),on_event=ev.append)
 try:
  pool.prepare(cfgdata);save(out/'pool.json',ev);prepared=next(e for e in ev if e['kind']=='batch_prepared');assert prepared['question_workers']==6 and not prepared['unavailable'];install_pools(pool.pools);tls=threading.local()
  def work(job):
   sid,arm=job;f=out/'results'/arm/f'{sid}.json'
   if f.exists():return read(f)['status']
   inp=read(out/'inputs'/f'{sid}.json')[arm];events=[]
   try:
    if not hasattr(tls,'model'):tls.model=ModelFactory.create_model(cfg.global_agent.model,cfg)
    with execution_scope(emit=events.append,deadline=time.monotonic()+180):r=tls.model.json_chat(messages=inp['messages'],json_schema=inp['json_schema'],schema_name=inp['schema'],max_tokens=2048,temperature=0,top_p=1)
    save(f,dict(sample_id=sid,arm=arm,status=r['status'],response=r,events=events));return r['status']
   except Exception as e:save(f,dict(sample_id=sid,arm=arm,status='error',error=str(e),events=events));return 'error'
  jobs=[(r['sample_id'],a) for r in p['samples'] for a in ['B0','D']];import random;random.Random(20260921).shuffle(jobs);counts=Counter();start=time.time()
  with cf.ThreadPoolExecutor(max_workers=6) as ex:
   for result in ex.map(work,jobs):counts[result]+=1;save(out/'status.json',dict(stage='running',completed=sum(counts.values()),target=len(jobs),counts=counts,elapsed_seconds=time.time()-start,pid=os.getpid()))
  score(out);save(out/'status.json',dict(stage='completed',completed=len(jobs),counts=counts,elapsed_seconds=time.time()-start))
 finally:pool.close()
def launch(out):
 with (out/'run.log').open('ab') as f:
  child=subprocess.Popen([PYTHON,str(out/'probe.py'),'run','--output',str(out)],stdin=subprocess.DEVNULL,stdout=f,stderr=subprocess.STDOUT,start_new_session=True)
 save(out/'process.json',dict(pid=child.pid));print('launched',child.pid)
if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['prepare','run','launch','score']);parser.add_argument('--output',type=Path,default=ROOT/'outputs/analysis/20260921_fixed_prompt_diagnosis/final_node_probe');parser.add_argument('--source',type=Path,default=ROOT/'outputs/analysis/20260922_fixed_prompt_validation');args=parser.parse_args()
 try:
  if args.mode=='prepare':prepare(args.output.resolve(),args.source.resolve())
  else:globals()[args.mode](args.output.resolve())
 except BaseException as e:
  if args.mode=='run':save(args.output/'status.json',dict(stage='failed',error=str(e)))
  raise
