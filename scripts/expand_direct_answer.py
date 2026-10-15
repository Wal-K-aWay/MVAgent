#!/usr/bin/env python3
"""Expand the frozen random panel without selecting questions by model outcomes."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import random
import shutil
from statistics import mean

import compare_direct_answer as core

PREVIOUS = Path('/runs/devbox/direct_answer_panel_20261015')
PER_BENCHMARK = 100


def expand(records, common, prior):
    groups = defaultdict(list)
    for sid in sorted(common):
        record = records[sid]
        groups[record.dataset, record.native_task].append(sid)
    rng = random.Random(0)
    # Continue the original sampling stream; the old 32 questions remain in the panel.
    assert [rng.choice(groups[key]) for key in sorted(groups)] == prior
    chosen = list(prior)
    strata = {}
    for dataset in ['cvbench', 'mvu_eval', 'crossvid']:
        keys = [key for key in sorted(groups) if key[0] == dataset]
        assert sum(len(groups[k]) for k in keys) >= PER_BENCHMARK
        weights = {k: 1 if dataset == 'crossvid' else records[groups[k][0]].task_population for k in keys}
        counts = {k: min(2, len(groups[k])) for k in keys}
        while sum(counts.values()) < PER_BENCHMARK:
            candidates = [k for k in keys if counts[k] < len(groups[k])]
            key = max(candidates, key=lambda k: PER_BENCHMARK*weights[k]/sum(weights.values())-counts[k])
            counts[key] += 1
        for key in keys:
            pool = [sid for sid in groups[key] if sid not in prior]
            chosen.extend(rng.sample(pool, counts[key]-1))
            strata['/'.join(key)] = dict(available=len(groups[key]), selected=counts[key], weight=weights[key])
    assert len(chosen) == len(set(chosen)) == 3*PER_BENCHMARK and set(prior) <= set(chosen)
    assert dict(Counter(records[s].dataset for s in chosen)) == dict(cvbench=100,mvu_eval=100,crossvid=100)
    rng.shuffle(chosen)
    return chosen, strata


def prepare(output):
    from skill_evolution.infra.benchmarks.catalog import load_multibench_records, build_official_scorer
    assert not (output/'selection.json').exists(), 'Do not reselect an existing experiment'
    previous = core.read(PREVIOUS/'selection.json')
    source = core.read(PREVIOUS/'manifest.json')
    checked = {}
    for relative, expected in source['source_hashes'].items():
        if relative.startswith(('src/models/','src/mvagent/','configs/inference/')) or relative == 'eval/agent_eval/run.py':
            actual = core.sha(core.ROOT/relative)
            assert actual == expected, f'Reused inference source changed: {relative}'
            checked[relative] = actual
    snapshots = {m: core.read(core.HISTORY/f'{m}_current_compact.json') for m in core.MODELS}
    available = [{sid for sid,r in rows.items() if r['status']=='ok' and r['task']!='CCQA'
                  and sid!='crossvid:NC:506'} for rows in snapshots.values()]
    common = set.intersection(*available)
    assert len(common) == previous['common_available']
    records = load_multibench_records('/assets', sorted(common))
    selected, strata = expand(records, common, previous['random_ids'])
    assert (selected,strata) == expand(records,common,previous['random_ids'])
    scorer, identity = build_official_scorer(records,{})
    selection = dict(created_at=core.now(), seed=0, inference_seed=0, random_ids=selected,
        common_available=len(common), historical_snapshot=str(core.HISTORY), models={}, scorer=identity,
        exclusions=previous['exclusions'], strata=strata, prior_random_ids=previous['random_ids'],
        previous=str(PREVIOUS), previous_selection_sha256=core.sha(PREVIOUS/'selection.json'),
        reused_source_sha256=checked,
        design='100 random questions per benchmark; retain prior 32 random questions, then sample by task '
               'without inspecting predictions. CrossVid allocation targets equal task counts; CV/MVU '
               'targets population proportions with at least two per task where available. '
               'Reuse any selected prior direct trajectory with identical inference sources, regardless of outcome.')
    for model,snapshot in snapshots.items():
        manifest = []
        for sid in selected:
            oldpath = Path(snapshot[sid]['source_path'])
            raw = oldpath.read_bytes();old = json.loads(raw)
            assert old['sample_id']==sid and old['prediction']==snapshot[sid]['prediction']
            target=output/'historical'/model/(sid+'.json');target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
            metrics=core.measure(old['prediction'],records[sid],scorer)
            assert abs(metrics['score']-old['score'])<1e-8, (model,sid)
            prior = PREVIOUS/model/'run/records'/records[sid].dataset/sid/'result.json'
            reused = None
            if prior.exists():
                saved=core.read(prior)
                assert saved['status']=='ok' and saved['sample_id']==sid
                assert saved['result']['input']['question']==old['result']['input']['question']
                destination=output/model/'run/records'/records[sid].dataset/sid/'result.json'
                destination.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(prior,destination)
                assert core.sha(destination)==core.sha(prior)
                reused=dict(source=str(prior),sha256=core.sha(prior))
            manifest.append(dict(sample_id=sid,dataset=records[sid].dataset,task=records[sid].native_task,
                task_population=records[sid].task_population,random_panel=True,diagnostic_reasons=[],
                prior_random=sid in previous['random_ids'],source=str(oldpath),sha256=core.sha(target),
                baseline=metrics,reused_direct=reused))
        selection['models'][model]=manifest
        core.write(output/model/'samples.json',selected)
    core.write(output/'selection.json',selection)
    counts={m:dict(total=len(rows),reused=sum(bool(r['reused_direct']) for r in rows),
                   new=sum(not r['reused_direct'] for r in rows)) for m,rows in selection['models'].items()}
    core.write(output/'progress.json',dict(phase='prepared',at=core.now(),counts=counts))
    shutil.copy2(__file__,output/'preparation_source.py')
    print(json.dumps(dict(phase='prepared',common=len(common),counts=counts,strata=strata)),flush=True)


def interval(rows, repetitions=2000):
    groups=defaultdict(list)
    for r in rows:
        groups[r['task']].append(r)
    weights={t:1 if rs[0]['dataset']=='crossvid' else rs[0]['task_population'] for t,rs in groups.items()}
    rng=random.Random(0);values=[]
    for _ in range(repetitions):
        values.append(sum(weights[t]*mean(r['new']['score']-r['old']['score']
            for r in rng.choices(rs,k=len(rs))) for t,rs in groups.items())/sum(weights.values()))
    values.sort()
    return dict(lower=values[int(.025*repetitions)],upper=values[int(.975*repetitions)],
                method='paired stratified percentile bootstrap; 2000 draws, seed0; conditional on this development pool')


def analyze(output):
    report=dict(at=core.now(),models={})
    selection=core.read(output/'selection.json')
    for model in core.MODELS:
        result=core.analyze_model(output,model,report_root=output/'analysis')
        assert result['completed']==result['expected']==300
        rows=core.read(output/'analysis'/model/'paired.json')
        for dataset,metrics in result['panels']['random'].items():
            metrics['paired_delta_ci95']=interval([r for r in rows if r['dataset']==dataset])
        result['benchmark_equal_score']={arm:mean(v[arm]['official_aggregate_score'] for v in result['panels']['random'].values()) for arm in ['old','new']}
        result['reused']=sum(bool(r['reused_direct']) for r in selection['models'][model])
        core.write(output/'analysis'/model/'comparison.json',result)
        report['models'][model]=result
    core.write(output/'analysis/summary.json',report)
    shutil.copy2(__file__,output/'analysis/expansion_source.py')
    print(json.dumps(report),flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=['prepare','run','analyze'])
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();out=args.output.resolve()
    assert out.is_relative_to(Path('/runs').resolve())
    out.mkdir(parents=True,exist_ok=True)
    if args.mode=='run':
        core.run(out)
    else:
        {'prepare':prepare,'analyze':analyze}[args.mode](out)


if __name__=='__main__':
    main()
