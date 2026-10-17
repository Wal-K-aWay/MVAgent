#!/usr/bin/env python3
"""Judge saved CCQA outputs and report independent BF16 reproducibility measurements."""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re

from benchmark_qwen35_fp8 import save
from confirm_bf16_e2e import compare
from confirm_bf16_mvagent import compare_traces, token_trace
from harness.ccqa import judge_outputs


def read(path):
    return json.loads(path.read_text())


def aggregate(rows, populations):
    groups = defaultdict(list)
    for row in rows:
        groups[(row['benchmark'], row['task'])].append(row)
    tasks = {}
    for (benchmark, task), items in groups.items():
        weights = [r.get('points', 1) if task == 'CCQA' else 1 for r in items]
        tasks.setdefault(benchmark, {})[task] = sum(r['score'] * w for r, w in zip(items, weights)) / sum(weights)
    return {name: {'samples': sum(r['benchmark'] == name for r in rows), 'tasks': scores,
            'official_estimate': (sum(scores.values()) / len(scores) if name == 'crossvid' else
                sum(value * populations[name][task] for task, value in scores.items()) /
                sum(populations[name][task] for task in scores))} for name, scores in tasks.items()}


def self_check():
    rows = [dict(benchmark='crossvid', task='CCQA', score=1, points=1),
            dict(benchmark='crossvid', task='CCQA', score=0, points=3),
            dict(benchmark='crossvid', task='BU', score=1),
            dict(benchmark='cvbench', task='a', score=0),
            dict(benchmark='cvbench', task='b', score=1)]
    result = aggregate(rows, {'cvbench': {'a': 3, 'b': 1}})
    assert result['crossvid']['official_estimate'] == 0.625
    assert result['cvbench']['official_estimate'] == 0.25
    print('Aggregation self-check passed: point-weighted CCQA, task macro, population weighting')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--e2e', type=Path)
    parser.add_argument('--mvagent', type=Path)
    parser.add_argument('--interrupted-mvagent', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--judge-endpoint')
    parser.add_argument('--self-check', action='store_true')
    args = parser.parse_args()
    if args.self_check:
        self_check()
        return
    if not args.output or not str(args.output).startswith('/runs/') or not args.e2e or not args.judge_endpoint:
        raise SystemExit('Require --e2e, --judge-endpoint, and /runs/ --output')
    assert read(args.e2e / 'progress.json')['phase'] == 'finished'
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'report_source.py').write_bytes(Path(__file__).read_bytes())
    selected = {r['sample_id']: r for r in read(args.e2e / 'selection.json')}
    populations = read(args.e2e / 'populations.json')
    metrics, counterexamples = [], []
    trajectory_stats, old_trajectories = [], {}

    def scored_metrics(kind, model, label, rows):
        pending = [(selected[r['sample_id']], r['output']) for r in rows if r['task'] == 'CCQA']
        if pending:
            identity, judgments = judge_outputs(pending, cache_dir=args.output / 'judge_cache',
                endpoints=[args.judge_endpoint], attempts=3, timeout=300)
            save(args.output / 'judge_identity.json', identity)
            save(args.output / kind / model / label / 'judgments.json', judgments)
            failed = [r for r in judgments.values() if r['status'] != 'ok']
            if failed:
                raise RuntimeError(f'CCQA judge failed: {failed}')
            for row in rows:
                if row['task'] == 'CCQA':
                    judgment = judgments[row['sample_id']]
                    row.update(score=judgment['score'], points=judgment['points'])
        assert all(isinstance(r['score'], (int, float)) for r in rows)
        result = dict(kind=kind, model=model, pass_name=label, metrics=aggregate(rows, populations))
        metrics.append(result)
        save(args.output / kind / model / label / 'scored.json', rows)
        save(args.output / 'metrics.json', metrics)
        print(json.dumps(result), flush=True)

    e2e = read(args.e2e / 'summary.json')
    for model in e2e:
        root = args.e2e / model['model']
        reference = read(root / 'references.json') if (root / 'references.json').exists() else {}
        for summary in model['passes']:
            label = summary['name']
            raw = [json.loads(line) for line in (root / label / 'raw.jsonl').read_text().splitlines()]
            assert len(raw) == summary['samples'] and len({r['sample_id'] for r in raw}) == len(raw)
            differences = []
            for row in raw:
                delta = compare(reference[row['sample_id']], row['request'])
                if any(delta[k] for k in ['input_changed', 'tokens_changed']):
                    differences.append(row['sample_id'])
                    counterexamples.append(dict(model=model['model'], pass_name=label,
                        sample_id=row['sample_id'], output=row['output'], **delta))
            assert set(differences) == {r['sample_id'] for r in summary['differences']}
            scored = read(root / label / 'scored.json')
            rows = [dict(sample_id=r['sample_id'], benchmark=r['benchmark'], task=r['task'], output=r['output'],
                         score=r.get('score', {}).get('score')) for r in scored]
            scored_metrics('e2e', model['model'], label, rows)
    mvagent = read(args.mvagent / 'summary.json') if args.mvagent else []
    interrupted = read(args.interrupted_mvagent / 'interruption.json') if args.interrupted_mvagent else None
    if interrupted:
        rows = []
        for path in (args.interrupted_mvagent / '35B-A3B/reference/records').rglob('result.json'):
            row = read(path)
            old_trajectories[row['sample_id']] = row
            if row['status'] == 'ok' and row['scoring_status'] in ['ok', 'deferred']:
                item = selected[row['sample_id']]
                rows.append(dict(sample_id=row['sample_id'], benchmark=item['benchmark'], task=item['task'],
                                 output=row['prediction'], score=row['score']))
        scored_metrics('mvagent_interrupted', '35B-A3B', 'reference_partial', rows)
    for model in mvagent:
        for summary in model.get('passes', []):
            rows, call_counts, output_counts, same_old = [], [], [], 0
            for path in (args.mvagent / model['model'] / summary['name'] / 'records').rglob('result.json'):
                row = read(path)
                calls = [e for e in row['events'] if e['kind'] == 'model_response']
                call_counts.append(len(calls))
                output_counts.append(sum(len(e.get('token_ids', [])) for e in calls))
                if summary['name'] == 'reference' and row['sample_id'] in old_trajectories:
                    previous = old_trajectories[row['sample_id']]
                    same_old += (not compare_traces(token_trace(previous['events']), token_trace(row['events']))
                                 and previous['prediction'] == row['prediction'])
                if row['status'] == 'ok' and row['scoring_status'] in ['ok', 'deferred']:
                    item = selected[row['sample_id']]
                    rows.append(dict(sample_id=row['sample_id'], benchmark=item['benchmark'], task=item['task'],
                                     output=row['prediction'], score=row['score']))
            scored_metrics('mvagent', model['model'], summary['name'], rows)
            assert sum(call_counts) == summary['model_calls'] and len(call_counts) == summary['rollouts']
            trajectory_stats.append(dict(model=model['model'], pass_name=summary['name'],
                calls_per_rollout=[min(call_counts), max(call_counts)],
                output_tokens_per_rollout=[min(output_counts), max(output_counts)],
                unchanged_from_previous_budget=same_old if summary['name'] == 'reference' else None))
    save(args.output / 'trajectory_stats.json', trajectory_stats)
    save(args.output / 'counterexamples.json', counterexamples)
    lines = ['# 独立单卡 BF16：真实 E2E 与 MVAgent 复现验收', '',
        '同一台8×H100 80GB，每卡完整权重，8个独立TP1/DP1服务、每卡在途请求≤1。',
        'BF16权重/KV；max_num_seqs8、prefill16384、context131072、mem0.95、prefix/Mamba align、MM4GiB；seed0、temperature0、thinking关闭。',
        'vLLM0.19.1 / torch2.10.0 / transformers4.57.6，VLLM_BATCH_INVARIANT=0。', '',
        'E2E：66题（CVBench30/MVU16/CrossVid20），覆盖33类、每类2题，CrossVid从已有Lite2500抽取。',
        '四轮：首次参考、同卡乱序重复、换卡、完整停服重启后再换卡。每轮重新调用真实adapter；无答案缓存。',
        '最多512帧/最长边448，图片输入；CV输出上限128，MVU/Cross8192，正常EOS。',
        '逐项比较实际输出token IDs、请求字节哈希、输入token哈希；重复次数不能当作独立题数。', '',
        '| 模型 | 响应数 | 同卡差异/66 | 换卡差异/66 | 重启换卡差异/66 | 请求错误 | E2E通过 |',
        '|---|---:|---:|---:|---:|---:|---|']
    for model in e2e:
        ps = {p['name']: len(p['differences']) for p in model['passes']}
        cells = [str(ps.get(k, '未完成')) for k in ['same_gpu_repeat', 'rotated_gpu', 'after_restart']]
        lines.append(f"| {model['model']} | {model['samples']} | {' | '.join(cells)} | {model['request_errors']} | {model['stable']} |")
    lines += ['', '| 单卡模型 | 权重加载 GiB | KV预算 GiB |', '|---|---:|---:|']
    for model in e2e:
        log = (args.e2e / model['model'] / 'servers_restart0/server_0.log').read_text()
        weights = re.search(r'Model loading took ([\d.]+) GiB', log)
        kv = re.search(r'Available KV cache memory: ([\d.]+) GiB', log)
        lines.append(f"| {model['model']} | {weights[1] if weights else '未记录'} | {kv[1] if kv else '未记录'} |")
    lines += ['', '以上为副本0的启动日志，不是任意输入长度或更大并发的容量保证。源码、配置及GPU UUID见原始目录的manifest与servers_restart*/文件。',
        '模型与Judge的Hugging Face下载metadata revision、小型配置哈希和权重文件大小见报告目录weight_provenance.json；没有重新哈希完整权重文件。']
    lines += ['', '## MVAgent', '',
        '只让E2E通过的模型进入；33题（每类1题），完整空skill库、Global/Video各最多5步、每次输出2048 token。',
        '逐调用记录实际token与输入哈希，按agent/video/decision比较轨迹，忽略并发视频的完成先后顺序；同时比较最终答案。',
        '服务另允许video输入，按真实MVAgent video_url协议运行；因此不把E2E图片请求和MVAgent视频请求视为同一协议。', '',
        '| 模型 | 完成rollout | 模型调用 | 差异轨迹 | 三轮通过 | 错误 |', '|---|---:|---:|---:|---|---|']
    for model in mvagent:
        lines.append(f"| {model['model']} | {model.get('rollouts', 0)} | {model.get('model_calls', 0)} | {model.get('differences', 0)} | {model['stable']} | {model.get('error')} |")
    for row in trajectory_stats:
        lines += ['', f"{row['model']}/{row['pass_name']}：每题{row['calls_per_rollout'][0]}–{row['calls_per_rollout'][1]}次模型调用，累计生成{row['output_tokens_per_rollout'][0]}–{row['output_tokens_per_rollout'][1]} token。"]
    if not mvagent:
        lines += ['', '没有模型进入MVAgent阶段。']
    if interrupted:
        lines += ['', f"首次MVAgent采用prefill/encoder预算16384，完成{interrupted['completed_rollouts']}/33条首轮轨迹后，另4题持续无forward进展；主执行者停止该轮，没有重复验收通过的结论。",
            '未完成题：' + ', '.join(interrupted['pending_sample_ids']) + '。',
            'EngineCore五秒采样258/258处于有未完成请求但未执行模型的sleep路径；GPU利用率为0。预算不足属于诊断假设，不能仅凭现象认定唯一原因。',
            f'初次负结果、干预记录和进程采样：`{args.interrupted_mvagent}`。',
            '后续MVAgent使用独立新目录，把prefill/encoder预算提高到32768，并新增实时事件落盘；模型、输入、seed、每卡C1等不变。两种预算不混作相同配置的重复。',
            '参考上游相似问题：[vLLM #26223](https://github.com/vllm-project/vllm/issues/26223)；本机安装源码与实际进程采样另行核对。']
        for row in trajectory_stats:
            if row['pass_name'] == 'reference':
                lines += ['', f"与旧预算下已完成的{len(old_trajectories)}条轨迹比较，{row['unchanged_from_previous_budget']}条的全部输入哈希、输出token与最终答案相同；配置改变不能被当作相同配置的重复。"]
    lines += ['', '## 分数与诊断耗时', '',
        '开发小面板分数，不能当作全集准确率。CV/MVU按全集题型频数加权估计；CrossVid十类macro，CCQA按评分点数加权。',
        'CCQA用项目既有本地Qwen3-30B-A3B-Instruct-2507 Judge；失败直接报错。其响应缓存只用于评分，不用于Actor复现检查。', '',
        '| 阶段/模型/轮次 | CVBench估计分 | MVU估计分 | CrossVid macro | 有效评分题数 |', '|---|---:|---:|---:|---:|']
    for entry in metrics:
        scores = [f"{100*entry['metrics'][b]['official_estimate']:.2f}" if b in entry['metrics'] and len(entry['metrics'][b]['tasks']) == len(populations[b]) else '题型未齐' for b in ['cvbench', 'mvu_eval', 'crossvid']]
        lines.append(f"| {entry['kind']}/{entry['model']}/{entry['pass_name']} | {' | '.join(scores)} | {sum(r['samples'] for r in entry['metrics'].values())} |")
    lines += ['', '| 模型 | 四轮端到端秒数（同上顺序） |', '|---|---|']
    for model in e2e:
        lines.append(f"| {model['model']} | {', '.join(str(round(p['seconds'], 2)) for p in model['passes'])} |")
    lines += ['', '这些时间包含媒体准备、首次读取/请求快照、推理、审计与评分；OS/服务缓存未全部控制，不能直接当作全集吞吐。',
        '三模型统一逐token稳定门槛未通过时，不发布满足该前提的全量耗时估计，也不启动全量测评。',
        '固定seed只固定随机状态；本轮无改seed或挑seed。有限样本通过也不保证任意输入、跨allocation或未来版本一致。', '',
        '原始实验与源码快照：', f'- E2E：`{args.e2e}`', f'- MVAgent：`{args.mvagent}`',
        f'- 派生评分、反例与本报告：`{args.output}`', '',
        '原始结果仅留Modal runs volume；本机只保存Markdown。']
    report = '\n'.join(lines) + '\n'
    (args.output / 'report.md').write_text(report)
    print('report_sha256', hashlib.sha256(report.encode()).hexdigest(), flush=True)


if __name__ == '__main__':
    main()
