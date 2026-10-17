"""Snapshot existing LensWalk scores on Modal CPU; never change or rerun predictions."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from statistics import mean


def summarize(rows):
    valid = [r for r in rows if not r['infrastructure_error']]
    scored = [r for r in valid if r['score'] is not None]
    terminal = [r for r in scored if r['terminal'] in ('finish', 'natural_text')]
    assert all(0 <= r['score'] <= 1 for r in scored)
    return dict(
        processed=len(rows), valid=len(valid), scored=len(scored),
        score_sum=sum(r['score'] for r in scored),
        score=mean(r['score'] for r in scored) if scored else None,
        pending_score=len(valid)-len(scored),
        terminal_counts=dict(Counter(r['terminal'] for r in valid)),
        terminal_scored=len(terminal),
        terminal_score=mean(r['score'] for r in terminal) if terminal else None,
        infrastructure_failures=[r['sample_id'] for r in rows if r['infrastructure_error']],
        mean_inference_seconds=mean(r['seconds'] for r in rows) if rows else None,
        mean_preparation_seconds=mean(r['prepared_seconds'] for r in rows) if rows else None,
    )


def main(root, output):
    assert not output.exists(), 'Keep previous snapshots unchanged'
    started = datetime.now(timezone.utc).isoformat()
    read = lambda p: json.loads(p.read_text())
    samples = read(root/'samples.json')
    progress_before = read(root/'progress.json')
    inherited = root/'inherited_records.json'
    rows = read(inherited) if inherited.exists() else {}
    paths = sorted((root/'lenswalk').glob('*/record.json'))

    def load(path):
        raw = path.read_bytes()
        return path.parent.name, json.loads(raw), dict(
            path=str(path), sha256=hashlib.sha256(raw).hexdigest())

    with ThreadPoolExecutor(max_workers=16) as pool:
        loaded = list(pool.map(load, paths))
    rows.update({key: row for key, row, source in loaded})
    rows = list(rows.values())
    ids = [r['sample_id'] for r in rows]
    assert len(ids) == len(set(ids)) and set(ids) <= set(samples)
    result = dict(source=str(root), started_at=started, processed=len(rows), expected=len(samples),
                  progress_before=progress_before, progress_after=read(root/'progress.json'), benchmarks={})
    for dataset in ('cvbench', 'mvu_eval', 'crossvid'):
        selected = [r for r in rows if r['dataset'] == dataset]
        summary = summarize(selected)
        tasks = {task: summarize([r for r in selected if r['task'] == task])
                 for task in sorted({r['task'] for r in selected})}
        summary['task_scores'] = tasks
        if dataset == 'crossvid':
            closed = [v['score'] for k, v in tasks.items() if k != 'CCQA' and v['score'] is not None]
            assert len(closed) == 9 and tasks['CCQA']['scored'] == 0
            summary['closed_nine_task_macro'] = mean(closed)
            summary['official_ten_task_macro'] = None
            # A point-weighted CCQA Judge score is required for the ten-task result.
        result['benchmarks'][dataset] = summary
    result['infrastructure_records'] = [r for r in rows if r['infrastructure_error']]
    result['finished_at'] = datetime.now(timezone.utc).isoformat()
    output.mkdir(parents=True)
    (output/'snapshot.json').write_text(json.dumps(dict(rows=rows, sources=[s for _, _, s in loaded]), ensure_ascii=False))
    (output/'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    (output/'analysis_source.py').write_bytes(Path(__file__).read_bytes())
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    # Model negatives remain in the denominator; infrastructure and unjudged answers do not.
    base = dict(sample_id='x', infrastructure_error=False, seconds=1, prepared_seconds=2)
    check = summarize([dict(base, score=1, terminal='finish'),
                       dict(base, score=0, terminal='empty_answer'),
                       dict(base, score=None, terminal='natural_text'),
                       dict(base, score=None, terminal='missing_result', infrastructure_error=True)])
    assert check['processed'] == 4 and check['valid'] == 3 and check['scored'] == 2
    assert check['score'] == .5 and check['terminal_score'] == 1 and check['pending_score'] == 1
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    main(args.root, args.output)
