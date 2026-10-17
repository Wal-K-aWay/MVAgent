#!/usr/bin/env python3
"""Same-PID, same-model-object BF16 GPU migration probe. Run only on Modal.

CUDA execution state is rebuilt; the retained model travels through CPU memory.
This is an eager, synchronous diagnostic, not the previous online protocol.
"""
from __future__ import annotations

import argparse
import gc
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

SOURCE = Path('/runs/devbox/independent_bf16_e2e_20261011_r1/9B/requests')
CASE_IDS = ['cvbench:286', 'cvbench:664', 'mvu_eval:ICL:713',
            'crossvid:CCQA:778', 'crossvid:CCQA:304', 'crossvid:FSA:121',
            'crossvid:PSS:288', 'crossvid:NC:1135']
STAGES = [('A_initial', 0), ('A_rebuilt', 0), ('B_migrated', 1), ('A_returned', 0)]


def restore_cache_bindings(context, originals):
    for name, layer in context.items():
        if name in originals:
            layer.kv_cache = originals[name]
        elif hasattr(layer, 'kv_cache'):
            # Mamba cache attributes are created after loading, not in the constructor.
            delattr(layer, 'kv_cache')


def difference(a, b):
    changed = a['token_ids'] != b['token_ids']
    index = next((i for i, (x, y) in enumerate(zip(a['token_ids'], b['token_ids'])) if x != y),
                 min(len(a['token_ids']), len(b['token_ids'])))
    return dict(input_changed=any(a[k] != b[k] for k in ['input_sha256', 'prompt_sha256']),
                tokens_changed=changed, first_difference_1based=index + 1 if changed else None)


def self_check():
    from types import SimpleNamespace
    a = dict(input_sha256='a', prompt_sha256='b', token_ids=[1, 2])
    assert not any(difference(a, a).values())
    assert difference(a, {**a, 'token_ids': [1, 3]})['first_difference_1based'] == 2
    assert difference(a, {**a, 'token_ids': [1]})['first_difference_1based'] == 2
    assert difference(a, {**a, 'prompt_sha256': 'changed'})['input_changed']
    assert [g for _, g in STAGES] == [0, 0, 1, 0]
    layers = {n: SimpleNamespace(kv_cache='allocated') for n in ['attention', 'mamba']}
    restore_cache_bindings(layers, {'attention': 'empty'})
    assert layers['attention'].kv_cache == 'empty' and not hasattr(layers['mamba'], 'kv_cache')
    print('Exact tokens, inputs, A-A-B-A control and late-created Mamba cache cleanup self-check passed')


def prepare_cases(output):
    cases = []
    for sid in CASE_IDS:
        source = SOURCE / (sid + '.json')
        wire = source.read_bytes()
        body = json.loads(wire)
        generation = {k: body[k] for k in ['temperature', 'top_p', 'max_tokens', 'seed']}
        assert generation['temperature'] == 0 and generation['seed'] == 0
        case = dict(name=sid, messages=body['messages'], generation=generation,
                    historical_wire_sha256=hashlib.sha256(wire).hexdigest())
        case['input_sha256'] = digest({'messages': case['messages'], 'generation': generation,
                                      'chat_template_kwargs': {'enable_thinking': False}})
        cases.append(case)
    save(output / 'inputs.json', cases)
    return cases


