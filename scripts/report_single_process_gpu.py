#!/usr/bin/env python3
"""Audit saved same-process GPU transitions; no scoring or model calls."""
import argparse
from collections import Counter
import hashlib
import importlib.metadata
import json
from pathlib import Path

from benchmark_qwen35_fp8 import digest, save
from confirm_single_process_gpu import CASE_IDS, STAGES, difference


def read(path):
    return json.loads(path.read_text())


def audit_identity(row, identity):
    expected = [identity['pid'], identity['gpu'], f"cuda:{identity['gpu']}", identity['model_object_id']]
    assert row['forward_identity'] == [expected] and row['forward_calls'] > 0
    assert all(row[key] == identity[key] for key in ['pid', 'gpu', 'model_object_id', 'stage'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, action='append')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--self-check', action='store_true')
    args = parser.parse_args()
    if args.self_check:
        identity = dict(pid=1, gpu=1, model_object_id=42, stage='B_migrated')
        row = dict(**identity, forward_identity=[[1, 1, 'cuda:1', 42]], forward_calls=2)
        audit_identity(row, identity)
        try:
            audit_identity({**row, 'forward_identity': [[2, 1, 'cuda:1', 42]]}, identity)
        except AssertionError:
            print('Actual forward PID/GPU/model identity audit self-check passed')
            return
        raise AssertionError('Different compute PID accepted')
    if not args.run or not args.output or not str(args.output).startswith('/runs/'):
        parser.error('Require --run and /runs/ --output')
    selected, failures, manifests = {}, [], {}
    manifest = read(args.run[0] / 'manifest.json')
    inputs_hash = hashlib.sha256((args.run[0] / 'inputs.json').read_bytes()).hexdigest()
    for run in args.run:
        current = read(run / 'manifest.json')
        manifests[str(run)] = current
        assert read(run / 'progress.json')['phase'] == 'finished'
        assert current['source_sha256'] == hashlib.sha256((run / 'driver_source.py').read_bytes()).hexdigest()
        assert current['config'] == manifest['config'] and current['versions'] == manifest['versions']
        assert current['gpu_inventory'] == manifest['gpu_inventory']
        assert hashlib.sha256((run / 'inputs.json').read_bytes()).hexdigest() == inputs_hash
        for summary in read(run / 'summary.json'):
            selected[summary['model']] = (run, summary)
            if summary['error']:
                failures.append(dict(run=str(run), model=summary['model'], error=summary['error'], responses=summary['responses']))
    inputs = {c['name']: c for c in read(args.run[0] / 'inputs.json')}
    assert set(inputs) == set(CASE_IDS)
    for case in inputs.values():
        assert case['input_sha256'] == digest({k: case[k] for k in ['messages', 'generation']} |
                                             {'chat_template_kwargs': {'enable_thinking': False}})
    metrics, counterexamples, process_comparisons = [], [], []
    lines = ['# 同一计算进程、同一模型对象跨 GPU 实验', '',
        '原始结果：' + '、'.join(f'`{run}`（PID {manifests[str(run)]["pid"]}）' for run in args.run) + '。',
        '每个模型的四阶段保持同一计算PID；不同模型可以使用不同进程。全部原始数据只在 Modal runs volume。',
        '2×H100 80GB HBM3；统一 BF16、TP1/DP1、单请求、seed0、temperature0、thinking关闭。',
        'vLLM0.19.1，离线 InprocClient，同步 eager、GDN Triton，关闭 prefix/MM 缓存；context131072、prefill16384、mem0.95。',
        '每模型从磁盘加载一次，保留同一 torch 模型对象，通过 CPU 搬运权重并重建执行器/KV状态。',
        '四阶段：A_initial → A_rebuilt（同卡重建对照）→ B_migrated → A_returned。',
        '每阶段8个冻结历史请求×2轮乱序；CVBench2、MVU1、CrossVid5。这是针对历史反例选择的开发小面板。',
        '输入为已归档真实帧的图片请求；CV上限128 token，其他8192，允许正常EOS，上限处截断。不重新解码视频。',
        '比较实际输出的完整 token IDs，并校验输入/输入token哈希、实际 forward 的 PID/GPU/model id。', '',
        '| 模型 | 响应 | 有效重复比较 | 同卡重复差异/8 | A→A差异/16 | GPU B差异/16 | 回GPU A差异/16 | 完整通过 |',
        '|---|---:|---:|---:|---:|---:|---:|---|']
    for run, summary in selected.values():
        model = summary['model']
        root = run / model
        refs = read(root / 'references.json')
        rows, stage_diffs, identities = [], Counter(), []
        for stage, gpu in STAGES:
            path = root / f'{stage}_identity.json'
            if path.exists():
                identity = read(path)
                identities.append(identity)
                assert identity['gpu'] == gpu and identity['disk_weight_loads'] == 1
                assert identity['engine_core_type'] == 'InprocClient'
            for repeat in range(2):
                directory = root / f'{stage}_repeat{repeat}'
                if not (directory / 'summary.json').exists():
                    continue
                raw = [json.loads(line) for line in (directory / 'raw.jsonl').read_text().splitlines()]
                assert len(raw) == 8 and {r['case'] for r in raw} == set(CASE_IDS)
                diffs = []
                for row in raw:
                    audit_identity(row, identity)
                    assert row['repeat'] == repeat and row['input_sha256'] == inputs[row['case']]['input_sha256']
                    delta = difference(refs[row['case']], row)
                    assert not delta['input_changed']
                    if delta['tokens_changed']:
                        diffs.append(dict(case=row['case'], **delta))
                        counterexamples.append(dict(model=model, stage=stage, repeat=repeat, **diffs[-1]))
                    rows.append(row)
                assert diffs == read(directory / 'summary.json')['differences']
                stage_diffs[stage] += len(diffs)
        assert len({i['pid'] for i in identities}) == len({i['model_object_id'] for i in identities}) == 1
        assert identities[0]['pid'] == manifests[str(run)]['pid']
        assert len({i['sampled_parameter_sha256'] for i in identities}) == 1
        assert len(rows) == summary['responses'] and sum(stage_diffs.values()) == summary['differences']
        complete = len(rows) == 64 and not summary['error']
        assert summary['stable'] == (complete and not sum(stage_diffs.values()))
        metric = dict(model=model, run=str(run), responses=len(rows), comparisons=max(0, len(rows)-8),
            stage_differences=dict(stage_diffs), error=summary['error'], complete=complete,
            token_range=[min(len(r['token_ids']) for r in rows), max(len(r['token_ids']) for r in rows)],
            finish_reasons=dict(Counter(r['finish_reason'] for r in rows)),
            length_limited_cases=dict(Counter(r['case'] for r in rows if r['finish_reason'] == 'length')),
            inference_seconds=sum(r['seconds'] for r in rows),
            initialization_seconds=sum(i['load_seconds'] for i in identities), identities=identities)
        example = next(r for r in rows if r['case'] == 'cvbench:664')
        metric['example'] = dict(case=example['case'], text=example['text'][:160], token_ids=example['token_ids'][:12])
        metrics.append(metric)
        counts = ' | '.join(str(stage_diffs[s]) for s, _ in STAGES)
        lines.append(f'| {model} | {len(rows)} | {metric["comparisons"]} | {counts} | {summary["stable"]} |')
    lines += ['', '重复比较均对 A_initial 第一轮参考；同卡列仅第二轮，其他列含两轮。重复次数不等于独立题数。', '',
        '| 模型 | 输出token范围 | finish_reason | 生成总秒数 | 四次初始化总秒数 |', '|---|---|---|---:|---:|']
    for m in metrics:
        lines.append(f'| {m["model"]} | {m["token_range"]} | {m["finish_reasons"]} | {m["inference_seconds"]:.2f} | {m["initialization_seconds"]:.2f} |')
        if m['length_limited_cases']:
            assert all(inputs[case]['generation']['max_tokens'] == 128 for case in m['length_limited_cases'])
    for m in metrics:
        if m['length_limited_cases']:
            lines += ['', f'{m["model"]} 上限截断记录：{m["length_limited_cases"]}；均在128 token处截断，一致性结论不覆盖上限之后的输出。']
    lines += ['', '实际输出示例（仅展示，不评分）：']
    for m in metrics:
        lines += ['', f'- {m["model"]}：`{json.dumps(m["example"], ensure_ascii=False)}`']
    lines += ['', '## 保留的失败尝试', '',
        'r1：9B同卡16响应、0差异；重建前遗漏加载后才创建的Mamba KV引用，约55GiB显存未释放，随后容量检查失败。',
        'r2：修复KV清理后，9B同卡原始与重建阶段共32响应、0差异；切到GPU B后的首次FlashInfer GDN prefill报run failed。',
        '这两次未获得跨卡响应；原始token、错误与冻结源码分别保留在同父目录的single_process_gpu_20261011_r1、_r2。',
        'r3全阶段统一改用vLLM内置Triton GDN，9B完整通过；随后27B初次初始化因共享RoPE对象仍在CPU而失败（0响应）。',
        'r4在新模型首次加载前清空全局RoPE对象缓存，补测27B和35B，不重跑已通过的9B。各模型内部跨卡协议一致。',
        'r4的27B完整通过；35B同卡16响应0差异，随后执行器重建因遗漏static_all_moe_layers登记而断言失败。',
        'r5恢复同一模型的MoE层名字列表，只重测35B；这项修复不影响没有MoE层的9B/27B。',
        '未定位FlashInfer内部的具体失败原因，不能声称只是硬件差异。']
    for failure in failures:
        if not failure['responses']:
            continue
        model = failure['model']
        previous = read(Path(failure['run']) / model / 'references.json')
        current_run = selected[model][0]
        current = read(current_run / model / 'references.json')
        deltas = [dict(case=case, **difference(previous[case], current[case])) for case in previous]
        assert all(not d['input_changed'] for d in deltas)
        changed = [d for d in deltas if d['tokens_changed']]
        process_comparisons.append(dict(model=model, previous_run=failure['run'], current_run=str(current_run),
                                        cases=len(deltas), differences=changed))
        lines += ['', f'附加历史启动间比较：{model} 两次首轮参考有 {len(changed)}/{len(deltas)} 组完整token不同，输入与输入token哈希相同。',
            '两次进程历史与定制加载器修复版本不同，这是非单变量对照，不能把差异单独归因于PID；也不能把本轮同PID通过推广为跨进程保证。']
        lines.append('')
        for d in changed:
            lines.append(f'- {d["case"]}：首次差异为第 {d["first_difference_1based"]} 个输出token。')
    lines += ['', '生成计时含离线请求预处理；初始化含权重装载/搬移与执行状态初始化，不含阶段末CPU搬移。不是全集吞吐估计。',
        '参数校验为每个参数抽样64个元素，不是全权重逐字节哈希；实际 forward 审计覆盖每个已返回请求。',
        '没有评估正确率、Judge、完整MVAgent、多请求并发、跨机器；未进行单变量受控的重启实验。',
        '这不是保持原KV/CUDA执行状态的在线热迁移，也未单变量证明保留PID就是一致性的原因。',
        '有限样本通过不能保证任意输入逐token一致。', '', 'GPU清单：', '', '```', manifest['gpu_inventory'].strip(), '```']
    args.output.mkdir(parents=True, exist_ok=True)
    provenance = {}
    for model in selected:
        weights = Path('/weights/Qwen3.5-' + model)
        metadata = {str(p.relative_to(weights)): p.read_text() for p in weights.glob('.cache/huggingface/download/*.metadata')}
        revisions = sorted({text.splitlines()[0] for text in metadata.values()})
        assert len(revisions) == 1
        provenance[model] = dict(revisions=revisions, download_metadata=metadata,
            config_sha256={name: hashlib.sha256((weights / name).read_bytes()).hexdigest()
                           for name in ['config.json', 'model.safetensors.index.json']},
            weight_file_sizes={p.name: p.stat().st_size for p in weights.glob('*.safetensors')})
    save(args.output / 'weight_provenance.json', provenance)
    save(args.output / 'failed_attempts.json', failures)
    save(args.output / 'historical_process_comparisons.json', process_comparisons)
    save(args.output / 'installed_packages.json', {d.metadata['Name']: d.version for d in importlib.metadata.distributions()})
    save(args.output / 'metrics.json', metrics)
    save(args.output / 'counterexamples.json', counterexamples)
    (args.output / 'report_source.py').write_bytes(Path(__file__).read_bytes())
    report = '\n'.join(lines) + '\n'
    (args.output / 'report.md').write_text(report)
    print(json.dumps(dict(models=len(metrics), responses=sum(m['responses'] for m in metrics),
                         differences=len(counterexamples), report_sha256=hashlib.sha256(report.encode()).hexdigest())))


if __name__ == '__main__':
    main()
