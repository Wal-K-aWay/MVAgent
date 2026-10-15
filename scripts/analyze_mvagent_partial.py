#!/usr/bin/env python3
"""Read-only paired analysis of completed Agent rows; no inference or Judge calls."""
import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
from statistics import mean
import sys
from types import SimpleNamespace


def read(path):
    return json.loads(path.read_text())


def aggregate(rows, key, macro=False):
    if not rows:
        return None
    if not macro:
        return mean(r[key] for r in rows)
    tasks = defaultdict(list)
    for row in rows:
        tasks[row['task']].append(row[key])
    return mean(mean(values) for values in tasks.values())


def metrics(rows, macro=False):
    result = {'n': len(rows), 'tasks': len({r['task'] for r in rows})}
    for field in ('score', 'robust_score', 'format_ok'):
        before = aggregate(rows, 'e2e_' + field, macro)
        after = aggregate(rows, 'agent_' + field, macro)
        result[field] = dict(e2e=before, agent=after, delta=after-before if rows else None)
    result['improved'] = sum(r['agent_score'] > r['e2e_score'] for r in rows)
    result['regressed'] = sum(r['agent_score'] < r['e2e_score'] for r in rows)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    assert out.is_relative_to(Path('/runs').resolve()) and not out.exists()
    out.mkdir(parents=True)
    shutil.copyfile(__file__, out/'source.py')
    primary = Path('/runs/devbox/mvagent_full_20261014_transport')
    secondary = Path('/runs/devbox/mvagent_full_35b_parallel_20261015')
    source = primary/'frozen_repo'
    sys.path[:0] = [str(source/'scripts'), str(source/'src'), str(source/'eval/e2e_eval')]
    spec = importlib.util.spec_from_file_location('frozen_full', source/'scripts/run_full_mvagent.py')
    core = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(core)
    from harness.common import official_function
    from harness.cvbench import CVBench, QUESTIONS, TASK
    from harness.mvu_eval import MVUEval
    from harness.crossvid import CrossVid, EVAL_DIR
    from harness.answers import leads_with_choice, read_choice, read_yes_no

    cv = CVBench.__new__(CVBench)
    cv.extract = official_function(TASK/'utils.py', 'extract_characters_regex', {'re': re})
    def score_agent_cv(item, text):
        row = item['row']
        labels = {str(option).strip().rstrip('.').upper(): chr(65+i) for i,option in enumerate(row['options'])}
        def canonical(token):
            return labels.get(token, token) if token in {'YES', 'NO'} else token
        answer = canonical(row['answer'].strip().upper())
        prediction = canonical(cv.extract(text).strip().upper())
        format_ok = leads_with_choice(text, 'ABCD') or bool(re.match(r'\s*(?i:yes|no)\b', text))
        robust = prediction if format_ok else canonical(read_choice(text, 'ABCD') or read_yes_no(text))
        return dict(score=float(prediction==answer), robust_score=float(robust==answer), format_ok=format_ok)
    yes_no = {'row': {'options': ['Yes.', 'No.'], 'answer': 'No'}}
    assert score_agent_cv(yes_no, 'B')['score'] == score_agent_cv(yes_no, 'No')['score'] == 1
    assert score_agent_cv(yes_no, 'Final answer: B')['robust_score'] == 1
    cross = CrossVid.__new__(CrossVid)
    cross.modules = {'FSA': SimpleNamespace(interval_iou=official_function(EVAL_DIR/'FSA.py', 'interval_iou'))}
    scorers = {'cvbench': cv, 'mvu_eval': MVUEval.__new__(MVUEval), 'crossvid': cross}
    items = {f"cvbench:{r['id']}": {'row': r, 'task': r['task_type']} for r in read(QUESTIONS)}
    items.update({f"mvu_eval:{r['task']}:{key}": {'row': r, 'task': r['task']}
                  for key, r in read(Path('/assets/mvu-eval/MVU_Eval_QAs.json')).items()})
    for path in sorted(Path('/assets/crossvid/QA').glob('*.json')):
        items.update({f"crossvid:{path.stem}:{r['id']}": {'row': r, 'task': path.stem} for r in read(path)})
    assert metrics([dict(task='a', e2e_score=0, agent_score=1, e2e_robust_score=0,
                        agent_robust_score=1, e2e_format_ok=False, agent_format_ok=True)])['score']['delta'] == 1
    assert aggregate([dict(task='a', value=0), dict(task='a', value=0), dict(task='b', value=1)], 'value', True) == .5
    report = dict(snapshot_started_at=datetime.now(timezone.utc).isoformat(), source=str(source), models={},
                  analysis_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  protocol='Same completed IDs per model; CrossVid excludes unjudged CCQA and uses nine-task macro; MVU reports both E2E instruction positions.')
    for model, root in [('9B', primary), ('27B', primary), ('35B-A3B', secondary)]:
        progress = read(root/'progress.json')
        if model == '9B':
            rows = read(root/'comparison/9B.json')['rows']
            for r in rows:
                r['score'] = r['agent_score']
        else:
            paths = sorted((root/model/'records').glob('*/*/result.json'))
            with ThreadPoolExecutor(max_workers=8) as pool:
                rows = list(pool.map(lambda path: core.compact(read(path)), paths))
        assert len(rows) == len({r['sample_id'] for r in rows})
        (out/f'{model}_compact.json').write_text(json.dumps(rows, ensure_ascii=False))
        baseline = core.E2E[model]
        old = {r['sample_id']: r for ds in core.EXPECTED for r in read(baseline/'scored'/f'{ds}.json')}
        after_root = Path('/runs/devbox/mvu_instruction_after_20261014')/model
        after = {r['sample_id']: r for r in read(after_root/'scored/mvu_eval.json')}
        raw = {}
        for ds in core.EXPECTED:
            raw_root = after_root if ds == 'mvu_eval' else baseline
            with (raw_root/'raw'/f'{ds}.jsonl').open() as handle:
                for line in handle:
                    r = json.loads(line)
                    if r['status'] == 'ok':
                        raw[r['sample_id']] = dict(seconds=r['seconds'])
        assert all(r['sample_id'] in raw for r in rows if r['status'] == 'ok')
        paired, reference_normalization = [], []
        for r in rows:
            if r['status'] != 'ok' or r['task'] == 'CCQA':
                continue
            sid, ds = r['sample_id'], r['dataset']
            scored = score_agent_cv(items[sid], r['prediction']) if ds == 'cvbench' else scorers[ds].score(items[sid], r['prediction'])
            if ds == 'crossvid' and isinstance(items[sid]['row']['answer'], str):
                normalized = deepcopy(items[sid])
                normalized['row']['answer'] = normalized['row']['answer'].strip()
                if normalized != items[sid]:
                    normalized_score = scorers[ds].score(normalized, r['prediction'].strip())
                    reference_normalization.append(dict(sample_id=sid, raw_reference=items[sid]['row']['answer'],
                        canonical_reference=normalized['row']['answer'], raw_score=scored['score'],
                        agent_score=normalized_score['score']))
                    scored = normalized_score
            assert abs(scored['score'] - r['score']) < 1e-9, (sid, scored['score'], r['score'])
            variants = {'original': old[sid]}
            if ds == 'mvu_eval':
                variants['instruction_after'] = after[sid]
            for variant, before in variants.items():
                paired.append(dict(sample_id=sid, dataset=ds, task=r['task'], variant=variant,
                    **{'e2e_'+k: before[k] for k in ('score', 'robust_score', 'format_ok')},
                    **{'agent_'+k: scored[k] for k in ('score', 'robust_score', 'format_ok')}))
        stats = dict(finished=len(rows), errors=sum(r['status'] != 'ok' for r in rows),
            reference_normalization=reference_normalization,
            progress_updated_at=progress['updated_at'], source_root=str(root/model), e2e_original=str(baseline),
            e2e_instruction_after=str(after_root), ccqa_pending=sum(r['task']=='CCQA' for r in rows), benchmarks={},
            total_calls=sum(r['calls'] for r in rows), model_errors=sum(r['model_errors'] for r in rows),
            structured_invalid=sum(r['structured_invalid'] for r in rows), repairs=sum(r['repairs'] for r in rows),
            token_truncations=sum(r['token_truncations'] for r in rows), empty_answers=sum(not r['prediction'].strip() for r in rows))
        for ds in core.EXPECTED:
            subset = [r for r in rows if r['dataset'] == ds and r['status'] == 'ok']
            stats['benchmarks'][ds] = dict(
                finished=len(subset), expected=core.EXPECTED[ds],
                mean_agent_seconds=mean(r['seconds'] for r in subset) if subset else None,
                mean_e2e_seconds=mean(raw[r['sample_id']]['seconds'] for r in subset) if subset else None,
                mean_agent_calls=mean(r['calls'] for r in subset) if subset else None,
                comparisons={})
            for variant in ('original', 'instruction_after') if ds == 'mvu_eval' else ('original',):
                group = [r for r in paired if r['dataset'] == ds and r['variant'] == variant]
                result = metrics(group, macro=ds == 'crossvid')
                result['by_task'] = {task: metrics([r for r in group if r['task']==task]) for task in sorted({r['task'] for r in group})}
                stats['benchmarks'][ds]['comparisons'][variant] = result
        report['models'][model] = stats
        (out/f'{model}_paired.json').write_text(json.dumps(paired, ensure_ascii=False))
        print('MODEL', model, json.dumps({**stats, 'benchmarks': {
            ds: {**data, 'comparisons': {k: {a:b for a,b in v.items() if a!='by_task'} for k,v in data['comparisons'].items()}}
            for ds,data in stats['benchmarks'].items()}}, ensure_ascii=False), flush=True)
    report['finished_at'] = datetime.now(timezone.utc).isoformat()
    (out/'analysis.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
