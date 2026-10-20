"""Verify compact answer/GT/timing/call fidelity against saved external-method results."""
import argparse
from collections import Counter
import json
from pathlib import Path

from common import sha256, write
from lenswalk_export import EXPECTED, MEDIA, source_metadata, export_score


def verify(output):
    read = lambda path: json.loads(path.read_text())
    bundle = read(output/'bundle.json'); root = Path(bundle['source'])
    for name, digest in bundle['source_hashes'].items():
        assert sha256(root/name) == digest, name
    source = read(root/'summary.json')
    rows = {r['sample_id']: r for r in source['rows']}
    labels, judge_paths, _ = source_metadata(root, bundle['method'])
    assert set(rows) == set(labels) and len(rows) == 5321
    calls = tokens_in = tokens_out = 0
    for entry in bundle['files']:
        path = output/'files'/entry['name']
        assert path.stat().st_size == entry['bytes'] and sha256(path) == entry['sha256']
    stats = {}
    for dataset, expected in EXPECTED.items():
        seen = set(); terminals = Counter(); failed = []; invalid = []
        with (output/'files'/f'{dataset}.jsonl').open() as stream:
            for line in stream:
                value = json.loads(line); sid = value['id']; row = rows[sid]; label = labels[sid]
                assert sid not in seen and row['dataset'] == dataset
                seen.add(sid); terminals[row['terminal']] += 1
                gt = label['sample']['ground_truth']
                if row['task'] == 'CCQA':
                    gt = dict(answer=label['reference_answer'], scoring_points=gt)
                assert value['gt'] == gt and value['seconds'] == row['seconds']
                assert value['output'] == row['answer'] or (value['output'] is None and not row['answer'])
                trace = value['trajectory']
                for key in ('terminal', 'infrastructure_error', 'score', 'prepared_seconds', 'archive_seconds'):
                    assert trace[key] == row[key], (sid, key)
                assert trace['source_archive_sha256'] == row['raw_archive']['sha256']
                assert not MEDIA.search(line) and all('"'+key+'":' not in line for key in
                       ('token_ids', 'prompt_token_ids', 'completion_token_ids', 'output_token_ids', '_sync_token_audit'))
                actual_calls = [c for c in trace['calls'] if c.get('error') != 'malformed_saved_jsonl']
                assert len(actual_calls) == row['calls'], sid
                assert all('request' not in c and 'response' not in c for c in actual_calls)
                valid = [c for c in actual_calls if c['http_status'] == 200 and not c['error']]
                assert sum(c['input_tokens'] for c in valid) == row['input_tokens'], sid
                assert sum(c['output_tokens'] for c in valid) == row['output_tokens'], sid
                calls += row['calls']; tokens_in += row['input_tokens']; tokens_out += row['output_tokens']
                if row['infrastructure_error']: failed.append(sid)
                if row['terminal'] == 'invalid_decision': invalid.append(sid)
        assert len(seen) == expected and seen == {sid for sid, r in rows.items() if r['dataset'] == dataset}
        stats[dataset] = dict(samples=len(seen), terminals=dict(terminals), infrastructure_failures=failed,
                              invalid_decisions=invalid)
    scores = [json.loads(line) for line in (output/'files/ccqa_scores.jsonl').read_text().splitlines()]
    assert len(scores) == len({s['id'] for s in scores}) == 239
    for score in scores:
        row = rows[score['id']]
        judge = None if row['infrastructure_error'] else read(judge_paths[score['id']])
        assert score == export_score(row, labels[score['id']], judge)
    archive = bundle['archive']; path = output/archive['name']
    assert path.stat().st_size == archive['bytes'] and sha256(path) == archive['sha256']
    result = dict(samples=5321, ccqa_scores=239, ccqa_judged=bundle['ccqa_judged'],
                  ccqa_infrastructure_failures=bundle['ccqa_infrastructure_failures'],
                  calls=calls, input_tokens=tokens_in, output_tokens=tokens_out,
                  benchmarks=stats, archive=archive, fidelity_verified=True, no_inline_media_or_token_arrays=True,
                  verifier_sha256=sha256(Path(__file__)))
    write(output/'verified.json', result)
    print(json.dumps({k:v for k,v in result.items() if k != 'benchmarks'}, ensure_ascii=False))
    print((output/'files/statistics.md').read_text())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    verify(parser.parse_args().output)
