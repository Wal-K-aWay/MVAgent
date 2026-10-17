"""Expand the unchanged concise Global System to the original 1,500 question IDs."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import tarfile

import run_system_ablation as trial
from analyze_direct_answer_large import mean_score, interval

ROOT = Path(__file__).resolve().parents[1]
OUT = Path('/runs/devbox/global_short_large_20261017')
PILOT = Path('/runs/devbox/system_ablation_20261017')
FULL = Path('/runs/devbox/direct_answer_large_20261016')
BASELINE = Path('/runs/devbox/direct_answer_large_recovery_20261017/analysis')
read, write, sha, now, MODELS = trial.read, trial.write, trial.sha, trial.now, trial.MODELS


def pending_partitions(ids, partitions, reused):
    flat = [sid for part in partitions for sid in part]
    assert len(ids) == len(set(ids)) == len(flat) == len(set(flat))
    assert set(flat) == set(ids) and set(reused) <= set(ids)
    pending = [[sid for sid in part if sid not in reused] for part in partitions]
    assert set(sid for part in pending for sid in part) == set(ids)-set(reused)
    return pending


def verify_actor():
    """Keep every runtime file byte-identical to the already tested System candidate."""
    manifest = read(PILOT/'manifest.json')
    assert sha(PILOT/'source.tar.gz') == manifest['archive_sha256']
    def runtime(name):
        return name.startswith(('src/','configs/','eval/')) or name in {'requirements.txt','demo.py'}
    expected = {}
    with tarfile.open(PILOT/'source.tar.gz') as archive:
        for member in archive:
            if member.isfile() and runtime(member.name):
                expected[member.name] = hashlib.sha256(archive.extractfile(member).read()).hexdigest()
    actual = {str(p.relative_to(ROOT)):sha(p) for folder in ['src','configs','eval']
              for p in (ROOT/folder).rglob('*') if p.is_file() and not {'__pycache__','.cache'} & set(p.parts)}
    actual.update({name:sha(ROOT/name) for name in ['requirements.txt','demo.py']})
    assert actual == expected, 'Runtime differs from the tested concise-Global candidate'
    for name, expected_sha in read(PILOT/'global_short/source_changes.json').items():
        assert actual[name] == expected_sha, name
    return actual


def prepare():
    assert not OUT.exists(), 'Do not replace an existing experiment'
    actor = verify_actor()
    full = read(FULL/'selection.json');ids = full['ids']
    assert len(ids) == 1500 and full['per_benchmark'] == dict(cvbench=500,mvu_eval=500,crossvid=500)
    reused = read(PILOT/'samples.json');assert len(reused) == 102
    partitions = pending_partitions(ids, full['partitions'], reused)
    baseline = {m:read(BASELINE/f'{m}_paired.json') for m in MODELS}
    pilot = {m:read(PILOT/'analysis'/f'global_short_{m}_paired.json') for m in MODELS}
    for m in MODELS:
        assert set(r['sample_id'] for r in baseline[m]) == set(ids)
        assert set(r['sample_id'] for r in pilot[m]) == set(reused)
    def validate(row):
        assert sha(Path(row['path'])) == row['sha256'], row['path']
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(validate, [r for rows in pilot.values() for r in rows]))
    ratios = {m:sum(r['stats']['seconds'] for r in pilot[m]) /
              sum(r['stats']['seconds'] for r in baseline[m] if r['sample_id'] in reused) for m in MODELS}
    predicted = [{m:sum(r['stats']['seconds']*ratios[m] for r in baseline[m] if r['sample_id'] in part)
                  for m in MODELS} for part in partitions]
    storage = os.statvfs('/runs')
    OUT.mkdir()
    write(OUT/'samples.json', ids);write(OUT/'baseline.json', baseline)
    write(OUT/'selection.json', dict(ids=ids,partitions=partitions,reused=reused,
        original_selection=str(FULL/'selection.json'),original_selection_sha256=sha(FULL/'selection.json'),
        original_partitions_preserved=True,counts=dict(Counter(r['dataset'] for r in baseline['9B'])),
        target_outputs=4500,reused_outputs=306,new_outputs=4194))
    with tarfile.open(OUT/'source.tar.gz','w:gz',compresslevel=1) as archive:
        for name in ['src','scripts','configs','eval','.git','requirements.txt','demo.py']:
            archive.add(ROOT/name,arcname=name,filter=lambda t:None if {'__pycache__','.cache'} & set(Path(t.name).parts) else t)
    parent = read(PILOT/'manifest.json')
    write(OUT/'manifest.json',dict(at=now(),commit=(ROOT/'.git/HEAD').read_text().strip(),
        profile=parent['profile'],archive_sha256=sha(OUT/'source.tar.gz'),
        actor_reference=str(PILOT),actor_reference_archive_sha256=parent['archive_sha256'],
        actor_source_hashes=actor,selection_sha256=sha(OUT/'selection.json'),
        baseline_sha256=sha(OUT/'baseline.json'),inference_seed=0,selection_resampled=False,
        model_seconds_by_shard=predicted,pilot_timing_ratios=ratios,
        expected_hours=.75+1.25*max(sum(s.values()) for s in predicted)/8/3600,
        free_inodes_at_prepare=storage.f_favail,free_bytes_at_prepare=storage.f_bavail*storage.f_frsize,
        policy='Only the already tested concise Global System; unchanged Video/User/schema/media/budgets/backend. '
               'Use all original 1500 IDs, inherit all 102 pilot IDs without selecting by scores.'))
    for shard,part in enumerate(partitions):
        group=OUT/f'shard{shard}';group.mkdir()
        for name in ['manifest.json','source.tar.gz','baseline.json']:(group/name).symlink_to(OUT/name)
        write(group/'samples.json',part)
        target=group/'global_short';target.mkdir()
        (target/'code').symlink_to(PILOT/'global_short/code',target_is_directory=True)
        write(target/'progress.json',dict(phase='prepared',models={},expected=len(part)*3))
    print(json.dumps(read(OUT/'manifest.json')),flush=True)
    print(json.dumps(dict(new_per_shard=list(map(len,partitions)),reused_per_model=len(reused))),flush=True)


def worker(shard):
    trial.OUT = OUT/f'shard{shard}'
    trial.worker('global_short')


def metrics(rows):
    report={}
    for dataset in ['cvbench','mvu_eval','crossvid']:
        group=[r for r in rows if r['dataset']==dataset]
        if not group:continue
        report[dataset]=dict(n=len(group),scores={a:mean_score(group,a) for a in ['direct','baseline','e2e']},
            baseline_delta_ci95=interval(group,'baseline'),
            format_errors={a:sum(r['arms'][a].get('format_ok') is False for r in group) for a in ['direct','baseline']},
            wins=sum(r['arms']['direct']['score']>r['arms']['baseline']['score'] for r in group),
            losses=sum(r['arms']['direct']['score']<r['arms']['baseline']['score'] for r in group))
    return report


def analyze():
    selection=read(OUT/'selection.json');ids=set(selection['ids']);reused=set(selection['reused'])
    write(OUT/'progress.json',dict(phase='analyzing',at=now()))
    for shard in range(2):
        trial.OUT=OUT/f'shard{shard}';trial.ARMS=('global_short',)
        trial.analyze()
    models={};complete=True
    for m in MODELS:
        rows=read(PILOT/'analysis'/f'global_short_{m}_paired.json')
        for shard in range(2):rows+=read(OUT/f'shard{shard}/analysis'/f'global_short_{m}_paired.json')
        seen=[r['sample_id'] for r in rows]
        assert len(seen)==len(set(seen)) and set(seen)<=ids
        for row in rows:row['reused']=row['sample_id'] in reused
        missing=sorted(ids-set(seen));complete &= not missing
        models[m]=dict(valid=len(rows),missing=missing,reused=sum(r['reused'] for r in rows),
            benchmarks=metrics(rows),new_only_benchmarks=metrics([r for r in rows if not r['reused']]),
            empty=sum(r['arms']['direct']['empty'] for r in rows),braces=sum(r['arms']['direct']['brace_only'] for r in rows),
            statistics={k:sum(r['stats'][k] for r in rows) for k in
                        ['seconds','calls','tokens','model_errors','structured_invalid','repairs','truncations']})
        write(OUT/'analysis'/f'{m}_paired.json',rows)
    summary=dict(at=now(),complete=complete,models=models,development_panel=True,
        selection_sha256=sha(OUT/'selection.json'),actor_manifest_sha256=sha(OUT/'manifest.json'))
    write(OUT/'analysis/summary.json',summary)
    write(OUT/'progress.json',dict(phase='completed' if complete else 'incomplete',at=now(),
        valid=sum(m['valid'] for m in models.values()),expected=4500,summary='analysis/summary.json'))
    print(json.dumps(summary),flush=True)
    assert complete,'Incomplete experiment: see missing IDs and per-shard errors; never count them as zero scores'


def self_check():
    assert pending_partitions(['a','b','c','d'],[['c','a'],['b','d']],['a','b']) == [['c'],['d']]
    for ids,parts,reused in [(['a','b'],[['a'],['a']],[]),(['a'],[['a']],['x'])]:
        try:pending_partitions(ids,parts,reused)
        except AssertionError:pass
        else:raise AssertionError('Invalid or overlapping selection accepted')
    trial.self_check()
    print('Fixed IDs, original order, disjoint reuse and unchanged System replacement checks passed')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('mode',choices=['prepare','worker','analyze','self-check']);p.add_argument('--shard',type=int,choices=[0,1])
    a=p.parse_args()
    if a.mode=='worker':assert a.shard is not None;worker(a.shard)
    else:globals()[a.mode.replace('-','_')]()
