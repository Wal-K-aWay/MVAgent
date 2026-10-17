#!/usr/bin/env python3
"""Repeat a frozen MVAgent panel on eight independent, serial H100 workers."""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time

from benchmark_qwen35_fp8 import event, save
from confirm_single_process_mvagent import SOURCE


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def shards(cases):
    ranked = sorted(cases, key=lambda c: (-c['old_calls'], -c['old_output_tokens'], c['name']))
    return [ranked[i::8] for i in range(8)]


def prepare(output):
    assert not output.exists()
    cases = []
    for path in sorted(SOURCE.rglob('result.json')):
        row = read(path)
        assert row['status'] == 'ok'
        calls = [e for e in row['events'] if e['kind'] == 'model_response']
        cases.append(dict(name=row['sample_id'], dataset=row['dataset'], native_task=row['native_task'],
            old_calls=len(calls), old_output_tokens=sum(len(c['token_ids']) for c in calls),
            source=str(path), source_sha256=sha(path)))
    assert len(cases) == len({c['name'] for c in cases}) == 33
    assert len({(c['dataset'], c['native_task']) for c in cases}) == 33
    assert Counter(c['dataset'] for c in cases) == {'cvbench': 15, 'mvu_eval': 8, 'crossvid': 10}
    output.mkdir(parents=True)
    save(output / 'inputs.json', cases)
    for rank, panel in enumerate(shards(cases)):
        save(output / f'shard{rank}.json', panel)
    save(output / 'manifest.json', dict(source=str(SOURCE), cases=33,
        input_sha256=sha(output / 'inputs.json'),
        selection='All 33 historical development cases, one per native task; no accuracy filter.',
        sharding='Descending historical call count / output tokens, round robin across eight workers.',
        protocol='Each shard twice in a process, then twice in new processes on GPU (rank+1)%8.',
        scoring_requested=False))
    print(json.dumps(dict(panel=str(output), cases=33, shards=[len(s) for s in shards(cases)])))


def self_check():
    cases = [dict(name=str(i), old_calls=i, old_output_tokens=2*i) for i in range(33)]
    panels = shards(cases)
    assert sorted(len(p) for p in panels) == [4]*7 + [5]
    assert {c['name'] for p in panels for c in p} == {c['name'] for c in cases}
    assert all(i != (i+1) % 8 for i in range(8))
    print('Replica panel self-check passed')