def run(args):
    os.environ.update(VLLM_ENABLE_V1_MULTIPROCESSING='0', VLLM_BATCH_INVARIANT='0',
                      OMP_NUM_THREADS='1', MKL_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1',
                      TOKENIZERS_PARALLELISM='false')
    import torch
    from vllm import LLM, SamplingParams
    from vllm.distributed.parallel_state import cleanup_dist_env_and_memory
    from vllm.model_executor.layers.rotary_embedding import _ROPE_DICT
    from vllm.model_executor.model_loader import register_model_loader
    from vllm.model_executor.model_loader.default_loader import DefaultModelLoader
    from vllm.v1.executor.uniproc_executor import UniProcExecutor
    import copy

    state = dict(model=None, context={}, moe_layers=[], empty_caches={}, gpu=0, first_loads=0,
                 observed=set(), forward_calls=0, stage='')
    pid = os.getpid()

    def forward_audit(module, inputs):
        observed = (os.getpid(), torch.cuda.current_device(),
                    str(next(module.parameters()).device), id(module))
        state['observed'].add(observed)
        state['forward_calls'] += 1
        assert observed == (pid, state['gpu'], f"cuda:{state['gpu']}", id(state['model']))

    class SelectedGPUExecutor(UniProcExecutor):
        def _distributed_args(self):
            init_method, rank, _ = super()._distributed_args()
            return init_method, rank, state['gpu']

    @register_model_loader('retained_gpu_probe')
    class RetainedModelLoader(DefaultModelLoader):
        def __init__(self, load_config):
            original = copy.deepcopy(load_config)
            original.load_format = 'auto'
            super().__init__(original)

        def load_model(self, vllm_config, model_config, prefix=''):
            if state['model'] is None:
                model = super().load_model(vllm_config, model_config, prefix)
                state['model'] = model
                state['first_loads'] += 1
                state['context'] = dict(vllm_config.compilation_config.static_forward_context)
                state['moe_layers'] = list(vllm_config.compilation_config.static_all_moe_layers)
                state['empty_caches'] = {name: layer.kv_cache for name, layer in state['context'].items()
                                         if hasattr(layer, 'kv_cache')}
                model.register_forward_pre_hook(forward_audit)
            else:
                assert str(next(state['model'].parameters()).device) == 'cpu'
                vllm_config.compilation_config.static_forward_context.update(state['context'])
                vllm_config.compilation_config.static_all_moe_layers.extend(state['moe_layers'])
                state['model'].to(torch.device('cuda', state['gpu']))
            assert all(p.device == torch.device('cuda', state['gpu']) for p in state['model'].parameters())
            return state['model']

    def fingerprint():
        # Sample every parameter; this is not a full cryptographic hash of all weight bytes.
        h = hashlib.sha256()
        for name, p in state['model'].named_parameters():
            flat = p.detach().reshape(-1)
            stride = max(1, flat.numel() // 64)
            sampled = flat[::stride][:64].contiguous().cpu().view(torch.uint8).numpy().tobytes()
            h.update(str((name, list(p.shape), str(p.dtype))).encode())
            h.update(sampled)
        return h.hexdigest()

    def park_model(llm):
        if state['model'] is not None:
            restore_cache_bindings(state['context'], state['empty_caches'])
            state['model'].to('cpu')
        if llm is not None:
            llm.llm_engine.engine_core.shutdown()
        cleanup_dist_env_and_memory()

    inventory = subprocess.check_output(['nvidia-smi', '--query-gpu=index,name,uuid,memory.total,driver_version',
                                         '--format=csv'], text=True)
    assert inventory.count('H100') == 2 and torch.cuda.device_count() == 2
    args.output.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(__file__, args.output / 'driver_source.py')
    shutil.copyfile(Path(__file__).with_name('benchmark_qwen35_fp8.py'), args.output / 'helpers.py')
    probe = None
    if args.mvagent:
        from confirm_single_process_mvagent import MVAgentProbe
        probe = MVAgentProbe(args.output)
        os.environ['MVAGENT_RECORD_TOKEN_IDS'] = '1'
        def timed_out(signum, frame):
            raise TimeoutError('In-process model call exceeded 600 seconds')
        signal.signal(signal.SIGALRM, timed_out)
    cases = probe.cases if probe else prepare_cases(args.output)
    config = dict(dtype='bfloat16', kv_cache_dtype='auto', tensor_parallel_size=1,
                  seed=0, generation_config='vllm', max_model_len=131072, max_num_seqs=1,
                  max_num_batched_tokens=16384, gpu_memory_utilization=.95,
                  enable_prefix_caching=False, mm_processor_cache_gb=0, mm_encoder_tp_mode='weights',
                  limit_mm_per_prompt={'image': {'count': 512, 'width': 448, 'height': 448}, 'video': 0},
                  async_scheduling=False, enforce_eager=True, load_format='retained_gpu_probe',
                  # FlashInfer GDN failed on the first GPU B prefill after migration.
                  additional_config={'gdn_prefill_backend': 'triton'})
    if probe:
        # Native MVAgent video requests previously stalled with the 16384 encoder budget.
        config['max_num_batched_tokens'] = 32768
        config['limit_mm_per_prompt']['video'] = 8
    manifest = dict(pid=pid, models=args.models, config=config, stages=STAGES,
        scope='Same Python PID and retained torch model object. Stage transitions move weights through CPU and rebuild execution/KV state. Eager synchronous offline diagnostic, not the prior HTTP deployment. No scoring or response cache.',
        gpu_inventory=inventory, workload='mvagent' if probe else 'e2e',
        input_source=str(SOURCE) if not probe else 'Historical longest two trajectories per benchmark',
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        git_commit=subprocess.check_output(['git', '-c', 'safe.directory=/repo', 'rev-parse', 'HEAD'], text=True).strip(),
        versions={p: importlib.metadata.version(p) for p in ['vllm', 'torch', 'transformers']},
        environment={k: os.environ.get(k) for k in ['CUDA_VISIBLE_DEVICES', 'PYTHONHASHSEED',
            'VLLM_ENABLE_V1_MULTIPROCESSING', 'VLLM_BATCH_INVARIANT', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS']})
    save(args.output / 'manifest.json', manifest)
    results = []
    for model in args.models:
        root = args.output / model
        root.mkdir()
        state.update(model=None, context={}, moe_layers=[], empty_caches={}, first_loads=0)
        # A previous model can leave shared RoPE modules parked on CPU.
        _ROPE_DICT.clear()
        refs, passes = {}, []
        result = dict(model=model, pid=pid, passes=passes, stable=False, error=None)
        save(root / 'summary.json', result)
        llm = None
        try:
            if probe:
                probe.prepare_model(root, model)
            weight_hash = None
            model_id = None
            for stage, gpu in STAGES:
                state.update(gpu=gpu, stage=stage)
                event(args.output, 'loading', model=model, stage=stage, gpu=gpu, pid=pid)
                started = time.perf_counter()
                llm = LLM(model='/weights/Qwen3.5-' + model, tokenizer='/weights/Qwen3.5-' + model,
                          distributed_executor_backend=SelectedGPUExecutor, **config)
                load_seconds = time.perf_counter() - started
                core_type = type(llm.llm_engine.engine_core).__name__
                assert core_type == 'InprocClient', core_type
                worker = llm.collective_rpc(lambda w: dict(pid=os.getpid(), device=str(w.device),
                    model_id=id(w.model_runner.model)))[0]
                assert worker['pid'] == pid and worker['device'] == f'cuda:{gpu}'
                if model_id is None:
                    model_id = id(state['model'])
                assert worker['model_id'] == model_id == id(state['model']) and state['first_loads'] == 1
                current_hash = fingerprint()
                weight_hash = weight_hash or current_hash
                assert weight_hash == current_hash
                audit = dict(stage=stage, gpu=gpu, pid=pid, model_object_id=model_id,
                             engine_core_type=core_type, worker=worker, disk_weight_loads=state['first_loads'],
                             moe_layer_count=len(state['moe_layers']),
                             sampled_parameter_sha256=current_hash, load_seconds=load_seconds)
                save(root / f'{stage}_identity.json', audit)
                if probe:
                    passes.extend(probe.run_stage(llm, state, audit))
                    save(root / 'summary.json', result)
                else:
                    for repeat in range(2):
                        directory = root / f'{stage}_repeat{repeat}'
                        directory.mkdir()
                        rows, diffs = [], []
                        order = list(range(len(cases)))
                        random.Random(20261011 + repeat).shuffle(order)
                        started = time.perf_counter()
                        with (directory / 'raw.jsonl').open('a', buffering=1) as raw:
                            for index in order:
                                case = cases[index]
                                actual_input_hash = digest({'messages': case['messages'], 'generation': case['generation'],
                                                            'chat_template_kwargs': {'enable_thinking': False}})
                                assert actual_input_hash == case['input_sha256'], 'Frozen request was mutated'
                                state['observed'].clear()
                                state['forward_calls'] = 0
                                before = time.perf_counter()
                                output = llm.chat(case['messages'], sampling_params=SamplingParams(**case['generation']),
                                                 use_tqdm=False, chat_template_kwargs={'enable_thinking': False})[0]
                                generated = output.outputs[0]
                                record = dict(case=case['name'], stage=stage, repeat=repeat, gpu=gpu, pid=pid,
                                    model_object_id=model_id, input_sha256=actual_input_hash,
                                    prompt_sha256=digest(output.prompt_token_ids), token_ids=list(generated.token_ids),
                                    text=generated.text, finish_reason=generated.finish_reason,
                                    seconds=time.perf_counter() - before, forward_calls=state['forward_calls'],
                                    forward_identity=sorted(state['observed']))
                                raw.write(json.dumps(record) + '\n')
                                assert state['forward_calls'] > 0 and len(state['observed']) == 1
                                rows.append(record)
                                ref = refs.setdefault(case['name'], record)
                                delta = difference(ref, record)
                                if delta['input_changed'] or delta['tokens_changed']:
                                    diffs.append(dict(case=case['name'], **delta))
                                event(args.output, 'measuring', model=model, stage=stage, repeat=repeat,
                                      responses=len(rows), differences=len(diffs), case=case['name'], pid=pid, gpu=gpu)
                        passes.append(dict(stage=stage, gpu=gpu, repeat=repeat, responses=len(rows), differences=diffs,
                                           seconds=time.perf_counter() - started))
                        save(directory / 'summary.json', passes[-1])
                        save(root / 'references.json', refs)
                        save(root / 'summary.json', result)
                event(args.output, 'parking_model', model=model, stage=stage, pid=pid)
                park_model(llm)
                del llm
                llm = None
                gc.collect()
                for device in range(2):
                    with torch.cuda.device(device):
                        torch.cuda.empty_cache()
                save(root / f'{stage}_parked.json', dict(pid=pid, model_object_id=id(state['model']),
                    parameter_devices=sorted({str(p.device) for p in state['model'].parameters()}),
                    gpu_allocated_bytes=[torch.cuda.memory_allocated(i) for i in range(2)]))
            result['stable'] = len(passes) == (5 if probe else 8) and all(not p['differences'] for p in passes)
        except Exception as exc:
            result.update(error=repr(exc), traceback=traceback.format_exc())
        finally:
            if llm is not None:
                park_model(llm)
                del llm
            state.update(model=None, context={}, moe_layers=[], empty_caches={})
            gc.collect()
            for device in range(2):
                with torch.cuda.device(device):
                    torch.cuda.empty_cache()
        result.update(responses=sum(p['responses'] for p in passes),
                      differences=sum(len(p['differences']) for p in passes))
        if probe:
            result['rollouts'] = sum(p['rollouts'] for p in passes)
        save(root / 'summary.json', result)
        results.append(result)
        save(args.output / 'summary.json', results)
        event(args.output, 'model_finished', model=model, responses=result['responses'],
              differences=result['differences'], stable=result['stable'], error=result['error'])
        if result['error']:
            break  # A broken migration invalidates continuing other models in this process.
    event(args.output, 'finished', models=len(results),
          stable=len(results) == len(args.models) and all(r['stable'] for r in results))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--models', nargs='+', choices=['9B', '27B', '35B-A3B'], default=['9B', '27B', '35B-A3B'])
    parser.add_argument('--self-check', action='store_true')
    parser.add_argument('--mvagent', action='store_true', help='Run complete long MVAgent trajectories instead of frozen E2E requests')
    args = parser.parse_args()
    if args.self_check:
        self_check()
        if args.mvagent:
            from confirm_single_process_mvagent import self_check as check_mvagent
            check_mvagent()
        return
    if args.output is None or not str(args.output).startswith('/runs/') or (args.output / 'manifest.json').exists():
        raise SystemExit('Use a fresh /runs/ output directory')
    signal.signal(signal.SIGTERM, signal.default_int_handler)
    run(args)


if __name__ == '__main__':
    main()
