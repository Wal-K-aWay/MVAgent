#!/usr/bin/env python3
"""Reaudit raw MVAgent trajectories from a completed in-process GPU experiment."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import time

from benchmark_qwen35_fp8 import save
from confirm_single_process_gpu import STAGES
from confirm_single_process_mvagent import compare_rollouts, token_trace


def read(path):
    return json.loads(path.read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, action='append', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    selected, manifests, interruptions = {}, {}, {}
    assert str(args.output).startswith('/runs/')
    ids = {r['name'] for r in read(args.run[0] / 'inputs.json')}
    assert len(ids) == 6
    for root in args.run:
        assert str(root).startswith('/runs/')
        progress = read(root / 'progress.json')
        if progress['phase'] != 'finished':
            interruption = read(root / 'interruption.json')
            assert interruption['reason'] in ['same_gpu_repeat_failed', 'completed_model_moved_remaining_work']
            interruptions[str(root)] = interruption
        manifest = read(root / 'manifest.json')
        manifests[str(root)] = manifest
        assert manifest['workload'] == 'mvagent'
        assert manifest['source_sha256'] == hashlib.sha256((root / 'driver_source.py').read_bytes()).hexdigest()
        assert {r['name'] for r in read(root / 'inputs.json')} == ids
        summaries = (read(root / 'summary.json') if progress['phase'] == 'finished' else
                     [read(root / model / 'summary.json') for model in interruption['measured_models']])
        for summary in summaries:
            assert summary['model'] not in selected, 'Duplicate model runs must be selected explicitly'
            selected[summary['model']] = (root, summary)
    first_manifest = manifests[str(args.run[0])]
    assert all(m['config'] == first_manifest['config'] and m['versions'] == first_manifest['versions']
               for m in manifests.values())
    metrics, differences = [], []
    lines = ['# 同进程跨GPU配置下的完整MVAgent长轨迹重复性', '',
        '原始目录：' + '、'.join(f'`{r}`（本机PID {manifests[str(r)]["pid"]}）' for r in args.run) + '。',
        '按模型使用独立的2×H100分配并行测试，每个模型内部的进程与GPU对固定。不评分，不运行Judge。',
        '三模型统一BF16、TP1/DP1、模型调用串行、vLLM0.19.1、inproc同步eager、Triton GDN，prefix/MM缓存关闭，seed0、temperature0、thinking关闭。',
        '完整GlobalAgent/VideoAgent，空skill库，Global/Video各最多5步，每次最多2048输出token/512帧，VideoAgent CPU并发2。',
        '相对前一E2E诊断，保留原生MVAgent video_url与逐请求FPS，并把prefill/encoder预算从16384改为32768、允许video8；旧视频实验在16384有真实卡住记录。',
        '实验transport把请求排队送至同一主线程的vLLM，保留原始prompt、schema、视频预处理与结构化校验；没有HTTP服务、没有答案回放。',
        '每模型保持同一计算PID与同一torch模型对象，权重只从磁盘加载一次，切卡经CPU搬运并重建执行器/KV状态。',
        '计划五轮：A参考、同卡重复、同卡重建、B卡、返回A卡。每轮6道任务，三个benchmark各2道，按历史成功轨迹调用数降序选择，不看正确率。',
        '同卡重复轮改变题目提交顺序，其余重建/换卡轮沿用参考顺序；没有单独验证固定整批顺序反复重跑。',
        '同卡完整重复轮出现差异后停止该模型的跨卡扩展；已足以否定严格重复性，失败不算通过。',
        '逐调用比较实际完整token IDs、输入字节SHA与prompt token SHA；另比较完整语义结果（动作、参数、报告、答案与轨迹，仅排除总耗时）。', '',
        '调用按agent/video/decision配对并保留各自顺序，不要求并发VideoAgent的完成先后顺序一致。', '',
        '| 模型 | 完成轨迹 | 重复轨迹比较 | 模型调用 | 重复调用比较 | 不一致轨迹 | 完整通过 |',
        '|---|---:|---:|---:|---:|---:|---|']
    for root, summary in selected.values():
        manifest = manifests[str(root)]
        model = summary['model']
        model_root = root / model
        identities = [read(p) for p in sorted(model_root.glob('*_identity.json'))]
        assert all(i['pid'] == manifest['pid'] and i['disk_weight_loads'] == 1 for i in identities)
        assert len({i['model_object_id'] for i in identities}) <= 1
        assert len({i['sampled_parameter_sha256'] for i in identities}) <= 1
        for identity in identities:
            assert dict(STAGES)[identity['stage']] == identity['gpu']
        refs, rows, changed, checked_requests = {}, [], [], set()
        compared_calls = compared_rollouts = 0
        all_calls, all_events, phase_stats = [], [], []
        for stage, gpu in STAGES:
            for repeat in range(2 if stage == 'A_initial' else 1):
                directory = model_root / f'{stage}_repeat{repeat}'
                if not (directory / 'summary.json').exists():
                    continue
                phase = read(directory / 'summary.json')
                assert {r['case'] for r in phase['rows']} == ids and phase['rollouts'] == 6
                identity = read(model_root / f'{stage}_identity.json')
                phase_diffs = []
                phase_calls = 0
                for item in phase['rows']:
                    row = read(Path(item['result_path']))
                    assert row['error'] is None
                    assert row['case'] in ids and row['stage'] == stage and row['repeat'] == repeat
                    calls = [e for e in row['events'] if e['kind'] == 'model_response']
                    raw = [json.loads(l) for l in Path(item['result_path']).with_name('calls.jsonl').read_text().splitlines()]
                    assert len(calls) == len(raw) == item['calls']
                    assert sorted(c['request_sha256'] for c in calls) == sorted(c['request_sha256'] for c in raw)
                    for call in calls:
                        assert call['forward_identity'] == [[identity['pid'], gpu, f'cuda:{gpu}', identity['model_object_id']]]
                        assert call['forward_calls'] > 0 and len(call['token_ids']) == call['usage']['completion_tokens']
                        request_hash = call['request_sha256']
                        if request_hash not in checked_requests:
                            with (model_root / 'requests' / (request_hash + '.json')).open('rb') as f:
                                assert hashlib.file_digest(f, 'sha256').hexdigest() == request_hash
                            checked_requests.add(request_hash)
                    token_trace(row['events'])
                    if stage == 'A_initial' and repeat == 0:
                        refs[row['case']] = row
                    else:
                        delta = compare_rollouts(refs[row['case']], row)
                        compared_rollouts += 1
                        before, after = token_trace(refs[row['case']]['events']), token_trace(row['events'])
                        compared_calls += sum(min(len(before[k]), len(after.get(k, []))) for k in before)
                        if delta['calls'] or delta['result_fields']:
                            entry = dict(case=row['case'], **delta)
                            phase_diffs.append(entry)
                            changed.append(entry)
                            differences.append(dict(model=model, stage=stage, repeat=repeat, **entry))
                    all_calls.extend(calls)
                    all_events.extend(row['events'])
                    rows.append(dict(**item, stage=stage, repeat=repeat, answer=row['result']['answer'],
                                     stop_reason=row['result']['stop_reason']))
                    phase_calls += len(calls)
                assert phase_calls == phase['responses'] and phase_diffs == phase['differences']
                phase_stats.append(dict(stage=stage, repeat=repeat, rollouts=6, calls=phase_calls,
                                        seconds=phase['seconds'], differences=len(phase_diffs)))
        stable = len(rows) == 30 and not changed and summary['error'] is None
        if str(root) not in interruptions:
            assert len(rows) == summary.get('rollouts', 0) and len(all_calls) == summary['responses']
            assert len(changed) == summary['differences'] and summary['stable'] == stable
        elif interruptions[str(root)]['reason'] == 'same_gpu_repeat_failed':
            assert len(rows) == 12 and compared_rollouts == 6 and changed and not stable
        else:
            assert len(rows) == 30
        metric = dict(model=model, run=str(root), rollouts=len(rows), comparisons=compared_rollouts,
            calls=len(all_calls), repeated_calls=compared_calls, differences=len(changed), stable=stable,
            error=summary['error'], phases=phase_stats, rows=rows,
            calls_per_rollout=[min((r['calls'] for r in rows), default=0), max((r['calls'] for r in rows), default=0)],
            output_tokens_per_rollout=[min((r['output_tokens'] for r in rows), default=0), max((r['output_tokens'] for r in rows), default=0)],
            long_rollouts=sum(r['calls'] >= 12 or r['output_tokens'] >= 3000 for r in rows),
            finish_reasons=dict(Counter(c['finish_reason'] for c in all_calls)),
            max_prompt_tokens=max((c['usage']['prompt_tokens'] for c in all_calls), default=0),
            structured_invalid=sum(e['kind'] == 'structured_invalid' for e in all_events),
            structured_repairs=sum(e['kind'] == 'structured_repair' for e in all_events),
            roles=dict(Counter(c.get('agent') for c in all_calls)))
        metrics.append(metric)
        runtime_path = model_root / 'runtime/run_manifest.json'
        runtime = read(runtime_path)
        runtime.update(status='finished', token_reproducible=stable, scoring_requested=False,
                       completed_rollouts=len(rows), compared_rollouts=compared_rollouts,
                       finished_at_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
        save(runtime_path, runtime)
        lines.append(f'| {model} | {len(rows)} | {compared_rollouts} | {len(all_calls)} | {compared_calls} | {len(changed)} | {stable} |')
    lines += ['', '重复次数不是独立题数。长轨迹采用描述性口径：至少12次模型调用，或累计至少3000个输出token。', '',
        '| 模型 | 每题调用数范围 | 每题累计输出token范围 | 单次最长输入token | 长轨迹数 | 模型结束原因 |',
        '|---|---|---|---:|---:|---|']
    for metric in metrics:
        lines.append(f'| {metric["model"]} | {metric["calls_per_rollout"]} | {metric["output_tokens_per_rollout"]} | {metric["max_prompt_tokens"]} | {metric["long_rollouts"]} | {metric["finish_reasons"]} |')
    lines += ['', '结构化输出校验与修复事件：' + '；'.join(
        f'{m["model"]} invalid={m["structured_invalid"]}/repair={m["structured_repairs"]}' for m in metrics) + '。']
    lines += ['', '## 阶段数据', '', '| 模型 | 阶段 | 轨迹 | 模型调用 | 耗时秒 | 不一致轨迹 |', '|---|---|---:|---:|---:|---:|']
    for metric in metrics:
        for phase in metric['phases']:
            lines.append(f'| {metric["model"]} | {phase["stage"]}/{phase["repeat"]} | {phase["rollouts"]} | {phase["calls"]} | {phase["seconds"]:.2f} | {phase["differences"]} |')
    lines += ['', '## 相同输入的直接反例', '',
        '轨迹分叉后的调用也可能因上游输出变化而改变输入；这里只展示请求字节与prompt token哈希均相同、输出token不同的调用。', '']
    for model in selected:
        for delta in (d for d in differences if d['model'] == model):
            direct = next((c for c in delta['calls'] if c.get('tokens_changed') and not c.get('input_changed')), None)
            if direct:
                lines.append(f'- {model}/{delta["case"]}，{delta["stage"]}/{delta["repeat"]}，{direct["scope"]}：第{direct["first_token_difference_1based"]}个输出token开始不同。')
                break
    lines += ['', '实际最终输出示例（不评分）：', '']
    for metric in metrics:
        if metric['rows']:
            example = metric['rows'][0]
            lines.append(f'- {metric["model"]}/{example["case"]} 的answer字段：{json.dumps(example["answer"].get("answer"), ensure_ascii=False)}')
    lines += ['', '## 范围与限制', '',
        '这是6道按历史调用深度选择的开发任务，未覆盖全部题型、全量benchmark、更高并发、进程重启或跨机器。不能声称任意输入确定性。',
        '切卡发生在完整轨迹之间，没有测试同一条轨迹执行到一半时切换GPU。',
        '各模型参考均在本次完整MVAgent协议下建立，不要求复制前一E2E探针或旧在线服务的输出。',
        '所有原始请求、事件、实际token、完整轨迹、冻结源码与配置留在runs volume；本地仅Markdown。',
        '未评正确率、未调用Judge，也未以这组长任务外推全量测评速度。']
    report = '\n'.join(lines) + '\n'
    args.output.mkdir(parents=True, exist_ok=True)
    save(args.output / 'audit_metrics.json', metrics)
    save(args.output / 'audit_differences.json', differences)
    save(args.output / 'source_manifests.json', manifests)
    save(args.output / 'interruptions.json', interruptions)
    (args.output / 'report_source.py').write_bytes(Path(__file__).read_bytes())
    (args.output / 'report.md').write_text(report)
    print(json.dumps(dict(rollouts=sum(m['rollouts'] for m in metrics), calls=sum(m['calls'] for m in metrics),
        differences=len(differences), report_sha256=hashlib.sha256(report.encode()).hexdigest())))


if __name__ == '__main__':
    main()