def run(output, panel, models, max_steps):
    assert not (output / 'manifest.json').exists()
    assert read(panel / 'manifest.json')['input_sha256'] == sha(panel / 'inputs.json')
    output.mkdir(parents=True, exist_ok=True)
    shutil.copytree(panel, output / 'panel')
    panel = output / 'panel'
    count = len(read(panel/'inputs.json'))
    shutil.copyfile(__file__, output / 'source.py')
    subprocess.run(['tar', '-czf', str(output / 'source.tar.gz'), '--exclude=__pycache__',
                    'src', 'eval', 'scripts', 'configs', 'requirements.txt', 'demo.py'], check=True)
    save(output / 'manifest.json', dict(panel_sha256=sha(panel / 'inputs.json'),
        source_sha256=sha(output / 'source.py'), snapshot_sha256=sha(output / 'source.tar.gz'),
        models=models, case_count=count, max_steps=max_steps, gpu_count=8,
        planned_rollouts=4*count*len(models), planned_comparisons=3*count*len(models), scoring_requested=False,
        commit=subprocess.check_output(['git', '-c', 'safe.directory=/repo', 'rev-parse', 'HEAD'], text=True).strip()))
    processes, streams, results = [], [], []

    def terminate():
        for proc in processes:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
        for proc in processes:
            if proc.poll() is None:
                try:
                    proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait(timeout=15)

    signal.signal(signal.SIGTERM, signal.default_int_handler)
    try:
        for model in models:
            index = output / model / 'references.json'
            for phase in ['p1', 'p2']:
                barrier = output / model / (phase + '_barrier')
                pool = []
                started = time.monotonic()
                for rank in range(8):
                    root = output / model / f'{phase}_rank{rank}'
                    root.mkdir(parents=True)
                    gpu = rank if phase == 'p1' else (rank+1) % 8
                    cmd = ['python', 'scripts/confirm_vllm_repro_fix.py', '--model', model,
                           '--gdn-backend', 'flashinfer', '--output', str(root),
                           '--max-steps', str(max_steps),
                           '--inputs', str(panel / f'shard{rank}.json'), '--barrier-dir', str(barrier)]
                    if phase == 'p2':
                        cmd += ['--reference-index', str(index)]
                    env = {**os.environ, 'CUDA_VISIBLE_DEVICES': str(gpu),
                           'PYTHONPATH': '/repo/src:/repo/scripts', 'OMP_NUM_THREADS': '1',
                           'MKL_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1'}
                    stream = (root / 'job.log').open('w')
                    streams.append(stream)
                    proc = subprocess.Popen(cmd, env=env, stdout=stream, stderr=subprocess.STDOUT,
                                            start_new_session=True)
                    processes.append(proc)
                    pool.append((root, proc))
                    event(output, 'child_started', model=model, phase_name=phase, rank=rank, gpu=gpu, pid=proc.pid)
                deadline = started + 1200
                while len(list(barrier.glob('*.ready'))) < 8:
                    assert all(p.poll() is None for _, p in pool), 'Worker exited before start barrier; inspect job.log'
                    if time.monotonic() > deadline:
                        raise TimeoutError(f'{model} {phase}: loading exceeded 20 minutes')
                    time.sleep(2)
                (barrier / 'go').touch()
                measured_start = time.monotonic()
                event(output, 'running', model=model, phase_name=phase)
                pending = list(pool)
                while pending:
                    for root, proc in list(pending):
                        if proc.poll() is None:
                            continue
                        row = read(root / 'summary.json') if (root / 'summary.json').exists() else dict(
                            error=f'Exit {proc.returncode} without summary', stable=False)
                        results.append(dict(root=str(root), phase=phase, exit_code=proc.returncode, **row))
                        save(output / 'results.json', results)
                        event(output, 'child_finished', root=str(root), stable=row['stable'],
                              rollouts=row.get('rollouts', 0), calls=row.get('calls', 0), error=row['error'])
                        pending.remove((root, proc))
                        assert proc.returncode == 0 and row['error'] is None, f'{root}: {row["error"]}'
                    if time.monotonic() - measured_start > 5400:
                        raise TimeoutError(f'{model} {phase}: inference exceeded 90 minutes')
                    if pending:
                        time.sleep(2)
                save(output / model / f'{phase}_timing.json', dict(started=started,
                    inference_started=measured_start, ended=time.monotonic(),
                    inference_seconds=time.monotonic()-measured_start))
                if phase == 'p1':
                    references = {}
                    for root, _ in pool:
                        for path in (root / model / 'A_initial_repeat0/records').glob('*/result.json'):
                            row = read(path)
                            assert row['error'] is None and row['case'] not in references
                            references[row['case']] = dict(path=str(path), sha256=sha(path))
                    assert set(references) == {c['name'] for c in read(panel / 'inputs.json')}
                    save(index, references)
            event(output, 'model_finished', model=model,
                  stable=all(r['stable'] for r in results if r.get('model') == model))
        event(output, 'finished', runs=len(results), stable=all(r['stable'] for r in results))
    except BaseException as exc:
        event(output, 'failed', error=repr(exc), completed_runs=len(results))
        raise
    finally:
        terminate()
        for stream in streams:
            stream.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--prepare', action='store_true')
    p.add_argument('--self-check', action='store_true')
    p.add_argument('--panel', type=Path)
    p.add_argument('--output', type=Path)
    p.add_argument('--models', nargs='+', choices=['9B', '27B', '35B-A3B'], default=['35B-A3B', '9B', '27B'])
    p.add_argument('--max-steps', type=int, choices=[5, 10], default=5)
    args = p.parse_args()
    if args.self_check:
        self_check()
        return
    assert args.output and str(args.output).startswith('/runs/')
    if args.prepare:
        prepare(args.output)
    else:
        assert args.panel and str(args.panel).startswith('/runs/')
        assert len(args.models) == len(set(args.models))
        run(args.output, args.panel, args.models, args.max_steps)


if __name__ == '__main__':
    main()
