"""Compare saved historical question results with a fresh shared-executor evaluation."""
import argparse
from collections import Counter
import json
from pathlib import Path
import statistics
import time


def steps(result):
    trajectory = result['trajectory']
    global_steps = [t for t in trajectory if t['agent'] == 'GlobalAgent' and t['action'] == 'decide']
    video_runs = [t for t in trajectory if t['agent'] == 'VideoAgent' and t['action'] == 'run']
    video_steps = [s for t in video_runs for s in t['output'].get('steps', [])
                   if not s.get('result', {}).get('terminal')]
    actions = Counter(s['action'] for s in video_steps)
    return dict(global_rounds=len(global_steps), video_runs=len(video_runs),
        video_steps=len(video_steps), observe=actions['observe'],
        watch=sum(t['output'].get('action') == 'watch_videos' for t in global_steps),
        seconds=result['time'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--wait-pid', type=int)
    args = parser.parse_args()
    root = args.root
    path = root / 'current/summary.json'
    if args.wait_pid:
        import psutil
        while not path.exists():
            if not psutil.pid_exists(args.wait_pid):
                raise RuntimeError('Evaluation exited without a summary; inspect current.log')
            time.sleep(5)
    current = json.loads(path.read_text())
    if current['status'] != 'completed':
        raise RuntimeError(f'Evaluation incomplete: {current}')
    old = json.loads((root / 'historical_rows.json').read_text())
    baseline = json.loads((root / 'historical_baseline.json').read_text())
    raw = {d['sample_id']: d['artifact'] for p in (root / 'fresh_cache/rollouts').rglob('*.json')
           for d in [json.loads(p.read_text())]}
    assert set(old) == set(current['samples']) == set(raw)
    assert current['generated'] == len(old)
    pairs = {}
    for sid, row in old.items():
        assert row['result']['input'] == raw[sid]['result']['input'], sid
        before, after = steps(row['result']), steps(raw[sid]['result'])
        pairs[sid] = dict(before=before, after=after,
            counts_equal=all(before[k] == after[k] for k in before if k != 'seconds'),
            old_score=row['score'], new_score=current['samples'][sid]['score'],
            old_prediction=row['prediction'], new_prediction=raw[sid]['prediction'])
    totals = {side: {k: sum(p[side][k] for p in pairs.values())
                    for k in next(iter(pairs.values()))[side]} for side in ('before', 'after')}
    old_seconds, new_seconds = baseline['event']['seconds'], current['seconds']
    matched = [p for p in pairs.values() if p['counts_equal']]
    report = dict(samples=len(pairs), old_seconds=old_seconds, new_seconds=new_seconds,
        old_score=baseline['event']['score'], new_score=current['score'],
        speed_ratio=old_seconds / new_seconds, elapsed_reduction=1 - new_seconds / old_seconds,
        old_buckets=baseline['event']['bucket_scores'], new_buckets=current['bucket_scores'],
        improved=sum(p['new_score'] > p['old_score'] for p in pairs.values()),
        regressed=sum(p['new_score'] < p['old_score'] for p in pairs.values()),
        unchanged=sum(p['new_score'] == p['old_score'] for p in pairs.values()),
        totals=totals, matched_counts=len(matched),
        matched_faster=sum(p['after']['seconds'] < p['before']['seconds'] for p in matched),
        matched_median_seconds_delta=statistics.median(
            p['after']['seconds'] - p['before']['seconds'] for p in matched) if matched else None,
        timing_note='Historical/current stage durations include readiness, inference and scoring. '
            'This is a full-infrastructure historical comparison: 3 fixed thread workers and serial '
            'VideoAgents versus 6 process workers and at most 2 parallel VideoAgents per question. '
            'Hardware load, historical server numerical behavior and trajectories are not held fixed.',
        baseline_timing_note=baseline['timing_note'],
        pairs=pairs)
    (root / 'comparison.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    lines = [f'# Historical {len(pairs)}-question comparison', '',
        '| Metric | Historical | Current |', '|---|---:|---:|',
        f'| Evaluation stage seconds | {old_seconds:.2f} | {new_seconds:.2f} |',
        f"| Dataset/task macro score | {report['old_score']:.4%} | {report['new_score']:.4%} |"]
    for key in totals['before']:
        lines.append(f"| {key} (sum over questions) | {totals['before'][key]:.2f} | {totals['after'][key]:.2f} |")
    lines += ['', f"Elapsed reduction: {report['elapsed_reduction']:.2%}; throughput ratio: {report['speed_ratio']:.3f}.",
        f"Score improved/regressed/unchanged: {report['improved']}/{report['regressed']}/{report['unchanged']}.",
        f"Same step-count pairs: {len(matched)}; current faster: {report['matched_faster']}.", '',
        report['timing_note'], '', report['baseline_timing_note'], '',
        'Step counts alone do not fix input/output tokens, video sampling or concurrent load. '
        'Historical request-level timing is unavailable; absent request metrics are not treated as zero.', '']
    (root / 'comparison.md').write_text('\n'.join(lines))
    print(json.dumps({k: v for k, v in report.items() if k not in ('pairs', 'old_buckets', 'new_buckets')}, indent=2))


if __name__ == '__main__':
    main()
