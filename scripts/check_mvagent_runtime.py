#!/usr/bin/env python3
"""Check repeatability and answer formatting through the public MVAgent CLI."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
MODELS = [('9B', '9b'), ('27B', '27b'), ('35B-A3B', '35b_a3b')]
SAMPLES = ['cvbench:664', 'mvu_eval:Comparison:818', 'crossvid:MOC:521', 'crossvid:FSA:121']


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n')
    temporary.replace(path)


def run(args, log):
    with log.open('w') as handle:
        subprocess.run([str(a) for a in args], cwd=ROOT, stdout=handle, stderr=subprocess.STDOUT,
                       env={**os.environ, 'PYTHONPATH': str(ROOT/'src')}, check=True)


def records(directory):
    return {row['sample_id']: row for p in directory.glob('records/*/*/result.json')
            if (row := json.loads(p.read_text()))}


def analyze(first, second, *, samples=SAMPLES):
    from confirm_single_process_mvagent import compare_rollouts
    spec = importlib.util.spec_from_file_location('answer_export', ROOT/'eval/agent_eval/export_results.py')
    export = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(export)
    report = dict(trajectories=0, completed=0, model_calls=0, paired_calls=0, comparisons=0,
                  differences={}, errors={}, event_errors={}, answer_format_failures=[],
                  truncated_calls=0, forced_answers=0, answers=[])
    kinds = Counter()
    for repeat, rows in enumerate([first, second]):
        for sid in samples:
            row = rows.get(sid)
            if row is None or row['status'] != 'ok':
                report['errors'][f'{repeat}:{sid}'] = row.get('error', '') if row else 'Missing record'
                continue
            report['completed'] += 1
            events = row['events']
            kinds.update(e['kind'] for e in events)
            calls = [e for e in events if e['kind'] == 'model_response']
            assert calls and all(e['worker']['forward_calls'] > 0 and
                len(e['token_ids']) == e['usage']['completion_tokens'] for e in calls)
            assert len({(e['worker']['pid'], e['worker']['gpu_uuid']) for e in calls}) == 1
            report['model_calls'] += len(calls)
            report['truncated_calls'] += sum(e['finish_reason'] == 'length' for e in calls)
            answer = row['result']['answer']
            report['forced_answers'] += answer.get('status') == 'forced_with_gaps'
            valid = bool(re.fullmatch(export.VALID[row['task_family']], row['prediction'], re.I))
            report['answers'].append(dict(repeat=repeat, sample_id=sid, prediction=row['prediction'],
                format_syntax_valid=valid, status=answer['status'], calls=len(calls)))
            if not valid:
                report['answer_format_failures'].append(f'{repeat}:{sid}')
    for sid in samples:
        a, b = first.get(sid, {}), second.get(sid, {})
        if a.get('status') == b.get('status') == 'ok':
            delta = compare_rollouts(a, b)
            report['comparisons'] += 1
            report['paired_calls'] += sum(e['kind']=='model_response' for e in a['events'])
            if delta['calls'] or delta['result_fields']:
                report['differences'][sid] = delta
    report['trajectories'] = len(first)+len(second)
    report['event_errors'] = {k: kinds[k] for k in ['model_error', 'structured_invalid']}
    return report


def self_check():
    from copy import deepcopy
    from mvagent.agents.global_agent.schema import build_global_decision_schema
    from models.utils import validate_json_schema
    validate_json_schema({'reason': 'Evidence reviewed', 'action': 'answer', 'parameters': {'answer': '}'}},
                         build_global_decision_schema(['answer']))
    result = dict.fromkeys(['input', 'video_metadata', 'video_reports', 'watch_results',
                           'action_history', 'trajectory', 'stop_reason'])
    result['answer'] = dict(answer='}', status='answered')
    call = dict(kind='model_response', token_ids=[1], request_sha256='request',
        prompt_token_ids_sha256='prompt', usage={'completion_tokens': 1}, finish_reason='stop',
        worker=dict(pid=1, gpu_uuid='gpu', forward_calls=1))
    row = dict(status='ok', prediction='}', task_family='choice', result=result,
               events=[{'kind': 'model_request'}, call])
    sid = SAMPLES[0]
    report = analyze({sid: row}, {sid: row})
    assert report['completed'] == 2 and len(report['errors']) == 6
    assert len(report['answer_format_failures']) == 2 and not report['differences']
    changed = deepcopy(row)
    changed['events'][-1]['token_ids'] = [2]
    assert sid in analyze({sid: row}, {sid: changed})['differences']
    print('Audit self-check passed: repeatability, missing records and invalid answer format stay separate')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--self-check', action='store_true')
    args = parser.parse_args()
    if args.self_check:
        self_check()
        return
    if not args.output:
        parser.error('--output is required')
    output = args.output
    assert output.resolve().is_relative_to(Path('/runs').resolve())
    output.mkdir(parents=True, exist_ok=True)
    frozen = output/'frozen_repo'
    if ROOT != frozen.resolve():
        if not frozen.exists():
            temporary = output/'frozen_repo.tmp'
            temporary.mkdir()
            for name in ['src', 'scripts', 'eval', 'configs', '.git']:
                shutil.copytree(ROOT/name, temporary/name, ignore=shutil.ignore_patterns('__pycache__', '.cache'))
            for name in ['requirements.txt', 'demo.py']:
                shutil.copy2(ROOT/name, temporary/name)
            # prelaunch normally imports /repo; this run must use its immutable snapshot.
            source = Path('/devtools/prelaunch.py').read_text().replace('"/repo/src"', repr(str(frozen/'src')))
            (temporary/'prelaunch.py').write_text(source)
            temporary.rename(frozen)
        os.execv(sys.executable, [sys.executable, str(frozen/'scripts'/Path(__file__).name), '--output', str(output)])
    import yaml
    from models.vlm.local.sync_server import execution_profile
    self_check()
    state = dict(started_at=datetime.now(timezone.utc).isoformat(), phase='preparing', results={})
    write(output/'samples.json', SAMPLES)
    write(output/'manifest.json', dict(samples=SAMPLES, models=MODELS, execution=execution_profile(),
        purpose='Runtime, complete-token repeatability and answer-format diagnosis; no accuracy scoring',
        repeats=2, gpus=2, max_steps=5, max_tokens=2048, skills=None))
    try:
        for model, slug in MODELS:
            target = output/model
            target.mkdir(exist_ok=True)
            config = yaml.safe_load((ROOT/f'configs/inference/modal_qwen35_{slug}_no_skill.yaml').read_text())
            name = next(iter(config['models']))
            config['runtime']['cache_dir'] = str(target/'runtime_cache')
            replicas = [dict(gpus=[i], endpoint=f'http://127.0.0.1:{8100+i}/v1', max_inflight=1) for i in range(2)]
            execution = dict(question_workers=2, max_prepared_requests=4, question_retries=0,
                question_timeout_sec=7200, media_cache=dict(root=str(target/'media'), max_bytes=10*1024**3),
                model_pools={name: dict(replicas=replicas)})
            cfg, ex = target/'config.yaml', target/'execution.yaml'
            cfg.write_text(yaml.safe_dump(config, sort_keys=False))
            ex.write_text(yaml.safe_dump(execution, sort_keys=False))
            state.update(model=model, phase='loading')
            write(output/'progress.json', state)
            run([sys.executable, ROOT/'prelaunch.py', '--replace', cfg, ex, name], target/'startup.log')
            passes = []
            for repeat in range(2):
                state.update(phase='agent', repeat=repeat)
                write(output/'progress.json', state)
                directory = target/f'repeat{repeat}'
                run([sys.executable, 'eval/agent_eval/run.py', '--config', cfg, '--execution-config', ex,
                     '--dataset-root', '/assets', '--sample-ids-file', output/'samples.json',
                     '--output', directory, '--inference-only'], target/f'repeat{repeat}.log')
                passes.append(records(directory))
            report = analyze(*passes)
            write(target/'report.json', report)
            state['results'][model] = report
            write(output/'progress.json', state)
            print(json.dumps(dict(model=model, **report), ensure_ascii=False), flush=True)
        findings = any(r['errors'] or r['differences'] or r['answer_format_failures'] or
                       any(r['event_errors'].values()) for r in state['results'].values())
        state['phase'] = 'completed_with_findings' if findings else 'completed'
    except Exception as exc:
        import traceback
        state.update(phase='failed', error=repr(exc), traceback=traceback.format_exc())
        print(state['traceback'], flush=True)
    finally:
        state['finished_at'] = datetime.now(timezone.utc).isoformat()
        write(output/'progress.json', state)
        (output/'report.md').write_text('# MVAgent runtime check\n\n```json\n'+json.dumps(state, ensure_ascii=False, indent=2)+'\n```\n')
        (Path('/work/jobs')/f'{output.name}.pid').unlink(missing_ok=True)
        os.utime('/work/heartbeat', (0, 0))


if __name__ == '__main__':
    main()
