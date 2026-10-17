"""Extend the existing 33-task panel; retain the timed-out preparation as an explicit exclusion."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import random
import sys

ADAPTERS = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ADAPTERS))
from common import sha256, write
from prepare import candidate_groups, prepare, timeline


def main(output, reuse=None):
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
    full_ids = previous + additional
    assert len(full_ids) == len(set(full_ids)) == 66
    excluded = {'crossvid:NC:808': 'Native mixed-codec lossless preparation exceeded the first-stage time budget'}
    assert set(excluded) <= set(additional)
    ids = [sid for sid in full_ids if sid not in excluded]
    if reuse:
        assert json.loads((reuse/'selection.json').read_text())['sample_ids'] == full_ids
    records = load_multibench_records('/assets', ids)
    output.mkdir(parents=True, exist_ok=False)
    write(output/'selection.json', dict(seed=0, sample_ids=ids, previous=previous,
        additional=[s for s in additional if s not in excluded], excluded=excluded,
        selection='retain original 33; add one seed-0 question per task except documented preprocessing exclusion'))
    write(output/'private_labels.json', {sid: dict(dataset=r.dataset, task=r.native_task,
        sample=r.sample.to_dict(), reference_answer=r.reference_answer, judge_question=r.judge_question,
        task_population=r.task_population) for sid, r in records.items()})

    def one(sid):
        slug = sid.replace(':', '_')
        cached = (reuse/'items'/f'{slug}.json') if reuse else old/'items'/f'{slug}.json'
        if cached.exists():
            item = json.loads(cached.read_text())
            metadata = json.loads((Path(item['video_path']).parent/'timeline.json').read_text())
            assert sha256(item['video_path']) == metadata['video_sha256']
            item['question'] = timeline(metadata['segments']) + '\n\nOriginal question:\n' + records[sid].sample.question
            write(output/'items'/f'{slug}.json', item)
        else:
            item = prepare(records[sid], output)
            metadata = json.loads((output/'media'/slug/'timeline.json').read_text())
        return item, dict(item_sha256=sha256(output/'items'/f'{slug}.json'),
                          video_sha256=metadata['video_sha256'])

    results, errors = {}, {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(one, sid): sid for sid in ids}
        for future in as_completed(futures):
            sid = futures[future]
            try:
                results[sid] = future.result()
            except Exception as exc:
                errors[sid] = repr(exc)
            write(output/'preparation_progress.json', dict(completed=len(results), expected=len(ids), errors=errors))
            print('progress', len(results), 'errors', errors, flush=True)
    if errors:
        raise RuntimeError(f'Preparation errors: {errors}')
    results = [results[sid] for sid in ids]
    write(output/'items.json', [item for item, _ in results])
    write(output/'input_hashes.json', {item['sample_id']: hashes for item, hashes in results})
    cached_count = sum(not Path(item['video_path']).is_relative_to(output) for item, _ in results)
    print(json.dumps(dict(prepared=len(results), reused=cached_count, new=len(results)-cached_count)), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--reuse', type=Path, help='Reuse only completed, hash-checked inputs from a previous attempt')
    args = parser.parse_args()
    main(args.output, args.reuse)
