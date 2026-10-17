#!/usr/bin/env python3
"""Full no-skill MVAgent repetition with a standard vLLM loader and explicit GDN backend."""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
import traceback

from benchmark_qwen35_fp8 import event, save
from confirm_single_process_mvagent import MVAgentProbe
from diagnose_vllm_repro import SOURCES

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'eval/e2e_eval'))
import harness
from models.vlm.local.sync_server import ENGINE_CONFIG, ENVIRONMENT, execution_profile


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--model', required=True, choices=list(SOURCES))
    p.add_argument('--output', required=True, type=Path)
    references = p.add_mutually_exclusive_group()
    references.add_argument('--reference', type=Path, help='Reference A_initial_repeat0/records from an earlier process')
    references.add_argument('--reference-index', type=Path, help='Frozen case-to-result paths and SHA256 from earlier replicas')
    p.add_argument('--inputs', type=Path, help='Frozen nonempty panel in the existing inputs.json format')
    p.add_argument('--barrier-dir', type=Path, help='Wait for the replica controller after loading')
    p.add_argument('--gdn-backend', required=True, choices=['triton', 'flashinfer'])
    p.add_argument('--max-steps', type=int, default=5, choices=[5, 10])
    args = p.parse_args()
    assert str(args.output).startswith('/runs/') and not (args.output / 'manifest.json').exists()
    os.environ.update(ENVIRONMENT, MVAGENT_RECORD_TOKEN_IDS='1')
    import torch
    from vllm import LLM
    from vllm.distributed.parallel_state import cleanup_dist_env_and_memory

    def timeout(signum, frame):
        raise TimeoutError('Model call exceeded 600 seconds')
    signal.signal(signal.SIGALRM, timeout)
    signal.signal(signal.SIGTERM, signal.default_int_handler)
    assert torch.cuda.device_count() == 1
    args.output.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(__file__, args.output / 'source.py')
    dependencies = args.output / 'driver_dependencies'
    dependencies.mkdir()
    for name in ['benchmark_qwen35_fp8.py', 'confirm_bf16_mvagent.py',
                 'confirm_single_process_mvagent.py', 'diagnose_vllm_repro.py']:
        shutil.copyfile(Path(__file__).with_name(name), dependencies / name)
    source = Path(SOURCES[args.model])
    config = dict(ENGINE_CONFIG)
    config['additional_config'] = {**config['additional_config'], 'gdn_prefill_backend': args.gdn_backend}
    probe = MVAgentProbe(args.output)
    if args.inputs:
        assert str(args.inputs).startswith('/runs/')
        cases = json.loads(args.inputs.read_text())
        assert cases and len(cases) == len({r['name'] for r in cases})
        assert all(hashlib.sha256(Path(r['source']).read_bytes()).hexdigest() == r['source_sha256']
                   for r in cases)
        probe.cases = cases
        save(args.output / 'inputs.json', cases)
    root = args.output / args.model
    root.mkdir()
    shutil.copyfile(source / args.model / 'weight_environment_metadata.json', root / 'weight_environment_metadata.json')
    probe.prepare_model(root, args.model, max_steps=args.max_steps,
                        gpu_memory_utilization=config['gpu_memory_utilization'])
    if args.reference:
        assert str(args.reference).startswith('/runs/') and args.reference.parents[1].name == args.model
        probe.references = {r['case']: r for path in args.reference.glob('*/result.json')
                            if (r := json.loads(path.read_text()))['error'] is None}
        assert set(probe.references) == {c['name'] for c in probe.cases}
    if args.reference_index:
        assert str(args.reference_index).startswith('/runs/')
        index = json.loads(args.reference_index.read_text())
        for case in probe.cases:
            ref = index[case['name']]
            path = Path(ref['path'])
            assert str(path).startswith('/runs/')
            assert hashlib.sha256(path.read_bytes()).hexdigest() == ref['sha256']
            row = json.loads(path.read_text())
            assert row['case'] == case['name'] and row['error'] is None
            probe.references[case['name']] = row
    save(args.output / 'manifest.json', dict(model=args.model, config=config,
        execution=execution_profile(), max_steps=args.max_steps,
        input_panel=str(args.inputs) if args.inputs else None,
        reference=str(args.reference) if args.reference else None, pid=os.getpid(), scoring_requested=False,
        reference_index=str(args.reference_index) if args.reference_index else None,
        reference_index_sha256=hashlib.sha256(args.reference_index.read_bytes()).hexdigest() if args.reference_index else None,
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        probe_sha256=hashlib.sha256(Path(__file__).with_name('confirm_single_process_mvagent.py').read_bytes()).hexdigest(),
        versions={k: importlib.metadata.version(k) for k in ['vllm', 'torch', 'transformers', 'xgrammar', 'flashinfer-python', 'triton']},
        commit=subprocess.check_output(['git', '-c', 'safe.directory=/repo', 'rev-parse', 'HEAD'], text=True).strip(),
        cuda_visible_devices=os.environ.get('CUDA_VISIBLE_DEVICES'),
        gpu_inventory=subprocess.check_output(['nvidia-smi', '--query-gpu=index,name,uuid,driver_version', '--format=csv'], text=True)))
    result = dict(model=args.model, passes=[], stable=False, error=None)
    llm = None
    try:
        event(args.output, 'loading', model=args.model, backend=args.gdn_backend)
        llm = LLM(model='/weights/Qwen3.5-' + args.model, **config)
        workers = []
        llm.collective_rpc(lambda worker: workers.append(worker))
        assert len(workers) == 1 and type(llm.llm_engine.engine_core).__name__ == 'InprocClient'
        model = workers[0].model_runner.model
        from vllm.model_executor.layers.layernorm import GemmaRMSNorm
        norms = [m for m in model.modules() if isinstance(m, GemmaRMSNorm)]
        assert norms and all(m._forward_method.__name__ == 'forward_native' for m in norms)
        state = dict(observed=set(), forward_calls=0)
        audit = dict(pid=os.getpid(), gpu=0, model_object_id=id(model), stage='A_initial')

        def forward_identity(module, inputs):
            state['observed'].add((os.getpid(), torch.cuda.current_device(),
                                   str(next(module.parameters()).device), id(module)))
            state['forward_calls'] += 1
        handle = model.register_forward_pre_hook(forward_identity)
        save(root / 'A_initial_identity.json', audit)
        if args.barrier_dir:
            assert str(args.barrier_dir).startswith('/runs/')
            args.barrier_dir.mkdir(parents=True, exist_ok=True)
            (args.barrier_dir / (args.output.name + '.ready')).touch()
            event(args.output, 'ready', model=args.model, pid=os.getpid())
            deadline = time.monotonic() + 1200
            while not (args.barrier_dir / 'go').exists():
                if time.monotonic() > deadline:
                    raise TimeoutError('Replica start barrier timed out')
                time.sleep(.2)
        result['passes'] = probe.run_stage(llm, state, audit)
        handle.remove()
        result['stable'] = len(result['passes']) == 2 and all(not r['differences'] for r in result['passes'])
    except BaseException as exc:
        result.update(error=repr(exc), traceback=traceback.format_exc())
        raise
    finally:
        result.update(rollouts=sum(r['rollouts'] for r in result['passes']),
                      calls=sum(r['responses'] for r in result['passes']),
                      differences=sum(len(r['differences']) for r in result['passes']))
        save(args.output / 'summary.json', result)
        if llm is not None:
            llm.llm_engine.engine_core.shutdown()
            cleanup_dist_env_and_memory()
        event(args.output, 'finished' if result['error'] is None else 'failed', model=args.model,
              rollouts=result['rollouts'], calls=result['calls'], stable=result['stable'], error=result['error'])


if __name__ == '__main__':
    main()
