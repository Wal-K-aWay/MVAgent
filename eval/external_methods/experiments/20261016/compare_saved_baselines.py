"""Compare saved RSI and MVAgent answers only; run inside Modal, with no inference."""
from collections import Counter
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import statistics
import sys

root = Path('/runs/devbox/external_vam65_20261015')
agent_root = Path('/runs/devbox/mvagent_full_35b_parallel_20261015/35B-A3B')
out = Path('/runs/devbox/baseline_survey_20261016')
out.mkdir(exist_ok=True)
read = lambda p: json.loads(p.read_text())
labels = read(root/'prepared/private_labels.json')
rsi = {r['sample_id']: r for r in read(root/'rsi/scores.json')['rows']}
timings = {r['sample_id']: r['seconds'] for r in read(root/'analysis.json')['methods']['rsi']['samples']}
sys.path.insert(0, str(root/'frozen_repo/src'))
from skill_evolution.infra.benchmarks.aggregation import HierarchicalScoreAggregator
aggregator = HierarchicalScoreAggregator(
    dataset_of={s:r['dataset'] for s,r in labels.items()},
    category_of={s:r['task'] for s,r in labels.items()},
    task_population={(r['dataset'],r['task']):r['task_population'] for r in labels.values()},
    sample_weights={s:len(r['sample']['ground_truth']) if r['sample']['task']=='open_qa' else 1
                    for s,r in labels.items()})
def scores(ids, values):
    return asdict(aggregator.aggregate(sample_ids=ids, scores=values, buckets={}))['bucket_scores']

saved = read(root/'rsi/scores.json')['aggregate']['bucket_scores']
assert scores(list(rsi), {s:r['score'] for s,r in rsi.items()}) == saved
rows, excluded = [], []
for sid, label in labels.items():
    path = agent_root/'records'/label['dataset']/sid/'result.json'
    if not path.exists():
        excluded.append(dict(sample_id=sid, reason='missing record'))
        continue
    record = read(path)
    assert record['sample_id'] == sid
    if record['status'] != 'ok' or record['score'] is None:
        excluded.append(dict(sample_id=sid, reason=record['status']+'/'+record['scoring_status']))
        continue
    assert record['ground_truth'] == label['sample']['ground_truth'], sid
    same_question = record['result']['input']['question'] == label['sample']['question']
    assert same_question, (sid, record['result']['input']['question'][:100], label['sample']['question'][:100])
    assert record['result']['input']['videos'] == label['sample']['videos'], sid
    rows.append(dict(sample_id=sid, dataset=label['dataset'], task=label['task'],
        rsi_score=rsi[sid]['score'], agent_score=record['score'],
        rsi_seconds=timings[sid], agent_seconds=record['result']['time'],
        rsi_answer=rsi[sid]['prediction'], agent_answer=record['prediction'],
        same_question=same_question, source_sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
ids = [r['sample_id'] for r in rows]
summary = dict(protocol='Historical MVAgent independent-answer protocol; RSI native image settings; identical underlying questions and references, method-specific prompts/media/budgets.',
    rsi_root=str(root), agent_root=str(agent_root), paired=len(rows), excluded=excluded,
    benchmarks={})
for ds in ('crossvid','cvbench','mvu_eval'):
    subset = [r for r in rows if r['dataset']==ds]
    summary['benchmarks'][ds] = dict(n=len(subset), tasks=len({r['task'] for r in subset}),
        **{m:dict(score=scores(ids,{r['sample_id']:r[m+'_score'] for r in rows})['dataset:'+ds],
                  mean_seconds=statistics.mean(r[m+'_seconds'] for r in subset),
                  median_seconds=statistics.median(r[m+'_seconds'] for r in subset)) for m in ('rsi','agent')},
        agent_better=sum(r['agent_score']>r['rsi_score'] for r in subset),
        rsi_better=sum(r['rsi_score']>r['agent_score'] for r in subset))
current = read(Path('/runs/devbox/direct_answer_random_20261015/analysis/35B-A3B/paired.json'))
summary['current_direct_protocol_overlap'] = [r['sample_id'] for r in current if r['sample_id'] in labels]
assert len(rows)==63 and {r['sample_id'] for r in excluded}=={'crossvid:CCQA:725','crossvid:CCQA:73'}
(out/'paired.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))
(out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
print(json.dumps(summary,ensure_ascii=False,indent=2))
