#!/usr/bin/env python3
"""Audit the complete eight-replica MVAgent experiment and its GPU rotation."""
import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys

from benchmark_qwen35_fp8 import save
from confirm_single_process_mvagent import compare_rollouts
from confirm_bf16_mvagent import token_trace


def read(path):
    return json.loads(path.read_text())


def gpu_uuids(inventory):
    return {row['uuid'].strip() for row in csv.DictReader(io.StringIO(inventory), skipinitialspace=True)}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--experiment', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    args = p.parse_args()
    assert all(p.is_relative_to('/runs') for p in [args.experiment, args.output])
    root = args.experiment
    assert read(root / 'progress.json')['phase'] == 'finished'
    manifest = read(root / 'manifest.json')
    for file, key in [('panel/inputs.json', 'panel_sha256'), ('source.py', 'source_sha256'),
                      ('source.tar.gz', 'snapshot_sha256')]:
        with (root / file).open('rb') as handle:
            assert hashlib.file_digest(handle, 'sha256').hexdigest() == manifest[key]
    cases = read(root / 'panel/inputs.json')
    count = manifest['case_count']
    assert len(cases) == len({c['name'] for c in cases}) == count
    results = read(root / 'results.json')
    assert len(results) == 16*len(manifest['models']) and all(r['error'] is None and r['exit_code'] == 0 for r in results)
    cmd = [sys.executable, str(Path(__file__).with_name('report_vllm_repro_fix.py')), '--output', str(args.output / 'raw_audit')]
    for model in manifest['models']:
        for phase in ['p1', 'p2']:
            for rank in range(8):
                run = root / model / f'{phase}_rank{rank}'
                current = read(run / 'manifest.json')
                assert current['cuda_visible_devices'] == str(rank if phase == 'p1' else (rank+1) % 8)
                assert current['scoring_requested'] is False
                assert read(run / 'inputs.json') == read(root / 'panel' / f'shard{rank}.json')
                if phase == 'p2':
                    first = read(root / model / f'p1_rank{rank}/manifest.json')
                    assert first['pid'] != current['pid']
                    assert first['gpu_inventory'] == current['gpu_inventory']
                cmd += ['--run', str(run)]
    subprocess.run(cmd, check=True)
    metrics = read(args.output / 'raw_audit/metrics.json')
    assert all(m['rollouts'] == 4*count and m['comparisons'] == 3*count and len(m['cases']) == count for m in metrics)
    historical = []
    for m in metrics:
        tag = {'9B': '9b', '27B': '27b', '35B-A3B': '35b'}[m['model']]
        references = read(root / m['model'] / 'references.json')
        for suffix in ['p1', 'extra']:
            old = Path(f'/runs/devbox/repro_agent_flashinfer_{tag}_20261011_{suffix}')
            previous = read(old / 'manifest.json')
            compatible = previous['config'] == m['config'] and all(
                m['versions'][key] == value for key, value in previous['versions'].items())
            old_weights = (old / m['model'] / 'weight_environment_metadata.json').read_bytes()
            new_weights = (root / m['model'] / 'p1_rank0' / m['model'] / 'weight_environment_metadata.json').read_bytes()
            compatible = compatible and old_weights == new_weights
            if not compatible:
                historical.append(dict(model=m['model'], source=str(old), compatible=False))
                continue
            seen = set()
            for path in sorted((old / m['model'] / 'A_initial_repeat0/records').glob('*/result.json')):
                before = read(path)
                assert before['error'] is None and before['case'] not in seen
                seen.add(before['case'])
                current = read(Path(references[before['case']]['path']))
                delta = compare_rollouts(before, current)
                a, b = token_trace(before['events']), token_trace(current['events'])
                historical.append(dict(model=m['model'], source=str(path), case=before['case'], compatible=True,
                    paired_calls=sum(min(len(v), len(b.get(k, []))) for k, v in a.items()),
                    gpu_uuid_overlap=sorted(gpu_uuids(previous['gpu_inventory']) &
                        gpu_uuids(read(root / m['model'] / 'p1_rank0/manifest.json')['gpu_inventory'])),
                    differences=delta))
            assert seen == {r['name'] for r in read(old / 'inputs.json')}
    save(args.output / 'historical_comparison.json', historical)
    lines = ['# 八个独立副本的完整 MVAgent 重复性验收', '',
        f'{count}道开发题，每模型四遍，共{4*count*len(metrics)}条完整轨迹；不评正确率、不调用Judge。',
        '8×H100 80GB，每卡独立TP1/DP1、模型请求并发1；三模型统一BF16，标准加载器、同步inproc/eager、FlashInfer GDN prefill。',
        '每题内部固定一个副本；每分片先在同一进程中乱序跑两遍，再完整重启并转到下一张卡跑两遍；每题后三遍都与首次结果比较。',
        'seed0、temperature0、thinking关闭，context131072、prefill32768、mem0.94、expandable segments，prefix/MM缓存关闭；正常解码KV保留。RMSNorm固定native，配置与E2E v2相同。',
        f'空skill，Global/Video各{manifest["max_steps"]}步，每调用2048输出token/512帧；Video CPU并发2，实际模型调用串行。', '',
        f'| 模型 | 完整轨迹 | 模型调用 | 配对调用比较 | 不一致轨迹/{3*count} | 8卡吞吐（轨迹/分钟） | 平均单题秒数 |',
        '|---|---:|---:|---:|---:|---:|---:|']
    performance = []
    for m in metrics:
        windows = []
        question_seconds = []
        for phase in ['p1', 'p2']:
            runs = [r for r in m['runs'] if Path(r['root']).name.startswith(phase + '_')]
            assert len(runs) == 8
            windows.append(max(r['ended_monotonic'] for r in runs)-min(r['started_monotonic'] for r in runs))
            for r in runs:
                summary = read(Path(r['root']) / 'summary.json')
                question_seconds.extend(row['seconds'] for stage in summary['passes'] for row in stage['rows'])
        speed = m['rollouts'] / sum(windows) * 60
        mean = sum(question_seconds) / len(question_seconds)
        performance.append(dict(model=m['model'], windows_seconds=windows, trajectories_per_minute=speed,
                                mean_question_seconds=mean))
        lines.append(f'| {m["model"]} | {m["rollouts"]} | {m["calls"]} | {m["repeated_calls"]} | {m["differences"]} | {speed:.3f} | {mean:.2f} |')
    lines += ['', '吞吐按两个阶段各自八副本实际墙钟窗口计算，包含Agent视频准备/动作/推理及分片尾部空闲，排除权重加载、进程退出和评分。',
        '缓存冷暖及静态分片影响速度；这些均衡题型开发样例不能直接当作全量benchmark平均耗时。', '', '## 长轨迹、错误与输出示例', '']
    for m in metrics:
        lines += [f'- {m["model"]}：每轨迹{min(m["call_lengths"])}–{max(m["call_lengths"])}次模型调用，'
            f'{min(m["output_lengths"])}–{max(m["output_lengths"])}累计输出token，单次最大输入{max(m["prompt_lengths"])} token；'
            f'结束原因{m["finishes"]}；结构化校验失败{m["event_counts"].get("structured_invalid", 0)}，模型错误{m["event_counts"].get("model_error", 0)}。']
        reference = read(root / m['model'] / 'references.json')
        example_id = 'cvbench:664' if 'cvbench:664' in reference else sorted(reference)[0]
        example = read(Path(reference[example_id]['path']))
        lines.append(f'  实际样例{example_id}最终答案：`{example["result"]["answer"]}`（仅展示输出，不判断正确率）。')
    lines += ['', '## 与此前独立GPU分配留存样例的附加对照', '',
        '另将本次首遍与历史FlashInfer核心六题及额外六题的首遍比较；不新增推理。先核对保存的推理配置、共同软件版本字段与权重元数据，再逐调用比较输入哈希、token和语义轨迹。',
        '历史manifest未记录全部新版本字段；这是历史复核，不能替代完整控制所有环境变量的跨主机实验。', '',
        '| 模型 | 可比轨迹 | 配对调用 | GPU UUID清单无交集的轨迹 | 不一致轨迹 |', '|---|---:|---:|---:|---:|']
    for m in metrics:
        pairs = [r for r in historical if r['model'] == m['model'] and r['compatible']]
        changed = sum(bool(r['differences']['calls'] or r['differences']['result_fields']) for r in pairs)
        lines.append(f'| {m["model"]} | {len(pairs)} | {sum(r["paired_calls"] for r in pairs)} | '
                     f'{sum(not r["gpu_uuid_overlap"] for r in pairs)} | {changed} |')
        incompatible = [r['source'] for r in historical if r['model'] == m['model'] and not r['compatible']]
        if incompatible:
            lines.append(f'未满足配置/版本/权重元数据可比条件：{incompatible}。')
    lines += ['', '## 样例与边界', '', '| Benchmark | 原生题型 | 样例 | 历史调用数 |', '|---|---|---|---:|']
    for c in sorted(cases, key=lambda c: (c['dataset'], c['native_task'])):
        lines.append(f'| {c["dataset"]} | {c["native_task"]} | {c["name"]} | {c["old_calls"]} |')
    lines += ['', f'原始记录：`{root}`；完整原始审计：`{args.output / "raw_audit"}`。',
        f'源码快照SHA256：`{manifest["snapshot_sha256"]}`；面板SHA256：`{manifest["panel_sha256"]}`。',
        '逐调用检查请求字节与prompt token哈希、完整输出token、真实forward进程/GPU身份及完整语义轨迹。独立VideoAgent调用按agent/video/decision配对，排除墙钟耗时。',
        '已测范围是同一台八卡主机上的四次完整运行、两次独立进程生命周期；不是任意输入、任意硬件/版本或无限重复的数学保证。',
        '仍使用原始MVAgent提示、视频处理、结构化验证和动作逻辑，实验仅以队列替换HTTP传输；正式HTTP服务、任意跨主机环境、一道题内逐调用轮换副本、进程内热迁卡、非空skill及更高并发未由本轮验收。']
    report = '\n'.join(lines) + '\n'
    (args.output / 'report.md').write_text(report)
    (args.output / 'source.py').write_bytes(Path(__file__).read_bytes())
    save(args.output / 'performance.json', performance)
    print(json.dumps(dict(rollouts=sum(m['rollouts'] for m in metrics), calls=sum(m['calls'] for m in metrics),
        differences=sum(m['differences'] for m in metrics), report_sha256=hashlib.sha256(report.encode()).hexdigest())))


if __name__ == '__main__':
    main()
