"""Score saved external-method predictions with the shared official protocols."""
import argparse
from collections import defaultdict
from dataclasses import asdict
import json
from pathlib import Path
import sys

from common import write


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--prepared',type=Path,required=True)
    p.add_argument('--run',type=Path,required=True)
    p.add_argument('--judge-endpoint')
    args=p.parse_args()
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
    from skill_evolution.infra.benchmarks.contracts import EvaluationSample, SampleTask
    from skill_evolution.infra.benchmarks.scoring import ChoiceScorer, OrderingScorer, TemporalLocalizationScorer
    from skill_evolution.infra.benchmarks.catalog import CHOICE_PROTOCOL
    from skill_evolution.infra.benchmarks.aggregation import HierarchicalScoreAggregator
    labels=json.loads((args.prepared/'private_labels.json').read_text())
    rows, scores, pending, errors = [], {}, [], []
    judge=None
    for path in sorted(args.run.glob('*/execution.json')):
        execution=json.loads(path.read_text())
        sid=execution['sample_id']
        if not execution['success']:
            errors.append(execution)
            continue
        result=json.loads((path.parent/'result.json').read_text())
        prediction=result['answer']
        sample=EvaluationSample(**labels[sid]['sample'])
        if sample.task is SampleTask.OPEN_QA:
            if not args.judge_endpoint:
                pending.append(sid)
                continue
            from eval.agent_eval.score_crossvid_ccqa import LocalJudge, _score_one, SCORE_PROMPT
            if judge is None:
                judge=LocalJudge([args.judge_endpoint],1860)
            scored=_score_one(judge,args.prepared/'judge_cache',dict(sample_id=sid,
                point_count=len(sample.ground_truth),prediction=prediction,prompt=SCORE_PROMPT.format(
                    QUESTION=labels[sid]['judge_question'],ANSWER=labels[sid]['reference_answer'],
                    POINTS=sample.ground_truth,OUTPUT=prediction)),attempts=3)
            write(path.parent/'judge.json',scored)
            if scored['status']!='ok':
                raise RuntimeError(f'Judge failed for {sid}: {scored["error"]}')
            value=scored['score']/(2*len(sample.ground_truth))
        else:
            scorer=(ChoiceScorer(protocol=CHOICE_PROTOCOL[labels[sid]['dataset']])
                if sample.task is SampleTask.CHOICE else OrderingScorer()
                if sample.task is SampleTask.ORDERING else TemporalLocalizationScorer())
            value=scorer.score(prediction=prediction,sample=sample).score
        scores[sid]=value
        rows.append(dict(sample_id=sid,prediction=prediction,score=value))
    aggregate=None
    if scores:
        aggregator=HierarchicalScoreAggregator(
            dataset_of={s:r['dataset'] for s,r in labels.items()},
            category_of={s:r['task'] for s,r in labels.items()},
            task_population={(r['dataset'],r['task']):r['task_population'] for r in labels.values()},
            sample_weights={s:len(r['sample']['ground_truth']) if r['sample']['task']=='open_qa' else 1
                            for s,r in labels.items()})
        aggregate=asdict(aggregator.aggregate(sample_ids=list(scores),scores=scores,buckets={}))
    seen=defaultdict(set)
    for sid in scores:
        seen[labels[sid]['dataset']].add(labels[sid]['task'])
    complete_tasks={dataset:len(tasks)==count for dataset,count in [('crossvid',10),('cvbench',15),('mvu_eval',8)]
                    for tasks in [seen[dataset]]}
    summary=dict(valid_predictions=len(rows)+len(pending),scored=len(scores),pending_judge=pending,
        failed=errors,aggregate=aggregate,complete_task_coverage=complete_tasks,rows=rows,
        limitation='Development smoke panel; incomplete task coverage is not a full benchmark score')
    write(args.run/'scores.json',summary)
    print(json.dumps({k:v for k,v in summary.items() if k not in ('rows','failed')},ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
