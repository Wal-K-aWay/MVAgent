#!/usr/bin/env python3
"""Validate a frozen CrossVid panel against metadata and saved predictions only."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from answer_parsing import extract_final_choice_with_method


def load(path):
    return json.loads(Path(path).read_text())


def record_header(path):
    # Saved records are pretty-printed; don't parse gigabytes of trajectories.
    lines = []
    with Path(path).open() as stream:
        for line in stream:
            if line.startswith('  "result":'):
                return json.loads(''.join(lines).rstrip().rstrip(',') + '\n}')
            lines.append(line)
    raise ValueError(f'Expected saved-record result boundary in {path}')


def ks(a, b):
    a, b = np.sort(a), np.sort(b)
    points = np.unique(np.concatenate([a, b]))
    return float(np.max(np.abs(np.searchsorted(a, points, side='right') / len(a)
                               - np.searchsorted(b, points, side='right') / len(b))))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    manifest_bytes = args.manifest.read_bytes()
    selected = load(args.output / 'selected_features.json')
    all_rows = load(args.output / 'all_features.json')
    audit = load(args.output / 'audit.json')
    ids = {r['sample_id'] for r in selected}
    assert ids == {r['sample_id'] for r in json.loads(manifest_bytes)['samples']}
    tasks = list(audit['quotas'])
    blocked = {s['sample_id'] for p in audit['exclusion_manifests'] for s in load(p)['samples']}
    blocked_keys = {k for r in all_rows if r['sample_id'] in blocked for k in r['source_keys']}
    duplicates = set(audit['content_duplicate_paths'])
    eligible = [r for r in all_rows if not set(r['source_keys']) & blocked_keys
                and not set(r['paths']) & duplicates]
    populations = {'full': all_rows, 'eligible': eligible, 'selected': selected}
    fields = ['total_seconds', 'max_seconds', 'duration_imbalance', 'question_chars',
              'video_count', 'min_fps', 'max_pixels', 'reference_seconds', 'object_count']
    metadata = {}
    for task in tasks:
        a = [r for r in eligible if r['task'] == task]
        b = [r for r in selected if r['task'] == task]
        full = [r for r in all_rows if r['task'] == task]
        metadata[task] = {}
        for field in fields:
            x, y = np.array([r[field] for r in a]), np.array([r[field] for r in b])
            metadata[task][field] = {'ks': ks(x, y),
                'ks_against_full': ks([r[field] for r in full], y),
                'standardized_mean_difference': float((y.mean() - x.mean()) / x.std()) if x.std() else 0.}
    print('Metadata comparisons complete; reading saved score headers', flush=True)
    dataset_root = Path('/home/kww/datasets/Multi-Video/CrossVid')
    qa = {r['id']: r for r in (json.loads(line) for line in (dataset_root/'qa.jsonl').read_text().splitlines())}
    ccqa = {int(r['id']): r for r in load(dataset_root/'QA/CCQA.json')}
    agent_root = ROOT/'outputs/mvagent/no_skill/qwen3_5_35b_a3b_mvagent_no_skill'
    judge = {int(r['id']): r for r in load(agent_root/'score/ccqa_scores_official_deepseek_v4_flash.json')['samples']}
    scores = {'MVAgent35B': {}}
    for i, r in enumerate(all_rows, 1):
        sid, task = r['sample_id'], r['task']
        row = record_header(agent_root/'records/crossvid'/sid/'result.json')
        if task == 'CCQA':
            native_id = int(sid.split(':')[-1]); j = judge[native_id]
            assert j['prediction'] == row['prediction'] and j['status'] == 'ok'
            score, denominator = float(j['score']), 2 * len(ccqa[native_id]['scoring_points'])
        else:
            assert row['score'] is not None, sid
            score, denominator = float(row['score']), 1
        scores['MVAgent35B'][sid] = [score, denominator, False]
        if i % 2000 == 0:
            print(f'Saved records {i}/{len(all_rows)}', flush=True)
    for model in ('9b', '27b', '35b_a3b'):
        key = f'E2E_{model}'; scores[key] = {}
        base = ROOT / f'outputs/e2e/qwen3_5_{model}_e2e'
        for task in tasks:
            raw = load(base/f'crossvid/raw/{task}_result.json')
            records = {int(r['id']): r for r in raw}
            assert len(records) == len(raw)
            if task == 'CCQA':
                score_path = ('crossvid/raw/CCQA_score_deepseek_v4_flash_final.json' if model == '9b'
                              else 'crossvid/score/raw/CCQA_score_deepseek_v4_flash.json')
                judgments = {int(r['id']): r for r in load(base/score_path)}
            for sid, q in qa.items():
                if q['task'] != task:
                    continue
                i = int(sid.split(':')[-1]); row = records.get(i)
                den = 2 * len(ccqa[i]['scoring_points']) if task == 'CCQA' else 1
                missing = row is None or (task == 'CCQA' and i not in judgments)
                if missing:
                    score = 0.
                elif task == 'CCQA':
                    assert judgments[i]['answer'] == row['answer']
                    score = float(judgments[i]['score'])
                elif task in ('MOC', 'MSR'):
                    pred, _ = extract_final_choice_with_method(row['answer'], q['options'])
                    score = float(pred == q['answer'])
                else:
                    score = float(row['iou'] if task == 'FSA' else row['correct'])
                scores[key][sid] = [score, den, missing]
    results = {}
    for model, values in scores.items():
        results[model] = {}
        for population, rows in populations.items():
            task_scores = {}
            for task in tasks:
                members = [r for r in rows if r['task'] == task]
                numerator = sum(values[r['sample_id']][0] for r in members)
                denominator = sum(values[r['sample_id']][1] for r in members)
                task_scores[task] = dict(score=numerator/denominator, n=len(members),
                                        missing=sum(values[r['sample_id']][2] for r in members))
                if population == 'selected':
                    task_scores[task]['weighted_eligible_estimate'] = (
                        sum(values[r['sample_id']][0] * r['population_weight'] for r in members) /
                        sum(values[r['sample_id']][1] * r['population_weight'] for r in members))
            results[model][population] = {'tasks': task_scores,
                'macro': sum(x['score'] for x in task_scores.values())/len(tasks)}
    baseline = load(agent_root/'summary_scored.json')['datasets']['crossvid']
    for task in tasks:
        assert abs(results['MVAgent35B']['full']['tasks'][task]['score'] - baseline['by_task'][task]['accuracy']) < 1e-9, task
    assert args.manifest.read_bytes() == manifest_bytes, 'Validation changed frozen selection'
    report = dict(manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
                  metadata=metadata, historical_scores=results,
                  note='Historical E2E missing inference/Judge uses zero as in the saved full comparison; missing counts are explicit. Judge versions, inputs, parsers and frame/call budgets differ. Descriptive validation only; no re-selection or proof of future model ranking preservation.')
    (args.output/'validation.json').write_text(json.dumps(report, indent=2)+'\n')
    (args.output/'historical_score_rows.json').write_text(json.dumps(scores)+'\n')
    lines = ['# 冻结后的代表性检查', '', '没有根据这些成绩重选样本。CCQA按评分点总分/总满分，其他任务沿用历史官方评分，再计算10任务宏平均。', '',
             '|系统|全集宏平均|来源隔离后可用总体|2500题子集|子集−可用总体 pp|', '|---|---:|---:|---:|---:|']
    for model, r in results.items():
        lines.append(f"|{model}|{r['full']['macro']*100:.3f}|{r['eligible']['macro']*100:.3f}|{r['selected']['macro']*100:.3f}|{(r['selected']['macro']-r['eligible']['macro'])*100:+.3f}|")
    lines += ['', '## 元数据差异（子集相对可用总体）', '',
              '|任务|总时长KS：可用/全集|总时长标准化均值差|问题长度KS|视频数KS|', '|---|---:|---:|---:|---:|']
    for task, m in metadata.items():
        lines.append(f"|{task}|{m['total_seconds']['ks']:.3f}/{m['total_seconds']['ks_against_full']:.3f}|{m['total_seconds']['standardized_mean_difference']:+.3f}|{m['question_chars']['ks']:.3f}|{m['video_count']['ks']:.3f}|")
    lines += ['', report['note'], '', 'KS越小，经验分布差异越小；它不是代表性或泛化的保证。完整逐任务分数、FPS/像素数等统计在validation.json。共享媒体限制独立信息量；不能仅凭题数或总分接近认定小幅改进显著。', '']
    (args.output/'validation.md').write_text('\n'.join(lines))
    print('\n'.join(lines), flush=True)


if __name__ == '__main__':
    main()
