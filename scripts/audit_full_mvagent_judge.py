
import hashlib, importlib.util, json
from collections import defaultdict
from pathlib import Path
root=Path('/runs/devbox/mvagent_final_score_20261016')
source=Path('/runs/devbox/mvagent_full_20261014_transport/frozen_repo/eval/agent_eval/score_crossvid_ccqa.py')
spec=importlib.util.spec_from_file_location('judge_module',source); mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
qa={int(r['id']):r for r in json.loads(Path('/assets/crossvid/QA/CCQA.json').read_text())}
audit={'models':{},'all_same_prompt_differences':[]}
all_prompts=defaultdict(list)
for model in ['9B','27B','35B-A3B']:
 report=json.loads((root/model/'score'/mod.REPORT_NAME).read_text())
 different=[]; response_tokens=0; cached_score=0; keys=set()
 for row in report['samples']:
  q=qa[row['id']]
  prompt=mod.SCORE_PROMPT.format(QUESTION=q['question'],ANSWER=q['answer'],POINTS=q['scoring_points'],OUTPUT=row['prediction'])
  key=hashlib.sha256(json.dumps({'model':mod.JUDGE_MODEL,'prompt':prompt},ensure_ascii=False,sort_keys=True).encode()).hexdigest();keys.add(key)
  c=json.loads((root/model/'ccqa_judge_cache'/key[:2]/(key+'.json')).read_text())
  parsed=json.loads(mod._extract(c['response'],'score'))
  assert parsed['coverage']==c['coverage'] and parsed['correctness']==c['correctness']
  assert c['score']==sum(c['coverage'])+sum(c['correctness'])
  assert len(row['coverage'])==len(q['scoring_points'])
  if (row['coverage'],row['correctness']) != (c['coverage'],c['correctness']):different.append(row['id'])
  cached_score+=c['score']
  all_prompts[key].append({'model':model,'id':row['id'],'coverage':row['coverage'],'correctness':row['correctness']})
 audit['models'][model]={'logical_judgements':len(report['samples']),'unique_prompts':len(keys),'reported_cache_hits':sum(r['cached'] for r in report['samples']),'reported_uncached':sum(not r['cached'] for r in report['samples']),'cache_report_disagreement_ids':different,'reported_ccqa_score':report['official_score'],'cache_reconciled_ccqa_score':cached_score/report['all_score'],'all_score':report['all_score']}
for key,group in all_prompts.items():
 if len({json.dumps([r['coverage'],r['correctness']]) for r in group})>1:audit['all_same_prompt_differences'].append({'prompt_key':key,'judgements':group})
(root/'judge_audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'models':audit['models'],'same_prompt_difference_groups':len(audit['all_same_prompt_differences'])},indent=2))
