#!/usr/bin/env python3
"""Recheck the archived BF16 TP8 commands, full answers, CVBench, and restart."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import random
import signal
import subprocess
import time
from types import SimpleNamespace
import traceback

from benchmark_qwen35_fp8 import digest, event, save, stop_server
from benchmark_qwen35_throughput import make_bodies, run_pass
from benchmark_vllm_eval import CVBench, TokenBackend, encode_request, evaluate_pass

ROOT = Path(__file__).resolve().parents[1]
LEGACY = Path('/runs/devbox/fp8_h100_tp8_20261009_r1')
LONG_INPUTS = Path('/runs/devbox/qwen35_confirmation_20261010/inputs.json')
PANEL = Path('/runs/devbox/cvbench_vllm_panel_20261010')
ENDPOINT = 'http://127.0.0.1:8100'
ENV = {'CUDA_VISIBLE_DEVICES': '0,1,2,3,4,5,6,7', 'CUDA_DEVICE_ORDER': 'PCI_BUS_ID',
       'VLLM_BATCH_INVARIANT': '0', 'TOKENIZERS_PARALLELISM': 'false',
       'OMP_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1'}


@contextmanager
def serve(command, directory):
    import httpx
    save(directory / 'server.json', {'command': command, 'environment_overrides': ENV})
    with (directory / 'server.log').open('w') as log:
        process = subprocess.Popen(command, env={**os.environ, **ENV}, stdout=log,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        try:
            deadline = time.monotonic() + 900
            with httpx.Client(timeout=2, trust_env=False) as client:
                while True:
                    if process.poll() is not None:
                        raise RuntimeError(f'vLLM exited {process.returncode}; see {directory}/server.log')
                    try:
                        if client.get(ENDPOINT + '/health').status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    if time.monotonic() > deadline:
                        raise TimeoutError('vLLM startup exceeded 900 seconds')
                    time.sleep(3)
            yield
        finally:
            stop_server(process)


def check_command(command, model):
    assert command[:3] == ['vllm', 'serve', '/weights/Qwen3.5-' + model]
    required = {'--tensor-parallel-size': '8', '--data-parallel-size': '1',
                '--dtype': 'bfloat16', '--kv-cache-dtype': 'auto', '--seed': '0',
                '--max-num-seqs': '1', '--max-num-batched-tokens': '8192',
                '--max-model-len': '131072', '--gpu-memory-utilization': '0.85',
                '--mm-processor-cache-gb': '0', '--mm-encoder-tp-mode': 'weights'}
    for option, value in required.items():
        assert command.count(option) == 1 and command[command.index(option) + 1] == value, option
    assert '--no-enable-prefix-caching' in command


def run_model(args, model, long_bodies, selected, expected, prepared, benchmark):
    root = args.output / model
    root.mkdir()
    old = LEGACY / ('Qwen3.5-' + model + '_bf16')
    command = json.loads((old / 'config.json').read_text())['command']
    check_command(command, model)
    names = [c['name'] for c in json.loads((LEGACY / 'input_manifest.json').read_text())]
    fixed = {name: json.dumps(json.loads((old / f'request_{name}.json').read_text()), separators=(',', ':')).encode()
             for name in names}
    assert len(fixed) == 4
    archived = {}
    for line in (old / 'records.jsonl').open():
        row = json.loads(line)
        archived.setdefault(row['case'], row)
    for name, body in fixed.items():
        assert hashlib.sha256(body).hexdigest() == archived[name]['request_sha256'], name
    refs = {'fixed256': {}, 'natural8192': {}, 'cvbench': {}}
    result = {'model': model, 'passes': [], 'stage': 'starting', 'error': None, 'stable': False}

    def checkpoint():
        result['samples'] = sum(p['samples'] for p in result['passes'])
        result['mismatches'] = sum(len(p['mismatches']) for p in result['passes'])
        result['request_errors'] = sum(len(p['errors']) for p in result['passes'])
        save(root / 'summary.json', result)

    try:
        for restart in [0, 1]:
            directory = root / f'restart{restart}'
            directory.mkdir()
            result.update(stage='loading', restart=restart)
            checkpoint()
            event(root, 'loading', model=model, restart=restart)
            with serve(command, directory):
                plans = [('fixed256', 'reference' if restart == 0 else 'after_restart', list(fixed))]
                if restart == 0:
                    plans.append(('fixed256', 'ten_repeats', list(fixed) * 10))
                plans.append(('natural8192', 'reference' if restart == 0 else 'after_restart', list(long_bodies)))
                mixed = list(long_bodies) * (2 if restart == 0 else 1)
                random.Random(121000 + restart).shuffle(mixed)
                plans.append(('natural8192', 'mixed', mixed))
                for profile, label, tasks in plans:
                    pdir = directory / profile
                    pdir.mkdir(exist_ok=True)
                    result.update(stage='measuring', profile=profile, current_pass=label)
                    checkpoint()
                    measured = run_pass(SimpleNamespace(output=root), pdir, label, [ENDPOINT],
                                        fixed if profile == 'fixed256' else long_bodies, 1, tasks,
                                        refs[profile], phase=label, request_timeout=300)
                    result['passes'].append({'restart': restart, 'profile': profile, **measured})
                    checkpoint()
                    if measured['errors']:
                        raise RuntimeError(f'Request errors in {profile}/{label}')
                pdir = directory / 'cvbench'
                pdir.mkdir()
                for number in range(2 if restart == 0 else 1):
                    label = f'pass{number}'
                    result.update(stage='measuring', profile='cvbench', current_pass=label)
                    checkpoint()
                    measured = evaluate_pass(SimpleNamespace(workers=1, media_uuids=False), pdir, label,
                                             benchmark, selected, expected, TokenBackend([ENDPOINT], 1),
                                             refs['cvbench'], 122000 + 10 * restart + number, prepared)
                    result['passes'].append({'restart': restart, 'profile': 'cvbench', **measured})
                    checkpoint()
                    if measured['errors']:
                        raise RuntimeError('CVBench request/scoring error')
        result['stable'] = len(result['passes']) == 10 and all(p['stable'] for p in result['passes'])
    except Exception as exc:
        result.update(error=repr(exc), traceback=traceback.format_exc())
    result['archived_output_comparison'] = {
        name: {'request_bytes_identical': True,
               'prompt_tokens_identical': refs['fixed256'][name]['prompt_token_ids_sha256'] == row['prompt_token_ids_sha256'],
               'output_tokens_identical': refs['fixed256'][name]['token_ids'] == row['token_ids']}
        for name, row in archived.items() if name in refs['fixed256']}
    result['stage'] = 'finished'
    checkpoint()
    event(root, 'finished', model=model, samples=result['samples'], mismatches=result['mismatches'],
          stable=result['stable'], error=result['error'])
    return result


def main():
    signal.signal(signal.SIGTERM, signal.default_int_handler)
    signal.signal(signal.SIGINT, signal.default_int_handler)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--models', nargs='+', choices=['9B', '27B', '35B-A3B'], default=['9B', '27B', '35B-A3B'])
    args = parser.parse_args()
    if not str(args.output).startswith('/runs/') or (args.output / 'manifest.json').exists():
        raise SystemExit('Use a fresh /runs/ experiment directory')
    args.output.mkdir(parents=True, exist_ok=True)
    old_manifest = json.loads((LEGACY / 'manifest.json').read_text())
    old_source = (LEGACY / 'benchmark_source.py').read_bytes()
    assert hashlib.sha256(old_source).hexdigest() == old_manifest['script_sha256']
    versions = {p: importlib.metadata.version(p) for p in ['vllm', 'torch', 'transformers']}
    assert versions == old_manifest['versions'], versions
    inventory = subprocess.check_output(['nvidia-smi', '--query-gpu=index,name,uuid,memory.total,driver_version', '--format=csv'], text=True)
    assert inventory.count('H100') == 8, inventory
    sources = {}
    for path in [Path(__file__), *(ROOT / 'scripts').glob('benchmark_*.py'), *(ROOT / 'eval/e2e_eval/harness').glob('*.py')]:
        relative = path.relative_to(ROOT)
        target = args.output / 'source' / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        data = path.read_bytes()
        target.write_bytes(data)
        sources[str(relative)] = hashlib.sha256(data).hexdigest()
    save(args.output / 'manifest.json', {'arguments': {'output': str(args.output), 'models': args.models},
         'git_commit': subprocess.check_output(['git', '-c', 'safe.directory=/repo', 'rev-parse', 'HEAD'], text=True).strip(),
         'versions': versions, 'gpu_inventory': inventory, 'sources_sha256': sources,
         'legacy_manifest': old_manifest, 'environment_overrides': ENV,
         'protocol': 'Exact archived BF16 TP8 server argv and fixed256 request bytes. C1 throughout; normal EOS max8192 on eight probes; real CVBench 30-item development panel. Every model server restarts once. All requests recomputed; no response caching. Not full MVAgent rollout validation.'})
    event(args.output, 'preparing')
    long_cases = json.loads(LONG_INPUTS.read_text())
    panel_cases = json.loads((PANEL / 'inputs.json').read_text())
    selected = json.loads((PANEL / 'selection.json').read_text())
    assert len(long_cases) == 8 and len(panel_cases) == len(selected) == 30
    for case in long_cases + panel_cases:
        assert digest(case['messages']) == case['messages_sha256'], case['name']
    input_files = [LONG_INPUTS, PANEL / 'inputs.json', PANEL / 'selection.json', LEGACY / 'inputs.json']
    save(args.output / 'input_provenance.json', {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in input_files})
    expected = {c['name']: c['messages_sha256'] for c in panel_cases}
    assert set(expected) == {item['sample_id'] for item in selected}
    prepared = {c['name']: {'wire': encode_request(c['messages'], c['generation']),
                          **{k: c[k] for k in ['generation', 'messages_sha256', 'media']}} for c in panel_cases}
    long_bodies = make_bodies(long_cases, 8192, fixed_output=False)
    del panel_cases, long_cases
    benchmark = CVBench(data_root=Path('/assets'), frames=512, max_side=448)
    results = []
    for model in args.models:
        event(args.output, 'running', model=model, completed_models=len(results))
        results.append(run_model(args, model, long_bodies, selected, expected, prepared, benchmark))
        save(args.output / 'summary.json', results)
    event(args.output, 'finished', samples=sum(r['samples'] for r in results),
          models=len(results), stable=all(r['stable'] for r in results))


if __name__ == '__main__':
    main()
