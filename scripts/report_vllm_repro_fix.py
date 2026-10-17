#!/usr/bin/env python3
"""Reaudit complete standard-loader MVAgent reproducibility runs from raw records."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from benchmark_qwen35_fp8 import save
from confirm_single_process_mvagent import compare_rollouts
from confirm_bf16_mvagent import token_trace


def read(path):
    return json.loads(path.read_text())


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run', action='append', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    args = p.parse_args()
    assert str(args.output).startswith('/runs/')
    groups, differences, checked = {}, [], set()
    for root in args.run:
        assert str(root).startswith('/runs/')
        manifest, summary = read(root / 'manifest.json'), read(root / 'summary.json')
        assert read(root / 'progress.json')['phase'] == 'finished' and summary['error'] is None
        assert manifest['source_sha256'] == hashlib.sha256((root / 'source.py').read_bytes()).hexdigest()
        model = manifest['model']
        group = groups.setdefault(model, dict(model=model, config=manifest['config'], versions=manifest['versions'], max_steps=manifest['max_steps'],
            refs={}, ref_paths={}, cases={}, runs=[], rollouts=0, calls=0, comparisons=0, repeated_calls=0, differences=0,
            finishes=Counter(), event_counts=Counter(), call_lengths=[], output_lengths=[], prompt_lengths=[],
            seconds=0., long_rollouts=0))
        assert group['config'] == manifest['config'] and group['versions'] == manifest['versions']
        assert group['max_steps'] == manifest['max_steps']
        inputs = read(root / 'inputs.json')
        cases = {r['name'] for r in inputs}
        assert cases and len(cases) == len(inputs)
        for case in inputs:
            if case['name'] in group['cases']:
                assert group['cases'][case['name']] == case
            group['cases'][case['name']] = case
        if manifest['reference']:
            expected_reference = group['runs'][0]['root'] + '/' + model + '/A_initial_repeat0/records'
            assert manifest['reference'] == expected_reference
            assert set(group['refs']) == cases
        elif manifest.get('reference_index'):
            reference_index = Path(manifest['reference_index'])
            assert reference_index.is_relative_to('/runs')
            assert hashlib.sha256(reference_index.read_bytes()).hexdigest() == manifest['reference_index_sha256']
            index = read(reference_index)
            assert cases <= set(group['refs']), 'Audit initial shards before restarted shards'
            for case in cases:
                assert index[case]['path'] == group['ref_paths'][case]
                assert hashlib.sha256(Path(index[case]['path']).read_bytes()).hexdigest() == index[case]['sha256']
        else:
            assert not cases.intersection(group['refs']), 'Initial shards must be disjoint'
        run_calls = run_differences = 0
        for repeat in range(2):
            phase = read(root / model / f'A_initial_repeat{repeat}' / 'summary.json')
            assert len(phase['rows']) == len(cases) and {r['case'] for r in phase['rows']} == cases
            phase_calls, phase_differences = 0, []
            for item in phase['rows']:
                path = Path(item['result_path'])
                assert path.is_relative_to(root)
                row = read(path)
                assert row['error'] is None and row['case'] == item['case']
                trace = token_trace(row['events'])
                calls = [e for e in row['events'] if e['kind'] == 'model_response']
                raw = [json.loads(s) for s in path.with_name('calls.jsonl').read_text().splitlines()]
                assert len(calls) == len(raw) == item['calls']
                assert sorted(c['request_sha256'] for c in calls) == sorted(c['request_sha256'] for c in raw)
                raw_by_id = {c['request_id']: c for c in raw}
                assert len(raw_by_id) == len(raw)
                identity = read(root / model / 'A_initial_identity.json')
                for call in calls:
                    assert all(call[k] == v for k, v in raw_by_id[call['request_id']].items())
                    assert call['forward_calls'] > 0
                    assert call['forward_identity'] == [[manifest['pid'], 0, 'cuda:0', identity['model_object_id']]]
                    assert len(call['token_ids']) == call['usage']['completion_tokens']
                    request = root / model / 'requests' / (call['request_sha256'] + '.json')
                    if request not in checked:
                        with request.open('rb') as handle:
                            assert hashlib.file_digest(handle, 'sha256').hexdigest() == call['request_sha256']
                        checked.add(request)
                reference = group['refs'].get(row['case'])
                if reference is None:
                    group['refs'][row['case']] = row
                    group['ref_paths'][row['case']] = str(path)
                else:
                    delta = compare_rollouts(reference, row)
                    group['comparisons'] += 1
                    before = token_trace(reference['events'])
                    group['repeated_calls'] += sum(min(len(v), len(trace.get(k, []))) for k, v in before.items())
                    if delta['calls'] or delta['result_fields']:
                        entry = dict(case=row['case'], **delta)
                        phase_differences.append(entry)
                        differences.append(dict(model=model, root=str(root), repeat=repeat, **entry))
                group['rollouts'] += 1
                group['finishes'].update(c['finish_reason'] for c in calls)
                group['event_counts'].update(e['kind'] for e in row['events'])
                group['prompt_lengths'].extend(c['usage']['prompt_tokens'] for c in calls)
                group['call_lengths'].append(len(calls))
                tokens = sum(len(c['token_ids']) for c in calls)
                group['output_lengths'].append(tokens)
                group['long_rollouts'] += len(calls) >= 12 or tokens >= 3000
                phase_calls += len(calls)
            assert phase_calls == phase['responses'] and phase_differences == phase['differences']
            run_calls += phase_calls
            run_differences += len(phase_differences)
            group['seconds'] += phase['seconds']
        assert summary['rollouts'] == 2*len(cases) and summary['calls'] == run_calls and summary['differences'] == run_differences
        assert summary['stable'] == (run_differences == 0)
        group['calls'] += run_calls
        group['differences'] += run_differences
        group['runs'].append(dict(root=str(root), pid=manifest['pid'], gpu=manifest['cuda_visible_devices'],
                                  calls=run_calls, differences=run_differences,
                                  cases=sorted(cases),
                                  started_monotonic=summary['passes'][0].get('started_monotonic'),
                                  ended_monotonic=summary['passes'][-1].get('ended_monotonic'),
                                  gpu_inventory=manifest['gpu_inventory']))
    metrics = []
    for group in groups.values():
        group.pop('refs')
        group.pop('ref_paths')
        metrics.append(group)
    assert all(m['config'] == metrics[0]['config'] and m['versions'] == metrics[0]['versions'] for m in metrics)
    lines = ['# GDN修复候选的完整MVAgent重复性复核', '',
        '仅重算原始输入SHA、实际完整token和语义轨迹；没有正确率或Judge。',
        '每次独立进程运行所分配的历史开发题两轮；第一轮固定乱序，第二轮更换提交顺序。面板与参考关系逐文件核对。',
        '统一BF16、TP1/DP1、C1、vLLM0.19.1、标准加载器、inproc同步eager，GDN prefill显式FlashInfer，prefix/MM缓存关闭。',
        f'seed0、temperature0、thinking关闭，prefill/encoder32768、context131072、maxseq1、mem{metrics[0]["config"]["gpu_memory_utilization"]}；RMSNorm使用native路径。',
        f'原MVAgent空skill、Global/Video各{metrics[0]["max_steps"]}步、每调用2048输出token/512帧；CPU VideoAgent并发2，模型调用仍串行。', '',
        '| 模型 | 独立题目 | 进程数 | 完整轨迹 | 重复轨迹比较 | 实际调用 | 配对调用比较 | 不一致轨迹 |',
        '|---|---:|---:|---:|---:|---:|---:|---:|']
    for m in metrics:
        lines.append(f'| {m["model"]} | {len(m["cases"])} | {len(m["runs"])} | {m["rollouts"]} | {m["comparisons"]} | {m["calls"]} | {m["repeated_calls"]} | {m["differences"]} |')
    lines += ['', '## 阶段与资源', '', '| 模型 | 原始目录 | PID | CUDA_VISIBLE_DEVICES | 调用 | 不一致轨迹 |',
              '|---|---|---:|---|---:|---:|']
    for m in metrics:
        for r in m['runs']:
            lines.append(f'| {m["model"]} | `{r["root"]}` | {r["pid"]} | {r["gpu"]} | {r["calls"]} | {r["differences"]} |')
    for m in metrics:
        lines += ['', f'{m["model"]}：每条轨迹{min(m["call_lengths"])}–{max(m["call_lengths"])}调用，'
            f'{min(m["output_lengths"])}–{max(m["output_lengths"])}累计输出token；'
            f'单次最大输入{max(m["prompt_lengths"])} token；'
            f'结束原因{dict(m["finishes"])}，完成阶段总耗时{m["seconds"]:.2f}秒（不含加载）。', '']
        lines += [f'结构化校验失败事件：{m["event_counts"]["structured_invalid"]}；'
                  f'模型调用错误事件：{m["event_counts"]["model_error"]}。', '']
    lines += ['有限开发面板通过不能保证任意题库、更高并发、其他软件版本或任意硬件。',
        '进程内参考与重复、原卡新进程以及更换GPU的新进程须按上表实际阶段引用；未测试轨迹中途迁卡。',
        'GPU编号是每个进程的可见设备选择；进程内部设备均显示cuda:0，物理设备信息保存在各manifest。',
        '输入相同还核对prompt token哈希；完整语义结果比较只排除总耗时，独立视频调用按agent/video/decision配对。',
        '本报告是原始记录复核；原始请求、完整token与结果、冻结源码/配置均留runs volume。']
    report = '\n'.join(lines) + '\n'
    args.output.mkdir(parents=True, exist_ok=True)
    save(args.output / 'metrics.json', metrics)
    save(args.output / 'differences.json', differences)
    (args.output / 'source.py').write_bytes(Path(__file__).read_bytes())
    (args.output / 'report.md').write_text(report)
    print(json.dumps(dict(models=len(metrics), rollouts=sum(m['rollouts'] for m in metrics),
        calls=sum(m['calls'] for m in metrics), differences=len(differences),
        report_sha256=hashlib.sha256(report.encode()).hexdigest())))


if __name__ == '__main__':
    main()
