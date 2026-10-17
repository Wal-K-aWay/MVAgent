"""Offline, same-question PRO6000/direct-answer comparisons and model interactions."""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
import shutil
from statistics import mean
import sys

PANEL = Path('/runs/devbox/direct_answer_random_20261015')
HISTORY = Path('/runs/devbox/pro6000_alignment_20261015/r2')
FROZEN = PANEL/'frozen_repo'
sys.path[:0] = [str(FROZEN/'scripts'), str(FROZEN/'src'), str(FROZEN/'eval/e2e_eval')]
import compare_direct_answer as core
from expand_direct_answer import interval

ARMS = ['pro_e2e', 'pro_agent', 'e2e_original', 'e2e_after', 'independent', 'direct']
MODELS = {'9B': 'qwen3_5_9b', '27B': 'qwen3_5_27b', '35B-A3B': 'qwen3_5_35b_a3b'}


def weighted(rows, value):
    groups = defaultdict(list)
    for row in rows:
        groups[row['task']].append(row)
    weights = {task: 1 if rs[0]['dataset']=='crossvid' else rs[0]['task_population']
               for task, rs in groups.items()}
    return sum(weights[t]*mean(value(r) for r in rs) for t,rs in groups.items())/sum(weights.values())


def delta(rows, before, after):
    pairs = [dict(dataset=r['dataset'], task=r['task'], task_population=r['task_population'],
                  old={'score': before(r)}, new={'score': after(r)}) for r in rows]
    return dict(point=weighted(rows, lambda r: after(r)-before(r)), ci95=interval(pairs))


def self_check():
    rows = [dict(dataset='cvbench', task=t, task_population=w, old=0.2, new=0.45)
            for t,w in [('a',9),('a',9),('b',1),('b',1)]]
    result = delta(rows, lambda r:r['old'], lambda r:r['new'])
    assert abs(result['point']-.25)<1e-12
    assert all(abs(result['ci95'][k]-.25)<1e-12 for k in ['lower','upper'])
    result = delta(rows, lambda r:r['new']-r['old'], lambda r:r['new']-r['old'])
    assert result['point']==result['ci95']['lower']==result['ci95']['upper']==0


def raw_e2e(model, slug, ids):
    result = {arm:{} for arm in ['pro_e2e','e2e_original','e2e_after']}
    sources = []
    current = Path('/runs/devbox')/('e2e_full_20261012' if model=='9B' else 'e2e_full_20261013_timeout')/model
    for ds in ['cvbench','mvu_eval','crossvid']:
        path=Path('/runs/lightsail_outputs/e2e')/slug/(ds+'.jsonl.gz');sources.append(path)
        with gzip.open(path,'rt') as stream:
            for line in stream:
                r=json.loads(line)
                sid=f"cvbench:{r['id']}" if ds=='cvbench' else f"{ds}:{r['task_type']}:{r['id']}"
                if sid not in ids:continue
                value=r.get('model_output',r.get('prediction',r.get('answer')))
                result['pro_e2e'][sid]=','.join(map(str,value)) if isinstance(value,list) else str(value or '')
        path=current/'raw'/(ds+'.jsonl');sources.append(path)
        with path.open() as stream:
            for line in stream:
                r=json.loads(line);sid=r['sample_id']
                if sid not in ids:continue
                assert r['status']=='ok',(model,sid)
                result['e2e_original'][sid]=r['output']
                if ds!='mvu_eval':result['e2e_after'][sid]=r['output']
    path=Path('/runs/devbox/mvu_instruction_after_20261014')/model/'raw/mvu_eval.jsonl';sources.append(path)
    with path.open() as stream:
        for line in stream:
            r=json.loads(line);sid=r['sample_id']
            if sid not in ids:continue
            assert r['status']=='ok',(model,sid)
            result['e2e_after'][sid]=r['output']
    assert all(set(values)==ids for values in result.values())
    return result, sources


def diagnostics(output):
    rows={model:core.read(output/f'{model}_paired.json') for model in MODELS}
    report={'format_contributions':{}, 'opposite_question_effects':{}}
    for model,data in rows.items():
        report['format_contributions'][model]={}
        for ds in ['cvbench','mvu_eval','crossvid']:
            group=[r for r in data if r['dataset']==ds]
            def category(r):
                old=r['arms']['independent']['format_ok'];new=r['arms']['direct']['format_ok']
                return 'both_good' if old and new else 'both_bad' if not old and not new else 'old_bad_new_good' if new else 'old_good_new_bad'
            def effect(r):return r['arms']['direct']['score']-r['arms']['independent']['score']
            parts={name:dict(n=sum(category(r)==name for r in group),
                contribution=weighted(group,lambda r:effect(r) if category(r)==name else 0))
                for name in ['both_good','both_bad','old_bad_new_good','old_good_new_bad']}
            assert abs(sum(v['contribution'] for v in parts.values())-weighted(group,effect))<1e-9
            report['format_contributions'][model][ds]=parts
    indexed={m:{r['sample_id']:r for r in data} for m,data in rows.items()}
    assert all(set(v)==set(indexed['9B']) for v in indexed.values())
    for ds in ['cvbench','mvu_eval','crossvid']:
        hits=[]
        for sid,row in indexed['9B'].items():
            if row['dataset']!=ds:continue
            effects={m:effect(data[sid]) for m,data in indexed.items()}
            if effects['9B']<0 and effects['27B']>0 and effects['35B-A3B']>0:
                hits.append(dict(sample_id=sid,effects=effects))
        report['opposite_question_effects'][ds]=hits
    core.write(output/'diagnostics.json',report)
    shutil.copy2(__file__,output/'diagnostics_source.py')
    print(json.dumps(report),flush=True)


