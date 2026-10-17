#!/usr/bin/env python3
"""Run the requested TP experiment stages on the already allocated eight GPUs."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import time

from benchmark_qwen35_fp8 import event, save


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--phase', required=True, choices=['tp8-e2e', 'tp1'])
    p.add_argument('--output', required=True, type=Path)
    p.add_argument('--executor', choices=['mp', 'external_launcher'], default='mp')
    args = p.parse_args()
    assert str(args.output).startswith('/runs/')
    args.output.mkdir(parents=True, exist_ok=True)
    processes, results = [], []

    def start(model, tp, suffix, reference=None, gpu=None, barrier=None):
        tag = {'9B': '9b', '27B': '27b', '35B-A3B': '35b'}[model]
        if tp == 8 and args.executor == 'external_launcher':
            suffix = 'ext_' + suffix
        root = Path(f'/runs/devbox/tp_compare_{tag}_tp{tp}_{suffix}_20261011')
        if (root / 'summary.json').exists():
            # Preserve completed negative results; never retry them in place.
            return root, None, None
        assert not (root / 'manifest.json').exists(), f'Existing unfinished run: {root}'
        root.mkdir(parents=True, exist_ok=True)
        cmd = ['python', 'scripts/benchmark_vllm_repro_tp.py', '--model', model,
               '--tp', str(tp), '--output', str(root)]
        if tp == 8 and args.executor == 'external_launcher':
            cmd = ['python', '-m', 'torch.distributed.run', '--standalone', '--nproc_per_node=8'] + cmd[1:]
            cmd += ['--executor', 'external_launcher']
        if reference:
            cmd += ['--reference', str(reference)]
        if barrier:
            cmd += ['--barrier-dir', str(barrier)]
        env = {**os.environ, 'CUDA_VISIBLE_DEVICES': str(gpu) if tp == 1 else '0,1,2,3,4,5,6,7',
               'PYTHONPATH': '/repo/src:/repo/scripts', 'OMP_NUM_THREADS': '1',
               'MKL_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1'}
        stream = (root / 'job.log').open('a')
        proc = subprocess.Popen(cmd, env=env, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
        processes.append(proc)
        event(args.output, 'child_started', root=str(root), pid=proc.pid, model=model, tp=tp)
        return root, proc, stream

    def finish(item):
        root, proc, stream = item
        if proc:
            try:
                code = proc.wait(timeout=3600)
            finally:
                stream.close()
            assert (root / 'summary.json').exists(), f'{root}: exit {code} without a result'
        row = json.loads((root / 'summary.json').read_text())
        if proc:
            assert code == 0 or row['error'], f'{root}: unrecorded failure, exit {code}'
        results.append(dict(root=str(root), **row))
        save(args.output / 'summary.json', results)
        event(args.output, 'child_finished', root=str(root), responses=row['responses'],
              stable=row['stable'], differences=row['differences'], error=row['error'])
        return row

    try:
        for model in ['9B', '27B', '35B-A3B']:
            if args.phase == 'tp8-e2e':
                first = start(model, 8, 'p1')
                row = finish(first)
                if row['stable']:
                    finish(start(model, 8, 'p2', reference=first[0]))
            else:
                first = start(model, 1, 'single', gpu=0)
                row = finish(first)
                if not row['stable']:
                    continue
                barrier = args.output / (model + '_barrier')
                assert not barrier.exists()
                pool = [start(model, 1, f'pool{gpu}', reference=first[0], gpu=gpu, barrier=barrier)
                        for gpu in range(8)]
                deadline = time.monotonic() + 1000
                while len(list(barrier.glob('*.ready'))) < 8:
                    assert all(proc.poll() is None for _, proc, _ in pool), 'Replica exited before barrier'
                    if time.monotonic() > deadline:
                        raise TimeoutError('Eight replicas did not become ready')
                    time.sleep(2)
                (barrier / 'go').touch()
                for item in pool:
                    finish(item)
        event(args.output, 'finished', runs=len(results), stable=all(r['stable'] for r in results))
    finally:
        for proc in processes:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
        for proc in processes:
            if proc.poll() is None:
                try:
                    proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)


if __name__ == '__main__':
    main()
