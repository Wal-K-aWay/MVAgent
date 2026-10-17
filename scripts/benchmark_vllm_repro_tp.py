#!/usr/bin/env python3
"""Compare TP1/TP8 with the frozen BF16 FlashInfer reproducibility settings."""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import random
import shutil
import signal
import subprocess
import time
import traceback

from benchmark_qwen35_fp8 import digest, event, save
from confirm_single_process_gpu import prepare_cases, difference
from confirm_single_process_mvagent import (install_worker_audit,
    begin_forward_audit, end_forward_audit)


def config_for(reference, tp, executor='mp'):
    config = json.loads(json.dumps(reference))
    assert config['tensor_parallel_size'] == 1
    assert config['additional_config']['gdn_prefill_backend'] == 'flashinfer'
    config.update(tensor_parallel_size=tp, distributed_executor_backend='uni' if tp == 1 else executor)
    return config


def self_check():
    from confirm_single_process_mvagent import self_check as check_agent
    check_agent()
    base = dict(tensor_parallel_size=1, distributed_executor_backend='uni',
                additional_config={'gdn_prefill_backend': 'flashinfer'}, max_num_seqs=1)
    assert config_for(base, 1) == base
    changed = config_for(base, 8)
    assert {k for k in base if base[k] != changed[k]} == {
        'tensor_parallel_size', 'distributed_executor_backend'}
    assert base['tensor_parallel_size'] == 1
    assert config_for(base, 8, 'external_launcher')['distributed_executor_backend'] == 'external_launcher'
    row = dict(input_sha256='a', prompt_sha256='b', token_ids=[1, 2])
    assert not any(difference(row, row).values())
    assert difference(row, {**row, 'token_ids': [1]})['tokens_changed']
    class FakeLLM:
        def collective_rpc(self, fn):
            return [dict(identity=(42, 0, 'cuda:0', 7), calls=2)]
    state = dict(workers=[(42, 0, 'cuda:0', 7)], observed=set(), forward_calls=0)
    assert end_forward_audit(FakeLLM(), state, {})[0]['calls'] == 2
    print('TP-only config changes, exact-token comparison and worker audit self-check passed')


