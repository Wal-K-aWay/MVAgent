#!/usr/bin/env python3
"""Recheck independent BF16 TP1 replicas through all three real E2E adapters.

Run on the Modal devbox. Rebuild media on every pass; never reuse model answers.
CCQA outputs are saved for the project's separate local-judge scoring stage.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import random
import signal
import subprocess
import sys
import time
import traceback
from types import SimpleNamespace

from benchmark_qwen35_fp8 import digest, event, save
from benchmark_qwen35_throughput import Pool
from benchmark_vllm_eval import TokenBackend, encode_request
from benchmark_vllm_options import VARIANTS

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'eval/e2e_eval'))
from harness.crossvid import CrossVid
from harness.cvbench import CVBench, QUESTIONS
from harness.media import CACHE_ENV
from harness.mvu_eval import MVUEval

SPLIT = ROOT / 'configs/skill_evolution/splits/crossvid_lite2500_eval_seed20260919.json'
OLD_PANEL = Path('/runs/devbox/cvbench_vllm_panel_20261010/selection.json')
MODELS = ['9B', '27B', '35B-A3B']
SEED = 20261011


def compare(reference, current):
    changed_input = any(reference[k] != current[k] for k in
                        ['request_sha256', 'prompt_token_ids_sha256'])
    a, b = reference['token_ids'], current['token_ids']
    position = next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))
    return {'input_changed': changed_input, 'tokens_changed': a != b,
            'first_different_token_1based': position + 1 if a != b else None}


def panel(benchmarks):
    cv_ids = {r['sample_id'] for r in json.loads(OLD_PANEL.read_text())}
    lite_ids = {r['sample_id'] for r in json.loads(SPLIT.read_text())['samples']}
    assert len(cv_ids) == 30 and len(lite_ids) == 2500
    selected = []
    for name, benchmark in benchmarks.items():
        groups = defaultdict(list)
        for item in benchmark.items:
            sid = item['sample_id']
            if name == 'cvbench' and sid not in cv_ids:
                continue
            if name == 'crossvid' and sid not in lite_ids:
                continue
            groups[item['task']].append(item)
        for task, items in sorted(groups.items()):
            items = sorted(items, key=lambda r: r['sample_id'])
            random.Random(SEED).shuffle(items)
            assert len(items) >= 2, (name, task)
            selected.extend({'benchmark': name, **item} for item in items[:2])
    assert Counter(r['benchmark'] for r in selected) == {'cvbench': 30, 'mvu_eval': 16, 'crossvid': 20}
    assert len({r['sample_id'] for r in selected}) == 66
    return selected


class RecordBackend:
    def __init__(self, backend, wire_path):
        self.backend, self.wire_path, self.calls = backend, wire_path, 0

    def complete(self, messages, **generation):
        self.calls += 1
        if self.calls != 1:
            raise RuntimeError('Adapter retried its model call; do not hide the failed attempt')
        assert generation['temperature'] == 0
        wire = encode_request(messages, generation)
        if self.wire_path is not None:
            self.wire_path.write_bytes(wire)
        return self.backend.send(wire, digest(messages), generation)


def measure(root, benchmarks, selected, endpoints, references, pass_index):
    label = ['reference', 'same_gpu_repeat', 'rotated_gpu', 'after_restart'][pass_index]
    directory = root / label
    directory.mkdir()
    os.environ[CACHE_ENV] = str(directory / 'media_cache')
    backends = [TokenBackend([endpoint], 1) for endpoint in endpoints]
    offset = [0, 0, 1, 2][pass_index]
    indexed = list(enumerate(selected))
    random.Random(SEED + pass_index).shuffle(indexed)
    raw, errors, differences = [], [], []

    def infer(index, item):
        slot = (index + offset) % len(endpoints)
        wire_path = (root / 'requests' / (item['sample_id'] + '.json')) if pass_index == 0 else None
        backend = RecordBackend(backends[slot], wire_path)
        started = time.perf_counter()
        record = benchmarks[item['benchmark']].infer(item, backend)
        assert backend.calls == 1
        record['request']['replica'] = slot
        return {'sample_id': item['sample_id'], 'benchmark': item['benchmark'], 'task': item['task'],
                'pass': label, 'seconds_with_media': time.perf_counter() - started, **record}

    started = time.perf_counter()
    with (directory / 'raw.jsonl').open('a', buffering=1) as stream, ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(infer, index, item): item for index, item in indexed}
        for future in as_completed(futures):
            item = futures[future]
            try:
                record = future.result()
                stream.write(json.dumps(record) + '\n')
                raw.append(record)
                sid, request = item['sample_id'], record['request']
                if sid not in references:
                    if pass_index != 0:
                        raise RuntimeError('No successful first-pass reference for ' + sid)
                    references[sid] = {k: request[k] for k in
                                      ['token_ids', 'request_sha256', 'prompt_token_ids_sha256']}
                difference = compare(references[sid], request)
                if difference['input_changed'] or difference['tokens_changed']:
                    differences.append({'sample_id': sid, 'replica': request['replica'], **difference})
                if item['benchmark'] == 'crossvid' and item['task'] == 'CCQA':
                    record['scoring_status'] = 'deferred_local_judge'
                else:
                    record['score'] = benchmarks[item['benchmark']].score(item, record['output'])
                    record['scoring_status'] = 'ok'
                event(root, 'measuring', pass_name=label, samples_this_pass=len(raw),
                      differences=len(differences), errors=len(errors), sample_id=sid)
            except Exception as exc:
                errors.append({'sample_id': item['sample_id'], 'error': repr(exc),
                               'traceback': traceback.format_exc()})
                save(directory / 'errors.json', errors)
    result = {'name': label, 'samples': len(raw), 'expected_samples': len(selected),
              'seconds': time.perf_counter() - started, 'differences': differences, 'errors': errors,
              'stable': len(raw) == len(selected) and not differences and not errors,
              'by_benchmark': {name: {'samples': sum(r['benchmark'] == name for r in raw),
                                    'differences': sum(d['sample_id'].startswith(name + ':') for d in differences)}
                               for name in benchmarks}}
    save(directory / 'scored.json', raw)
    save(directory / 'summary.json', result)
    save(root / 'references.json', references)
    return result


def run_model(output, name, benchmarks, selected):
    root = output / name
    (root / 'requests').mkdir(parents=True)
    references, passes = {}, []
    result = {'model': name, 'stage': 'starting', 'passes': passes, 'error': None, 'stable': False}

    def checkpoint():
        result.update(samples=sum(p['samples'] for p in passes),
                      differences=sum(len(p['differences']) for p in passes),
                      request_errors=sum(len(p['errors']) for p in passes))
        save(root / 'summary.json', result)

    try:
        for restart, plans in [(0, [0, 1, 2]), (1, [3])]:
            directory = root / f'servers_restart{restart}'
            directory.mkdir()
            result.update(stage='loading', restart=restart)
            checkpoint()
            pool = Pool(SimpleNamespace(output=root, startup_timeout=900), directory)
            try:
                cfg = VARIANTS['bf16_prefix']
                pool.start('bf16', 1, 8, 0, 8, 16384, 'weights', model_size=name,
                           flags=cfg['flags'], env_overrides=cfg['env'])
                for index in plans:
                    result.update(stage='measuring', pass_index=index)
                    checkpoint()
                    passes.append(measure(root, benchmarks, selected, pool.endpoints, references, index))
                    checkpoint()
            finally:
                pool.close()
        result['stable'] = len(passes) == 4 and all(p['stable'] for p in passes)
    except Exception as exc:
        result.update(error=repr(exc), traceback=traceback.format_exc())
    result['stage'] = 'finished'
    checkpoint()
    event(output, 'model_finished', model=name, samples=result['samples'],
          stable=result['stable'], differences=result['differences'], error=result['error'])
    return result


def self_check():
    ref = {'request_sha256': 'r', 'prompt_token_ids_sha256': 'p', 'token_ids': [1, 2, 3]}
    assert compare(ref, dict(ref)) == {'input_changed': False, 'tokens_changed': False,
                                     'first_different_token_1based': None}
    assert compare(ref, {**ref, 'token_ids': [1, 9, 3]})['first_different_token_1based'] == 2
    assert compare(ref, {**ref, 'token_ids': [1, 2]})['first_different_token_1based'] == 3
    assert compare(ref, {**ref, 'request_sha256': 'changed'})['input_changed']
    for offset in [0, 1, 2]:
        assert set((index + offset) % 8 for index in range(66)) == set(range(8))
    print('Exact-token, changed-input, length, and replica-coverage self-check passed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--models', nargs='+', choices=MODELS, default=MODELS)
    parser.add_argument('--self-check', action='store_true')
    args = parser.parse_args()
    if args.self_check:
        self_check()
        return
    if args.output is None or not str(args.output).startswith('/runs/') or (args.output / 'manifest.json').exists():
        raise SystemExit('Use a fresh /runs/ output directory')
    signal.signal(signal.SIGTERM, signal.default_int_handler)
    args.output.mkdir(parents=True, exist_ok=True)
    inventory = subprocess.check_output(['nvidia-smi', '--query-gpu=index,name,uuid,memory.total,driver_version', '--format=csv'], text=True)
    assert inventory.count('H100') == 8
    sources = [Path(__file__), *sorted((ROOT / 'scripts').glob('benchmark_*.py')),
               *sorted((ROOT / 'eval/e2e_eval').rglob('*.py')), *sorted((ROOT / 'eval/e2e_eval').rglob('*.yaml')), SPLIT, QUESTIONS]
    hashes = {}
    for path in sources:
        data = path.read_bytes()
        target = args.output / 'source' / path.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        hashes[str(path.relative_to(ROOT))] = hashlib.sha256(data).hexdigest()
    save(args.output / 'manifest.json', {'models': args.models, 'gpu_inventory': inventory,
         'versions': {p: importlib.metadata.version(p) for p in ['vllm', 'torch', 'transformers']},
         'git_commit': subprocess.check_output(['git', '-c', 'safe.directory=/repo', 'rev-parse', 'HEAD'], text=True).strip(),
         'sources_sha256': hashes, 'variant': VARIANTS['bf16_prefix'],
         'protocol': '8 independent TP1/DP1 BF16 full models, max_num_seqs8, each C1; 66 actual E2E questions, four passes; rebuild media every pass; same GPU repeat, rotated GPU, complete service restart; no response cache. CCQA judging deferred.'})
    shared = dict(data_root=Path('/assets'), frames=512, max_side=448)
    benchmarks = {'cvbench': CVBench(**shared), 'mvu_eval': MVUEval(**shared), 'crossvid': CrossVid(**shared)}
    selected = panel(benchmarks)
    save(args.output / 'selection.json', selected)
    save(args.output / 'protocols.json', {name: b.protocol() for name, b in benchmarks.items()})
    save(args.output / 'populations.json', {name: dict(Counter(i['task'] for i in b.items)) for name, b in benchmarks.items()})
    results = []
    for name in args.models:
        event(args.output, 'running', model=name, completed_models=len(results))
        results.append(run_model(args.output, name, benchmarks, selected))
        save(args.output / 'summary.json', results)
    event(args.output, 'finished', samples=sum(r['samples'] for r in results),
          stable=all(r['stable'] for r in results))


if __name__ == '__main__':
    main()
