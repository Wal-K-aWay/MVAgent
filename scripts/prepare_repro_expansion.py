#!/usr/bin/env python3
"""Freeze larger stratified E2E/Agent panels without consulting correctness."""
import argparse
from collections import defaultdict, Counter
import hashlib
import json
from pathlib import Path
import random
import shutil

from run_mvagent_replica_repro import shards

ROOT = Path(__file__).resolve().parents[1]
OLD = Path('/runs/devbox/agent_replica_repro_20261011/panel/inputs.json')


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')


def select(groups, anchors, count):
    rng = random.Random(20261012)
    result = []
    for key, values in sorted(groups.items()):
        chosen = sorted([v for v in values if v['name'] in anchors], key=lambda v: v['name'])
        rest = sorted([v for v in values if v['name'] not in anchors], key=lambda v: v['name'])
        rng.shuffle(rest)
        assert 0 < len(chosen) <= count and len(chosen)+len(rest) >= count
        result.extend(chosen+rest[:count-len(chosen)])
    assert len(result) == len({r['name'] for r in result}) == len(groups)*count
    return result


def prepare(output):
    assert output.is_relative_to('/runs') and not output.exists()
    old = json.loads(OLD.read_text())
    anchors = {r['name'] for r in old}
    split = ROOT/'configs/skill_evolution/splits/crossvid_lite2500_eval_seed20260919.json'
    lite = {r['sample_id'] for r in json.loads(split.read_text())['samples']}
    assert {sid for sid in anchors if sid.startswith('crossvid:')} <= lite
    groups = defaultdict(list)
    for dataset, file in [('cvbench', 'cvbench/QAs.json'), ('mvu_eval', 'mvu-eval/QAs.json'),
                          ('crossvid', 'crossvid/qa.jsonl')]:
        path = Path('/assets')/file
        rows = ([json.loads(line) for line in path.read_text().splitlines()] if path.suffix == '.jsonl'
                else json.loads(path.read_text()))
        for row in rows:
            task = row['task_type'] if dataset == 'cvbench' else row['task']
            name = (f'cvbench:{row["id"]}' if dataset == 'cvbench' else
                    f'mvu_eval:{task}:{row["id"]}' if dataset == 'mvu_eval' else row['id'])
            if name in {'cvbench:64', 'cvbench:65', 'cvbench:66'}:
                continue
            if dataset == 'crossvid' and name not in lite:
                continue
            groups[dataset, task].append(dict(name=name, dataset=dataset, native_task=task,
                old_calls=0, old_output_tokens=0, source_record=str(path)))
    assert len(groups) == 33
    panel = select(groups, anchors, 10)
    agent = select(groups, anchors, 2)
    old_by_id = {r['name']: r for r in old}
    output.mkdir(parents=True)
    shutil.copyfile(__file__, output/'source.py')
    for row in {r['name']: r for r in panel+agent}.values():
        src = output/'provenance'/(row['name']+'.json')
        save(src, dict(sample_id=row['name'], source_record=row['source_record'],
                       dataset=row['dataset'], native_task=row['native_task']))
    for row in panel+agent:
        src = output/'provenance'/(row['name']+'.json')
        row.update(source=str(src), source_sha256=hashlib.sha256(src.read_bytes()).hexdigest())
        if row['name'] in old_by_id:
            row.update({k: old_by_id[row['name']][k] for k in ['old_calls', 'old_output_tokens']})
    # Rank long cases by the maximum observed trajectory, including the 9B 56-call case.
    for model in ['9B', '27B', '35B-A3B']:
        for path in (OLD.parents[1]/model).glob('p1_rank*/summary.json'):
            for phase in json.loads(path.read_text())['passes']:
                for item in phase['rows']:
                    for row in agent:
                        if row['name'] == item['case']:
                            row['old_calls'] = max(row['old_calls'], item['calls'])
                            row['old_output_tokens'] = max(row['old_output_tokens'], item['output_tokens'])
    stress = sorted([r for r in agent if r['name'] in anchors],
                    key=lambda r: (-r['old_calls'], -r['old_output_tokens'], r['name']))[:8]
    for name, cases in [('e2e', panel), ('agent', agent), ('stress', stress)]:
        folder = output/name
        save(folder/'inputs.json', cases)
        for rank, rows in enumerate(shards(cases)):
            assert rows
            save(folder/f'shard{rank}.json', rows)
        save(folder/'manifest.json', dict(cases=len(cases), seed=20261012,
            input_sha256=hashlib.sha256((folder/'inputs.json').read_bytes()).hexdigest(),
            selection='Stratified anchors plus seeded new cases; stress uses historical length only.',
            historical_cases=sum(r['name'] in anchors for r in cases),
            per_dataset=dict(Counter(r['dataset'] for r in cases)), scoring_requested=False))
    save(output/'manifest.json', dict(e2e_cases=330, agent_cases=66, stress_cases=8,
        crossvid_split=str(split), crossvid_split_sha256=hashlib.sha256(split.read_bytes()).hexdigest(),
        excluded={'cvbench:64': 'Known truncated source video', 'cvbench:65': 'Same truncated source',
                  'cvbench:66': 'Same truncated source'}, scoring_requested=False))
    print(json.dumps(dict(e2e=len(panel), agent=len(agent), stress=[(r['name'],r['old_calls']) for r in stress])))


def self_check():
    groups = {('a',str(t)): [dict(name=f'{t}:{i}') for i in range(20)] for t in range(3)}
    anchors = {f'{t}:0' for t in range(3)}
    result = select(groups, anchors, 10)
    assert len(result) == 30 and anchors <= {r['name'] for r in result}
    assert result == select(groups, anchors, 10)
    assert len(select(groups, anchors, 2)) == 6
    print('Stratified panel self-check passed')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path)
    p.add_argument('--self-check', action='store_true')
    args = p.parse_args()
    self_check() if args.self_check else prepare(args.output)
