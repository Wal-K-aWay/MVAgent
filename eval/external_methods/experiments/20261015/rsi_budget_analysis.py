"""Audit saved paired outputs, official scores, latency, and scheduling counterfactuals."""
import argparse
from collections import Counter
import csv
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import statistics
import sys


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def simulate(jobs, count=8, static=False):
    loads = [0.0] * count
    for index, seconds in enumerate(jobs):
        gpu = index % count if static else min(range(count), key=loads.__getitem__)
        loads[gpu] += seconds
    return max(loads)


def stats(values):
    values = sorted(values)
    return dict(n=len(values), total=sum(values), mean=statistics.mean(values),
                median=statistics.median(values), p90=values[int(.9*(len(values)-1))], maximum=max(values))


def ungrounded(value):
    if isinstance(value, dict):
        return int(value.get('status') == 'ungrounded_response') + sum(ungrounded(v) for v in value.values())
    return sum(map(ungrounded, value)) if isinstance(value, list) else 0


def main(root):
    assert simulate([8, 7, 6, 5], 2) == 13
    assert simulate([8, 7, 6, 5], 2, static=True) == 14
    sys.path.insert(0, str(root/'frozen_repo/src'))
    from models.vlm.local.sync_server import token_audit
    from skill_evolution.infra.benchmarks.aggregation import HierarchicalScoreAggregator
    labels = json.loads((root/'prepared/private_labels.json').read_text())
    items = {r['sample_id']: r for r in json.loads((root/'prepared/items.json').read_text())}
    progress = json.loads((root/'progress.json').read_text())
    runs, traces, scores = {}, {}, {}
    aggregator = HierarchicalScoreAggregator(
        dataset_of={s:r['dataset'] for s,r in labels.items()}, category_of={s:r['task'] for s,r in labels.items()},
        task_population={(r['dataset'],r['task']):r['task_population'] for r in labels.values()},
        sample_weights={s:len(r['sample']['ground_truth']) if r['sample']['task']=='open_qa' else 1 for s,r in labels.items()})
    for cap in (8192, 2048):
        runs[cap] = {}
        scores[cap] = {r['sample_id']:r['score'] for r in json.loads((root/f'cap{cap}/scores.json').read_text())['rows']}
        for path in sorted(root.glob(f'cap{cap}/*/execution.json')):
            execution = json.loads(path.read_text())
            sid = execution['sample_id']
            result_file = path.parent/'result.json'
            result = json.loads(result_file.read_text()) if result_file.exists() else {}
            trace = []
            request_file = path.parent/'requests.jsonl'
            if request_file.exists():
                with request_file.open() as stream:
                    for line in stream:
                        call = json.loads(line)
                        request, response = call['request'], call['response']
                        token_audit(response, json.dumps(request).encode())
                        assert response['usage']['prompt_tokens_details']['cached_tokens'] == 0
                        choice = response['choices'][0]
                        visual = any(isinstance(m.get('content'), list) and any(
                            c.get('type') == 'image_url' for c in m['content']) for m in request['messages'])
                        assert request['max_tokens'] == (cap if visual else 8192)
                        trace.append(dict(messages=digest(request['messages']), tokens=choice['token_ids'],
                            visual=visual, finish=choice['finish_reason'], max_tokens=request['max_tokens'],
                            input_tokens=response['usage']['prompt_tokens'], output_tokens=len(choice['token_ids']),
                            model_seconds=response['audit']['inference_seconds'], http_seconds=call['seconds']))
            traces[cap, sid] = trace
            runs[cap][sid] = dict(**execution, status=result.get('status', 'missing_result'),
                calls=len(trace), input_tokens=sum(c['input_tokens'] for c in trace),
                output_tokens=sum(c['output_tokens'] for c in trace),
                model_seconds=sum(c['model_seconds'] for c in trace),
                http_seconds=sum(c['http_seconds'] for c in trace),
                visual_calls=sum(c['visual'] for c in trace),
                visual_truncated=sum(c['visual'] and c['finish']=='length' for c in trace),
                ungrounded_observations=ungrounded([t.get('observation') for t in result.get('trace', [])]),
                decisions_hash=digest([t.get('decision') for t in result.get('trace', [])]))
    paired = sorted(set(scores[8192]) & set(scores[2048]))
    assert paired, 'No valid scored pairs'
    changes, comparisons = [], []
    for sid in paired:
        old, new = runs[8192][sid], runs[2048][sid]
        assert old['gpu'] == new['gpu'] and old['input_hashes'] == new['input_hashes']
        first = None
        before, after = traces[8192,sid], traces[2048,sid]
        for index, (a,b) in enumerate(zip(before,after)):
            if a['messages'] != b['messages'] or a['tokens'] != b['tokens']:
                limit = min(len(a['tokens']), len(b['tokens']))
                first = dict(call=index, identical_messages=a['messages']==b['messages'],
                    first_token_difference=next((i for i in range(limit) if a['tokens'][i]!=b['tokens'][i]), limit),
                    shorter_is_prefix=a['tokens'][:limit]==b['tokens'][:limit])
                break
        if first is None and len(before) != len(after):
            first = dict(call=min(len(before),len(after)), different_call_count=True)
        comparisons.append(dict(sample_id=sid, first_divergence=first,
            identical_decisions=old['decisions_hash']==new['decisions_hash']))
        if old['answer'] != new['answer'] or scores[8192][sid] != scores[2048][sid]:
            changes.append(dict(sample_id=sid, old_answer=old['answer'], new_answer=new['answer'],
                old_score=scores[8192][sid], new_score=scores[2048][sid],
                old_seconds=old['seconds'], new_seconds=new['seconds']))
    report = dict(phase=progress['phase'], paired_scored=len(paired), changed=changes, comparisons=comparisons,
                  datasets={}, conditions={}, scheduling={}, limitation='Two development examples per native task; no non-inferiority claim.')
    aggregate = {cap:asdict(aggregator.aggregate(sample_ids=paired, scores=scores[cap], buckets={})) for cap in scores}
    for dataset in ('crossvid', 'cvbench', 'mvu_eval'):
        ids = [s for s in paired if labels[s]['dataset']==dataset]
        report['datasets'][dataset] = dict(n=len(ids), expected=sum(r['dataset']==dataset for r in labels.values()),
            scores={str(cap):aggregate[cap]['bucket_scores'].get('dataset:'+dataset) for cap in scores},
            subset_means={str(cap):statistics.mean(scores[cap][s] for s in ids) for cap in scores},
            answer_changes=sum(runs[8192][s]['answer']!=runs[2048][s]['answer'] for s in ids),
            gains=sum(scores[2048][s]>scores[8192][s] for s in ids), losses=sum(scores[2048][s]<scores[8192][s] for s in ids),
            seconds={str(cap):stats([runs[cap][s]['seconds'] for s in ids]) for cap in scores})
    for cap in scores:
        rows = [runs[cap][s] for s in paired]
        report['conditions'][str(cap)] = dict(successful=sum(r['success'] for r in runs[cap].values()),
            status_counts=dict(Counter(r['status'] for r in runs[cap].values())),
            seconds=stats([r['seconds'] for r in rows]), official_aggregate_paired=aggregate[cap],
            **{key:sum(r[key] for r in rows) for key in ('calls','input_tokens','output_tokens','model_seconds',
                'http_seconds','visual_calls','visual_truncated','ungrounded_observations')})
        ordered = sorted(runs[cap].values(), key=lambda r:r['pair_index'])
        costs = [r['seconds'] for r in ordered]
        report['scheduling'][str(cap)] = dict(
            simulated_static_round_robin_seconds=simulate(costs, static=True),
            simulated_dynamic_fifo_seconds=simulate(costs),
            simulated_video_duration_priority_seconds=simulate([r['seconds'] for r in sorted(
                ordered, key=lambda r:items[r['sample_id']]['duration'], reverse=True)]),
            oracle_measured_duration_lpt_seconds=simulate(sorted(costs, reverse=True)),
            ideal_work_conservation_lower_bound_seconds=max(sum(costs)/8,max(costs)),
            simulated_replica_counts={str(n):dict(seconds=simulate(costs, n),
                allocated_gpu_seconds=n*simulate(costs, n)) for n in (4,8,16)})
    wall = progress['inference_finished_epoch'] - progress['inference_started_epoch']
    all_rows = [r for by_id in runs.values() for r in by_id.values()]
    report['actual_paired_schedule'] = dict(seconds=wall,
        lease_occupancy=sum(r['seconds'] for r in all_rows)/(8*wall),
        model_service_occupancy=sum(r['model_seconds'] for r in all_rows)/(8*wall),
        gpu_utilization_percent=stats([float(r[2]) for r in csv.reader((root/'gpu.csv').open()) if len(r)==5]))
    report['order_effect'] = {str(first): {str(cap):stats([r['seconds'] for r in runs[cap].values()
        if (8192 if r['pair_index']%2==0 else 2048)==first and r['sample_id'] in paired]) for cap in scores}
        for first in (8192,2048)}
    (root/'analysis.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({k:v for k,v in report.items() if k not in ('changed','comparisons')}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    main(parser.parse_args().output)
