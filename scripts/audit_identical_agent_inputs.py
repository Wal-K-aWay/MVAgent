#!/usr/bin/env python3
"""Compare identical Agent request bytes regardless of trajectory/call position."""
import argparse
import hashlib
import json
from pathlib import Path

from benchmark_qwen35_fp8 import save
from confirm_single_process_mvagent import first_token_difference


def compare(first, current):
    return dict(prompt_changed=first['prompt_token_ids_sha256'] != current['prompt_token_ids_sha256'],
        first_token_difference=first_token_difference(first['token_ids'], current['token_ids']),
        text_changed=first['text'] != current['text'],
        finish_changed=first['finish_reason'] != current['finish_reason'])


def audit(roots, output):
    assert output.is_relative_to('/runs') and roots and len(set(roots)) == len(roots)
    groups, changed, checked = {}, [], set()
    for root in roots:
        assert root.is_relative_to('/runs')
        manifest = json.loads((root/'manifest.json').read_text())
        summary = json.loads((root/'summary.json').read_text())
        assert summary['error'] is None
        model = manifest['model']
        group = groups.setdefault(model, dict(config=manifest['config'], versions=manifest['versions'],
            calls=0, comparisons=0, repeated_within_trajectory=0, refs={}))
        assert (group['config'], group['versions']) == (manifest['config'], manifest['versions'])
        for file in sorted(root.glob('*/A_initial_repeat*/records/*/calls.jsonl')):
            for line in file.read_text().splitlines():
                call = json.loads(line)
                assert call['forward_calls'] > 0
                digest = call['request_sha256']
                request = root/model/'requests'/(digest+'.json')
                if request not in checked:
                    with request.open('rb') as handle:
                        assert hashlib.file_digest(handle, 'sha256').hexdigest() == digest
                    checked.add(request)
                group['calls'] += 1
                first, location = group['refs'].setdefault(digest, (call, str(file)))
                if first is call:
                    continue
                group['comparisons'] += 1
                group['repeated_within_trajectory'] += location == str(file)
                delta = compare(first, call)
                if any(delta.values()):
                    changed.append(dict(model=model, request_sha256=digest, reference=location,
                        current=str(file), reference_request_id=first['request_id'],
                        current_request_id=call['request_id'], **delta))
    metrics = []
    for model, group in groups.items():
        refs = group.pop('refs')
        metrics.append(dict(model=model, unique_inputs=len(refs),
            differences=sum(r['model'] == model for r in changed), **group))
    save(output/'metrics.json', metrics)
    save(output/'differences.json', changed)
    (output/'source.py').write_bytes(Path(__file__).read_bytes())
    text = ['# 相同请求跨轨迹与调用位置的一致性复核', '',
            '| 模型 | 实际调用 | 不同请求字节 | 相同请求比较 | 不一致 |',
            '|---|---:|---:|---:|---:|']
    for row in metrics:
        text.append(f'| {row["model"]} | {row["calls"]} | {row["unique_inputs"]} | {row["comparisons"]} | {row["differences"]} |')
    text += ['', '每个完全相同的请求SHA只以首次实际输出为参考，不按题目、轨迹、角色或调用序号隔离。',
             '核对实际请求文件SHA，比较完整token、prompt token SHA、文本和结束原因；不评正确率。']
    (output/'report.md').write_text('\n'.join(text)+'\n')
    print(json.dumps(dict(calls=sum(r['calls'] for r in metrics),
        comparisons=sum(r['comparisons'] for r in metrics), differences=len(changed))))


def self_check():
    first = dict(prompt_token_ids_sha256='p', token_ids=[1,2], text='a', finish_reason='stop')
    assert not any(compare(first, dict(first)).values())
    assert compare(first, {**first, 'token_ids':[1,3]})['first_token_difference'] == 2
    assert compare(first, {**first, 'prompt_token_ids_sha256':'q'})['prompt_changed']
    print('Identical-input comparison self-check passed')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run', type=Path, action='append')
    p.add_argument('--output', type=Path)
    p.add_argument('--self-check', action='store_true')
    args = p.parse_args()
    self_check() if args.self_check else audit(args.run, args.output)
