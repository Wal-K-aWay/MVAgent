"""Paired official scores and reliability for the frozen enlarged direct-answer panel."""
from collections import defaultdict
import json
from pathlib import Path
import random
import shutil
import sys

from run_direct_answer_large import OUT, FULL, MODELS, REPORT, read, write, sha, now, core
from skill_evolution.infra.benchmarks.catalog import load_multibench_records, build_official_scorer


def mean_score(rows, arm):
    groups = defaultdict(list)
    for row in rows:
        groups[row['task']].append(row)
    weights = {task:1 if rs[0]['dataset']=='crossvid' else rs[0]['task_population'] for task,rs in groups.items()}
    def task_score(task, rs):
        if task == 'CCQA':
            return sum(r['arms'][arm]['score']*r['points'] for r in rs)/sum(r['points'] for r in rs)
        return sum(r['arms'][arm]['score'] for r in rs)/len(rs)
    return sum(weights[t]*task_score(t,rs) for t,rs in groups.items())/sum(weights.values())


def interval(rows, arm, repetitions=2000):
    groups = defaultdict(list)
    for row in rows:
        groups[row['task']].append(row)
    rng = random.Random(0)
    values = []
    for _ in range(repetitions):
        sampled = [r for rs in groups.values() for r in rng.choices(rs,k=len(rs))]
        values.append(mean_score(sampled,'direct')-mean_score(sampled,arm))
    values.sort()
    return [values[int(.025*repetitions)], values[int(.975*repetitions)]]


def self_check():
    rows = [dict(dataset='crossvid',task=t,task_population=1,points=p,
                 arms={'direct':{'score':a},'e2e':{'score':b}})
            for t,p,a,b in [('CCQA',1,1.,0.),('CCQA',3,0.,0.),('BU',1,.5,.5)]]
    assert abs(mean_score(rows,'direct')-.375)<1e-10
    assert abs(mean_score(rows,'e2e')-.25)<1e-10
    constant=[dict(dataset='cvbench',task=t,task_population=w,points=1,
                   arms={'direct':{'score':.7},'e2e':{'score':.4}}) for t,w in [('a',9),('b',1)]]
    assert all(abs(v-.3)<1e-10 for v in interval(constant,'e2e',100))
    print('Official aggregation and paired bootstrap checks passed')


