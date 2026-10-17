"""Paired official scores and reliability for the frozen enlarged direct-answer panel."""
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
import argparse
import hashlib
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
    import tempfile
    from types import SimpleNamespace
    rows = [dict(dataset='crossvid',task=t,task_population=1,points=p,
                 arms={'direct':{'score':a},'e2e':{'score':b}})
            for t,p,a,b in [('CCQA',1,1.,0.),('CCQA',3,0.,0.),('BU',1,.5,.5)]]
    assert abs(mean_score(rows,'direct')-.375)<1e-10
    assert abs(mean_score(rows,'e2e')-.25)<1e-10
    constant=[dict(dataset='cvbench',task=t,task_population=w,points=1,
                   arms={'direct':{'score':.7},'e2e':{'score':.4}}) for t,w in [('a',9),('b',1)]]
    assert all(abs(v-.3)<1e-10 for v in interval(constant,'e2e',100))
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp)
        path=root/'model/records/test/a/result.json'
        path.parent.mkdir(parents=True)
        raw=b'{"sample_id":"a","status":"ok"}'
        path.write_bytes(raw)
        rows=list(saved_records(root,'model',['a','b'],{s:SimpleNamespace(dataset='test') for s in ['a','b']}))
        assert rows[0][2]['sample_id']=='a' and rows[0][3]==hashlib.sha256(raw).hexdigest()
        assert rows[1][2:] == (None,None)
    print('Official aggregation and paired bootstrap checks passed')


def saved_records(group, model, sample_ids, records):
    def load(sid):
        path=group/model/'records'/records[sid].dataset/sid/'result.json'
        try:raw=path.read_bytes()
        except FileNotFoundError:return sid,path,None,None
        return sid,path,json.loads(raw),hashlib.sha256(raw).hexdigest()
    # Bound decoded trajectories in memory while overlapping Volume reads.
    with ThreadPoolExecutor(max_workers=8) as readers:
        for start in range(0,len(sample_ids),64):
            yield from readers.map(load,sample_ids[start:start+64])


def analyze(*, partial=False, report_dir=None):
    self_check()
    selection = read(OUT/'selection.json')
    records = {}
    chunks = [selection['ids'][i::8] for i in range(8)]
    with ThreadPoolExecutor(max_workers=8) as readers:
        for part in readers.map(lambda ids:load_multibench_records('/assets',ids),chunks):
            assert not records.keys() & part.keys()
            records.update(part)
    assert set(records)==set(selection['ids'])
    scorer, identity = build_official_scorer(records,{})
    summary = dict(at=now(), selection_sha256=sha(OUT/'selection.json'), scorer=identity, models={},
        inference_repeated=False, bootstrap='2000 paired within-task resamples, seed0; no multiplicity or shared-video correction',
        limits='Development/evaluation overlap is disclosed; same-panel improvements are not guarantees for all inputs.')
    report_dir = report_dir or OUT/'analysis'
    assert report_dir.is_relative_to(OUT) and report_dir != OUT
    summary['partial'] = partial
    summary['shards'] = {str(shard):read(OUT/f'shard{shard}/progress.json')['phase'] for shard in range(2)}
    if not partial:
        assert all(phase=='completed' for phase in summary['shards'].values())
    for model in MODELS:
        previous_path = FULL/f'{model}.json'
        previous = {r['sample_id']:r for r in read(previous_path)['rows']}
        mvu_path = Path('/runs/devbox/mvu_instruction_after_20261014')/model/'raw/mvu_eval.jsonl'
        mvu = {r['sample_id']:r for r in map(json.loads,mvu_path.read_text().splitlines())}
        rows=[];errors=[];missing=[];audited_calls=0;failed_attempts=[]
        for shard in range(2):
            group=OUT/f'shard{shard}'
            judge = {}
            if (group/model/REPORT).exists():
                judged=read(group/model/REPORT)
                assert not judged['failed_ids']
                judge={f"crossvid:CCQA:{r['id']}":r for r in judged['samples']}
            else:
                assert partial, ('Missing Judge report',group/model/REPORT)
            for p in (group/model/'attempts').glob('*/result.json'):
                attempt=read(p)
                failed_attempts.append(dict(sample_id=attempt['sample_id'],error=attempt.get('error'),path=str(p),sha256=sha(p)))
            for sid,p,saved,record_sha in saved_records(group,model,read(group/'samples.json'),records):
                rec=records[sid]
                if saved is None:
                    missing.append(sid);continue
                if saved['status']!='ok':
                    errors.append(dict(sample_id=sid,error=saved.get('error'),path=str(p)));continue
                reused=selection['reused'][model].get(sid)
                if reused: assert record_sha==reused['sha256']
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
                    assert sid in judge, ('Completed CCQA needs a valid Judge result',sid)
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
                    assert abs(direct['score']-saved['score'])<1e-8,(model,sid)
                    e2e=core.measure(prediction,rec,scorer)
                    independent=core.measure(old['prediction'],rec,scorer)
                # Historical infrastructure failure is missing comparison data, never a new zero score.
                if old['status']!='ok': independent['score']=None
                rows.append(dict(sample_id=sid,dataset=rec.dataset,task=rec.native_task,
                    task_population=rec.task_population,points=old['points'],reused=bool(reused),
                    arms=dict(direct=direct,e2e=e2e,independent=independent),stats=stats,
                    answer_status=saved['result']['answer']['status'],path=str(p),sha256=record_sha))
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
        if not partial:
            assert len(rows)==len(selection['ids']) and not errors and not missing
        write(report_dir/f'{model}_paired.json',rows)
        write(report_dir/f'{model}_summary.json',result)
        summary['models'][model]=result
    write(report_dir/'summary.json',summary)
    if not partial:
        write(OUT/'progress.json',dict(phase='completed',at=now(),models={m:{k:v for k,v in r.items() if k in ['expected','valid','empty','closed_format_errors','reused','audited_calls','errors','missing']} for m,r in summary['models'].items()}))
    printable = {m:{k:v for k,v in r.items() if k not in ['missing','failed_attempts','reference_sha256']} for m,r in summary['models'].items()}
    print(json.dumps(printable,ensure_ascii=False),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--self-check',action='store_true')
    parser.add_argument('--partial',action='store_true')
    parser.add_argument('--report-dir',type=Path)
    args=parser.parse_args()
    if args.self_check:self_check()
    else:analyze(partial=args.partial,report_dir=args.report_dir)
