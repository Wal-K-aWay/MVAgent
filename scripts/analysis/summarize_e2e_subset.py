"""Summarize saved direct E2E predictions on the fixed development split; no inference."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'scripts')]
from answer_parsing import extract_final_choice_with_method
from skill_evolution.infra.benchmarks.catalog import load_multibench_records
from skill_evolution.infra.benchmarks.aggregation import HierarchicalScoreAggregator


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=ROOT / 'configs/skill_evolution/splits/multibench_train300_val200_seed20260908.json')
    parser.add_argument('--output', type=Path, default=ROOT / 'outputs/analysis/20260908_e2e_baseline_train300_val200')
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    membership = {r['sample_id']: r['split'] for r in manifest['samples']}
    assert len(membership) == len(manifest['samples']) == 500
    assert list(membership.values()).count('train') == 300
    assert list(membership.values()).count('eval') == 200
    groups = {split: {r['group_id'] for r in manifest['samples'] if r['split'] == split} for split in ['train', 'eval']}
    assert groups['train'].isdisjoint(groups['eval'])
    records = load_multibench_records('/home/kww/datasets/Multi-Video', list(membership))
    aggregator = HierarchicalScoreAggregator(
        dataset_of={sid: r.dataset for sid, r in records.items()},
        category_of={sid: r.native_task for sid, r in records.items()},
        sample_weights={sid: r.sample_weight for sid, r in records.items()},
    )
    hashes = {}

    def read(path):
        data = path.read_bytes()
        hashes[str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)] = hashlib.sha256(data).hexdigest()
        rows = [json.loads(line) for line in data.splitlines() if line.strip()] if path.suffix == '.jsonl' else json.loads(data)
        index = {}
        for row in rows:
            key = str(row['id'])
            if key in index:
                assert row.get('error') and index[key].get('error'), f'Duplicate predictions: {path}/{key}'
            index[key] = row
        return index

    rows, summary = [], {}
    for model in ['9b', '27b', '35b_a3b']:
        base = ROOT / f'outputs/e2e/qwen3_5_{model}_e2e'
        paths = {'cvbench': base / 'cvbench/raw/cvbench_predictions.jsonl', 'mvu_eval': base / 'mvu_eval/raw/mvu_eval_predictions.jsonl'}
        paths.update({task: base / f'crossvid/raw/{task}_result.json' for task in sorted({r.native_task for r in records.values() if r.dataset == 'crossvid'})})
        paths['judge'] = base / ('crossvid/raw/CCQA_score_deepseek_v4_flash_final.json' if model == '9b' else 'crossvid/score/raw/CCQA_score_deepseek_v4_flash.json')
        sources = {key: read(path) for key, path in paths.items()}
        scores = {}
        parser_changes = {'mvu_final_vs_first_character': 0, 'crossvid_final_vs_saved_strict': 0}
        for sid, record in records.items():
            key = record.native_task if record.dataset == 'crossvid' else record.dataset
            raw = sources[key][sid.split(':')[-1]]
            assert not raw.get('error'), (model, sid, raw.get('error'))
            prediction = raw.get('prediction', raw.get('answer'))
            if key == 'CCQA':
                judged = sources['judge'][str(raw['id'])]
                assert judged['answer'] == raw['answer'], (model, sid, 'stale judgment')
                n = len(record.sample.ground_truth)
                assert len(judged['coverage']) == len(judged['correctness']) == n
                assert all(type(v) is bool for v in judged['coverage'] + judged['correctness'])
                assert judged['score'] == sum(judged['coverage']) + sum(judged['correctness'])
                score = judged['score'] / (2 * n)
            elif key == 'FSA':
                score = float(raw['iou'])
            elif key in {'MOC', 'MSR'}:
                prediction, _ = extract_final_choice_with_method(raw['answer'], record.sample.options)
                score = float(prediction == record.sample.ground_truth[0])
                parser_changes['crossvid_final_vs_saved_strict'] += score != float(raw['correct'])
            else:
                field = 'legacy_first_character_correct' if key == 'mvu_eval' else 'correct'
                assert type(raw[field]) is bool
                score = float(raw[field])
                if key == 'mvu_eval':
                    parser_changes['mvu_final_vs_first_character'] += raw['correct'] != raw[field]
            assert 0 <= score <= 1
            scores[sid] = score
            rows.append(dict(model=model, sample_id=sid, split=membership[sid], dataset=record.dataset,
                             task=record.native_task, score=score, weight=record.sample_weight,
                             prediction=json.dumps(prediction, ensure_ascii=False),
                             source=str(paths[key].relative_to(ROOT)),
                             judge_source=str(paths['judge'].relative_to(ROOT)) if key == 'CCQA' else ''))
        summary[model] = {'parser_audit': parser_changes}
        for split in ['train', 'eval', 'all']:
            ids = [sid for sid, part in membership.items() if split == 'all' or part == split]
            result = aggregator.aggregate(sample_ids=ids, scores=scores, buckets={})
            summary[model][split] = {'count': len(ids), 'score': result.official_score, 'bucket_scores': result.bucket_scores}
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'split_manifest.json').write_bytes(args.manifest.read_bytes())
    hashes[str(args.manifest)] = hashlib.sha256(args.manifest.read_bytes()).hexdigest()
    for path in [Path(__file__), ROOT / 'scripts/answer_parsing.py', ROOT / 'src/skill_evolution/infra/benchmarks/aggregation.py']:
        hashes[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
    (args.output / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
    (args.output / 'source_sha256.json').write_text(json.dumps(hashes, indent=2) + '\n')
    with (args.output / 'per_sample.csv').open('w') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    report = ['# 固定 500 题：历史端到端模型基线', '',
              '从历史保存的预测和 Judge 结果提取，没有重新推理。三种模型各覆盖全部 500 题，Train 300 / Val 200，来源组不跨集合。这里是直接端到端模型基线，不是 MVAgent 无 Skill 基线。', '',
              '## 汇总分（%）', '', '| Qwen3.5 | Train 300 | Val 200 | 全部 500 |', '| --- | ---: | ---: | ---: |']
    for model, values in summary.items():
        report.append('| ' + model + ' | ' + ' | '.join(f"{values[s]['score'] * 100:.2f}" for s in ['train', 'eval', 'all']) + ' |')
    report += ['', '先按原生题型汇总，再对数据集内题型等权平均，最后对三个数据集等权平均；这是项目混合宏平均分，不是 500 题答对率。CCQA 按评分点数量加权，FSA 使用 IoU。', '',
               '## 数据集与题型（%，全部 500 题）', '', '| 分组 | 题数 | 9B | 27B | 35B-A3B |', '| --- | ---: | ---: | ---: | ---: |']
    for key in summary['9b']['all']['bucket_scores']:
        kind, name = key.split(':', 1)
        count = sum((r.dataset if kind == 'dataset' else f'{r.dataset}/{r.native_task}') == name for r in records.values())
        report.append(f'| {name} | {count} | ' + ' | '.join(f"{summary[m]['all']['bucket_scores'][key] * 100:.2f}" for m in summary) + ' |')
    report += ['', '## 评分和使用边界', '',
               '- CVBench 使用历史原生 correct；MVU 使用历史首字符评分。该子集中，三种模型的 MVU 首字符与最终选项评分均无差异。',
               '- CrossVid MOC/MSR 沿用历史报告的最终选项提取口径，其他选择/排序题使用保存的 correct，FSA 使用保存的 IoU。解析与原始严格比较的差异数量见 summary.json 的 parser_audit。',
               '- CCQA 使用保存的 DeepSeek-v4-flash Judge；逐题验证答案一致、评分点数与参考一致、布尔评分及合计一致。每题得分为 Coverage 与 Correctness 得分之和除以最大分，题型总分按评分点汇总。后续比较应固定相同 Judge 和评分规则。',
               '- 历史直接端到端输入采用每题总帧上限 512、最长边 720；不能据此认为与 MVAgent 的分步观察输入和实际帧消耗相同。',
               '- Val 是开发和候选选择集，不是独立 Test；全部 500 分适合描述，不应作为唯一选优指标。这里只统计一次历史运行，不能据此估计随机波动。',
               '- per_sample.csv 保存 1500 条逐题得分及来源；summary.json 包含每个划分的全部题型/数据集分数；source_sha256.json 固定输入文件及统计代码版本。', '',
               '复算：`PYTHONPATH=src /home/kww/miniconda3/envs/MVAgent/bin/python scripts/analysis/summarize_e2e_subset.py`。', '']
    (args.output / 'report.md').write_text('\n'.join(report))
    print('\n'.join(report[:14]))


if __name__ == '__main__':
    main()
