"""Controlled clipping/routing comparison; experiment hooks never enter Runtime."""
import argparse
from collections import Counter, defaultdict
from functools import partial
import hashlib
import json
from pathlib import Path
import random
import shutil
import statistics
import subprocess
import sys
import time

REPO = Path(__file__).resolve().parents[2]
ARMS = ('slow_fixed', 'fast_dynamic', 'fast_fixed', 'slow_dynamic')


def write(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')
    temporary.replace(path)


def benchmark_worker(connection, pools, media_slots, media_cache, *, fixed, counter):
    from models.pool import ModelPool
    from mvagent.batch import question_worker
    if fixed:
        with counter.get_lock():
            index = counter.value
            counter.value += 1
        # Two of six workers bind to each of three services for their full lifetime.
        pools = {name: ModelPool(name, [pool.replicas[index % len(pool.replicas)]],
                    pool.identity, root=pool.root, runtime_config=pool.runtime_config)
                 for name, pool in pools.items()}
    question_worker(connection, pools, media_slots, media_cache)


def run_arm(root, arm, repeat):
    import yaml
    source = root / 'sources' / arm.split('_')[0]
    sys.path.insert(0, str(source))
    from mvagent.batch import BatchExecutor, ExecutionConfig
    from skill_evolution.infra.benchmarks import load_multibench_records, ChoiceScorer, extract_prediction
    from profile_rollout import analyze, service_metrics

    directory = root / f'{repeat}_{arm}'
    directory.mkdir()
    settings = yaml.safe_load((root / 'execution.yaml').read_text())
    config = yaml.safe_load((root / 'runtime.yaml').read_text())
    manifest = json.loads((root / 'manifest.json').read_text())
    records = load_multibench_records(manifest['dataset_root'], manifest['sample_ids'])
    jobs = [dict(sample_id=sid, question=records[sid].sample.question,
                 videos=dict(records[sid].sample.videos)) for sid in manifest['sample_ids']]
    events = (directory / 'rollout_events.jsonl').open('w')
    def event(value):
        events.write(json.dumps(value) + '\n')
        events.flush()
    batch = BatchExecutor(ExecutionConfig(**settings), on_event=event)
    batch.worker_target = partial(benchmark_worker, fixed=arm.endswith('fixed'),
                                 counter=batch.context.Value('i', 0))
    scores, predictions = {}, {}
    def completed(payload):
        sid = payload['sample_id']
        write(directory / (sid.replace('/', '_') + '.json'), payload)
        if payload['status'] == 'ok':
            prediction = extract_prediction(payload['result'])
            predictions[sid] = prediction
            scores[sid] = ChoiceScorer(strict_format=True).score(
                prediction=prediction, sample=records[sid].sample).score

    try:
        batch.prepare(config)  # Startup and readiness probes are outside timed inference.
        endpoints = [r.endpoint for pool in batch.pools.values() for r in pool.replicas]
        before = service_metrics(endpoints)
        write(directory / 'metrics_before.json', before)
        started = time.monotonic()
        batch.run(jobs, config, on_complete=completed)
        elapsed = time.monotonic() - started
        after = service_metrics(endpoints)
        write(directory / 'metrics_after.json', after)
    finally:
        batch.close()
        events.close()
    result = analyze(directory, before, after)
    rows = [json.loads(line) for line in (directory / 'rollout_events.jsonl').read_text().splitlines()]
    per_question = defaultdict(set)
    for row in rows:
        if row['kind'] == 'request_admitted':
            per_question[row['sample_id']].add(row['endpoint'])
    gpu = defaultdict(list)
    for row in rows:
        if row['kind'] == 'gpu_metrics':
            for entry in row['rows']:
                index, uuid, utilization, memory = entry.split(',')
                gpu[index.strip()].append(float(utilization))
    result.update(arm=arm, repeat=repeat, executor_seconds=elapsed,
                  score=sum(scores.values()) / len(jobs), predictions=predictions,
                  questions_using_multiple_endpoints=sum(len(v) > 1 for v in per_question.values()),
                  gpu_utilization_sample_mean={k: statistics.mean(v) for k, v in gpu.items()},
                  source_roots=sorted({e['source_root'] for e in rows if e['kind'] == 'worker_runtime'}))
    if arm.endswith('fixed'):
        assert all(len(v) == 1 for v in per_question.values()), 'Fixed routing escaped its endpoint'
    assert result['completed'] == len(jobs)
    write(directory / 'profile.json', result)
    print(json.dumps({k: result[k] for k in ('arm', 'repeat', 'completed', 'batch_seconds',
                                           'clip_calls', 'score')}), flush=True)


def prepare(root, args):
    import yaml
    root.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(__file__, root / Path(__file__).name)
    for mode in ('fast', 'slow'):
        shutil.copytree(REPO / 'src', root / 'sources' / mode,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    # Restore the exact historical function retained as comments at the user's request.
    media = root / 'sources/slow/mvagent/utils/media.py'
    text = media.read_text()
    begin = text.index('# @cached_media("clip")')
    end = text.index('\ndef validate_video_ranges(', begin)
    old = '\n'.join(line[2:] if line.startswith('# ') else ''
                    for line in text[begin:end].splitlines())
    compile(old, str(media), 'exec')
    media.write_text(text[:begin] + old + '\n' + text[end:])
    for mode in ('fast', 'slow'):
        files = sorted((root / 'sources' / mode).rglob('*.py'))
        write(root / f'{mode}_source_hashes.json', {
            str(p.relative_to(root / 'sources' / mode)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in files})
    sys.path.insert(0, str(root / 'sources/fast'))
    from skill_evolution.infra.benchmarks import load_multibench_records
    from mvagent.utils.snapshot import mask_sensitive_data
    split = json.loads((REPO / args.split).read_text())
    ids = [s['sample_id'] for s in split['samples'] if s['split'] == 'eval']
    records = load_multibench_records(args.dataset_root, ids)
    rng = random.Random(20260907)
    selected = []
    for dataset in ('crossvid', 'cvbench', 'mvu_eval'):
        eligible = sorted(sid for sid in ids if records[sid].dataset == dataset
                          and records[sid].sample.task.value == 'choice')
        selected.extend(rng.sample(eligible, args.per_dataset))
    rng.shuffle(selected)
    write(root / 'manifest.json', dict(dataset_root=args.dataset_root, sample_ids=selected,
          seed=20260907, repeats=args.repeats, source_split=str(args.split),
          design='4 arms; reverse order on odd repeats; no media or trajectory cache; '
                 'same model, inputs, workers, admission limits; server caches not flushed'))
    config = yaml.safe_load((REPO / args.config).read_text())
    (root / 'runtime.yaml').write_text(yaml.safe_dump(mask_sensitive_data(config), sort_keys=False))
    execution = yaml.safe_load((REPO / args.execution_config).read_text())
    execution.update(question_workers=6, max_prepared_requests=12, media_cache=None,
                     question_timeout_sec=600, question_retries=0)
    (root / 'execution.yaml').write_text(yaml.safe_dump(execution, sort_keys=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--config', default='configs/skill_evolution/runtime/local_qwen35_35b_a3b_qwen38_optimizer_gpu5_7.yaml')
    parser.add_argument('--execution-config', default='configs/inference/execution/gpu5_7.yaml')
    parser.add_argument('--split', default='configs/skill_evolution/splits/multibench_broad_train130_eval70_seed20260828.json')
    parser.add_argument('--dataset-root', default='/home/kww/datasets/Multi-Video')
    parser.add_argument('--per-dataset', type=int, default=8)
    parser.add_argument('--repeats', type=int, default=2)
    parser.add_argument('--arm', choices=ARMS)
    parser.add_argument('--repeat', type=int, default=0)
    args = parser.parse_args()
    root = args.output_dir.resolve()
    if args.arm:
        run_arm(root, args.arm, args.repeat)
        return
    prepare(root, args)
    results = []
    for repeat in range(args.repeats):
        for arm in (ARMS if repeat % 2 == 0 else ARMS[::-1]):
            write(root / 'progress.json', dict(status='running', repeat=repeat, arm=arm,
                  completed_runs=len(results), total_runs=args.repeats * len(ARMS), started_at=time.time()))
            with (root / f'{repeat}_{arm}.log').open('w') as log:
                process = subprocess.run([sys.executable, '-u', str(Path(__file__).resolve()),
                    '--output-dir', str(root), '--arm', arm, '--repeat', str(repeat)],
                    cwd=REPO, stdout=log, stderr=subprocess.STDOUT)
            if process.returncode:
                write(root / 'progress.json', dict(status='failed', arm=arm, repeat=repeat,
                                                  log=str(log.name)))
                raise RuntimeError(f'{arm} failed: {log.name}')
            result = json.loads((root / f'{repeat}_{arm}/profile.json').read_text())
            results.append(result)
            medians = {a: statistics.median(r['batch_seconds'] for r in results if r['arm'] == a)
                       for a in ARMS if any(r['arm'] == a for r in results)}
            write(root / 'summary.json', dict(runs=results, median_batch_seconds=medians,
                  baseline_over_new=(medians['slow_fixed'] / medians['fast_dynamic']
                                     if 'slow_fixed' in medians and 'fast_dynamic' in medians else None)))
    write(root / 'progress.json', dict(status='finished', completed_runs=len(results)))


if __name__ == '__main__':
    main()
