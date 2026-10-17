#!/usr/bin/env python3
"""Run full no-skill MVAgent trajectories only for models passing the E2E gate."""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import time
import traceback
from types import SimpleNamespace

from benchmark_qwen35_fp8 import digest, event, save
from benchmark_qwen35_throughput import Pool
from benchmark_vllm_options import VARIANTS

ROOT = Path(__file__).resolve().parents[1]


def token_trace(events):
    grouped = defaultdict(list)
    requests = sum(e['kind'] == 'model_request' for e in events)
    responses = [e for e in events if e['kind'] == 'model_response']
    if not responses or len(responses) != requests or any(e['kind'] == 'model_error' for e in events):
        raise ValueError('Incomplete or failed model calls in trajectory')
    for e in responses:
        if any(k not in e for k in ['token_ids', 'request_sha256', 'prompt_token_ids_sha256']):
            raise ValueError('Missing actual token audit in trajectory')
        # Concurrent videos may finish in different orders; decisions within each video remain ordered.
        key = json.dumps([e.get(k) for k in ['agent', 'video_id', 'global_round', 'decision_id', 'schema']])
        grouped[key].append({k: e[k] for k in ['token_ids', 'request_sha256', 'prompt_token_ids_sha256']})
    return dict(grouped)


def compare_traces(reference, current):
    changed = []
    for key in sorted(reference.keys() | current.keys()):
        a, b = reference.get(key, []), current.get(key, [])
        if len(a) != len(b):
            changed.append({'scope': key, 'call_count_before': len(a), 'call_count_after': len(b)})
        for i, (x, y) in enumerate(zip(a, b)):
            if x != y:
                changed.append({'scope': key, 'call': i,
                                'input_changed': any(x[k] != y[k] for k in ['request_sha256', 'prompt_token_ids_sha256']),
                                'tokens_changed': x['token_ids'] != y['token_ids']})
    return changed


def self_check():
    request = {'kind': 'model_request'}
    def response(video, tokens):
        return {'kind': 'model_response', 'agent': 'VideoAgent', 'video_id': video,
                'token_ids': tokens, 'request_sha256': video, 'prompt_token_ids_sha256': video}
    a, b = response('a', [1, 2]), response('b', [3])
    ref = token_trace([request, request, a, b])
    assert not compare_traces(ref, token_trace([request, request, b, a]))
    changed = token_trace([request, request, {**a, 'token_ids': [1, 9]}, b])
    assert compare_traces(ref, changed)[0]['tokens_changed']
    changed = token_trace([request, request, {**a, 'request_sha256': 'changed'}, b])
    assert compare_traces(ref, changed)[0]['input_changed']
    for bad in [[], [request], [request, {'kind': 'model_response'}],
                [request, a, {'kind': 'model_error'}]]:
        try:
            token_trace(bad)
        except ValueError:
            pass
        else:
            raise AssertionError('Incomplete trace accepted')
    print('Trajectory self-check passed: exact IDs/inputs, scoped order, missing calls, errors')


