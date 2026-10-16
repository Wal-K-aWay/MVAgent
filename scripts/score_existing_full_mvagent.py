#!/usr/bin/env python3
"""Finish deferred CCQA judging without changing frozen Actor results."""
import argparse
from collections import Counter, defaultdict
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import traceback


SOURCE = Path('/runs/devbox/mvagent_full_20261014_transport/frozen_repo')
ORIGINALS = {
    '9B': Path('/runs/devbox/mvagent_full_20261014_transport/9B'),
    '27B': Path('/runs/devbox/mvagent_full_20261014_transport/27B'),
    '35B-A3B': Path('/runs/devbox/mvagent_full_35b_parallel_20261015/35B-A3B'),
}
KNOWN_HIDDEN_FAILURES = {'crossvid:PEA:510', 'crossvid:PEA:838'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    sys.path[:0] = [str(SOURCE / 'scripts'), str(SOURCE / 'src')]
    import run_full_mvagent as core

    state_path = output / 'progress.json'
    state = core.read(state_path) if state_path.exists() else {
        'started_at': core.now(), 'models': {}, 'actor_rerun': False,
    }
    if state.get('phase') == 'completed':
        print('Scoring already complete', flush=True)
        return

    def save(phase, **details):
        state.update(phase=phase, updated_at=core.now(), **details)
        core.write(state_path, state)
        print(json.dumps({'phase': phase, **details}), flush=True)

    def run(command, log, env=None):
        with (output / log).open('a') as stream:
            subprocess.run(command, cwd=SOURCE, check=True, stdout=stream,
                           stderr=subprocess.STDOUT, env=env)

    try:
        save('preparing')
        source_files = ['eval/agent_eval/score_crossvid_ccqa.py',
                        'eval/agent_eval/serve_ccqa_judge.sh',
                        'scripts/run_full_mvagent.py', 'scripts/run_full_e2e.py']
        manifest = {
            'created_at': core.now(), 'source': str(SOURCE),
            'source_hashes': {name: core.sha(SOURCE / name) for name in source_files},
            'controller_sha256': core.sha(Path(__file__)),
            'originals': {m: str(p) for m, p in ORIGINALS.items()},
            'actor_manifests': {m: core.read(p / 'run_manifest.json') for m, p in ORIGINALS.items()},
            'versions': {name: importlib.metadata.version(name) for name in
                         ['vllm', 'torch', 'transformers', 'openai']},
            'gpu': subprocess.check_output(['nvidia-smi', '--query-gpu=name,uuid',
                                            '--format=csv,noheader'], text=True),
            'policy': 'Frozen official scorer; no Actor rerun; original records remain unchanged. '
                      'Primary comparison excludes top-level Actor errors. Known hidden 9B failures '
                      'remain in recorded scores, with separate clean-subset sensitivity.',
        }
        if not (output / 'manifest.json').exists():
            core.write(output / 'manifest.json', manifest)
            shutil.copy2(__file__, output / 'controller.py')
        else:
            previous = core.read(output / 'manifest.json')
            for key in ['source_hashes', 'controller_sha256', 'originals']:
                assert manifest[key] == previous[key], key
        for model, original in ORIGINALS.items():
            directory = output / model
            directory.mkdir(exist_ok=True)
            records = directory / 'records'
            if not records.exists():
                records.symlink_to(original / 'records', target_is_directory=True)
            assert records.resolve() == (original / 'records').resolve()
            ccqa = list(records.glob('crossvid/crossvid:CCQA:*/result.json'))
            assert len(ccqa) == 239, (model, len(ccqa))
            assert all(core.read(p)['status'] == 'ok' for p in ccqa), model

        save('judge_loading')
        run(['bash', str(SOURCE / source_files[1]), '0-7', '8100'], 'judge_startup.log',
            {**os.environ, 'JUDGE_LOG_DIR': str(output / 'judge')})
        for model in ORIGINALS:
            if state['models'].get(model, {}).get('judge_complete'):
                continue
            save('judging', model=model)
            run([sys.executable, str(SOURCE / source_files[0]), '--output',
                 str(output / model), '--endpoints', '8100-8107'], f'{model}_judge.log')
            report = core.read(output / model / 'score' / core.CCQA_REPORT)
            assert not report['failed_ids'] and report['scored_answer_count'] == 239, report['failed_ids']
            state['models'][model] = {'judge_complete': True, 'judged': 239,
                                      'ccqa_score': report['official_score']}
            save('judging', model=model)

        save('aggregating')
        analysis = {'models': {}, 'scope': manifest['policy'], 'source': str(SOURCE)}
        for model, original in ORIGINALS.items():
            rows, hashes = [], {}
            for path in sorted((original / 'records').glob('*/*/result.json')):
                content = path.read_bytes()
                row = json.loads(content)
                hashes[row['sample_id']] = hashlib.sha256(content).hexdigest()
                rows.append(core.compact(row))
            assert len(rows) == len(hashes) == 5321
            expected_ids = set(core.read(original.parent / 'samples.json'))
            assert set(hashes) == expected_ids
            core.write(output / model / 'record_hashes.json', hashes)
            metrics = core.compare(output, model, rows)
            paired = core.read(output / 'comparison' / f'{model}.json')['rows']
            by_task = {}
            for dataset in core.EXPECTED:
                groups = defaultdict(list)
                for row in paired:
                    if row['dataset'] == dataset and row['status'] == 'ok' and row['agent_score'] is not None:
                        groups[row['task']].append(row)
                by_task[dataset] = {}
                for task, group in groups.items():
                    if dataset == 'crossvid' and task == 'CCQA':
                        score = sum(r['agent_score'] * r['points'] for r in group) / sum(r['points'] for r in group)
                    else:
                        score = sum(r['agent_score'] for r in group) / len(group)
                    by_task[dataset][task] = {'count': len(group), 'score': score}
            assert len(by_task['crossvid']) == 10
            assert abs(sum(x['score'] for x in by_task['crossvid'].values()) / 10
                       - metrics['crossvid']['agent_score']) < 1e-12
            report = core.read(output / model / 'score' / core.CCQA_REPORT)
            assert abs(by_task['crossvid']['CCQA']['score'] - report['official_score']) < 1e-12
            failures = [r['sample_id'] for r in paired if r['status'] != 'ok']
            hidden = sorted(KNOWN_HIDDEN_FAILURES) if model == '9B' else []
            clean = [r for r in paired if r['dataset'] == 'crossvid' and r['status'] == 'ok'
                     and r['agent_score'] is not None and r['sample_id'] not in hidden]
            analysis['models'][model] = {
                'metrics': metrics, 'by_task': by_task, 'actor_errors': failures,
                'known_hidden_errors': hidden, 'record_count': len(rows),
                'ccqa': {k: report[k] for k in ['scored_answer_count', 'failed_ids',
                                             'sum_score', 'all_score', 'official_score']},
                'clean_crossvid': {'count': len(clean), 'agent_score': core.paired_score(clean, 'agent_score'),
                                  'e2e_score': core.paired_score(clean, 'e2e_score')},
                'recorded_empty_answers': sum(not str(r['prediction'] or '').strip() for r in paired),
            }
            state['models'][model].update(aggregated=True, records=len(rows), actor_errors=failures)
            save('aggregating', model=model)
        core.write(output / 'analysis.json', analysis)
        report_state = {'phase': 'scoring_completed_with_recorded_actor_failures',
                        'comparisons': {m: d['metrics'] for m, d in analysis['models'].items()}}
        core.report(output, report_state)
        save('completed', judged=717, judge_errors=0, finished_at=core.now())
    except BaseException as exc:
        save('failed', error=repr(exc), traceback=traceback.format_exc())
        raise
    finally:
        (Path('/work/jobs') / f'{output.name}.pid').unlink(missing_ok=True)


if __name__ == '__main__':
    main()