def main(output):
    from skill_evolution.infra.benchmarks.catalog import load_multibench_records, build_official_scorer
    self_check()
    selection=core.read(PANEL/'selection.json');ids=set(selection['random_ids'])
    assert len(ids)==300 and output.is_relative_to(Path('/runs'))
    assert not (output/'summary.json').exists(), 'Keep completed analyses immutable'
    output.mkdir(parents=True,exist_ok=True)
    shutil.copy2(__file__,output/'source.py')
    records=load_multibench_records('/assets', sorted(ids));scorer,identity=build_official_scorer(records,{})
    report=dict(at=datetime.now(timezone.utc).isoformat(), source_panel=str(PANEL),
        seed=0, judge=False, new_inference=False, scorer=identity, models={}, interactions={}, sources={})
    all_rows={}
    for model,slug in MODELS.items():
        current_path=PANEL/'analysis'/model/'paired.json';history_path=HISTORY/f'{model}_paired.json'
        current={r['sample_id']:r for r in core.read(current_path)}
        history={r['sample_id']:r for r in core.read(history_path)}
        assert set(current)==ids and ids<=set(history)
        e2e,sources=raw_e2e(model,slug,ids)
        rows=[]
        for sid in sorted(ids):
            saved=current[sid];old=history[sid]
            assert saved['old']['prediction'].strip()==old['new_agent_prediction'].strip()
            values={arm:preds[sid] for arm,preds in e2e.items()}
            values.update(pro_agent=old['old_agent_prediction'],independent=saved['old']['prediction'],direct=saved['new']['prediction'])
            measures={arm:core.measure(text,records[sid],scorer) for arm,text in values.items()}
            for arm,previous in [('independent','old'),('direct','new')]:
                for key in ['score','robust_score','format_ok','empty']:
                    assert abs(measures[arm][key]-saved[previous][key])<1e-8,(model,sid,key)
            rows.append(dict(sample_id=sid,dataset=saved['dataset'],task=saved['task'],
                             task_population=saved['task_population'],arms=measures))
        all_rows[model]={r['sample_id']:r for r in rows}
        summary={}
        for ds in ['cvbench','mvu_eval','crossvid']:
            group=[r for r in rows if r['dataset']==ds];assert len(group)==100
            stats=dict(n=len(group),arms={},contrasts={})
            for arm in ARMS:
                stats['arms'][arm]={key:weighted(group,lambda r:r['arms'][arm][key]) for key in ['score','robust_score']}
                stats['arms'][arm].update({key:sum(r['arms'][arm][key] for r in group) for key in ['empty','brace_only']})
                stats['arms'][arm]['format_errors']=sum(not r['arms'][arm]['format_ok'] for r in group)
            for before,after in [('pro_e2e','pro_agent'),('pro_agent','direct'),('e2e_after','direct'),('independent','direct')]:
                stats['contrasts'][after+'-minus-'+before]=delta(group,lambda r:r['arms'][before]['score'],lambda r:r['arms'][after]['score'])
            summary[ds]=stats
        report['models'][model]=summary
        report['sources'][model]={str(p):core.sha(p) for p in [current_path,history_path,*sources]}
        core.write(output/f'{model}_paired.json',rows)
        print(json.dumps(dict(model=model,stats=summary)),flush=True)
    for ds in ['cvbench','mvu_eval','crossvid']:
        group=[r for r in all_rows['9B'].values() if r['dataset']==ds]
        report['interactions'][ds]={}
        for small,large in [('9B','27B'),('9B','35B-A3B'),('27B','35B-A3B')]:
            def effect(row,model):
                values=all_rows[model][row['sample_id']]['arms']
                return values['direct']['score']-values['independent']['score']
            report['interactions'][ds][large+'-minus-'+small]=delta(group,lambda r:effect(r,small),lambda r:effect(r,large))
    report['limits']=['Development pool, no CCQA; no inference after History/terminal-answer changes.',
        'Task-stratified question bootstrap, not video-cluster bootstrap; no multiplicity correction.',
        'Interactions compare model identities, not a causal effect of parameter count.']
    core.write(output/'summary.json',report)
    diagnostics(output)
    print(json.dumps({'interactions':report['interactions'],'completed':True}),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    main(parser.parse_args().output.absolute())
