"""Compare existing LensWalk/RSI results with current MVAgent and E2E on identical IDs."""
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from statistics import mean
from summarize_lenswalk_partial import summarize

ROOT = Path('/runs/devbox')
LENS = ROOT/'lenswalk_partial_20261017_1108/snapshot.json'
PANEL = ROOT/'direct_answer_large_recovery_20261017/analysis/35B-A3B_paired.json'
RSI = ROOT/'rsi_full_35b_20261016'
OUTPUT = ROOT/'external_baselines_paired_20261017'


def score(rows, arm, macro=False):
    if not macro:
        return mean(r['scores'][arm] for r in rows)
    groups = defaultdict(list)
    for row in rows:
        groups[row['task']].append(row['scores'][arm])
    return mean(mean(values) for values in groups.values())


def compare(available, panel, method):
    assert len(panel) == len({r['sample_id'] for r in panel})
    shared = []
    for row in panel:
        sid = row['sample_id']
        if sid not in available:
            continue
        saved = available[sid]
        assert saved['dataset'] == row['dataset'] and saved['task'] == row['task']
        shared.append(dict(sample_id=sid, dataset=row['dataset'], task=row['task'],
            task_population=row['task_population'],
            scores={method:saved['score'], 'mvagent':row['arms']['direct']['score'],
                    'e2e':row['arms']['e2e']['score']},
            terminal=saved['terminal'], mvagent_answer_status=row['answer_status'],
            seconds=saved['seconds'], mvagent_seconds=row['stats']['seconds'],
            mvagent_path=row['path'], mvagent_sha256=row['sha256']))
    assert all(0 <= value <= 1 for r in shared for value in r['scores'].values())
    summary = {}
    for dataset in ('cvbench', 'mvu_eval', 'crossvid'):
        rows = [r for r in shared if r['dataset'] == dataset]
        assert rows
        macro = dataset == 'crossvid'
        tasks = sorted({r['task'] for r in rows})
        assert not macro or len(tasks) == 9
        scores = {arm:score(rows, arm, macro) for arm in (method, 'mvagent', 'e2e')}
        summary[dataset] = dict(n=len(rows), scores=scores,
            method_minus_mvagent=scores[method]-scores['mvagent'],
            method_minus_e2e=scores[method]-scores['e2e'],
            by_task={task:dict(n=len(group), **{a:score(group, a) for a in scores})
                     for task in tasks if (group:=[r for r in rows if r['task'] == task])},
            paired_outcomes={arm:dict(
                method_better=sum(r['scores'][method] > r['scores'][arm] for r in rows),
                method_worse=sum(r['scores'][method] < r['scores'][arm] for r in rows),
                equal=sum(r['scores'][method] == r['scores'][arm] for r in rows))
                for arm in ('mvagent', 'e2e')},
            terminal=dict(Counter(r['terminal'] for r in rows)),
            mean_inference_seconds={method:mean(r['seconds'] for r in rows),
                                    'mvagent':mean(r['mvagent_seconds'] for r in rows)})
    return summary, shared