def analyze():
    self_check()
    selection = read(OUT/'selection.json')
    records = load_multibench_records('/assets', selection['ids'])
    scorer, identity = build_official_scorer(records,{})
    summary = dict(at=now(), selection_sha256=sha(OUT/'selection.json'), scorer=identity, models={},
        inference_repeated=False, bootstrap='2000 paired within-task resamples, seed0; no multiplicity or shared-video correction',
        limits='Development/evaluation overlap is disclosed; same-panel improvements are not guarantees for all inputs.')
    for shard in range(2):
        assert read(OUT/f'shard{shard}/progress.json')['phase']=='completed'
    for model in MODELS:
        previous_path = FULL/f'{model}.json'
        previous = {r['sample_id']:r for r in read(previous_path)['rows']}
        mvu_path = Path('/runs/devbox/mvu_instruction_after_20261014')/model/'raw/mvu_eval.jsonl'
        mvu = {r['sample_id']:r for r in map(json.loads,mvu_path.read_text().splitlines())}
        rows=[];errors=[];missing=[];audited_calls=0;failed_attempts=[]
        for shard in range(2):
            group=OUT/f'shard{shard}'
            judged=read(group/model/REPORT)
            assert not judged['failed_ids']
            judge={f"crossvid:CCQA:{r['id']}":r for r in judged['samples']}
            for p in (group/model/'attempts').glob('*/result.json'):
                attempt=read(p)
                failed_attempts.append(dict(sample_id=attempt['sample_id'],error=attempt.get('error'),path=str(p),sha256=sha(p)))
            for sid in read(group/'samples.json'):
                rec=records[sid]
                p=group/model/'records'/rec.dataset/sid/'result.json'
                if not p.exists():
                    missing.append(sid);continue
                saved=read(p)
                if saved['status']!='ok':
                    errors.append(dict(sample_id=sid,error=saved.get('error'),path=str(p)));continue
                reused=selection['reused'][model].get(sid)
                if reused: assert sha(p)==reused['sha256']
                stats=core.event_stats(saved)
                workers=set()
                for e in saved['events']:
                    if e['kind']!='model_response':continue
                    assert e['usage']['prompt_tokens_details']['cached_tokens']==0
                    assert e['token_ids'] and len(e['token_ids'])==e['usage']['completion_tokens']
                    workers.add((e['worker']['pid'],e['worker']['gpu_uuid']))
                    audited_calls+=1
                assert len(workers)==1,(model,sid,workers)
                old=previous[sid]
                if rec.native_task=='CCQA':
                    result=judge[sid]
                    assert result['status']=='ok' and result['prediction']==saved['prediction'].strip()
                    direct=dict(prediction=result['prediction'],score=result['score']/(2*len(result['coverage'])),
                                empty=not result['prediction'].strip(),brace_only=result['prediction'].strip()=='}',format_ok=None)
                    e2e=dict(prediction=old['e2e_prediction'],score=old['e2e_score'])
                    independent=dict(prediction=old['prediction'],score=old['agent_score'])
                else:
                    prediction=old['e2e_prediction']
                    if rec.dataset=='mvu_eval':
                        assert mvu[sid]['status']=='ok'
                        prediction=mvu[sid]['output']
                    direct=core.measure(saved['prediction'],rec,scorer)
                    e2e=core.measure(prediction,rec,scorer)
                    independent=core.measure(old['prediction'],rec,scorer)
                # Historical infrastructure failure is missing comparison data, never a new zero score.
                if old['status']!='ok': independent['score']=None
                rows.append(dict(sample_id=sid,dataset=rec.dataset,task=rec.native_task,
                    task_population=rec.task_population,points=old['points'],reused=bool(reused),
                    arms=dict(direct=direct,e2e=e2e,independent=independent),stats=stats,
                    answer_status=saved['result']['answer']['status'],path=str(p),sha256=sha(p)))
        result=dict(expected=len(selection['ids']),valid=len(rows),errors=errors,missing=missing,
            failed_attempts=failed_attempts,reused=sum(r['reused'] for r in rows),audited_calls=audited_calls,
            empty=sum(r['arms']['direct']['empty'] for r in rows),brace_only=sum(r['arms']['direct']['brace_only'] for r in rows),
            closed_format_errors=sum(r['arms']['direct']['format_ok'] is False for r in rows),
            truncations=sum(r['stats']['truncations'] for r in rows),
            forced=sum(r['answer_status']=='forced_with_gaps' for r in rows),benchmarks={},
            reference_sha256={str(previous_path):sha(previous_path),str(mvu_path):sha(mvu_path)})
        for ds in ['cvbench','mvu_eval','crossvid']:
            selected=[r for r in rows if r['dataset']==ds]
            entry={'n':len(selected),'comparisons':{}}
            for arm in ['e2e','independent']:
                paired=[r for r in selected if r['arms'][arm]['score'] is not None]
                entry['comparisons'][arm]=dict(n=len(paired),direct=mean_score(paired,'direct'),
                    reference=mean_score(paired,arm),delta=mean_score(paired,'direct')-mean_score(paired,arm),
                    ci95=interval(paired,arm),improved=sum(r['arms']['direct']['score']>r['arms'][arm]['score'] for r in paired),
                    regressed=sum(r['arms']['direct']['score']<r['arms'][arm]['score'] for r in paired))
            fresh=[r for r in selected if not r['reused']]
            entry['new_questions_only']=dict(n=len(fresh),direct=mean_score(fresh,'direct'),e2e=mean_score(fresh,'e2e'))
            entry['by_task']={task:dict(n=len(rs),direct=mean_score(rs,'direct'),e2e=mean_score(rs,'e2e'))
                for task in sorted({r['task'] for r in selected}) if (rs:=[r for r in selected if r['task']==task])}
            result['benchmarks'][ds]=entry
        write(OUT/'analysis'/f'{model}_paired.json',rows)
        write(OUT/'analysis'/f'{model}_summary.json',result)
        summary['models'][model]=result
    write(OUT/'analysis/summary.json',summary)
    write(OUT/'progress.json',dict(phase='completed',at=now(),models={m:{k:v for k,v in r.items() if k in ['expected','valid','empty','closed_format_errors','reused','audited_calls','errors','missing']} for m,r in summary['models'].items()}))
    print(json.dumps(summary,ensure_ascii=False),flush=True)


if __name__=='__main__':
    if '--self-check' in sys.argv:self_check()
    else:analyze()
