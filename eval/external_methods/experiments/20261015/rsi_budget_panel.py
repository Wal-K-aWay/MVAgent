"""Extend the existing 33-task panel to two questions per task, without replacing it."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import random
import sys

ADAPTERS = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ADAPTERS))
from common import sha256, write
from prepare import candidate_groups, prepare, timeline


def main(output):
    from skill_evolution.infra.benchmarks.catalog import load_multibench_records
    old = Path('/runs/devbox/external_methods_native_20261014/prepared_r2')
    previous = json.loads((old/'selection.json').read_text())['sample_ids']
    groups = candidate_groups(ADAPTERS.parents[1])
    assert len(previous) == len(set(previous)) == len(groups) == 33
    rng = random.Random(0)
    additional = []
    for key in sorted(groups):
        assert len(set(groups[key]) & set(previous)) == 1, key
        additional.append(rng.choice(sorted(set(groups[key]) - set(previous))))
    ids = previous + additional
    assert len(ids) == len(set(ids)) == 66
    records = load_multibench_records('/assets', ids)
    output.mkdir(parents=True, exist_ok=False)
    write(output/'selection.json', dict(seed=0, sample_ids=ids, previous=previous,
        additional=additional, selection='retain original 33; add one seed-0 question per task'))
    write(output/'private_labels.json', {sid: dict(dataset=r.dataset, task=r.native_task,
        sample=r.sample.to_dict(), reference_answer=r.reference_answer, judge_question=r.judge_question,
        task_population=r.task_population) for sid, r in records.items()})

    def one(sid):
        slug = sid.replace(':', '_')
        if sid in previous:
            item = json.loads((old/'items'/f'{slug}.json').read_text())
            metadata = json.loads((old/'media'/slug/'timeline.json').read_text())
            assert sha256(item['video_path']) == metadata['video_sha256']
            item['question'] = timeline(metadata['segments']) + '\n\nOriginal question:\n' + records[sid].sample.question
            write(output/'items'/f'{slug}.json', item)
        else:
            item = prepare(records[sid], output)
            metadata = json.loads((output/'media'/slug/'timeline.json').read_text())
        return item, dict(item_sha256=sha256(output/'items'/f'{slug}.json'),
                          video_sha256=metadata['video_sha256'])

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(one, ids))
    write(output/'items.json', [item for item, _ in results])
    write(output/'input_hashes.json', {item['sample_id']: hashes for item, hashes in results})
    print(json.dumps(dict(prepared=len(results), reused=len(previous), new=len(additional))), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    main(parser.parse_args().output)
