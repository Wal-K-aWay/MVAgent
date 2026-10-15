"""Audit paired efficiency runs and report speed alongside complete request/output equality."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import statistics
import sys

ROOT = Path('/runs/devbox/external_efficiency_20261015')
BASE = Path('/runs/devbox/external_methods_current_20261014_r2')
sys.path.insert(0, str(BASE/'frozen_repo/src'))
from models.vlm.local.sync_server import token_audit


def requests(path):
    rows = []
    for line in path.open():
        row = json.loads(line)
        response = row['response']
        token_audit(response, json.dumps(row['request']).encode())
        choice = response['choices'][0]
        rows.append(dict(input=response['audit']['input_sha256'], tokens=choice['token_ids'],
            messages_sha256=hashlib.sha256(json.dumps(row['request']['messages']).encode()).hexdigest(),
            prompt_tokens=response['usage']['prompt_tokens'], output_tokens=response['usage']['completion_tokens'],
            inference_seconds=response['audit']['inference_seconds'], http_seconds=row['seconds'],
            finish=choice.get('finish_reason'), max_tokens=row['request']['max_tokens']))
    return rows


def main():
    measurements = json.loads((ROOT/'e2e_measurements.json').read_text())
    assert len(measurements) == 8 and all(r['returncode'] == 0 for r in measurements)
    report = dict(media=json.loads((ROOT/'media_r2/summary.json').read_text()), e2e=[], comparisons=[], methods={})
    traces = {}
    for row in measurements:
        key = row['method'], row['repeat'], row['variant']
        trace = requests(ROOT/'e2e'/f'{row["repeat"]}_{row["variant"]}'/row['method']/'requests.jsonl')
        traces[key] = trace
        report['e2e'].append(dict(**row, calls=len(trace), prompt_tokens=sum(r['prompt_tokens'] for r in trace),
            output_tokens=sum(r['output_tokens'] for r in trace),
            model_seconds=sum(r['inference_seconds'] for r in trace),
            non_model_seconds=row['seconds']-sum(r['inference_seconds'] for r in trace)))
    for method in ('rsi', 'vam'):
        reference = traces[method, 0, 'baseline']
        ref_inputs = [r['input'] for r in reference]
        ref_pairs = Counter((r['input'], tuple(r['tokens'])) for r in reference)
        for repeat, variant in ((0, 'candidate'), (1, 'candidate'), (1, 'baseline')):
            trace = traces[method, repeat, variant]
            report['comparisons'].append(dict(method=method, repeat=repeat, variant=variant,
                identical_request_order=ref_inputs == [r['input'] for r in trace],
                identical_request_multiset=Counter(ref_inputs) == Counter(r['input'] for r in trace),
                identical_inputs_and_tokens=ref_pairs == Counter((r['input'], tuple(r['tokens'])) for r in trace)))
        medians = {variant: statistics.median(r['seconds'] for r in report['e2e']
                   if r['method'] == method and r['variant'] == variant) for variant in ('baseline', 'candidate')}
        report['methods'][method] = dict(**medians, observed_speedup=medians['baseline']/medians['candidate'])
    probe = ROOT/'budget_probe/summary.json'
    if probe.exists():
        summary = json.loads(probe.read_text())
        old = requests(BASE/'rsi/mvu_eval_TR_1585/requests.jsonl')
        new = requests(ROOT/'budget_probe/result/requests.jsonl')
        prior = json.loads((BASE/'rsi/mvu_eval_TR_1585/result.json').read_text())
        report['budget_probe'] = dict(returncode=summary['returncode'], answer=summary.get('answer'),
            prior_answer=prior.get('answer'), prior_agent_seconds=prior['seconds'], agent_seconds=summary['seconds'],
            prior_output_tokens=sum(r['output_tokens'] for r in old), output_tokens=sum(r['output_tokens'] for r in new),
            first_visual_messages_identical=old[1]['messages_sha256'] == new[1]['messages_sha256'],
            first_visual_token_prefix_identical=old[1]['tokens'][:len(new[1]['tokens'])] == new[1]['tokens'],
            prior_calls=len(old), calls=len(new), calls_detail=[{k:v for k,v in r.items() if k != 'tokens'} for r in new],
            limitation='One development example; changed output budget; historical baseline on a different allocation')
    (ROOT/'analysis.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
