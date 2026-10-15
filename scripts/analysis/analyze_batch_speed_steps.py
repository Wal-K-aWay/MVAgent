"""Pair saved speed-benchmark questions by action counts and observation geometry."""
import argparse
from collections import Counter
import csv
import json
from pathlib import Path
import statistics


COUNT_FIELDS = ('global_rounds', 'video_runs', 'video_planner_steps', 'observe', 'watch',
                'finalizers', 'http_calls', 'repairs')


def describe(payload, profile):
    events = payload['events']
    trajectory = payload['result']['trajectory']
    global_steps = [t for t in trajectory if t['agent'] == 'GlobalAgent' and t['action'] == 'decide']
    runs = [t for t in trajectory if t['agent'] == 'VideoAgent' and t['action'] == 'run']
    schemas = Counter(e['schema'] for e in events if e['kind'] == 'structured_request')
    assert len(global_steps) == schemas['global_decision']
    steps = [s for t in runs for s in t['output'].get('steps', [])]
    actions = Counter(s['action'] for s in steps)
    usage = [e.get('usage') or {} for e in events if e['kind'] == 'model_response']
    # Preserve dependency grouping but remove free text and thread completion order.
    shape = {'global': [], 'video': []}
    for t in global_steps:
        output = t['output']
        params = output.get('parameters', {})
        shape['global'].append(dict(action=output.get('action'),
            videos=[v['video_id'] for v in params.get('videoagent_request', [])],
            clips=params.get('videos', [])))
    for t in runs:
        shape['video'].append(dict(round=t['input']['global_round'], video=t['video_id'],
            steps=[dict(action=s['action'], where=s.get('parameters', {}).get('where'),
                        fps=s.get('parameters', {}).get('fps')) for s in t['output'].get('steps', [])]))
    shape['video'].sort(key=lambda v: (v['round'], v['video']))
    clips = profile['clips']
    return dict(global_rounds=len(global_steps), video_runs=len(runs),
        video_planner_steps=schemas['video_action'], observe=actions['observe'],
        watch=sum(t['output'].get('action') == 'watch_videos' for t in global_steps),
        finalizers=schemas['video_finish'] + sum(t['action'] == 'terminal_answer' for t in trajectory),
        http_calls=sum(e['kind'] == 'http_end' for e in events),
        repairs=sum(e['kind'] == 'structured_repair' for e in events),
        prompt_tokens=sum(u.get('prompt_tokens', 0) for u in usage),
        completion_tokens=sum(u.get('completion_tokens', 0) for u in usage),
        clip_calls=len(clips), clip_seconds=sum(c['seconds'] for c in clips),
        wall_seconds=profile['wall_seconds'],
        http_seconds=profile['all_work_seconds'].get('http_seconds', 0),
        queue_seconds=profile['all_work_seconds'].get('client_queue_seconds', 0),
        shape=shape)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    args = parser.parse_args()
    summary = json.loads((args.run / 'summary.json').read_text())
    data, totals = {}, []
    for run in summary['runs']:
        label = f"{run['repeat']}_{run['arm']}"
        data[label] = {}
        for sid, profile in run['questions'].items():
            payload = json.loads((args.run / label / (sid.replace('/', '_') + '.json')).read_text())
            data[label][sid] = describe(payload, profile)
        totals.append(dict(label=label, batch_seconds=run['batch_seconds'], **{
            k: sum(q[k] for q in data[label].values())
            for k in next(iter(data[label].values())) if k != 'shape'}))
        assert sum(q['http_calls'] for q in data[label].values()) == sum(run['client_http_calls'].values())
        for field, metric in (('prompt_tokens', 'vllm:request_prompt_tokens_sum'),
                              ('completion_tokens', 'vllm:request_generation_tokens_sum')):
            assert sum(q[field] for q in data[label].values()) == sum(
                metrics[metric] for metrics in run['server_metric_deltas'].values())
    comparisons, pairs = [], []
    for before, after in (('slow_fixed', 'fast_dynamic'), ('slow_fixed', 'slow_dynamic'),
                          ('fast_fixed', 'fast_dynamic'), ('slow_dynamic', 'fast_dynamic')):
        group = []
        for repeat in (0, 1):
            a, b = data[f'{repeat}_{before}'], data[f'{repeat}_{after}']
            assert a.keys() == b.keys()
            for sid in a:
                x, y = a[sid], b[sid]
                equal = all(x[k] == y[k] for k in COUNT_FIELDS)
                pair = dict(comparison=f'{before}->{after}', repeat=repeat, sample_id=sid,
                    counts_equal=equal, shape_equal=equal and x['shape'] == y['shape'],
                    before=x, after=y, delta_seconds=y['wall_seconds'] - x['wall_seconds'])
                group.append(pair)
        for level in ('all', 'counts_equal', 'shape_equal'):
            selected = [p for p in group if level == 'all' or p[level]]
            comparisons.append(dict(comparison=f'{before}->{after}', subset=level,
                count=len(selected), faster=sum(p['delta_seconds'] < 0 for p in selected),
                before_wall_sum=sum(p['before']['wall_seconds'] for p in selected),
                after_wall_sum=sum(p['after']['wall_seconds'] for p in selected),
                median_paired_delta=(statistics.median(p['delta_seconds'] for p in selected)
                                     if selected else None)))
        pairs.extend(group)
    output = dict(count_fields=COUNT_FIELDS, runs=totals, comparisons=comparisons, pairs=pairs)
    (args.run / 'step_analysis.json').write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n')
    with (args.run / 'step_analysis.csv').open('w') as stream:
        writer = csv.DictWriter(stream, fieldnames=['run', 'sample_id', *[k for k in totals[0] if k not in ('label', 'batch_seconds')]])
        writer.writeheader()
        for label, rows in data.items():
            for sid, row in rows.items():
                writer.writerow(dict(run=label, sample_id=sid, **{k: v for k, v in row.items() if k != 'shape'}))
    print(json.dumps(dict(runs=totals, comparisons=comparisons), indent=2))


if __name__ == '__main__':
    main()
