#!/usr/bin/env python3
"""Recount TP comparisons from raw records on the Modal runs volume."""
import argparse
from collections import Counter
import json
from pathlib import Path

from benchmark_qwen35_fp8 import save
from benchmark_vllm_repro_tp import config_for
from confirm_single_process_gpu import difference


def read(path):
    return json.loads(path.read_text())


def throughput_window(phases):
    seconds = max(p['ended'] for p in phases) - min(p['started'] for p in phases)
    requests = sum(p['responses'] for p in phases)
    return dict(seconds=seconds, requests=requests, requests_per_minute=requests/seconds*60)


def audit_e2e(root):
    manifest, summary = read(root / 'manifest.json'), read(root / 'summary.json')
    base = read(Path(manifest['source']) / 'manifest.json')['config']
    assert manifest['config'] == config_for(base, manifest['tp'], manifest.get('executor', 'mp'))
    workers = read(root / 'workers.json')
    refs = read(Path(manifest['reference']) / 'references.json') if manifest['reference'] else {}
    rows, changes, comparisons = [], [], 0
    for path in sorted(root.glob('raw_*.jsonl')):
        for line in path.read_text().splitlines():
            row = json.loads(line)
            assert [w['identity'] for w in row['worker_forwards']] == workers
            assert all(w['calls'] > 0 for w in row['worker_forwards'])
            if row['case'] in refs:
                comparisons += 1
                delta = difference(refs[row['case']], row)
                if delta['input_changed'] or delta['tokens_changed']:
                    changes.append(dict(case=row['case'], repeat=row['repeat'], **delta))
            else:
                refs[row['case']] = row
            rows.append(row)
    assert len(rows) == summary['responses'] and len(changes) == summary['differences']
    assert summary['stable'] == (not changes and summary['error'] is None)
    warm = [r for r in rows if r['repeat'] > 0]
    if manifest.get('executor') == 'external_launcher':
        for rank in range(1, 8):
            replica = root / f'rank{rank}'
            other = [json.loads(line) for path in sorted(replica.glob('raw_*.jsonl'))
                     for line in path.read_text().splitlines()]
            assert len(other) == len(rows)
            assert all(all(a[k] == b[k] for k in ['case', 'repeat', 'input_sha256', 'prompt_sha256', 'token_ids'])
                       for a, b in zip(rows, other)), f'Rank {rank} differs from rank 0'
    return dict(root=str(root), model=manifest['model'], tp=manifest['tp'],
        responses=len(rows), comparisons=comparisons, differences=changes,
        input_differences=sum(d['input_changed'] for d in changes),
        stable=summary['stable'], error=summary['error'],
        warm_mean_seconds=sum(r['seconds'] for r in warm)/len(warm) if warm else None,
        load_seconds=summary['load_seconds'], passes=summary['passes'],
        finish_reasons=dict(Counter(r['finish_reason'] for r in rows)),
        output_tokens=[min(len(r['token_ids']) for r in rows), max(len(r['token_ids']) for r in rows)],
        max_prompt_tokens=max(r['prompt_tokens'] for r in rows),
        actual_example={k: rows[0][k] for k in ['case', 'text', 'token_ids']})


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path)
    p.add_argument('--self-check', action='store_true')
    args = p.parse_args()
    if args.self_check:
        # Two replicas overlap their round boundaries: summing round spans double-counts time.
        phases = [dict(started=a, ended=b, responses=8) for a, b in [(0,10),(10,20),(0,15),(15,30)]]
        assert throughput_window(phases) == dict(seconds=30, requests=32, requests_per_minute=64)
        print('Overlapping replica rounds use one actual wall-clock window: passed')
        return
    assert str(args.output).startswith('/runs/')
    e2e, failures = [], []
    for root in sorted(Path('/runs/devbox').glob('tp_compare_*_tp*_20261011')):
        if not (root / 'summary.json').exists():
            continue
        manifest, summary = read(root / 'manifest.json'), read(root / 'summary.json')
        if summary['error']:
            failures.append(dict(root=str(root), error=summary['error']))
        else:
            assert manifest['workload'] == 'e2e'
            e2e.append(audit_e2e(root))
    pools, cross_layout = [], []
    for model in ['9B', '27B', '35B-A3B']:
        rows = [r for r in e2e if r['model'] == model and '_pool' in r['root']]
        if len(rows) == 8:
            periods = []
            for repeat in [1, 2]:
                phases = [next(s for s in r['passes'] if s['repeat'] == repeat) for r in rows]
                seconds = max(s['ended'] for s in phases)-min(s['started'] for s in phases)
                periods.append(dict(repeat=repeat, seconds=seconds,
                    requests=sum(s['responses'] for s in phases),
                    requests_per_minute=sum(s['responses'] for s in phases)/seconds*60))
            warm = [s for r in rows for s in r['passes'] if s['repeat'] > 0]
            all_rounds = [s for r in rows for s in r['passes']]
            pools.append(dict(model=model, stable=all(r['stable'] for r in rows), periods=periods,
                **throughput_window(warm), all_rounds=throughput_window(all_rounds)))
        one = next((r for r in e2e if r['model'] == model and '_single_' in r['root']), None)
        eight = next((r for r in e2e if r['model'] == model and '_tp8_ext_p1_' in r['root']), None)
        if one and eight:
            a, b = read(Path(one['root'])/'references.json'), read(Path(eight['root'])/'references.json')
            assert a.keys() == b.keys()
            assert all(a[k]['input_sha256'] == b[k]['input_sha256'] and
                       a[k]['prompt_sha256'] == b[k]['prompt_sha256'] for k in a)
            cross_layout.append(dict(model=model, questions=len(a),
                differences=[dict(case=k, **difference(a[k], b[k])) for k in a if a[k]['token_ids'] != b[k]['token_ids']]))
    data = dict(e2e=e2e, failures=failures, pools=pools, cross_layout=cross_layout)
    save(args.output / 'audit.json', data)
    lines = ['# FlashInfer BF16 TP1/TP8 原始记录复核', '',
        'H10080GB；配置仅改变TP及必要的uni/mp/external_launcher执行器；不正确率、不Judge。',
        'E2E为8个冻结历史图片请求，非独立测试集；每次重新推理，不计视频重新解码。', '',
        '| 模型/运行 | 响应 | 配对比较 | 差异 | 输入差异 | 后两轮平均秒/请求 |',
        '|---|---:|---:|---:|---:|---:|']
    for row in e2e:
        lines.append(f"| {Path(row['root']).name} | {row['responses']} | {row['comparisons']} | {len(row['differences'])} | {row['input_differences']} | {row['warm_mean_seconds']:.3f} |")
    lines += ['', '## 八独立副本实测', '']
    for row in pools:
        lines.append(f"- {row['model']}: {row['requests_per_minute']:.2f} 请求/min，全部副本重复检查通过={row['stable']}。")
    lines += ['', '## 相同八卡预算的速度', '',
        '| 模型 | TP1单卡秒/请求 | TP8秒/请求 | 八独立TP1请求/min | TP8组请求/min | 八独立副本/TP8吞吐 |',
        '|---|---:|---:|---:|---:|---:|']
    for model in ['9B', '27B', '35B-A3B']:
        one = next((r for r in e2e if r['model'] == model and '_single_' in r['root']), None)
        group = [r for r in e2e if r['model'] == model and r['tp'] == 8]
        pool = next((r for r in pools if r['model'] == model), None)
        if one is None or pool is None:
            continue
        phases = [p for r in group for p in r['passes'] if p['repeat'] > 0]
        count = sum(p['responses'] for p in phases)
        latency = sum(p['inference_seconds'] for p in phases)/count if count else None
        rate = count/sum(p['seconds'] for p in phases)*60 if count else None
        cells = [model, f"{one['warm_mean_seconds']:.3f}", f'{latency:.3f}' if latency else '无有效响应',
                 f"{pool['requests_per_minute']:.3f}", f'{rate:.3f}' if rate else '无有效响应',
                 f"{pool['requests_per_minute']/rate:.3f}×" if rate else '不可比较']
        lines.append('| ' + ' | '.join(cells) + ' |')
    lines += ['', '加载/首次处理另计，速度使用后两轮；副本吞吐用整个实际墙钟窗口。',
              '输出长度可能随TP改变；请求按原EOS/输出上限结束，不是固定token数的内核比较。', '',
              '## 不同TP之间的输出变化', '']
    for row in cross_layout:
        lines.append(f"- {row['model']}: {len(row['differences'])}/{row['questions']} 输入的完整输出token不同；请求与prompt token哈希相同。")
    lines += ['', '## TP1输出结束方式', '']
    for model in ['9B', '27B', '35B-A3B']:
        reasons = Counter()
        for row in e2e:
            if row['model'] == model and row['tp'] == 1:
                reasons.update(row['finish_reasons'])
        lines.append(f'- {model}: {dict(reasons)}；达到上限的比较只覆盖实际生成序列。')
    lines += ['', '## 失败与限制', '']
    for row in failures:
        lines.append(f"- {row['root']}: {row['error']}")
    lines.append('不同TP之间的输出变化与配置内部重复失败分开；有限面板通过不是任意输入/其他硬件或版本的保证。')
    (args.output / 'report.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps(dict(e2e_runs=len(e2e), failures=failures, pools=pools)))


if __name__ == '__main__':
    main()
