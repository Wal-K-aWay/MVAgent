"""Compare official and robust scores on unchanged same-question predictions."""
import ast,collections,hashlib,json,random,tarfile
from pathlib import Path
base=Path('/runs/devbox/global_short_large_20261017')
out=Path('/runs/devbox/global_short_scoring_20261018')
assert not out.exists()
with tarfile.open(base/'source.tar.gz') as archive:
 source=archive.extractfile('scripts/analyze_direct_answer_large.py').read().decode()
tree=ast.parse(source)
namespace={'defaultdict':collections.defaultdict,'random':random}
exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ('mean_score','interval')],type_ignores=[]),'frozen_score_helpers','exec'),namespace)
mean,interval=namespace['mean_score'],namespace['interval']
assert 'B. explanation'.strip().upper()[:1]=='B'
assert 'The answer is B'.strip().upper()[:1]!='B'
report={'models':{},'new_inference':False,'new_judge':False,'same_ids':True}
rows_out={}
for model in ('9B','27B','35B-A3B'):
 path=base/'analysis'/f'{model}_paired.json'
 rows=json.loads(path.read_text());assert len(rows)==1500
 mvu=[r for r in rows if r['dataset']=='mvu_eval'];assert len(mvu)==500
 original=(Path('/runs/devbox/e2e_full_20261012') if model=='9B' else Path('/runs/devbox/e2e_full_20261013_timeout'))/model/'scored/mvu_eval.json'
 old={r['sample_id']:r for r in json.loads(original.read_text())}
 after_path=Path('/runs/devbox/mvu_instruction_after_20261014')/model/'scored/mvu_eval.json'
 after={r['sample_id']:r for r in json.loads(after_path.read_text())}
 assert len(old)==len(after)==1824
 metrics={}
 for ds in ('cvbench','mvu_eval','crossvid'):
  group=[r for r in rows if r['dataset']==ds];assert len(group)==500
  metrics[ds]=dict(n=500,agent=mean(group,'direct'),e2e=mean(group,'e2e'),delta=mean(group,'direct')-mean(group,'e2e'),ci95=interval(group,'e2e'))
 original_rows=[];robust_rows=[];recomputed=[]
 for r in mvu:
  orig=old[r['sample_id']];cur=after[r['sample_id']]
  assert orig['task']==r['task']==cur['task']
  assert r['arms']['e2e']['score']==cur['score']
  original_rows.append({**r,'arms':{**r['arms'],'e2e':orig}})
  robust_rows.append({**r,'arms':{key:{**r['arms'][key],'score':r['arms'][key]['robust_score']} for key in ('direct','e2e')}})
  recomputed.append(dict(sample_id=r['sample_id'],task=r['task'],population=r['task_population'],agent=r['arms']['direct'],e2e_after=r['arms']['e2e'],e2e_original=orig))
 diag=dict(n=500,original_e2e_official=mean(original_rows,'e2e'),after_e2e_official=mean(mvu,'e2e'),
  agent_official=mean(mvu,'direct'),original_gap=mean(mvu,'direct')-mean(original_rows,'e2e'),
  after_gap=mean(mvu,'direct')-mean(mvu,'e2e'),after_e2e_robust=mean(robust_rows,'e2e'),agent_robust=mean(robust_rows,'direct'),
  robust_gap=mean(robust_rows,'direct')-mean(robust_rows,'e2e'),robust_ci95=interval(robust_rows,'e2e'),
  format_errors=dict(agent=sum(not r['arms']['direct']['format_ok'] for r in mvu),
    e2e_after=sum(not r['arms']['e2e']['format_ok'] for r in mvu),e2e_original=sum(not old[r['sample_id']]['format_ok'] for r in mvu)),
  e2e_stored_robust_disagreements=sum(r['arms']['e2e']['robust_score']!=after[r['sample_id']]['robust_score'] for r in mvu))
 report['models'][model]=dict(official=metrics,mvu=diag,paired_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
  e2e_original_path=str(original),e2e_original_sha256=hashlib.sha256(original.read_bytes()).hexdigest(),
  e2e_after_path=str(after_path),e2e_after_sha256=hashlib.sha256(after_path.read_bytes()).hexdigest())
 rows_out[model]=recomputed
out.mkdir()
(out/'summary.json').write_text(json.dumps(report,indent=2))
(out/'mvu_paired.json').write_text(json.dumps(rows_out,indent=2))
print(json.dumps(report),flush=True)

