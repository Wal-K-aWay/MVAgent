#!/usr/bin/env python3
"""Replay a captured GDN prefill tensor set without loading a language model."""
import argparse
import hashlib
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import sys
import time

from benchmark_qwen35_fp8 import event, save
from diagnose_vllm_repro import LogitAudit


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    p.add_argument('--repeats', type=int, default=20)
    p.add_argument('--backends', nargs='+', choices=['triton', 'flashinfer'], default=['triton', 'flashinfer'])
    p.add_argument('--kkt-single-stage', action='store_true', help='A/B/A test pinning KKT to BK64/4 warps/1 stage')
    args = p.parse_args()
    assert str(args.input).startswith('/runs/') and str(args.output).startswith('/runs/')
    assert args.repeats >= 2 and not (args.output / 'manifest.json').exists()
    os.environ.update(OMP_NUM_THREADS='1', MKL_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1')
    import torch
    from vllm.triton_utils.allocation import set_triton_allocator
    from vllm.model_executor.layers.mamba.gdn_linear_attn import fi_chunk_gated_delta_rule
    set_triton_allocator(torch.device('cuda:0'))
    chunk = importlib.import_module('vllm.model_executor.layers.fla.ops.chunk')
    import triton
    kkt = importlib.import_module('vllm.model_executor.layers.fla.ops.chunk_scaled_dot_kkt')
    tuner = kkt.chunk_scaled_dot_kkt_fwd_kernel
    while not hasattr(tuner, 'configs'):
        tuner = tuner.fn
    args.output.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(__file__, args.output / 'source.py')
    capsule = torch.load(args.input, map_location='cpu', weights_only=True)
    values = capsule['kwargs']
    tensor_hashes = {k: LogitAudit.tensor_hashes(v) for k, v in values.items()}
    save(args.output / 'manifest.json', dict(input=str(args.input), inputs=tensor_hashes,
        metadata={k: v.tolist() if isinstance(v, torch.Tensor) else v for k, v in capsule['metadata'].items()},
        vllm=importlib.metadata.version('vllm'), pid=os.getpid(), kkt_single_stage=args.kkt_single_stage,
        cuda_visible_devices=os.environ.get('CUDA_VISIBLE_DEVICES'),
        initial_state_nonzero=int(torch.count_nonzero(values['initial_state']))))
    traces, current, originals = [], [], {}

    def wrapper(name, original):
        def wrapped(*a, **kw):
            output = original(*a, **kw)
            current.append(dict(stage=name, outputs=LogitAudit.tensor_hashes(output)))
            if len(traces) == 0:
                cpu = lambda x: x.detach().cpu() if isinstance(x, torch.Tensor) else x
                torch.save(dict(args=[cpu(v) for v in a], kwargs={k: cpu(v) for k, v in kw.items()}),
                           args.output / (name + '_inputs.pt'))
            return output
        return wrapped

    for name in ['l2norm_fwd', 'chunk_local_cumsum', 'chunk_scaled_dot_kkt_fwd', 'solve_tril',
                 'recompute_w_u_fwd', 'chunk_gated_delta_rule_fwd_h', 'chunk_fwd_o']:
        originals[name] = getattr(chunk, name)
        setattr(chunk, name, wrapper(name, originals[name]))
    results = []
    kernels = [('triton', chunk.chunk_gated_delta_rule)]
    if args.kkt_single_stage:
        kernels += [('triton_kkt_fixed', chunk.chunk_gated_delta_rule),
                    ('triton_restored', chunk.chunk_gated_delta_rule)]
    kernels += [('flashinfer', fi_chunk_gated_delta_rule)]
    with torch.inference_mode():
        for backend, kernel in kernels:
            if backend.split('_')[0] not in args.backends:
                continue
            if backend == 'triton_kkt_fixed':
                original_configs, original_cache = tuner.configs, dict(tuner.cache)
                tuner.configs = [triton.Config({'BK': 64}, num_warps=4, num_stages=1)]
                tuner.cache.clear()
            elif backend == 'triton_restored':
                tuner.configs = original_configs
                tuner.cache.clear()
                tuner.cache.update(original_cache)
            refs = None
            for index in range(args.repeats):
                kwargs = {k: v.to('cuda').clone() if isinstance(v, torch.Tensor) else v for k, v in values.items()}
                current.clear()
                start = time.perf_counter()
                output = kernel(**kwargs)
                torch.cuda.synchronize()
                seconds = time.perf_counter() - start
                output_hashes = LogitAudit.tensor_hashes(output)
                after_hashes = {k: LogitAudit.tensor_hashes(v) for k, v in kwargs.items()}
                assert tensor_hashes == after_hashes, 'GDN mutated its input tensors'
                if refs is None:
                    refs = output_hashes
                    reference_tensors = [x.detach().float().cpu() for x in output]
                delta = [dict(changed_values=int(torch.count_nonzero(x.float().cpu() != ref)),
                              max_absolute_difference=float((x.float().cpu() - ref).abs().max()))
                         for x, ref in zip(output, reference_tensors)]
                assert (output_hashes == refs) == all(d['changed_values'] == 0 for d in delta)
                traces.append(list(current))
                row = dict(backend=backend, repeat=index, output_hashes=output_hashes,
                           different=output_hashes != refs, delta=delta, seconds=seconds,
                           stages=list(current), kkt_configs={str(k): str(v) for k, v in tuner.cache.items()})
                results.append(row)
                save(args.output / 'records' / f'{backend}_{index:02d}.json', row)
                event(args.output, 'measured', backend=backend, repeat=index,
                      different=row['different'], delta=delta)
                del output, kwargs
    configs = {}
    for name, module in list(sys.modules.items()):
        if not name.startswith('vllm.model_executor.layers.fla.ops.') or module is None:
            continue
        for key, value in vars(module).items():
            for _ in range(3):
                if type(value).__name__ == 'Autotuner':
                    configs[name + '.' + key] = {str(k): str(v) for k, v in value.cache.items()}
                    break
                if type(value).__name__ == 'Heuristics':
                    value = value.fn
                else:
                    break
    save(args.output / 'autotuner_configs.json', configs)
    save(args.output / 'summary.json', {b: dict(calls=sum(r['backend'] == b for r in results),
        differences=sum(r['backend'] == b and r['different'] for r in results))
        for b in dict.fromkeys(r['backend'] for r in results)})
    event(args.output, 'finished', calls=len(results))


if __name__ == '__main__':
    main()