def load_runner():
    spec = importlib.util.spec_from_file_location('agent_eval_repro_runner', ROOT / 'eval/agent_eval/run.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_model(args, model, selected):
    import httpx
    import yaml
    runner = load_runner()
    root = args.output / model
    root.mkdir()
    cfg = yaml.safe_load((ROOT / 'configs/inference/modal_qwen35_35b_a3b_no_skill.yaml').read_text())
    model_cfg = next(iter(cfg['models'].values()))
    model_cfg.pop('execution_profile', None)  # This historical diagnostic selects its own serving configuration.
    model_cfg.update(model_name='/weights/Qwen3.5-' + model, dtype='bfloat16',
                     gpu_memory_utilization=0.95, max_model_len=131072, reasoning_parser=None,
                     timeout_sec=900, max_retries=1)
    cfg['models'] = {'bench': model_cfg}
    cfg['agents']['global_agent']['model']['model_type'] = 'bench'
    cfg['agents']['video_agent']['planner']['model_type'] = 'bench'
    cfg['agents']['video_agent']['observer']['model_type'] = 'bench'
    cfg['runtime']['cache_dir'] = str(root / 'runtime_cache')
    config_path = root / 'config.yaml'
    config_path.write_text(yaml.safe_dump(cfg, sort_keys=False))
    ids = tuple(item['sample_id'] for item in selected)
    _, configs, _, records, manifest = runner._prepare_output(
        output_dir=root / 'runtime', config_path=config_path, dataset_root=Path('/assets'),
        sample_ids=ids, judge_model=None, resume=False, defer_open_qa_judge=True)
    from mvagent.batch import BatchExecutor, ExecutionConfig
    from models.pool import ModelPool, Replica, install_pools
    config = configs.MVAgentConfig.from_dict(cfg)
    references, answers, passes = {}, {}, []
    result = {'model': model, 'passes': passes, 'stage': 'starting', 'stable': False, 'error': None}
    closed_records = {sid: r for sid, r in records.items() if not sid.startswith('crossvid:CCQA:')}
    scorer, scorer_identity = runner._build_scorer(closed_records, judge_model=None,
                                                  cache_dir=root / 'judge_cache')
    save(root / 'scorer_identity.json', scorer_identity)

    def checkpoint():
        result.update(rollouts=sum(p['rollouts'] for p in passes),
                      model_calls=sum(p['model_calls'] for p in passes),
                      differences=sum(len(p['differences']) for p in passes))
        save(root / 'summary.json', result)

    try:
        for restart, labels in [(0, ['reference', 'repeat']), (1, ['after_restart'])]:
            server_dir = root / f'servers_restart{restart}'
            server_dir.mkdir()
            serving = Pool(SimpleNamespace(output=root, startup_timeout=900), server_dir)
            result.update(stage='loading', restart=restart)
            checkpoint()
            try:
                flags = {**VARIANTS['bf16_prefix']['flags'], '--limit-mm-per-prompt': json.dumps({
                    'image': {'count': 512, 'width': 448, 'height': 448}, 'video': 8})}
                serving.start('bf16', 1, 8, 0, 8, 32768, 'weights', model_size=model,
                              flags=flags, env_overrides=VARIANTS['bf16_prefix']['env'])
                # These servers are owned by this experiment; verify identities before installing admission.
                with httpx.Client(timeout=10, trust_env=False) as client:
                    for endpoint in serving.endpoints:
                        cards = client.get(endpoint + '/v1/models').json()['data']
                        assert len(cards) == 1 and cards[0]['id'] == 'bench'
                        assert cards[0]['root'] == model_cfg['model_name'] and cards[0]['max_model_len'] == 131072
                replicas = [Replica(endpoint + '/v1', (i,), 1) for i, endpoint in enumerate(serving.endpoints)]
                commands = json.loads((server_dir / 'servers.json').read_text())
                pool = ModelPool('bench', replicas, digest(commands), root=str(root / f'admission{restart}'))
                pool.register()
                install_pools({'bench': pool})
                execution = ExecutionConfig(question_workers=8, max_prepared_requests=16,
                    question_timeout_sec=1800, question_retries=0,
                    model_pools={'bench': {'replicas': [r.to_dict() for r in replicas]}},
                    media_cache={'root': str(root / 'media_cache'), 'max_bytes': 10737418240})
                save(root / 'execution.json', execution.to_dict())
                for label in labels:
                    directory = root / label
                    directory.mkdir()
                    changed, errors, completed = [], [], []
                    result.update(stage='measuring', pass_name=label)
                    checkpoint()
                    started = time.perf_counter()

                    def completed_one(payload):
                        sid = payload['sample_id']
                        source = records[sid]
                        row = dict(sample_id=sid, dataset=source.dataset, native_task=source.native_task,
                            prediction=runner._extract_prediction(payload['result']),
                            ground_truth=list(source.sample.ground_truth), judge_question=source.judge_question,
                            reference_answer=source.reference_answer, status=payload['status'],
                            error=payload.get('error', ''), result=payload['result'], events=payload['events'])
                        path = runner._record_path(directory, sid)
                        save(path, row)
                        completed.append(row)
                        try:
                            if row['status'] != 'ok':
                                raise RuntimeError(row['error'])
                            trace = token_trace(row['events'])
                            if label == 'reference':
                                references[sid], answers[sid] = trace, row['prediction']
                            elif sid not in references:
                                raise ValueError('Missing successful reference')
                            delta = compare_traces(references[sid], trace)
                            if delta or row['prediction'] != answers[sid]:
                                changed.append({'sample_id': sid, 'calls': delta,
                                                'answer_changed': row['prediction'] != answers[sid]})
                            runner._score_saved_row(row, source, scorer, defer_open_qa_judge=True)
                            save(path, row)
                            if row.get('scoring_error'):
                                raise RuntimeError(row['scoring_error'])
                        except Exception as exc:
                            errors.append({'sample_id': sid, 'error': repr(exc), 'traceback': traceback.format_exc()})
                        event(root, 'measuring', pass_name=label, rollouts=len(completed),
                              differences=len(changed), errors=len(errors), sample_id=sid)

                    live_events = (directory / 'execution_events.jsonl').open('a', buffering=1)
                    batch = BatchExecutor(execution, pool_factory=lambda *_: ({'bench': pool}, []),
                        on_event=lambda e: live_events.write(json.dumps(e) + '\n'))
                    try:
                        jobs = [dict(sample_id=sid, question=records[sid].sample.question,
                                     videos=dict(records[sid].sample.videos)) for sid in ids]
                        batch.run(jobs, config.to_dict(), on_complete=completed_one)
                    finally:
                        batch.close()
                        live_events.close()
                    events = [e for row in completed for e in row['events']]
                    calls = [e for e in events if e['kind'] == 'model_response']
                    coverage = dict(global_calls=sum(e.get('agent') == 'GlobalAgent' for e in calls),
                                    video_calls=sum(e.get('agent') == 'VideoAgent' for e in calls))
                    passes.append({'name': label, 'rollouts': len(completed), 'model_calls': len(calls),
                        'seconds': time.perf_counter() - started, 'differences': changed, 'errors': errors,
                        'coverage': coverage, 'stable': len(completed) == len(ids) and not changed and not errors and all(coverage.values())})
                    save(directory / 'summary.json', passes[-1])
                    save(root / 'references.json', references)
                    checkpoint()
            finally:
                serving.close()
        result['stable'] = len(passes) == 3 and all(p['stable'] for p in passes)
    except Exception as exc:
        result.update(error=repr(exc), traceback=traceback.format_exc())
    result['stage'] = 'finished'
    checkpoint()
    manifest.update(status='finished', token_reproducible=result['stable'],
                    finished_at_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
    save(root / 'runtime/run_manifest.json', manifest)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--e2e-result', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--self-check', action='store_true')
    args = parser.parse_args()
    if args.self_check:
        self_check()
        return
    if args.output is None or not str(args.output).startswith('/runs/') or (args.output / 'manifest.json').exists():
        raise SystemExit('Use a fresh /runs/ output directory')
    if args.e2e_result is None:
        raise SystemExit('--e2e-result is required')
    assert json.loads((args.e2e_result / 'progress.json').read_text())['phase'] == 'finished'
    summaries = json.loads((args.e2e_result / 'summary.json').read_text())
    accepted = [r['model'] for r in summaries if r['stable'] and r['samples'] == 264]
    args.output.mkdir(parents=True, exist_ok=True)
    save(args.output / 'manifest.json', {'e2e_result': str(args.e2e_result), 'accepted_models': accepted,
         'e2e_summary_sha256': hashlib.sha256((args.e2e_result / 'summary.json').read_bytes()).hexdigest(),
         'driver_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
         'protocol': 'Full frozen no-skill MVAgent, 5 Global/Video steps, max2048 output, max512 frames; actual tokens on every model call; 33 tasks/three passes including restart; independent BF16 TP1/DP1 C1. Prefill/encoder budget 32768 after the initial 16384 video run stalled. Serving also enables video input; E2E used image-only inputs with prefill16384.'})
    (args.output / 'driver_source.py').write_bytes(Path(__file__).read_bytes())
    for name in ['benchmark_qwen35_fp8.py', 'benchmark_qwen35_throughput.py', 'benchmark_vllm_options.py']:
        (args.output / name).write_bytes((ROOT / 'scripts' / name).read_bytes())
    selected = {}
    for item in json.loads((args.e2e_result / 'selection.json').read_text()):
        selected.setdefault((item['benchmark'], item['task']), item)
    assert len(selected) == 33
    save(args.output / 'selection.json', list(selected.values()))
    signal.signal(signal.SIGTERM, signal.default_int_handler)
    os.environ['MVAGENT_RECORD_TOKEN_IDS'] = '1'
    results = []
    save(args.output / 'summary.json', results)
    for model in accepted:
        event(args.output, 'running', model=model)
        results.append(run_model(args, model, list(selected.values())))
        save(args.output / 'summary.json', results)
    event(args.output, 'finished', models=len(results), stable=bool(results) and all(r['stable'] for r in results))


if __name__ == '__main__':
    main()
