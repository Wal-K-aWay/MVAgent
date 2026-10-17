"""Paired uncertainty and MVU format/task diagnostics for the fixed existing comparison."""
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
from math import comb
from pathlib import Path
from statistics import mean
import sys

import numpy as np

ROOT = Path('/runs/devbox')
OUT = ROOT/'rsi_gap_uncertainty_20261017'
FROZEN = ROOT/'direct_answer_large_20261016/frozen_repo'
sys.path[:0] = [str(FROZEN/'scripts'), str(FROZEN/'src'), str(FROZEN/'eval/e2e_eval')]
from compare_direct_answer import measure
from skill_evolution.infra.benchmarks.catalog import load_multibench_records, build_official_scorer


def exact_p(wins, losses):
    n = wins+losses
    return min(1., 2*sum(comb(n, i) for i in range(min(wins, losses)+1))/2**n)


def estimate(rows, population=False):
    groups = defaultdict(list)
    for row in rows:
        groups[row['task']].append(row)
    macro = rows[0]['dataset'] == 'crossvid'
    weights = {t:1 if macro else rs[0]['task_population'] if population else len(rs)
               for t,rs in groups.items()}
    total = sum(weights.values())
    rng = np.random.default_rng(0)
    samples = np.zeros(20000)
    observed = 0.
    for task, group in sorted(groups.items()):
        differences = np.array([r['scores']['video_rsi']-r['scores']['mvagent'] for r in group])
        weight = weights[task]/total
        observed += weight*float(differences.mean())
        samples += weight*differences[rng.integers(len(group),size=(len(samples),len(group)))].mean(axis=1)
    return dict(n=len(rows), rsi_minus_mvagent=observed,
                ci95=[float(x) for x in np.quantile(samples,[.025,.975])])


def main():
    assert not OUT.exists()
    hashes = {}
    def read(path):
        data = path.read_bytes(); hashes[str(path)] = hashlib.sha256(data).hexdigest()
        return json.loads(data)
    rows = read(ROOT/'external_baselines_paired_20261017/paired.json')['three_way']['video_rsi']
    assert len(rows) == 399
    report = dict(at=datetime.now(timezone.utc).isoformat(), bootstrap='20000 paired within-task resamples, seed0; '
                  'no shared-video clustering, no multiplicity/sequential correction', benchmarks={})
    for dataset in ('cvbench','mvu_eval','crossvid'):
        group = [r for r in rows if r['dataset']==dataset]
        value = estimate(group)
        value['population_weighted_sensitivity'] = estimate(group,True)
        if dataset != 'crossvid':
            wins = sum(r['scores']['video_rsi'] > r['scores']['mvagent'] for r in group)
            losses = sum(r['scores']['video_rsi'] < r['scores']['mvagent'] for r in group)
            value.update(rsi_only_correct=wins, mvagent_only_correct=losses, exact_mcnemar_p=exact_p(wins,losses))
        report['benchmarks'][dataset] = value
    mvu = [r for r in rows if r['dataset']=='mvu_eval']
    assert len(mvu)==131
    direct = {r['sample_id']:r for r in read(ROOT/'direct_answer_large_recovery_20261017/analysis/35B-A3B_paired.json')}
    rsi = {r['sample_id']:r for r in read(ROOT/'external_baselines_paired_20261017/rsi_snapshot.json')['rows']}
    records = load_multibench_records('/assets',[r['sample_id'] for r in mvu])
    scorer, _ = build_official_scorer(records,{})
    diagnostic = []
    for row in mvu:
        sid = row['sample_id']
        arms = dict(video_rsi=measure(rsi[sid]['answer'],records[sid],scorer),mvagent=direct[sid]['arms']['direct'])
        assert all(arms[a]['score']==row['scores'][a] for a in arms)
        diagnostic.append(dict(sample_id=sid,task=row['task'],arms=arms))
    report['mvu_format'] = {a:dict(official=mean(r['arms'][a]['score'] for r in diagnostic),
        extracted_diagnostic=mean(r['arms'][a]['robust_score'] for r in diagnostic),
        format_failures=sum(not r['arms'][a]['format_ok'] for r in diagnostic)) for a in ('video_rsi','mvagent')}
    report['mvu_by_task'] = {t:dict(n=len(group),population=group[0]['task_population'],
        rsi_correct=sum(r['scores']['video_rsi'] for r in group),mvagent_correct=sum(r['scores']['mvagent'] for r in group),
        net_correct=sum(r['scores']['video_rsi']-r['scores']['mvagent'] for r in group))
        for t in sorted({r['task'] for r in mvu}) if (group:=[r for r in mvu if r['task']==t])}
    report['mvu_cost'] = dict(
        video_rsi=dict(mean_output_tokens=mean(rsi[r['sample_id']]['output_tokens'] for r in mvu),
                       mean_calls=mean(rsi[r['sample_id']]['calls'] for r in mvu),
                       mean_seconds=mean(rsi[r['sample_id']]['seconds'] for r in mvu)),
        mvagent=dict(mean_output_tokens=mean(direct[r['sample_id']]['stats']['tokens'] for r in mvu),
                     mean_calls=mean(direct[r['sample_id']]['stats']['calls'] for r in mvu),
                     mean_seconds=mean(direct[r['sample_id']]['stats']['seconds'] for r in mvu)))
    report['source_sha256'] = hashes
    OUT.mkdir()
    (OUT/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    (OUT/'mvu_format_diagnostics.json').write_text(json.dumps(diagnostic,ensure_ascii=False,indent=2))
    (OUT/'analysis_source.py').write_bytes(Path(__file__).read_bytes())
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':
    assert exact_p(0,0)==1 and exact_p(3,0)==.25 and exact_p(28,19)==exact_p(19,28)
    fixture=[dict(dataset='cvbench',task=t,task_population=w,scores={'video_rsi':1,'mvagent':0})
             for t,w in [('a',9),('b',1)]]
    assert estimate(fixture)['ci95']==[1.,1.] and estimate(fixture,True)['rsi_minus_mvagent']==1
    main()
