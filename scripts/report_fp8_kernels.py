#!/usr/bin/env python3
"""Report paired FP8 kernel probes and complete evaluation passes on Modal."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import statistics


def read(path):
    return json.loads(path.read_text())


def records(root, pattern):
    for path in sorted(root.glob(pattern)):
        with path.open() as handle:
            for line in handle:
                yield json.loads(line)


def metric_totals(root, label):
    result = defaultdict(float)
    for path in root.glob(f'metrics_{label}_*.txt'):
        for line in path.read_text().splitlines():
            if line.startswith('#') or not line:
                continue
            name = line.split('{', 1)[0]
            if name.endswith(('_sum', '_count')):
                result[name] += float(line.rsplit(' ', 1)[-1])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--screens', nargs='*', type=Path, default=[])
    parser.add_argument('--evaluations', nargs='*', type=Path, default=[])
    parser.add_argument('--confirmations', nargs='*', type=Path, default=[])
    parser.add_argument('--restricted', nargs='*', type=Path, default=[],
                        help='Fixed-physical-routing diagnostics; never merge with cross-replica validation')
    parser.add_argument('--interrupted', nargs='*', type=Path, default=[])
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not str(args.output).startswith('/runs/'):
        raise SystemExit('Results must stay on the runs volume')
    args.output.mkdir(parents=True, exist_ok=True)
    screens, evaluations, confirmations, restricted = [], [], [], []
    for root in args.screens:
        manifest = read(root / 'manifest.json')
        for summary in read(root / 'summary.json'):
            rows = list(records(root / summary['variant'], 'restart*/records.jsonl'))
            groups = defaultdict(list)
            for row in rows:
                if row['phase'] == 'warmup' or (row['phase'] == 'measure' and row['pass'].startswith('c1_')):
                    groups[(row['phase'], row['case'])].append(row)
            measurements = []
            for (phase, case), group in sorted(groups.items()):
                measurements.append({'phase': phase, 'case': case, 'samples': len(group),
                    'output_lengths': sorted({r['output_tokens'] for r in group}),
                    'seconds': statistics.median(r['seconds'] for r in group),
                    'ttft_seconds': statistics.median(r['ttft_seconds'] for r in group),
                    'decode_tokens_per_second': statistics.median(r['decode_tokens_per_second'] for r in group),
                    'request_hashes': sorted({r['request_sha256'] for r in group}),
                    'prompt_hashes': sorted({r['prompt_token_ids_sha256'] for r in group})})
            log = root / summary['variant'] / 'restart0/server_0.log'
            evidence = []
            if log.exists():
                for line in log.read_text(errors='replace').splitlines():
                    if re.search(r'Model loading took|Available KV cache memory|Using .*([Kk]ernel|backend)|Selected .*Kernel|FP8.*backend', line):
                        evidence.append(line[-500:])
            screens.append({**summary, 'root': str(root), 'model': manifest['arguments'].get('model_size', '35B-A3B'),
                            'measurements': measurements, 'kernel_evidence': evidence})
    for root in args.evaluations:
        manifest = read(root / 'manifest.json')
        for summary in read(root / 'summary.json'):
            row = {**summary, 'root': str(root), 'model': manifest['arguments'].get('model_size', '35B-A3B'),
                                'input_mode': 'media_uuid' if manifest['arguments'].get('media_uuids') else 'prepared',
                                'input_preparation_seconds': manifest['input_preparation_seconds'],
                                'prepared_wire_bytes': manifest.get('prepared_wire_bytes'),
                                'prepared_cached_wire_bytes': manifest.get('prepared_cached_wire_bytes'),
                                'arguments': manifest['arguments']}
            previous = {}
            for p in row['passes']:
                directory = root / row['variant'] / f"restart{p['restart']}"
                before = previous[p['restart']] if p['restart'] in previous else metric_totals(directory, 'start')
                after = metric_totals(directory, f"after_{p['name']}")
                phases = {}
                for phase in ['queue', 'prefill', 'decode', 'inference']:
                    prefix = f'vllm:request_{phase}_time_seconds'
                    count = after.get(prefix + '_count', 0) - before.get(prefix + '_count', 0)
                    total = after.get(prefix + '_sum', 0) - before.get(prefix + '_sum', 0)
                    if count == p['samples'] and count > 0:
                        phases[phase] = total / count
                p['server_seconds_per_request'] = phases
                previous[p['restart']] = after
            evaluations.append(row)
    for root in [*args.confirmations, *args.restricted]:
        manifest = read(root / 'manifest.json')
        if bool(manifest['arguments'].get('fixed_routing')) != (root in args.restricted):
            raise ValueError(f'Incorrect reproducibility scope for {root}')
        for summary in read(root / 'summary.json'):
            rows = list(records(root / summary['variant'], 'restart*/records.jsonl'))
            inputs = defaultdict(lambda: defaultdict(set))
            for record in rows:
                for field in ['request_sha256', 'prompt_token_ids_sha256', 'output_tokens']:
                    inputs[record['case']][field].add(record[field])
            target = restricted if root in args.restricted else confirmations
            target.append({**summary, 'root': str(root), 'model': manifest['arguments'].get('model_size', '35B-A3B'),
                'arguments': manifest['arguments'], 'input_sha256': manifest['input_sha256'],
                'gpu_inventory': manifest['gpu_inventory'],
                'case_audit': {case: {k: sorted(v) for k, v in fields.items()} for case, fields in inputs.items()},
                'output_lengths': [min((r['output_tokens'] for r in rows), default=0), max((r['output_tokens'] for r in rows), default=0)],
                'finish_reasons': dict(Counter(r['finish_reason'] for r in rows))})
    all_rows = [*screens, *evaluations, *confirmations, *restricted]
    totals = {field: sum(r[field] for r in all_rows) for field in ['formal_samples', 'warmup_samples']}
    result = {'screens': screens, 'evaluations': evaluations, 'confirmations': confirmations,
              'restricted': restricted, 'totals': totals}
    lines = ['# FP8 内核与配对加速实验', '',
             '8×H100 80GB，vLLM0.19.1；每服务TP=1、DP=1。temperature=0、seed=0、thinking关闭。',
             '首台机器05:04前后被平台抢占，之后一次恢复；每个速度比仅使用同一allocation内的配对，不能跨机器拼接速度。',
             '目标是在已测范围内逐token重复一致，再比较速度。每个配置有自己的参考；跨精度/内核不要求输出相同。',
             '9B FP8使用已下载的社区lovedheart checkpoint；27B/35B FP8为官方Qwen。冻结来源与revision见各轮weight_manifest.json。', '',
             f"本轮合计{totals['formal_samples']}次正式响应、{totals['warmup_samples']}次参考响应；重复调用不计作独立题数。", '',
             '## 内核筛选', '',
             '默认固定1024输出token，消除正常EOS回答长度不同的影响；输入为既有文本及32/128/512帧开发探针。',
             '配置副本数见表。不同GPU配置并行且共享CPU，速率仅用于该配置，不乘8推断整机吞吐。TTFT是客户端观测值，包含请求处理，并非纯GPU prefill时间。',
             'Marlin是FP8权重的W8A16路径；它的收益不能当成原生W8A8 Tensor Core的加速证明。', '',
             '| 模型 | 配置 | 运行 | 副本 | 每副本并发 | 正式响应 | token差异 | 此并发通过 | 请求/min |',
             '|---|---|---|---:|---:|---:|---:|---|---:|']
    for row in screens:
        for level in row.get('levels', []):
            lines.append(f"| {row['model']} | {row['variant']} | {Path(row['root']).name} | {row['replicas']} | {level['concurrency']} | {level['samples']} | {level['mismatches']} | {level['stable']} | {level['requests_per_minute']:.2f} |")
    for row in screens:
        if row.get('error'):
            lines += ['', f"`{row['model']}/{row['variant']}`：{row['error']}。已完成且通过的C1和失败C2分别解释；启动失败为零测量。"]
    lines += ['', '### 固定长度下的配对延时', '',
              'warmup为清空prefix后的首次参考，可能包含首次形状预热，不能当成稳态GPU prefill测速；measure为C1热轮。下表比较同模型BF16与FP8候选；加速比>1代表FP8候选更快。', '',
              '| 模型 | 配置 | 阶段 | 输入 | 样本 | 请求/提示hash及输出长度相同 | 总延时加速比 | TTFT秒 | 解码token/s |',
              '|---|---|---|---|---:|---|---:|---:|---:|']
    for row in screens:
        if row['variant'].startswith('bf16_'):
            continue
        baseline_name = ('bf16_prefix_invariant_sync' if row['variant'] == 'prefix_invariant_sync' else
                         'bf16_mm_cache' if row['variant'].startswith('mm_') else 'bf16_prefix')
        baseline = next((r for r in screens if r['model'] == row['model'] and r['variant'] == baseline_name and r['root'] == row['root']), None)
        if baseline is None:
            baseline = next((r for r in screens if r['model'] == row['model'] and r['variant'] == baseline_name), None)
        if baseline is None or row is baseline:
            continue
        for item in row['measurements']:
            ref = next((r for r in baseline['measurements'] if (r['case'], r['phase']) == (item['case'], item['phase'])), None)
            if ref is None:
                continue
            matched = all(item[k] == ref[k] for k in ['request_hashes', 'prompt_hashes', 'output_lengths'])
            item['bf16_speedup'] = ref['seconds'] / item['seconds'] if matched else None
            ratio = f"{item['bf16_speedup']:.3f}" if matched else '不可比'
            lines.append(f"| {row['model']} | {row['variant']} | {item['phase']} | {item['case']} | {item['samples']} | {matched} | {ratio} | {item['ttft_seconds']:.3f} | {item['decode_tokens_per_second']:.2f} |")
    lines += ['', '## 真实评测与媒体UUID烟测', '',
              '采用此前冻结的30题CVBench开发面板（15题型各2题），512帧/448、原生max_tokens128及官方评分。',
              'prepared模式只复用请求字节，每次仍重新推理。首轮冷模型缓存单列；热轮吞吐不包含首次视频处理和模型加载。', '',
              'media_uuid模式先运行未修改的完整图片请求，再上传图片及其JPEG SHA256 UUID，之后只传UUID。三种表示的prompt token和完整输出必须一致；缓存缺失直接失败。',
              '因此UUID热请求与首次上传的HTTP字节不同，但对应同一份冻结图片/文本；同模式的重复请求字节固定。没有缓存模型答案。', '',
              '| 模型 | 配置 | 副本 | 输入模式 | 正式/冷参考 | token差异 | 全部通过 | 热题/min | 首轮题/min |',
              '|---|---|---:|---|---:|---:|---|---:|---:|']
    for row in evaluations:
        rate = f"{row['questions_per_minute']:.2f}" if row.get('questions_per_minute') else '—'
        first = row['passes'][0]['questions_per_minute'] if row['passes'] else 0
        lines.append(f"| {row['model']} | {row['variant']} | {row['arguments'].get('replicas', 8)} | {row['input_mode']} | {row['formal_samples']}/{row['warmup_samples']} | {row['mismatches']} | {row['stable']} | {rate} | {first:.2f} |")
    for model in sorted({r['model'] for r in evaluations}):
        rows = [r for r in evaluations if r['model'] == model]
        for row in rows:
            baseline = next((r for r in rows if r['variant'] == 'bf16_prefix' and r['input_mode'] == row['input_mode']), None)
            if baseline is None:
                continue
            reference = read(Path(baseline['root']) / baseline['variant'] / 'restart0/references.json')
            if row is baseline or not row['stable']:
                continue
            actual = read(Path(row['root']) / row['variant'] / 'restart0/references.json')
            common = sorted(reference.keys() & actual.keys())
            matched = bool(common) and reference.keys() == actual.keys() and all(
                all(reference[k][f] == actual[k][f] for f in ['request_sha256', 'prompt_token_ids_sha256']) for k in common)
            equal = sum(reference[k]['token_ids'] == actual[k]['token_ids'] for k in common)
            ratio = row['questions_per_minute'] / baseline['questions_per_minute']
            row['vs_bf16'] = {'speedup': ratio, 'same_inputs': matched, 'identical_outputs': equal, 'compared': len(common)}
            lines += ['', f"`{model}/{row['variant']}`相对BF16热吞吐{ratio:.3f}×；输入hash相同{matched}，跨配置输出相同{equal}/{len(common)}。"]
    lines += ['', '### 热轮服务阶段与答案长度', '',
              '以下为vLLM服务直方图的每请求均值，各阶段计数必须与本轮响应数相等。prefill包含服务端该阶段墙钟时间，不能当成纯CUDA算子剖析。',
              '开发面板准确率仅用于发现明显行为变化，非全量独立Test结论。', '',
              '| 模型 | 配置 | 题数/轮 | 输出token/题 | queue秒 | prefill秒 | decode秒 | 面板正确率 | 分层估计官方分 |',
              '|---|---|---:|---:|---:|---:|---:|---:|---:|']
    for row in evaluations:
        hot = [p for p in row['passes'] if p['name'] not in {'base_reference', 'pass0'}]
        if not hot:
            continue
        count = sum(p['samples'] for p in hot)
        phase_values = []
        for phase in ['queue', 'prefill', 'decode']:
            values = [(p['server_seconds_per_request'][phase], p['samples']) for p in hot if phase in p['server_seconds_per_request']]
            phase_values.append(f"{sum(v * n for v, n in values) / sum(n for _, n in values):.6f}" if values else '—')
        lines.append(f"| {row['model']} | {row['variant']} | {hot[0]['samples']} | {sum(p['output_tokens'] for p in hot) / count:.2f} | "
                     + ' | '.join(phase_values) + f" | {hot[0]['panel_accuracy']:.3f} | {hot[0]['estimated_official_accuracy']:.3f} |")
    lines += ['', '## 全8卡固定长度与重启复核', '',
              '固定1024输出用于控制回答长度；不是自然EOS的准确率试验。每配置单独建立参考，逐token比较所有副本、混合输入、清空prefix以及重启前后。', '',
              'BF16对照一次启动、2热轮；Marlin候选两次启动、4热轮。速度只汇总热轮，每轮每副本接收相同输入集合；按配置顺序测量，未进行跨机器随机化试验。', '',
              '| 模型 | 配置 | 正式/冷参考 | token差异 | 全部通过 | C1混合请求/min | 各热轮范围 | 输出长度范围 |',
              '|---|---|---:|---:|---|---:|---|---|']
    for row in confirmations:
        level = next((p for p in row['levels'] if p['concurrency'] == 1), None)
        rate = f"{level['requests_per_minute']:.2f}" if level else '—'
        pass_rates = [p['requests_per_minute'] for p in row['passes'] if p['phase'] == 'measure']
        spread = f"{min(pass_rates):.2f}–{max(pass_rates):.2f}" if pass_rates else '—'
        lines.append(f"| {row['model']} | {row['variant']} | {row['formal_samples']}/{row['warmup_samples']} | {row['mismatches']} | {row['stable']} | {rate} | {spread} | {row['output_lengths']} |")
        if row['error']:
            lines += ['', f"`{row['model']}/{row['variant']}`失败：{row['error']}。"]
        baseline = next((r for r in confirmations if r['model'] == row['model'] and r['variant'] == 'bf16_prefix'
                         and r['gpu_inventory'] == row['gpu_inventory']), None)
        if row['variant'].startswith('bf16_') or not row['stable'] or not baseline or not baseline['stable']:
            continue
        matched = row['input_sha256'] == baseline['input_sha256'] and row['case_audit'] == baseline['case_audit']
        ref_level = next(p for p in baseline['levels'] if p['concurrency'] == 1)
        row['vs_bf16'] = {'same_inputs_and_lengths': matched,
                          'speedup': level['requests_per_minute'] / ref_level['requests_per_minute'] if matched else None}
    for row in confirmations:
        pair = row.get('vs_bf16')
        if pair:
            lines += ['', f"`{row['model']}/{row['variant']}`配对输入与长度核对{pair['same_inputs_and_lengths']}；FP8/BF16全8卡吞吐比{pair['speedup']}。"]
    if restricted:
        lines += ['', '## 受限诊断：固定输入到固定物理GPU', '',
                  '每个冻结输入固定到一个物理副本；8组输入占8卡，每副本并发1。重启仍保持同一物理GPU及输入映射。',
                  '每卡仅一个长输入；未验证多个长输入在同卡交错的完整Agent流量。此处吞吐与4输入跨副本面板也不直接混比。',
                  '本节不验证换卡、重分配或新机器上的一致性，不能替代上面的跨副本要求；不是通过缓存答案实现重复。', '',
                  '| 模型 | 配置 | 正式/冷参考 | token差异 | 全部通过 | 请求/min |',
                  '|---|---|---:|---:|---|---:|']
        for row in restricted:
            level = next((p for p in row['levels'] if p['concurrency'] == 1), None)
            rate = f"{level['requests_per_minute']:.2f}" if level else '—'
            lines.append(f"| {row['model']} | {row['variant']} | {row['formal_samples']}/{row['warmup_samples']} | {row['mismatches']} | {row['stable']} | {rate} |")
            baseline = next((r for r in restricted if r['model'] == row['model'] and r['variant'] == 'bf16_prefix'
                             and r['gpu_inventory'] == row['gpu_inventory']), None)
            if row['error']:
                lines += ['', f"`{row['variant']}`：{row['error']}。"]
            if row['variant'].startswith('bf16_') or not row['stable'] or not baseline or not baseline['stable']:
                continue
            matched = row['input_sha256'] == baseline['input_sha256'] and row['case_audit'] == baseline['case_audit']
            ref = next(p for p in baseline['levels'] if p['concurrency'] == 1)
            row['vs_bf16_restricted'] = {'same_inputs_and_lengths': matched,
                'speedup': level['requests_per_minute'] / ref['requests_per_minute'] if matched else None}
        for row in restricted:
            if 'vs_bf16_restricted' in row:
                lines += ['', f"固定物理路由下`{row['variant']}`相对BF16：`{row['vs_bf16_restricted']}`。"]
        bf16 = next((r for r in restricted if r['variant'] == 'bf16_prefix'), None)
        fp8 = next((r for r in restricted if r['variant'] == 'prefix_marlin'), None)
        if bf16 and fp8:
            first = [[p for p in r['passes'] if p['restart'] == 0] for r in [bf16, fp8]]
            matched = bf16['input_sha256'] == fp8['input_sha256'] and bf16['case_audit'] == fp8['case_audit']
            if matched and all(group and all(p['stable'] for p in group) for group in first):
                rates = []
                for group in first:
                    hot = [p for p in group if p['phase'] == 'measure']
                    rates.append(sum(p['samples'] for p in hot) * 60 / sum(p['seconds'] for p in hot))
                fp8['first_startup_speedup'] = rates[1] / rates[0]
                lines += ['', f"仅首次驻留服务：BF16 {rates[0]:.4f}、Marlin {rates[1]:.4f}请求/min，后者{rates[1] / rates[0]:.4f}×。"
                          '这是受限阶段的速度，不能作为通过完整重启协议的成绩。']
            for p in fp8['passes']:
                if p['mismatches']:
                    lines += ['', f"Marlin restart={p['restart']} `{p['name']}`差异：`{p['mismatches']}`。"]
    lines += ['', '### 实际模型输出示例', '']
    for row in evaluations:
        example = next(records(Path(row['root']) / row['variant'], 'restart0/raw.jsonl'), None)
        if example:
            request = example['request']
            lines.append(f"- `{row['model']}/{row['variant']}`，`{example['sample_id']}`：输出 `{example['output'].strip()}`；"
                         f"token IDs `{request['token_ids']}`。全序列复核结果见上表，完整原始响应留volume。")
    lines += ['', '## 部署限制与结论', '',
              '- 所测布局为独立TP1/DP1服务、每副本请求并发1。固定路由提高缓存复用；C1和固定路由本身不能保证确定性，较大请求并发也已出现反例。',
              '- 9B Marlin虽通过短答案面板，但固定1024输出全8卡冷text有1/8跨副本差异，首次差异索引101（第102个token），不推荐为通用长输出方案。27B默认BF16为7/8不同、Marlin为5/8不同，均未进入正式长输出吞吐轮；不能只归因于FP8。',
              '- Marlin由`VLLM_TEST_FORCE_FP8_MARLIN=1`选择。这个测试环境开关属于固定vLLM0.19.1协议，升级后须重验；不得把W8A16收益当成原生W8A8峰值证明。',
              '- Marlin明确不支持batch-invariant。最后的确定性配对使用原生FP8，与BF16一同开启batch-invariant、FLASH_ATTN和同步调度，实际结果见筛选表。',
              '- 固定GPU/题目路由也未解决重启复现：27B Marlin首次服务48响应一致且约快47%，同卡服务重启后3/8输入改变，淘汰为完整可复现方案。',
              '- 35B-A3B淘汰MoE Marlin：启用或禁用prefix都观察到C1输出差异。仅线性层Marlin、MoE保留Triton通过单卡24次响应，但与同轮BF16均约10.59请求/min，未见加速；未升级为全8卡推荐方案。当前未找到稳定且明确快于BF16的35B新内核。',
              '- 媒体UUID只引用固定JPEG内容；服务重启或缓存驱逐后重新上传。缓存缺失时报错，不以缓存答案代替推理。',
              '- 本轮没有自动改动正式评测或Actor配置。保持模型、版本、内核、缓存模式与生成参数固定；配置自身重复一致不代表跨配置答案相同。', '']
    if args.interrupted:
        lines += ['## 平台中断', '',
                  '05:04前后原Sandbox `sb-nLeByRHkCltvSgCASJ6aql`被平台终止；app日志明确为“Container terminated due to preemption”。',
                  '恢复Sandbox `sb-cdO8VA9S2yfV1KRTK4s9Sr`于05:05:35创建，H100!:8、0.58h，截止05:40:23。',
                  'GPU Sandbox可能被抢占，见[Modal说明](https://modal.com/docs/guide/preemption)。该中断不能算模型失败或已完成测量。', '']
        for root in args.interrupted:
            count = sum(1 for _ in records(root, '**/records.jsonl'))
            lines.append(f'- `{root}`：已落盘响应{count}，无完整summary，不纳入速度配对。')
    lines += ['', '## 实际选用内核与显存日志', '']
    for row in screens:
        if row['kernel_evidence']:
            lines += [f"### {row['model']}/{row['variant']}", '', '```text', *row['kernel_evidence'], '```', '']
    lines += ['## 范围与留档', '',
              '有限开发输入和重复次数不能保证任意输入、其他硬件/版本或长期运行确定；完整MVAgent/skill循环与全量准确率不在本轮结论内。',
              '原始token IDs、模型文本、请求hash、逐轮评分、日志、源码与权重来源均保存在runs volume wxu-evolve-agent-runs-20261006。',
              '本轮无skill库或Judge，使用冻结输入hash界定开发面板。固定长度探针不是准确率评测。', '',
              '源码依据：[vLLM FP8内核选择](https://github.com/vllm-project/vllm/blob/v0.19.1/vllm/model_executor/layers/fused_moe/oracle/fp8.py)。', '']
    for root in [*args.screens, *args.evaluations, *args.confirmations, *args.restricted, *args.interrupted]:
        manifest = read(root / 'manifest.json')
        lines += [f'- `{root}`；commit `{manifest.get("git_commit")}`；版本 `{manifest.get("versions")}`；',
                  f'  参数 `{json.dumps(manifest["arguments"], ensure_ascii=False, sort_keys=True)}`；',
                  f'  源码hash `{json.dumps(manifest.get("sources_sha256"), sort_keys=True)}`。']
    overview = ['', '## 主要结果', '',
                '| 模型 | FP8候选/BF16：固定1024输出吞吐比 | 真实短答案热吞吐比 |',
                '|---|---:|---:|']
    for model in ['9B', '27B', '35B-A3B']:
        long_row = next((r for r in confirmations if r['model'] == model and 'vs_bf16' in r), None)
        short_row = next((r for r in evaluations if r['model'] == model and 'vs_bf16' in r), None)
        long_ratio = long_row['vs_bf16']['speedup'] if long_row else None
        short_ratio = short_row['vs_bf16']['speedup'] if short_row else None
        failed = any(r['model'] == model and not r['stable'] for r in confirmations)
        long_label = f'{long_ratio:.3f}×' if long_ratio else ('未通过全卡一致性' if failed else '筛选未见优势')
        overview.append(f"| {model} | {long_label} | {f'{short_ratio:.3f}×' if short_ratio else '未完成合格配对'} |")
    overview += ['', '比值>1表示FP8候选更快。只纳入全部复现检查通过的配置；不同任务的速率不能直接混用。', '']
    lines[1:1] = overview
    (args.output / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
    (args.output / 'report.md').write_text('\n'.join(lines) + '\n')
    source = Path(__file__).read_bytes()
    (args.output / Path(__file__).name).write_bytes(source)
    print(json.dumps({'screens': len(screens), 'evaluations': len(evaluations), 'confirmations': len(confirmations),
                      'report_sha256': hashlib.sha256((args.output / 'report.md').read_bytes()).hexdigest()}))


if __name__ == '__main__':
    main()
