#!/usr/bin/env python3
"""Rescore saved predictions on eval/crossvid_2500.json; no inference or API calls."""
import csv
import hashlib
import json
from pathlib import Path

from audit_crossvid_representative_subset import record_header
import sys
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from answer_parsing import extract_final_choice_with_method


def load(path):
    return json.loads(path.read_text())


def main():
    ids = load(ROOT / 'eval/crossvid_2500.json')
    assert len(ids) == len(set(ids)) == 2500
    manifest = load(ROOT / 'configs/skill_evolution/splits/crossvid_lite2500_eval_seed20260919.json')
    assert set(ids) == {s['sample_id'] for s in manifest['samples']}
    data = Path('/home/kww/datasets/Multi-Video/CrossVid')
    qa = {r['id']: r for r in map(json.loads, (data / 'qa.jsonl').read_text().splitlines())}
    ccqa = {int(r['id']): r for r in load(data / 'QA/CCQA.json')}
    tasks = sorted({qa[s]['task'] for s in ids})
    all_rows, summary = [], {}

    def collect(name, base, values):
        stats = {}
        for task in tasks:
            selected = [s for s in ids if qa[s]['task'] == task]
            scored = [values[s] for s in selected if values[s]['score'] is not None]
            stats[task] = dict(expected=len(selected), predictions=sum(values[s]['present'] for s in selected),
                               scored=len(scored), score=sum(v['score'] for v in scored) / sum(v['denominator'] for v in scored) if len(scored) == len(selected) else None)
        macro = sum(t['score'] for t in stats.values()) / len(tasks) if all(t['score'] is not None for t in stats.values()) else None
        summary[name] = dict(source=str(base.relative_to(ROOT)), predictions=sum(v['present'] for v in values.values()),
                             scored=sum(v['score'] is not None for v in values.values()), macro=macro, tasks=stats)
        for sid, v in values.items():
            all_rows.append(dict(system=name, sample_id=sid, task=qa[sid]['task'], **v))

    for model in ['9b', '27b', '35b_a3b']:
        base = ROOT / f'outputs/e2e/qwen3_5_{model}_e2e'
        values = {}
        for task in tasks:
            raw = load(base / f'crossvid/raw/{task}_result.json')
            indexed = {int(r['id']): r for r in raw}
            assert len(indexed) == len(raw)
            if task == 'CCQA':
                path = 'crossvid/raw/CCQA_score_deepseek_v4_flash_final.json' if model == '9b' else 'crossvid/score/raw/CCQA_score_deepseek_v4_flash.json'
                judged = {int(r['id']): r for r in load(base / path)}
            for sid in ids:
                if qa[sid]['task'] != task: continue
                native = int(sid.split(':')[-1]); row = indexed.get(native)
                den = 2 * len(ccqa[native]['scoring_points']) if task == 'CCQA' else 1
                score = None
                if row is not None:
                    if task == 'CCQA' and native in judged:
                        j = judged[native]; assert j['answer'] == row['answer']
                        assert len(j['coverage']) == len(j['correctness']) == den // 2
                        assert all(type(v) is bool for v in j['coverage'] + j['correctness'])
                        assert j['score'] == sum(j['coverage']) + sum(j['correctness'])
                        score = float(j['score'])
                    elif task in ('MOC', 'MSR'):
                        pred, _ = extract_final_choice_with_method(row['answer'], qa[sid]['options'])
                        score = float(pred == qa[sid]['answer'])
                    elif task != 'CCQA': score = float(row['iou'] if task == 'FSA' else row['correct'])
                assert score is None or 0 <= score <= den
                values[sid] = dict(present=row is not None, score=score, denominator=den)
        collect('E2E_' + model, base, values)

    for base in sorted((ROOT / 'outputs/mvagent/no_skill').iterdir()):
        if not base.is_dir(): continue
        judge_path = base / 'score/ccqa_scores_official_deepseek_v4_flash.json'
        judged = {int(r['id']): r for r in load(judge_path)['samples']} if judge_path.exists() else {}
        values = {}
        for sid in ids:
            task = qa[sid]['task']; native = int(sid.split(':')[-1])
            den = 2 * len(ccqa[native]['scoring_points']) if task == 'CCQA' else 1
            path = base / 'records/crossvid' / sid / 'result.json'
            row = record_header(path) if path.exists() else None
            score = None
            if row is not None:
                assert row['sample_id'] == sid
                if task == 'CCQA':
                    j = judged.get(native)
                    if j is not None:
                        assert j['prediction'] == row['prediction'] and j['status'] == 'ok'
                        score = float(j['score'])
                elif row.get('score') is not None: score = float(row['score'])
            assert score is None or 0 <= score <= den
            values[sid] = dict(present=row is not None, score=score, denominator=den)
        collect(base.name, base, values)

    # Report coverage of each frozen E0–E3 audit separately; never pool different Skills.
    skill_coverage = {}
    root = ROOT / 'outputs/mvagent/skill/20260916_evolution_redesign/runs'
    for base in sorted(root.glob('audit_*')):
        samples = load(base / 'split_manifest.json')['samples']
        overlap = sorted(set(ids) & {s['sample_id'] for s in samples})
        saved = load(base / 'summary.json')['samples']
        task_scores = {}
        for task in tasks:
            members = [sid for sid in overlap if qa[sid]['task'] == task]
            weights = {sid: 2 * len(ccqa[int(sid.split(':')[-1])]['scoring_points']) if task == 'CCQA' else 1 for sid in members}
            task_scores[task] = dict(n=len(members), score=sum(saved[sid]['score'] * weights[sid] for sid in members) / sum(weights.values()) if members else None)
        macro = sum(v['score'] for v in task_scores.values()) / len(tasks) if all(v['score'] is not None for v in task_scores.values()) else None
        skill_coverage[base.name] = dict(panel_overlap=len(overlap), sample_ids=overlap, source=str(base.relative_to(ROOT)), overlap_macro=macro, tasks=task_scores,
                                       samples={sid: saved[sid]['score'] for sid in overlap})
    out = ROOT / 'outputs/reports/crossvid_2500'; out.mkdir(parents=True, exist_ok=True)
    result = dict(id_file_sha256=hashlib.sha256((ROOT/'eval/crossvid_2500.json').read_bytes()).hexdigest(), systems=summary, skill_audit_coverage=skill_coverage)
    (out/'summary.json').write_text(json.dumps(result, indent=2)+'\n')
    with (out/'per_sample.csv').open('w') as f:
        w = csv.DictWriter(f, fieldnames=list(all_rows[0])); w.writeheader(); w.writerows(all_rows)
    lines = ['# CrossVid 固定 2500 题历史结果重统计', '',
             '使用 eval/crossvid_2500.json；没有重新推理或调用 Judge。CCQA 按总得分/总评分点满分，FSA 用 IoU，其他任务用保存评分；E2E MOC/MSR 使用既有最终选项解析器。最终分为 10 任务等权宏平均。缺失预测/评分不当成零，覆盖不全不报告完整宏平均。', '',
             '|系统|预测覆盖|有效评分|宏平均 %|', '|---|---:|---:|---:|']
    for name, s in summary.items():
        value = f"{s['macro']*100:.3f}" if s['macro'] is not None else '—'
        lines.append(f"|{name}|{s['predictions']}/2500|{s['scored']}/2500|{value}|")
    complete = {n:s for n,s in summary.items() if s['macro'] is not None}
    lines += ['', '|任务|题数|'+'|'.join(complete)+'|', '|---|---:|'+'---:|'*len(complete)]
    for task in tasks:
        lines.append('|'+task+'|'+str(sum(qa[s]['task']==task for s in ids))+'|'+'|'.join(f"{s['tasks'][task]['score']*100:.3f}" for s in complete.values())+'|')
    lines += ['', '## Skill 结果覆盖', '', 'E3 扩展评估只有 CVBench/MVU-Eval，没有 CrossVid。E0–E3 的 audit500 含 CrossVid 200 题，和本面板的交集如下；不能据此报告完整 2500 题效果，也不能跨 Skill/checkpoint 拼接。', '']
    lines += [f"- {n}: {s['panel_overlap']}/2500；仅交集题宏平均 {s['overlap_macro']*100:.3f}%" for n,s in skill_coverage.items()]
    missing9 = [r for r in all_rows if r['system'] == 'E2E_9b' and r['score'] is None]
    lines += ['', '9B E2E 缺失评分 ID：' + ', '.join(r['sample_id'] for r in missing9) + '。历史报告缺失按零口径得到 32.420%；本报告不把未评分当成实际零分。']
    lines += ['', '这些是历史运行的描述性对比。各版本 Runtime、输入/帧预算及 Judge 返回模型可能不同，不能把差异全部归因于模型大小或 Skill。preflight 是诊断样例，不是完整基准。冻结预测、评分、执行时路径均保留原样；目录映射见 outputs/maintenance/layout_20260919/moves.json。', '']
    (out/'report.md').write_text('\n'.join(lines))
    print('\n'.join(lines[:len(summary)+7]))


if __name__ == '__main__':
    main()
