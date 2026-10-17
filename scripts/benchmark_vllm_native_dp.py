#!/usr/bin/env python3
"""Benchmark native vLLM DP=8/TP=1 in BF16 on a single Modal allocation.

Explicit rank headers and automatic internal load balancing use the same request
bytes. Per-rank max_num_seqs=1 is enforced by the server. Token mismatches are
retained while completing a bounded first-start measurement; failing settings
are never promoted to higher concurrency or declared reproducible.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import importlib.metadata
import json
from pathlib import Path
import random
import re
import signal
import subprocess
import time
from types import SimpleNamespace
import traceback

from benchmark_qwen35_fp8 import digest, event, save
from benchmark_qwen35_throughput import Pool, balanced_tasks, make_bodies, run_pass
from benchmark_vllm_options import reset_prefix


def snapshot_metrics(endpoint, path):
    import httpx
    response = httpx.get(endpoint + '/metrics', timeout=30, trust_env=False)
    response.raise_for_status()
    path.write_text(response.text)
    counts = defaultdict(float)
    for line in response.text.splitlines():
        if line.startswith('vllm:request_success_total{'):
            match = re.search(r'engine="(\d+)"', line)
            if match:
                counts[int(match.group(1))] += float(line.rsplit(' ', 1)[1])
    return dict(counts)


def measured_pass(args, root, directory, label, endpoints, bodies, tasks, refs, *, route, phase):
    native = args.layout == 'native'
    metric_endpoints = endpoints[:1] if native else endpoints
    before = [snapshot_metrics(e, directory / f'metrics_{label}_before_{i}.txt')
              for i, e in enumerate(metric_endpoints)]
    if native and route == 'pinned':
        urls = [endpoints[0]] * 8
        headers = [{'X-data-parallel-rank': str(rank)} for rank in range(8)]
        concurrency = 1
    elif native:
        urls, headers, concurrency = endpoints, None, 8
    else:
        urls, headers, concurrency = endpoints, None, 1
    measured = run_pass(SimpleNamespace(output=root), directory, label, urls, bodies, concurrency,
                        tasks, refs, phase=phase, client_headers=headers,
                        request_timeout=args.request_timeout,
                        dynamic_routing=not native and route == 'auto')
    after = None
    deadline = time.monotonic() + 20
    while True:
        after = [snapshot_metrics(e, directory / f'metrics_{label}_after_{i}.txt')
                 for i, e in enumerate(metric_endpoints)]
        if native:
            delta = {rank: after[0].get(rank, 0) - before[0].get(rank, 0) for rank in range(8)}
        else:
            delta = {rank: sum(after[rank].values()) - sum(before[rank].values()) for rank in range(8)}
        if sum(delta.values()) == measured['samples'] or time.monotonic() >= deadline:
            break
        time.sleep(1)
    measured.update(route=route, rank_success_delta=delta,
                    all_ranks_used=all(value > 0 for value in delta.values()),
                    metric_count_matches=sum(delta.values()) == measured['samples'],
                    global_client_concurrency=8,
                    row_replica_semantics=('requested_DP_rank' if native and route == 'pinned' else
                                           'API_endpoint_index_not_actual_DP_rank' if native else 'independent_replica'))
    if route == 'pinned' and measured['samples'] and not measured['errors']:
        expected = len(tasks) // 8
        measured['routing_verified'] = all(value == expected for value in delta.values())
    else:
        measured['routing_verified'] = measured['metric_count_matches']
    save(directory / f'{label}.json', measured)
    return measured


def run_model(args, model_size, cases):
    root = args.output / model_size
    root.mkdir()
    refs = {profile: {} for profile in args.profiles}
    result = dict(model=model_size, layout=args.layout, precision='bf16', passes=[],
                  stable=False, error=None, stage='starting')
    source_bodies = {profile: make_bodies(cases, 512 if profile == 'fixed512' else 2048,
                                         fixed_output=profile == 'fixed512') for profile in args.profiles}
    def checkpoint():
        result['formal_samples'] = sum(p['samples'] for p in result['passes'] if p['phase'] != 'reference')
        result['reference_samples'] = sum(p['samples'] for p in result['passes'] if p['phase'] == 'reference')
        result['mismatches'] = sum(len(p['mismatches']) for p in result['passes'])
        save(root / 'summary.json', result)
    try:
        for restart in range(args.restarts + 1):
            directory = root / f'restart{restart}'
            directory.mkdir()
            pool = Pool(SimpleNamespace(output=root, startup_timeout=args.startup_timeout), directory)
            result.update(stage='loading', current_restart=restart)
            checkpoint()
            event(root, 'loading', restart=restart, model=model_size, layout=args.layout)
            try:
                flags = {'--gpu-memory-utilization': '0.95', '--enable-prefix-caching': None,
                         '--mamba-cache-mode': 'align', '--mm-processor-cache-gb': '4',
                         '--mm-processor-cache-type': args.mm_cache_type}
                if args.api_server_count is not None:
                    flags['--api-server-count'] = args.api_server_count
                pool.start('bf16', 1, 1 if args.layout == 'native' else 8, args.invariant, 1, 16384, 'weights',
                           model_size=model_size, data_parallel_size=8 if args.layout == 'native' else 1,
                           flags=flags,
                           env_overrides={'VLLM_SERVER_DEV_MODE': '1'})
                for profile, bodies in source_bodies.items():
                    pdir = directory / profile
                    pdir.mkdir()
                    names = list(bodies)
                    stages = [('cold_' + name, [name] * 8, 'pinned', 'reference', True) for name in names]
                    if restart == 0 and profile == 'fixed512':
                        stages.append(('pinned_mixed', balanced_tasks(names, 8, 1, 921), 'pinned', 'measure', False))
                    automatic_tasks = names * 8
                    random.Random(1020 + restart).shuffle(automatic_tasks)
                    stages.append(('automatic_mixed', automatic_tasks, 'auto', 'measure', False))
                    if restart == 0 and profile == 'fixed512':
                        reset_tasks = names * 8
                        random.Random(923).shuffle(reset_tasks)
                        stages.append(('automatic_after_reset', reset_tasks, 'auto', 'reset', True))
                    for label, tasks, route, phase, clear in stages:
                        if clear:
                            reset_prefix(pool.endpoints)
                        result.update(stage='measuring', current_profile=profile, current_pass=label)
                        checkpoint()
                        measured = measured_pass(args, root, pdir, label, pool.endpoints, bodies,
                                                 tasks, refs[profile], route=route, phase=phase)
                        result['passes'].append(dict(restart=restart, profile=profile, **measured))
                        checkpoint()
                        event(root, 'unit_finished', restart=restart, profile=profile, name=label,
                              samples=measured['samples'], mismatches=len(measured['mismatches']),
                              requests_per_minute=measured['requests_per_minute'],
                              rank_success_delta=measured['rank_success_delta'])
                        if measured['errors']:
                            raise RuntimeError(f"Request failures in {label}: {measured['errors'][:1]}")
            finally:
                pool.close()
            if any(not p['stable'] for p in result['passes']):
                result['restart_skipped_reason'] = 'Within-start token counterexample already observed; bounded first-start profiles completed.'
                break
        result['stable'] = bool(result['passes']) and all(p['stable'] and p['routing_verified'] for p in result['passes'])
    except Exception as exc:
        result.update(error=repr(exc), traceback=traceback.format_exc())
    result['stage'] = 'finished'
    checkpoint()
    event(root, 'finished', model=model_size, formal_samples=result['formal_samples'],
          reference_samples=result['reference_samples'], mismatches=result['mismatches'],
          stable=result['stable'], error=result['error'])
    return result


def main():
    signal.signal(signal.SIGTERM, signal.default_int_handler)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--models', nargs='+', choices=['9B', '27B', '35B-A3B'], default=['9B', '27B', '35B-A3B'])
    parser.add_argument('--layout', choices=['native', 'independent'], default='native')
    parser.add_argument('--api-server-count', type=int, choices=[1, 8],
                        help='Explicit frontend count for the observed native routing imbalance')
    parser.add_argument('--mm-cache-type', choices=['shm', 'lru'], default='shm',
                        help='Single API worker hit a missing SHM object during initialization')
    parser.add_argument('--inputs', type=Path, default=Path('/runs/devbox/qwen35_confirmation_20261010/inputs.json'))
    parser.add_argument('--case-names', nargs='+', default=['text', 'video_32frames', 'video_128frames', 'video_512frames'])
    parser.add_argument('--profiles', nargs='+', choices=['fixed512', 'natural2048'], default=['fixed512', 'natural2048'])
    parser.add_argument('--restarts', type=int, default=1)
    parser.add_argument('--invariant', type=int, choices=[0, 1], default=0)
    parser.add_argument('--startup-timeout', type=int, default=900)
    parser.add_argument('--request-timeout', type=int, default=300)
    args = parser.parse_args()
    if not str(args.output).startswith('/runs/') or (args.output / 'manifest.json').exists():
        raise SystemExit('Use a fresh /runs/ experiment directory')
    args.output.mkdir(parents=True, exist_ok=True)
    cases = [case for case in json.loads(args.inputs.read_text()) if case['name'] in args.case_names]
    if {case['name'] for case in cases} != set(args.case_names):
        raise SystemExit('Missing frozen inputs')
    for case in cases:
        if digest(case['messages']) != case['messages_sha256']:
            raise ValueError('Frozen input hash mismatch')
    save(args.output / 'inputs.json', cases)
    inventory = subprocess.check_output(['nvidia-smi', '--query-gpu=index,name,uuid,memory.total,driver_version', '--format=csv'], text=True)
    if inventory.count('H100') != 8:
        raise SystemExit('Expected eight actual H100 GPUs')
    sources = {}
    for name in [Path(__file__).name, 'benchmark_qwen35_throughput.py', 'benchmark_qwen35_fp8.py', 'benchmark_vllm_options.py']:
        source = (Path(__file__).parent / name).read_bytes()
        (args.output / name).write_bytes(source)
        sources[name] = hashlib.sha256(source).hexdigest()
    save(args.output / 'manifest.json', dict(arguments={k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()},
         git_commit=subprocess.check_output(['git', '-c', 'safe.directory=/repo', 'rev-parse', 'HEAD'], text=True).strip(),
         gpu_inventory=inventory, sources_sha256=sources,
         input_sha256=hashlib.sha256((args.output / 'inputs.json').read_bytes()).hexdigest(),
         versions={p: importlib.metadata.version(p) for p in ['vllm', 'torch', 'transformers']},
         protocol='Native DP8 has one public HTTP endpoint and eight core engines. API worker count is explicit or the pinned vLLM default and is audited from runtime logs. Rank headers and engine metrics audit routing. Each rank max_num_seqs=1. Fixed512 and normal-EOS2048 own separate references; no response caching. Not an accuracy benchmark.'))
    results = []
    for model in args.models:
        event(args.output, 'running', model=model, completed_models=len(results))
        results.append(run_model(args, model, cases))
        save(args.output / 'summary.json', results)
    event(args.output, 'finished', models=len(results),
          formal_samples=sum(r['formal_samples'] for r in results),
          reference_samples=sum(r['reference_samples'] for r in results))


if __name__ == '__main__':
    main()