def run_e2e(args, llm, state, audit):
    from vllm import SamplingParams
    cases = prepare_cases(args.output)
    refs = json.loads((args.reference / 'references.json').read_text()) if args.reference else {}
    if refs:
        assert set(refs) == {c['name'] for c in cases}
    passes = []
    for repeat in range(args.repeats):
        order = list(cases)
        random.Random(20261011 + repeat).shuffle(order)
        rows, differences = [], []
        started = time.perf_counter()
        with (args.output / f'raw_{repeat}.jsonl').open('x', buffering=1) as stream:
            for case in order:
                actual = digest(dict(messages=case['messages'], generation=case['generation'],
                                     chat_template_kwargs={'enable_thinking': False}))
                assert actual == case['input_sha256']
                begin_forward_audit(llm, state)
                before = time.perf_counter()
                signal.alarm(600)
                try:
                    out = llm.chat(case['messages'], sampling_params=SamplingParams(**case['generation']),
                                   use_tqdm=False, chat_template_kwargs={'enable_thinking': False})[0]
                finally:
                    signal.alarm(0)
                seconds = time.perf_counter() - before
                workers = end_forward_audit(llm, state, audit)
                generated = out.outputs[0]
                row = dict(case=case['name'], repeat=repeat, input_sha256=actual,
                    prompt_sha256=digest(out.prompt_token_ids), token_ids=list(generated.token_ids),
                    prompt_tokens=len(out.prompt_token_ids), text=generated.text,
                    finish_reason=generated.finish_reason, seconds=seconds, worker_forwards=workers)
                stream.write(json.dumps(row) + '\n')
                rows.append(row)
                delta = difference(refs.setdefault(case['name'], row), row)
                if delta['input_changed'] or delta['tokens_changed']:
                    differences.append(dict(case=case['name'], **delta))
                event(args.output, 'e2e_measuring', model=args.model, tp=args.tp, repeat=repeat,
                      responses=len(rows), differences=len(differences), case=case['name'])
        ended = time.perf_counter()
        passes.append(dict(repeat=repeat, responses=len(rows), differences=differences,
            started=started, ended=ended, seconds=ended-started,
            inference_seconds=sum(r['seconds'] for r in rows),
            output_tokens=sum(len(r['token_ids']) for r in rows)))
        save(args.output / 'passes.json', passes)
        save(args.output / 'references.json', refs)
    return passes


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--model', choices=['9B', '27B', '35B-A3B'])
    p.add_argument('--tp', type=int, choices=[1, 8], default=8)
    p.add_argument('--executor', choices=['mp', 'external_launcher'], default='mp')
    p.add_argument('--output', type=Path)
    p.add_argument('--reference', type=Path)
    p.add_argument('--repeats', type=int, default=3)
    p.add_argument('--barrier-dir', type=Path)
    p.add_argument('--self-check', action='store_true')
    args = p.parse_args()
    if args.self_check:
        self_check()
        return
    rank = int(os.environ.get('RANK', '0'))
    if args.executor == 'external_launcher':
        assert args.tp == 8 and int(os.environ['WORLD_SIZE']) == 8
        if rank:
            args.output = args.output / f'rank{rank}'
            if args.reference:
                args.reference = args.reference / f'rank{rank}'
    assert args.model and str(args.output).startswith('/runs/') and args.repeats >= 2
    assert not (args.output / 'manifest.json').exists()
    if args.reference:
        previous = json.loads((args.reference / 'manifest.json').read_text())
        assert previous['model'] == args.model and previous['tp'] == args.tp
        assert previous['workload'] == 'e2e'
    os.environ.update(VLLM_ENABLE_V1_MULTIPROCESSING='0', VLLM_BATCH_INVARIANT='0',
        OMP_NUM_THREADS='1', MKL_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1',
        TOKENIZERS_PARALLELISM='false', MVAGENT_RECORD_TOKEN_IDS='1')
    import torch
    from vllm import LLM
    from vllm.distributed.parallel_state import cleanup_dist_env_and_memory
    assert torch.cuda.device_count() == args.tp
    args.output.mkdir(parents=True, exist_ok=True)
    tag = {'9B': '9b', '27B': '27b', '35B-A3B': '35b'}[args.model]
    source = Path(f'/runs/devbox/repro_agent_flashinfer_{tag}_20261011_p1')
    original = json.loads((source / 'manifest.json').read_text())
    config = config_for(original['config'], args.tp, args.executor)
    if args.reference:
        assert config == previous['config']
    for name in [Path(__file__).name, 'benchmark_qwen35_fp8.py', 'confirm_single_process_gpu.py',
                 'confirm_single_process_mvagent.py', 'confirm_bf16_mvagent.py']:
        shutil.copyfile(Path(__file__).with_name(name), args.output / name)
    shutil.copyfile(source / args.model / 'weight_environment_metadata.json',
                    args.output / 'weight_environment_metadata.json')
    save(args.output / 'manifest.json', dict(model=args.model, tp=args.tp, executor=args.executor,
        rank=rank, workload='e2e',
        config=config, source=str(source), reference=str(args.reference) if args.reference else None,
        source_manifest_sha256=hashlib.sha256((source / 'manifest.json').read_bytes()).hexdigest(),
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        versions={k: importlib.metadata.version(k) for k in
                  ['vllm', 'torch', 'transformers', 'flashinfer-python', 'triton', 'xgrammar']},
        environment={k: os.environ.get(k) for k in ['CUDA_VISIBLE_DEVICES',
            'VLLM_ENABLE_V1_MULTIPROCESSING', 'VLLM_BATCH_INVARIANT', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS']},
        gpu_inventory=subprocess.check_output(['nvidia-smi', '--query-gpu=index,name,uuid,driver_version',
                                               '--format=csv'], text=True),
        commit=subprocess.check_output(['git', '-c', 'safe.directory=/repo', 'rev-parse', 'HEAD'], text=True).strip()))

    def timeout(signum, frame):
        raise TimeoutError('Model operation exceeded its time budget')
    signal.signal(signal.SIGALRM, timeout)
    signal.signal(signal.SIGTERM, signal.default_int_handler)
    llm = None
    result = dict(model=args.model, tp=args.tp, workload='e2e', passes=[], error=None, stable=False)
    try:
        event(args.output, 'loading', model=args.model, tp=args.tp)
        before = time.perf_counter()
        signal.alarm(900)
        llm = LLM(model='/weights/Qwen3.5-' + args.model, **config)
        signal.alarm(0)
        result['load_seconds'] = time.perf_counter() - before
        assert type(llm.llm_engine.engine_core).__name__ == 'InprocClient'
        workers = [tuple(w) for w in llm.collective_rpc(install_worker_audit)]
        cpu_group = None
        if args.executor == 'external_launcher':
            import torch.distributed as dist
            from vllm.distributed.parallel_state import get_world_group
            cpu_group = get_world_group().cpu_group
            gathered = [None] * args.tp
            dist.all_gather_object(gathered, workers[0], group=cpu_group)
            workers = [tuple(w) for w in gathered]
        assert len(workers) == args.tp and len(set(workers)) == args.tp
        save(args.output / 'workers.json', workers)
        state = dict(workers=workers, observed=set(), forward_calls=0)
        if cpu_group is not None:
            state['cpu_group'] = cpu_group
        local_worker = workers[rank] if cpu_group is not None else workers[0]
        audit = dict(pid=os.getpid(), gpu=local_worker[1], model_object_id=local_worker[3], stage='A_initial')
        if args.barrier_dir:
            assert str(args.barrier_dir).startswith('/runs/') and args.tp == 1
            args.barrier_dir.mkdir(parents=True, exist_ok=True)
            (args.barrier_dir / f'{args.output.name}.ready').touch()
            deadline = time.monotonic() + 900
            while not (args.barrier_dir / 'go').exists():
                if time.monotonic() > deadline:
                    raise TimeoutError('Replica start barrier timed out')
                time.sleep(.2)
        event(args.output, 'ready', model=args.model, tp=args.tp, workers=workers)
        result['passes'] = run_e2e(args, llm, state, audit)
        result['stable'] = all(not r['differences'] for r in result['passes'])
    except BaseException as exc:
        result.update(error=repr(exc), traceback=traceback.format_exc())
        raise
    finally:
        signal.alarm(0)
        result.update(responses=sum(r['responses'] for r in result['passes']),
                      differences=sum(len(r['differences']) for r in result['passes']))
        save(args.output / 'summary.json', result)
        if llm is not None:
            llm.llm_engine.engine_core.shutdown()
            cleanup_dist_env_and_memory()
        event(args.output, 'finished' if result['error'] is None else 'failed',
              model=args.model, tp=args.tp, responses=result['responses'],
              differences=result['differences'], stable=result['stable'], error=result['error'])


if __name__ == '__main__':
    main()
