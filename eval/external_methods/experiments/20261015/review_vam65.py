"""Review saved scores and timing on Modal CPU; no inference or semantic rescoring."""
from collections import Counter
from dataclasses import asdict
import json
from pathlib import Path
import statistics
import sys


def main(root):
    labels=json.loads((root/'prepared/private_labels.json').read_text())
    report=json.loads((root/'final_summary.json').read_text())
    analysis=json.loads((root/'analysis.json').read_text())
    result=dict(methods={})
    for method in ('rsi','vam'):
        scored=report['methods'][method]['predictions']
        attempts=analysis['methods'][method]['samples']
        datasets={}
        for dataset in ('crossvid','cvbench','mvu_eval'):
            rows=[r for r in scored if labels[r['sample_id']]['dataset']==dataset]
            choice=[r for r in rows if labels[r['sample_id']]['sample']['task']=='choice']
            bare=[r for r in choice if r['prediction'].strip().upper() in
                  {chr(65+i) for i in range(len(labels[r['sample_id']]['sample']['options']))}]
            times=[r for r in attempts if r['success'] and labels[r['sample_id']]['dataset']==dataset]
            datasets[dataset]=dict(scored=len(rows),zero_score=sum(r['score']==0 for r in rows),
                partial_score=sum(0<r['score']<1 for r in rows),full_score=sum(r['score']==1 for r in rows),
                choice_answers=len(choice),single_bare_option_answers=len(bare),
                index_mean_seconds=statistics.mean(r['index_seconds'] for r in times)
                    if method=='vam' and times else None,
                query_mean_seconds=statistics.mean(r['query_seconds'] for r in times)
                    if method=='vam' and times else None)
        result['methods'][method]=dict(datasets=datasets,
            slowest=sorted(attempts,key=lambda r:r['seconds'],reverse=True)[:3],
            answer_examples=[dict(sample_id=r['sample_id'],score=r['score'],answer=r['prediction'][:240])
                for r in scored if labels[r['sample_id']]['dataset']=='cvbench'][:4])
    sys.path.insert(0,str(root/'frozen_repo/src'))
    from skill_evolution.infra.benchmarks.aggregation import HierarchicalScoreAggregator
    aggregator=HierarchicalScoreAggregator(dataset_of={s:r['dataset'] for s,r in labels.items()},
        category_of={s:r['task'] for s,r in labels.items()},
        task_population={(r['dataset'],r['task']):r['task_population'] for r in labels.values()},
        sample_weights={s:len(r['sample']['ground_truth']) if r['sample']['task']=='open_qa' else 1
                        for s,r in labels.items()})
    scores={m:{r['sample_id']:r['score'] for r in report['methods'][m]['predictions']} for m in ('rsi','vam')}
    common=sorted(scores['rsi'].keys() & scores['vam'].keys())
    assert len(common)==64 and len(scores['rsi'])==65 and len(scores['vam'])==64
    result['common_scored_subset']=dict(n=len(common),counts=dict(Counter(labels[s]['dataset'] for s in common)),
        scores={m:asdict(aggregator.aggregate(sample_ids=common,scores=scores[m],buckets={}))['bucket_scores']
                for m in ('rsi','vam')})
    result['limitation']='Bare option count is descriptive, not a semantic accuracy or complete format-failure measure; CrossVid BU allows multiple letters.'
    (root/'result_review.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main(Path(sys.argv[1]))
