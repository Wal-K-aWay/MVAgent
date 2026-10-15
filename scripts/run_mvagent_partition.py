#!/usr/bin/env python3
"""Run an explicitly assigned model group using an existing immutable runtime."""
import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import traceback


def process_alive(pid):
    path = Path(f'/proc/{pid}/stat')
    return path.exists() and path.read_text().rsplit(') ', 1)[1].split()[0] != 'Z'


def validate_adoption(pid, output, model):
    command = Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')
    assert process_alive(pid) and any(v.endswith(b'eval/agent_eval/run.py') for v in command)
    index = command.index(b'--output')
    assert Path(os.fsdecode(command[index+1])).resolve() == (output/model).resolve()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--models', nargs='+', required=True, choices=['9B', '27B', '35B-A3B'])
    parser.add_argument('--adopt-pid', type=int)
    args = parser.parse_args()
    output, source = args.output.absolute(), args.source.resolve()
    assert output.resolve().is_relative_to(Path('/runs').resolve())
    assert len(args.models) == len(set(args.models))
    output.mkdir(parents=True, exist_ok=True)
    lock = (output/'partition.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    sys.path[:0] = [str(source/'scripts'), str(source/'src')]
    spec = importlib.util.spec_from_file_location('frozen_controller', source/'scripts/run_full_mvagent.py')
    core = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(core)
    assignment = dict(models=args.models, source=str(source),
        controller_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    assignment_path = output/'partition.json'
    if assignment_path.exists():
        assert core.read(assignment_path) == assignment, 'Partition assignment changed'
    else:
        core.write(assignment_path, assignment)
    core.MODELS = {m: core.MODELS[m] for m in args.models}
    manifest = core.prepare(output)
    state_path = output/'progress.json'
    state = core.read(state_path) if state_path.exists() else dict(started_at=core.now(), models={}, comparisons={})
    state.update(model_scope=args.models)
    state.pop('error', None); state.pop('traceback', None)
    process = None
    requested_adoption, adopted = args.adopt_pid, None
    caches = {m: {} for m in args.models}

    def save():
        state['updated_at'] = core.now()
        core.write(state_path, state)
        core.report(output, state)

    def refresh(model):
        rows = core.refresh(output/model, caches[model])
        state['models'][model].update(core.summary(rows))
        return rows

    def interrupted(signum, frame):
        raise InterruptedError(f'Partition interrupted by {signum}')

    signal.signal(signal.SIGTERM, interrupted)

    def run(command, log, model=None):
        nonlocal process
        with (output/log).open('a') as stream:
            process = subprocess.Popen([str(v) for v in command], cwd=source,
                env={**os.environ, 'PYTHONPATH': str(source/'src')}, stdout=stream,
                stderr=subprocess.STDOUT, start_new_session=True)
        while process.poll() is None:
            if model:
                refresh(model)
            save()
            time.sleep(30)
        code = process.returncode
        process = None
        if code:
            raise RuntimeError(f'Command exited {code}; see {log}')

    try:
        for model, suffix in core.MODELS.items():
            record = state['models'].setdefault(model, {})
            if record.get('inference_done'):
                continue
            config, execution = manifest['configs'][model], manifest['executions'][model]
            if requested_adoption:
                validate_adoption(requested_adoption, output, model)
                adopted, requested_adoption = requested_adoption, None
                core.write(output/'adoption.json', dict(pid=adopted, model=model, at=core.now()))
                state.update(phase='inference', model=model)
                while process_alive(adopted):
                    refresh(model); save(); time.sleep(30)
                adopted = None
                assert core.read(output/model/'run_manifest.json')['status'] == 'completed'
            else:
                state.update(phase='loading', model=model); save()
                run([sys.executable, source/'prelaunch.py', '--replace', config, execution,
                     f'qwen3_5_{suffix}_local'], f'{model}_startup.log')
                state.update(phase='inference', model=model)
                record.setdefault('started_at', core.now()); save()
                command = [sys.executable, source/'eval/agent_eval/run.py', '--config', config,
                    '--execution-config', execution, '--dataset-root', '/assets',
                    '--sample-ids-file', output/'samples.json', '--output', output/model, '--defer-open-qa-judge']
                if (output/model/'run_manifest.json').exists():
                    command.append('--resume')
                run(command, f'{model}_inference.log', model)
            rows = refresh(model)
            assert record['finished'] == sum(core.EXPECTED.values()) and record['errors'] == 0
            record.update(inference_done=True, finished_at=core.now())
            state['comparisons'][model] = core.compare(output, model, rows); save()
        if not all(state['models'][m].get('scoring_done') for m in args.models):
            from run_mvagent_pilot import stop_actor_servers
            state['phase'] = 'judge_loading'; save(); stop_actor_servers()
            os.environ['JUDGE_LOG_DIR'] = str(output/'judge')
            run(['bash', source/'eval/agent_eval/serve_ccqa_judge.sh', '0-7', '8100'], 'judge_startup.log')
            for model in args.models:
                if state['models'][model].get('scoring_done'):
                    continue
                state.update(phase='scoring', model=model); save()
                run([sys.executable, source/'eval/agent_eval/score_crossvid_ccqa.py', '--output', output/model,
                     '--endpoints', '8100-8107'], f'{model}_score.log')
                judge = core.read(output/model/'score'/core.CCQA_REPORT)
                assert not judge['failed_ids'] and judge['scored_answer_count'] == 239
                run([sys.executable, source/'eval/agent_eval/finalize_results.py', '--output', output/model],
                    f'{model}_finalize.log')
                state['comparisons'][model] = core.compare(output, model, refresh(model))
                state['models'][model]['scoring_done'] = True; save()
        state.update(phase='completed', finished_at=core.now()); save()
    except BaseException as exc:
        state.update(phase='interrupted' if isinstance(exc, InterruptedError) else 'failed',
                     error=repr(exc), traceback=traceback.format_exc())
        save(); print(state['traceback'], flush=True)
    finally:
        core.stop(process)
        if adopted and process_alive(adopted):
            os.kill(adopted, signal.SIGTERM)
        (Path('/work/jobs')/f'{output.name}.pid').unlink(missing_ok=True)


if __name__ == '__main__':
    main()
