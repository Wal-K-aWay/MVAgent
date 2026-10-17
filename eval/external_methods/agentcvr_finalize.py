"""Audit the completed frozen AgentCVR run on Modal CPU without new inference."""
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from itertools import batched
import hashlib
import json
from pathlib import Path
import sys
import tarfile
import time

import modal

image = None
if modal.is_local():
    from agentcvr_assets import image

app = modal.App('wxu-evolve-agent-agentcvr-final-audit-20261017')
runs = modal.Volume.from_name('wxu-evolve-agent-runs-20261006')
assets = modal.Volume.from_name('wxu-evolve-agent-inf-asset-20261006')


@app.function(image=image, cpu=4, memory=8192, timeout=3600,
              volumes={'/runs': runs, '/assets': assets.with_mount_options(read_only=True)})
def audit():
    output = Path('/runs/devbox/agentcvr_eval_h100_20261016_r2')
    def read(path):
        return json.loads(path.read_text())
    def digest(path):
        with path.open('rb') as stream:
            return hashlib.file_digest(stream, 'sha256').hexdigest()

    manifest = read(output / 'manifest.json')
    progress = read(output / 'progress.json')
    scores = read(output / 'scores.json')
    assert progress['phase'] == 'completed' and progress['completed'] == 2821
    assert digest(output / 'frozen_source.tar.gz') == manifest['source_archive_sha256']
    working = Path('/tmp/agentcvr-final-source')
    working.mkdir(exist_ok=True)
    with tarfile.open(output / 'frozen_source.tar.gz') as archive:
        archive.extractall(working, filter='data')
    for name, expected in manifest['source_hashes'].items():
        assert digest(working / name) == expected, name
    for name, key in [('items.json', 'input_sha256'), ('agent_system.prompt', 'protocol_sha256'),
                      ('assets_manifest.json', 'assets_manifest_sha256')]:
        assert digest(output / name) == manifest[key], name
    sys.path[:0] = [str(working), str(working / 'src'), str(working / 'eval/external_methods')]
    from agentcvr_eval import official_inputs
    from eval.e2e_eval.harness.cvbench import CVBench
    from eval.e2e_eval.harness.mvu_eval import MVUEval
    official_items, labels = official_inputs()
    assert official_items == read(output / 'items.json')
    assert labels == read(output / 'private_labels.json')
    items = {item['sample_id']: item for item in official_items}
    protocol = (output / 'agent_system.prompt').read_text()
    scored = {row['sample_id']: row for row in scores['rows']}
    assert len(scored) == 2821 and set(scored) == set(items)
    cv = CVBench(data_root=Path('/assets'), frames=512, max_side=360)
    counts, calls, tools, finishes = Counter(), Counter(), Counter(), Counter()
    by_task = defaultdict(lambda: {'n': 0, 'correct': 0, 'format_errors': 0})
    observed, not_answered, transport_samples = set(), [], []
    http_errors = token_mismatches = 0
    inherited = read(output / 'recovery_manifest.json')['inherited']
    def load_record(path):
        return path, read(path), (output / 'raw' / path.name).read_bytes()
    index = 0
    with ThreadPoolExecutor(max_workers=8) as readers:
        for batch in batched(sorted((output / 'records').glob('*.json')), 16):
            for path, record, raw_bytes in readers.map(load_record, batch):
                index += 1
                sid = record['sample_id']; item = items[sid]
                assert sid not in observed
                observed.add(sid)
                assert hashlib.sha256(raw_bytes).hexdigest() == record['raw_sha256'], sid
                if sid in inherited:
                    assert record['raw_sha256'] == inherited[sid], sid
                raw = json.loads(raw_bytes)
                assert raw['sample_id'] == sid
                for key in ('answer', 'status', 'seconds', 'input_sha256'):
                    assert raw[key] == record[key], (sid, key)
                assert record['input_sha256'] == hashlib.sha256(json.dumps(item, sort_keys=True).encode()).hexdigest()
                assert raw['status'] != 'infrastructure_error', sid
                result = cv.score(labels[sid], raw['answer']) if item['dataset'] == 'cvbench' else MVUEval.score(None, labels[sid], raw['answer'])
                if raw['status'] != 'answered':
                    result['score'] = 0.0
                    not_answered.append({'sample_id': sid, 'answer': raw['answer'],
                                         'calls': len(raw['calls']), 'tools': len(raw.get('tools', []))})
                for key, value in result.items():
                    assert scored[sid][key] == value, (sid, key)
                counts[item['dataset']] += result['score']
                task = item['dataset'] + '/' + labels[sid]['task']
                by_task[task]['n'] += 1
                by_task[task]['correct'] += result['score']
                by_task[task]['format_errors'] += not result['format_ok']
                errors_here = 0
                for call in raw['calls']:
                    request = call['request']; calls[request['model']] += 1
                    assert request['temperature'] == .5 and request['max_tokens'] == 8192 and request['seed'] == 0
                    if request['model'] == 'agentcvr-master':
                        payload = json.loads(request['messages'][1]['content'][0]['text'])
                        assert payload['query'] == item['query'] and 'possible_answers' not in payload
                        assert request['messages'][0]['content'] == item['system'] + '\n\n' + protocol
                    failed = bool(call.get('error') or call.get('http_status', 200) >= 400)
                    http_errors += failed; errors_here += failed
                    response = call.get('response', {})
                    if not failed and response.get('choices'):
                        choice = response['choices'][0]; usage = response['usage']
                        finishes[choice['finish_reason']] += 1
                        token_mismatches += len(response.get('prompt_token_ids') or []) != usage['prompt_tokens']
                        token_mismatches += len(choice.get('token_ids') or []) != usage['completion_tokens']
                if errors_here:
                    transport_samples.append({'sample_id': sid, 'failed_calls': errors_here})
                tools.update(t['tool_name'] for t in raw.get('tools', []))
                if index % 500 == 0:
                    print(json.dumps({'audited_records': index}), flush=True)
    assert observed == set(items) and len(list((output / 'raw').glob('*.json'))) == 2821
    assert token_mismatches == 0
    for dataset, total in scores['datasets'].items():
        assert counts[dataset] == total['correct']
        assert total == progress['datasets'][dataset]
    report = dict(time=time.time(), phase='passed', source_commit=manifest['project_commit'],
                  samples=len(observed), inherited=len(inherited), datasets=scores['datasets'],
                  by_task=dict(by_task), calls=dict(calls), tools=dict(tools), finish_reasons=dict(finishes),
                  http_errors=http_errors, transport_samples=transport_samples, token_mismatches=token_mismatches,
                  not_answered=not_answered, completed_at=progress['updated'],
                  manifest_sha256=digest(output / 'manifest.json'), scores_sha256=digest(output / 'scores.json'))
    (output / 'final_audit.json').write_text(json.dumps(report, indent=2))
    runs.commit()
    return report


@app.local_entrypoint()
def main():
    print(json.dumps(audit.remote(), indent=2))