def main():
    assert not OUTPUT.exists(), 'Do not overwrite previous comparisons'
    raw = {str(p):p.read_bytes() for p in (LENS, PANEL, RSI/'progress.json')}
    snapshot = json.loads(raw[str(LENS)])
    assert len(snapshot['rows']) == 2360
    lens = {r['sample_id']:r for r in snapshot['rows']
            if not r['infrastructure_error'] and r['score'] is not None}
    assert len(lens) == 2259
    panel = json.loads(raw[str(PANEL)])
    assert len(panel) == 1500 and Counter(r['dataset'] for r in panel) == dict(cvbench=500,mvu_eval=500,crossvid=500)
    def load(path):
        data = path.read_bytes()
        return json.loads(data), dict(path=str(path), sha256=hashlib.sha256(data).hexdigest())
    with ThreadPoolExecutor(max_workers=16) as pool:
        loaded = list(pool.map(load, sorted((RSI/'rsi').glob('*/record.json'))))
    rsi_rows = [r for r, _ in loaded]
    progress = json.loads(raw[str(RSI/'progress.json')])
    assert len(rsi_rows) == progress['completed'] == len({r['sample_id'] for r in rsi_rows})
    rsi = {r['sample_id']:r for r in rsi_rows if not r['infrastructure_error'] and r['score'] is not None}
    results, paired = {}, {}
    for method, available in [('lenswalk', lens), ('video_rsi', rsi)]:
        results[method], paired[method] = compare(available, panel, method)
    prior = json.loads((ROOT/'lenswalk_paired_20261017/summary.json').read_text())
    assert all(results['lenswalk'][ds]['scores'] == prior['benchmarks'][ds]['scores'] for ds in prior['benchmarks'])
    rsi_by_id = {r['sample_id']:r for r in paired['video_rsi']}
    common = []
    for row in paired['lenswalk']:
        other = rsi_by_id.get(row['sample_id'])
        if other is None:
            continue
        assert all(row['scores'][arm] == other['scores'][arm] for arm in ('mvagent', 'e2e'))
        common.append(dict(sample_id=row['sample_id'], dataset=row['dataset'], task=row['task'],
            scores={**row['scores'], 'video_rsi':other['scores']['video_rsi']},
            seconds=dict(lenswalk=row['seconds'], video_rsi=other['seconds'], mvagent=row['mvagent_seconds'])))
    four_way, rsi_summary = {}, {}
    for ds in ('cvbench', 'mvu_eval', 'crossvid'):
        group = [r for r in common if r['dataset'] == ds]
        assert group and (ds != 'crossvid' or len({r['task'] for r in group}) == 9)
        four_way[ds] = dict(n=len(group), scores={a:score(group,a,ds=='crossvid')
            for a in ('lenswalk','video_rsi','mvagent','e2e')},
            mean_inference_seconds={a:mean(r['seconds'][a] for r in group) for a in ('lenswalk','video_rsi','mvagent')})
        group = [r for r in rsi_rows if r['dataset'] == ds]
        tasks = {t:summarize([r for r in group if r['task']==t]) for t in sorted({r['task'] for r in group})}
        rsi_summary[ds] = dict(summarize(group), task_scores=tasks)
        if ds == 'crossvid':
            closed = [v['score'] for t,v in tasks.items() if t != 'CCQA']
            assert len(closed) == 9 and tasks['CCQA']['scored'] == 0
            rsi_summary[ds]['closed_nine_task_macro'] = mean(closed)
    hashes = {}
    for name in ('scoring.py', 'catalog.py'):
        hashes[name] = {}
        for label, source in [('lenswalk', 'lenswalk_full_35b_recovery_20261017'),
                              ('mvagent', 'direct_answer_large_20261016'),
                              ('video_rsi', 'rsi_full_35b_20261016')]:
            path = ROOT/source/'frozen_repo/src/skill_evolution/infra/benchmarks'/name
            hashes[name][label] = hashlib.sha256(path.read_bytes()).hexdigest()
        assert len(set(hashes[name].values())) == 1, ('Review scoring differences before comparing', hashes)
    result = dict(at=datetime.now(timezone.utc).isoformat(), model='Qwen3.5-35B-A3B',
        source_sha256={p:hashlib.sha256(value).hexdigest() for p,value in raw.items()},
        scorer_hashes=hashes, lenswalk_scored_available=len(lens), rsi_scored_available=len(rsi),
        rsi_progress=progress, rsi_observed=rsi_summary, comparisons=results, four_way=four_way,
        protocol='Same IDs and shared official scorer; CV/MVU observed question mean, CrossVid nine-task macro; '
                 'current direct-answer MVAgent; MVU E2E official instruction after options; CCQA excluded.')
    OUTPUT.mkdir()
    (OUTPUT/'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    (OUTPUT/'paired.json').write_text(json.dumps(dict(three_way=paired, four_way=common), ensure_ascii=False))
    (OUTPUT/'rsi_snapshot.json').write_text(json.dumps(dict(rows=rsi_rows, sources=[s for _,s in loaded]), ensure_ascii=False))
    (OUTPUT/'analysis_source.py').write_bytes(Path(__file__).read_bytes())
    (OUTPUT/'summarize_lenswalk_partial.py').write_bytes(Path(__file__).with_name('summarize_lenswalk_partial.py').read_bytes())
    printable = dict(at=result['at'], four_way=four_way,
        rsi_observed={ds:{k:v for k,v in b.items() if k != 'task_scores'} for ds,b in rsi_summary.items()},
        comparisons={m:{ds:{k:v for k,v in b.items() if k != 'by_task'} for ds,b in groups.items()} for m,groups in results.items()})
    print(json.dumps(printable, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    fixture = [dict(task=t, scores=dict(lenswalk=s)) for t,s in [('a',0),('a',0),('b',1)]]
    assert score(fixture,'lenswalk') == 1/3 and score(fixture,'lenswalk',True) == .5
    main()
