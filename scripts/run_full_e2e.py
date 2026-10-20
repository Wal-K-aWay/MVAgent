#!/usr/bin/env python3
"""Run the three BF16 E2E baselines unattended on one eight-H100 Modal sandbox."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import random
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
MODELS = ['9B', '27B', '35B-A3B']
BENCHMARKS = ['cvbench', 'mvu_eval', 'crossvid']
RANKS = 8
SPLIT = Path('configs/skill_evolution/splits/crossvid_lite2500_eval_seed20260919.json')


def now():
    return datetime.now(timezone.utc).isoformat()


def read(path):
    return json.loads(path.read_text())


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    tmp.replace(path)


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def shards(items, count=RANKS):
    groups = defaultdict(list)
    for item in items:
        groups[item['task']].append(item['sample_id'])
    result = [[] for _ in range(count)]
    for task, ids in sorted(groups.items()):
        random.Random(f'20261012:{task}').shuffle(ids)
        for sid in ids:
            rank = min(range(count), key=lambda r: len(result[r]))
            result[rank].append(sid)
    assert sum(map(len, result)) == len({sid for group in result for sid in group}) == len(items)
    return result


def self_check():
    items = [dict(sample_id=str(i), task=str(i % 3)) for i in range(97)]
    groups = shards(items)
    assert groups == shards(items)
    assert max(map(len, groups)) - min(map(len, groups)) <= 1
    split = read(ROOT / SPLIT)['samples']
    assert len(split) == len({r['sample_id'] for r in split}) == 2500
    assert {r['sample_id'].split(':')[1] for r in split} == set('BU CC CCQA FSA MOC MSR NC PEA PI PSS'.split())
    with tempfile.TemporaryDirectory() as tmp:
        output = Path(tmp)
        (output / 'frozen_repo').symlink_to(ROOT, target_is_directory=True)
        freeze(output)
        info = dict(selection={name: [f'{name}:{rank}' for rank in range(RANKS)] for name in BENCHMARKS}, unavailable=[])
        for rank in range(RANKS):
            target = output / 'test' / f'rank{rank}'
            write(target / 'manifest.json', dict(identity=dict(source={}, model={'name': 'test'}, protocol={}, benchmarks={}, config={}), runs=[]))
            (target / 'source').mkdir()
            for name in BENCHMARKS:
                path = target / 'raw' / f'{name}.jsonl'
                path.parent.mkdir(exist_ok=True)
                path.write_text(json.dumps(dict(sample_id=f'{name}:{rank}', status='ok', seconds=1,
                    request=dict(token_ids=[1], usage={'completion_tokens': 1}, worker={'forward_calls': 1}, input_sha256=f'{name}:{rank}')))+'\n')
        merge(output, info, 'test')
        assert read(output / 'test/selection.json') == info['selection']
        assert len(read(output / 'test/input_audit.json')['input_sha256']) == 24
        assert len((output / 'test/raw/crossvid.jsonl').read_text().splitlines()) == RANKS
        path = output / 'test/rank1/manifest.json'
        wrong = read(path)
        wrong['identity']['model'] = {'name': 'different'}
        write(path, wrong)
        try:
            merge(output, info, 'test')
        except AssertionError:
            pass
        else:
            raise AssertionError('Merging different model identities must fail')
    print('Deterministic shards, Lite2500, merge coverage and identity guards passed', flush=True)


def freeze(output):
    frozen = output / 'frozen_repo'
    if ROOT == frozen.resolve():
        return
    if not frozen.exists():
        temporary = output / 'frozen_repo.tmp'
        if temporary.exists():
            shutil.rmtree(temporary)
        temporary.mkdir(parents=True)
        for name in ['src', 'scripts', 'eval', 'configs', '.git']:
            shutil.copytree(ROOT / name, temporary / name, ignore=shutil.ignore_patterns('__pycache__', '.cache'))
        for name in ['requirements.txt', 'demo.py']:
            shutil.copy2(ROOT / name, temporary / name)
        temporary.rename(frozen)
    os.execv(sys.executable, [sys.executable, str(frozen / 'scripts/run_full_e2e.py'), '--output', str(output), '--models', *MODELS])


def prepare(output):
    path = output / 'manifest.json'
    if path.exists():
        info = read(path)
        assert info['models'] == MODELS, 'Use the original model selection when resuming'
        return info
    sys.path.insert(0, str(ROOT / 'eval/e2e_eval'))
    from run import build_benchmarks, source_hashes, vendored_hashes
    from harness.mvu_eval import OFFICIAL_INSTRUCTION
    config = dict(benchmarks=BENCHMARKS, frames=512, max_side=448, data_root='/assets',
                  crossvid_tasks='BU CC CCQA FSA MOC MSR NC PEA PI PSS'.split(), limit=None, ids={})
    benchmarks = build_benchmarks(config)
    wanted = {r['sample_id'] for r in read(ROOT / SPLIT)['samples']}
    selection, unavailable = {}, []
    bad = Path('/assets/cvbench/125/RQorrnJIc2Q.mp4')
    broken = {'cvbench:64', 'cvbench:65', 'cvbench:66'} if bad.stat().st_size == 26214400 else set()
    for name, benchmark in benchmarks.items():
        items = [row for row in benchmark.items if name != 'crossvid' or row['sample_id'] in wanted]
        selection[name] = [row['sample_id'] for row in items]
        write(output / 'selection' / f'{name}.json', selection[name])
        if name == 'cvbench':
            for row in items:
                if row['sample_id'] in broken:
                    assert '125/RQorrnJIc2Q.mp4' in row['row'].values()
                    unavailable.append(dict(sample_id=row['sample_id'], task=row['task'], status='error',
                        error='Known truncated source video (26214400 bytes); decoder/model not retried. See known_unavailable.json.',
                        seconds=0, finished_at=now()))
        groups = shards([row for row in items if row['sample_id'] not in broken])
        for rank, ids in enumerate(groups):
            write(output / 'selection' / f'rank{rank}' / f'{name}.json', ids)
    assert {k: len(v) for k, v in selection.items()} == dict(cvbench=1000, mvu_eval=1824, crossvid=2500)
    assert set(selection['crossvid']) == wanted
    write(output / 'known_unavailable.json', dict(source=str(bad), size=bad.stat().st_size, records=unavailable))
    info = dict(created_at=now(), models=MODELS, ranks=RANKS, selection=selection,
                selection_counts={k: len(v) for k, v in selection.items()}, unavailable=unavailable,
                config=config, split=str(SPLIT), split_sha256=sha(ROOT / SPLIT),
                source=source_hashes(), vendored=vendored_hashes(), driver_sha256=sha(Path(__file__)),
                commit=subprocess.check_output(['git', '-c', f'safe.directory={ROOT}', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip(),
                mvu_instruction=OFFICIAL_INSTRUCTION, skill_library=None, judge='Qwen3-30B-A3B-Instruct-2507',
                input_policy='One serial CLI per GPU and per-rank frame cache shared across all three models; first-seen SHA bound and checked.')
    write(path, info)
    return info


def launch(command, log, env=None):
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open('w') as stream:
        return subprocess.Popen([str(arg) for arg in command], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
            env={**os.environ, 'PYTHONPATH': str(ROOT / 'src'), **(env or {})}, start_new_session=True)


def stop(process):
    if process is None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=30)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=10)


def rows_in(directory):
    result = {}
    for path in directory.glob('rank*/raw/*.jsonl'):
        for line in path.read_text().splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue  # The writer can still be appending its last line.
            sid = row['sample_id']
            if row['status'] == 'ok' or result.get(sid, {}).get('status') != 'ok':
                result[sid] = row
    return result


def counts(directory):
    rows = rows_in(directory)
    by_benchmark = {name: dict(ok=0, error=0, mean_seconds=None) for name in BENCHMARKS}
    for name in BENCHMARKS:
        group = [row for sid, row in rows.items() if sid.startswith(name + ':')]
        good = [row for row in group if row['status'] == 'ok']
        by_benchmark[name] = dict(ok=len(good), error=len(group)-len(good),
            mean_seconds=sum(r['seconds'] for r in good)/len(good) if good else None)
    return dict(ok=sum(row['status'] == 'ok' for row in rows.values()),
                error=sum(row['status'] != 'ok' for row in rows.values()), by_benchmark=by_benchmark)


def progress(output, state):
    state['updated_at'] = now()
    state['models'] = {model: {**state.get('models', {}).get(model, {}), **counts(output / model)} for model in MODELS}
    write(output / 'progress.json', state)
    print(json.dumps(dict(phase=state['phase'], model=state.get('model'),
        ok={model: row['ok'] for model, row in state['models'].items()}, updated_at=state['updated_at'])), flush=True)


def ready(pool, ports, timeout=1200):
    pending, deadline = set(ports), time.monotonic()+timeout
    while pending:
        if pool.poll() is not None:
            raise RuntimeError(f'Server pool exited: {pool.returncode}')
        for port in list(pending):
            try:
                with urllib.request.urlopen(f'http://127.0.0.1:{port}/v1/models', timeout=2):
                    pending.remove(port)
            except OSError:
                pass
        if time.monotonic() > deadline:
            raise TimeoutError(f'Server readiness timeout: {sorted(pending)}')
        time.sleep(5)


def infer_model(output, info, state, model):
    target = output / model
    expected = sum(info['selection_counts'].values()) - len(info['unavailable'])
    if counts(target)['ok'] == expected:
        return
    for attempt in range(2):
        epoch = str(time.time_ns())
        state.update(phase='loading', model=model, epoch=epoch, attempt=attempt)
        progress(output, state)
        logs = target / 'servers' / epoch
        pool, clients = None, []
        try:
            pool = launch([sys.executable, 'eval/e2e_eval/serve.py', '--model', f'/weights/Qwen3.5-{model}',
                '--gpus', '0-7', '--port', '8100', '--log-dir', logs], logs / 'pool.log')
            ready(pool, range(8100, 8108))
            state.update(phase='inference', phase_started_at=now())
            for rank in range(RANKS):
                args = [sys.executable, 'eval/e2e_eval/run.py', 'infer', '--output', target / f'rank{rank}',
                    '--endpoints', str(8100+rank), '--benchmarks', ','.join(BENCHMARKS), '--workers', '1',
                    '--retries', '1', '--media-cache-dir', output / 'media' / f'rank{rank}']
                for benchmark in BENCHMARKS:
                    args += ['--ids', f'{benchmark}={output / "selection" / f"rank{rank}" / (benchmark+".json")}']
                clients.append(launch(args, target / f'infer_{epoch}_rank{rank}.log'))
            last_count, last_change = -1, time.monotonic()
            while any(p.poll() is None for p in clients):
                progress(output, state)
                completed = state['models'][model]['ok'] + state['models'][model]['error']
                if completed != last_count:
                    last_count, last_change = completed, time.monotonic()
                if pool.poll() is not None:
                    raise RuntimeError('Model server pool exited during inference')
                if time.monotonic()-last_change > 2400:
                    raise TimeoutError('No completed question for 40 minutes')
                time.sleep(30)
            progress(output, state)
            if state['models'][model]['ok'] == expected:
                return
            state['last_error'] = f'{model}: incomplete inference after attempt {attempt+1}'
        except Exception as exc:
            state['last_error'] = repr(exc)
            print(traceback.format_exc(), flush=True)
        finally:
            for child in clients:
                stop(child)
            stop(pool)
        progress(output, state)
    state.setdefault('inference_failures', []).append(model)


def merge(output, info, model):
    target = output / model
    manifests = [read(path) for path in sorted(target.glob('rank*/manifest.json'))]
    if len(manifests) != RANKS:
        raise RuntimeError(f'{model}: cannot merge {len(manifests)} shard manifests')
    merged = copy.deepcopy(manifests[0])
    for other in manifests[1:]:
        for key in ['source', 'model', 'protocol', 'benchmarks']:
            assert other['identity'][key] == merged['identity'][key], (model, key)
    merged['identity']['config']['ids'] = {name: str(output/'selection'/f'{name}.json') for name in BENCHMARKS}
    merged['identity']['selection'] = {name: dict(count=len(ids), sha256=hashlib.sha256('\n'.join(sorted(ids)).encode()).hexdigest())
                                     for name, ids in info['selection'].items()}
    merged['runs'] = [{**entry, 'shard_output': f'rank{rank}'} for rank, m in enumerate(manifests) for entry in m['runs']]
    merged['aggregation'] = dict(kind='disjoint fixed GPU shards; original manifests and raw records retained',
        sources={str(path.relative_to(target)): sha(path) for path in sorted(target.glob('rank*/manifest.json'))})
    shutil.copytree(target / 'rank0/source', target / 'source', dirs_exist_ok=True)
    rows = rows_in(target)
    audit = {}
    for sid, row in rows.items():
        if row['status'] != 'ok':
            continue
        req = row['request']
        assert len(req['token_ids']) == req['usage']['completion_tokens'] and req['worker']['forward_calls'] > 0
        audit[sid] = req['input_sha256']
    for row in info['unavailable']:
        rows[row['sample_id']] = row
    for name, ids in info['selection'].items():
        path = target / 'raw' / f'{name}.jsonl'
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('w') as handle:
            for sid in ids:
                row = rows.get(sid, dict(sample_id=sid, status='error', error='No completed shard record', seconds=0, finished_at=now()))
                handle.write(json.dumps(row, ensure_ascii=False)+'\n')
    write(target / 'input_audit.json', dict(input_sha256=audit))
    write(target / 'selection.json', info['selection'])
    write(target / 'manifest.json', merged)


def score_all(output, state):
    state.update(phase='judge_loading', model=None)
    progress(output, state)
    logs = output / 'judge' / str(time.time_ns())
    starter = launch(['bash', 'eval/agent_eval/serve_ccqa_judge.sh', '0-7', '8100'], logs / 'startup.log',
                     env={'JUDGE_LOG_DIR': str(logs)})
    try:
        code = starter.wait(timeout=1500)
        if code:
            raise RuntimeError(f'Judge startup exited {code}')
        for model in MODELS:
            if not (output / model / 'manifest.json').exists():
                continue
            state.update(phase='scoring', model=model)
            process = launch([sys.executable, 'eval/e2e_eval/run.py', 'score', '--output', output / model,
                '--judge-endpoints', '8100-8107'], output / model / 'score.log')
            try:
                while process.poll() is None:
                    progress(output, state)
                    time.sleep(30)
            finally:
                stop(process)
            summary = read(output / model / 'summary.json')
            state['models'][model]['score_failures'] = summary['failures']
            state['models'][model]['scores'] = {name: {k: v for k, v in summary[name].items()
                if k in ['accuracy', 'o_avg', 'robust_accuracy', 'robust_o_avg', 'complete', 'selected', 'inferred', 'scored', 'scored_mean']}
                for name in BENCHMARKS}
    finally:
        stop(starter)


def main():
    global MODELS
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--models', nargs='+', choices=MODELS, default=MODELS)
    parser.add_argument('--self-check', action='store_true')
    args = parser.parse_args()
    MODELS = list(dict.fromkeys(args.models))
    if args.self_check:
        self_check()
        return
    assert args.output and args.output.is_relative_to('/runs')
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    freeze(output)
    state = dict(started_at=now(), phase='preparing', models={})
    try:
        self_check()
        info = prepare(output)
        state.update(selection_counts=info['selection_counts'], known_unavailable=[r['sample_id'] for r in info['unavailable']],
                     target_responses_per_model=sum(info['selection_counts'].values())-len(info['unavailable']))
        inventory = subprocess.check_output(['nvidia-smi', '--query-gpu=name,uuid', '--format=csv,noheader'], text=True)
        assert len(inventory.splitlines()) == RANKS and all('H100' in line for line in inventory.splitlines())
        (output / f'gpu_inventory_{time.time_ns()}.txt').write_text(inventory)
        for model in MODELS:
            infer_model(output, info, state, model)
            try:
                merge(output, info, model)
            except Exception as exc:
                state.setdefault('merge_failures', {})[model] = repr(exc)
        score_all(output, state)
        state['phase'] = 'completed_with_recorded_failures' if (info['unavailable'] or state.get('inference_failures') or state.get('merge_failures')
            or any(row.get('score_failures') for row in state['models'].values())) else 'completed'
    except Exception as exc:
        state.update(phase='failed', last_error=repr(exc), traceback=traceback.format_exc())
        print(state['traceback'], flush=True)
    finally:
        state['finished_at'] = now()
        progress(output, state)
        (output / 'report.md').write_text('# Full E2E run\n\n```json\n'+json.dumps(state, ensure_ascii=False, indent=2)+'\n```\n')
        # The existing sandbox watchdog releases all GPUs once its sole registered job finishes.
        (Path('/work/jobs') / f'{output.name}.pid').unlink(missing_ok=True)
        os.utime('/work/heartbeat', (0, 0))


if __name__ == '__main__':
    main()
