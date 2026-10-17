#!/usr/bin/env python3
"""Compare the old probe and HTTP on the same model object, thread, GPU and inputs."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import random
import shutil
import signal
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'eval/e2e_eval'), str(ROOT / 'scripts')]
import httpx
from harness import sync_vllm
from harness.common import write_json, sha256_file
from confirm_single_process_gpu import SOURCE, CASE_IDS, difference
from confirm_single_process_mvagent import install_worker_audit, begin_forward_audit, end_forward_audit
from benchmark_qwen35_fp8 import event


def schedule(target):
    rows = [(target, 'old_reused')] * 3
    rows += [(target, mode) for mode in ['old', 'wrapped', 'http', 'old', 'http', 'wrapped']]
    history = list(CASE_IDS)
    random.Random(20261011).shuffle(history)
    for index, name in enumerate(history):
        rows.extend([(name, 'old_reused'), (target, 'old' if index % 2 == 0 else 'http')])
    rows += [(target, mode) for mode in ['old', 'wrapped', 'http', 'old', 'http', 'wrapped']]
    return rows


def http_call(server, pool, wire):
    def send():
        with httpx.Client(timeout=650, trust_env=False) as client:
            response = client.post(f'http://127.0.0.1:{server.server_port}/v1/chat/completions',
                                   content=wire, headers={'Content-Type': 'application/json'})
            response.raise_for_status()
            return response.json()
    response = pool.submit(send)
    server.handle_request()  # The GPU always stays on this main thread.
    return response.result(timeout=660)


class BoundaryAudit:
    def __init__(self, runner, components=None):
        from diagnose_vllm_repro import LogitAudit
        self.logits = LogitAudit(runner)
        self.rows, self.handles, self.request_index = [], [], -1
        original = runner.model.compute_logits

        def logits(*args, **kwargs):
            result = original(*args, **kwargs)
            if self.logits.enabled:
                self.logits.pending.update(discarded=bool(runner.discard_request_mask.np[0]),
                    computed_tokens=int(runner.input_batch.num_computed_tokens_cpu[0]),
                    sequence_length=int(runner.optimistic_seq_lens_cpu[0]),
                    prompt_tokens=int(runner.input_batch.num_prompt_tokens[0]))
            return result

        runner.model.compute_logits = logits

        def prefill():
            return (self.logits.enabled and runner.input_batch.num_computed_tokens_cpu[0]
                    < runner.input_batch.num_prompt_tokens[0])

        def hashes(value):
            if isinstance(value, dict):
                return {k: hashes(v) for k, v in value.items()}
            return LogitAudit.tensor_hashes(value)

        def before(name):
            def hook(module, args, kwargs):
                if prefill():
                    self.rows.append(dict(name=name+'.input', tensors=hashes(dict(args=args,
                        kwargs={k: v for k, v in kwargs.items() if k != 'output'}))))
            return hook

        def after(name):
            def hook(module, args, kwargs, output):
                if prefill():
                    if output is None:
                        output = kwargs.get('output')
                    self.rows.append(dict(name=name+'.output', tensors=hashes(output)))
            return hook

        for name, module in [('visual', runner.model.visual),
                             ('decoder0', runner.model.language_model.model.layers[0]),
                             ('final_norm', runner.model.language_model.model.norm)]:
            self.handles.append(module.register_forward_pre_hook(before(name), with_kwargs=True))
            self.handles.append(module.register_forward_hook(after(name), with_kwargs=True))
        if components:
            layer = runner.model.language_model.model.layers[0]
            for name, module in layer.named_modules():
                if name and ('.' not in name or name.startswith('linear_attn.')):
                    self.handles.append(module.register_forward_pre_hook(before('decoder0.'+name), with_kwargs=True))
                    self.handles.append(module.register_forward_hook(after('decoder0.'+name), with_kwargs=True))

            def capture(module, args, kwargs):
                if not prefill() or runner.input_batch.num_computed_tokens_cpu[0] != 0:
                    return
                import torch
                from vllm.forward_context import get_forward_context
                assert not args
                meta = get_forward_context().attn_metadata[layer.linear_attn.prefix]
                cpu = lambda v: v.detach().clone().cpu() if isinstance(v, torch.Tensor) else v
                torch.save(dict(kwargs={k: cpu(v) for k, v in kwargs.items()},
                    metadata={k: cpu(getattr(meta, k)) for k in ['num_prefills', 'num_decodes',
                        'has_initial_state', 'non_spec_state_indices_tensor', 'non_spec_query_start_loc']}),
                    components/f'gdn_{self.request_index:03d}.pt')
            self.handles.append(layer.linear_attn.chunk_gated_delta_rule.register_forward_pre_hook(capture, with_kwargs=True))

            def capture_norm(module, args, kwargs):
                if not prefill() or runner.input_batch.num_computed_tokens_cpu[0] != 0:
                    return
                import torch
                assert len(args) == 1 and not kwargs
                torch.save(dict(x=args[0].detach().cpu(), weight=module.weight.detach().cpu(),
                    eps=module.variance_epsilon), components/f'norm_{self.request_index:03d}.pt')
            self.handles.append(layer.input_layernorm.register_forward_pre_hook(capture_norm, with_kwargs=True))

    def reset(self, enabled):
        self.request_index += 1
        self.rows = []
        self.logits.enabled = enabled
        self.logits.rows, self.logits.pending = [], None

    def close(self):
        for handle in self.handles:
            handle.remove()
        self.logits.close()


def run(args):
    if args.native_norm:
        sync_vllm.ENGINE_CONFIG['compilation_config'] = {'custom_ops': ['all', '-gemma_rms_norm']}
    else:
        # Preserve the pre-fix control even after the shared production profile changes.
        sync_vllm.ENGINE_CONFIG.pop('compilation_config', None)
    if args.profile == 'legacy':
        sync_vllm.ENGINE_CONFIG['gpu_memory_utilization'] = .95
        sync_vllm.ENVIRONMENT.pop('PYTORCH_ALLOC_CONF')
        os.environ.pop('PYTORCH_ALLOC_CONF', None)
        os.environ.pop('PYTORCH_CUDA_ALLOC_CONF', None)
    os.environ['MVAGENT_RECORD_TOKEN_IDS'] = '1'
    args.output.mkdir(parents=True, exist_ok=False)
    for path in [Path(__file__), ROOT/'src/models/vlm/local/sync_server.py',
                 ROOT/'scripts/diagnose_vllm_repro.py', ROOT/'scripts/confirm_single_process_gpu.py']:
        shutil.copyfile(path, args.output/path.name)
    target = args.target or ('cvbench:171' if args.model == '35B-A3B' else 'mvu_eval:ICL:713')
    plan = schedule(target)
    if args.adjacent_only:
        plan = plan[:9]
    if args.trace_components:
        assert args.trace
        plan = plan[:3]
    cases, retained = {}, {}
    for name in dict.fromkeys(row[0] for row in plan):
        source = SOURCE/(name+'.json')
        body = json.loads(source.read_bytes())
        body = dict(model='/weights/Qwen3.5-'+args.model, messages=body['messages'],
                    **{k: body[k] for k in ['temperature', 'top_p', 'max_tokens', 'seed']},
                    return_token_ids=True, chat_template_kwargs={'enable_thinking': False})
        wire = json.dumps(body, separators=(',', ':')).encode()
        cases[name] = wire
        retained[name] = body
    write_json(args.output/'manifest.json', dict(model=args.model, profile=args.profile, trace=args.trace,
        trace_components=args.trace_components, native_norm=args.native_norm,
        target=target, schedule=plan, config=sync_vllm.ENGINE_CONFIG, environment=sync_vllm.ENVIRONMENT,
        inputs={k: hashlib.sha256(v).hexdigest() for k, v in cases.items()},
        source_sha256=sha256_file(Path(__file__))))
    engine, audit, references, rows = None, None, {}, []

    def timeout(signum, frame):
        raise TimeoutError('Alignment request exceeded 600 seconds')
    signal.signal(signal.SIGALRM, timeout)
    signal.signal(signal.SIGTERM, signal.default_int_handler)
    try:
        event(args.output, 'loading', model=args.model, profile=args.profile, trace=args.trace)
        engine = sync_vllm.Engine(Path('/weights/Qwen3.5-'+args.model), args.output/'server')
        workers = []
        engine.llm.collective_rpc(lambda w: workers.append(w))
        if args.native_norm:
            from vllm.model_executor.layers.layernorm import GemmaRMSNorm
            norms = [m for m in workers[0].model_runner.model.modules() if isinstance(m, GemmaRMSNorm)]
            assert norms and all(m._forward_method.__name__ == 'forward_native'
                                 and not getattr(m, '_is_compiled', False) for m in norms)
            write_json(args.output/'norm_dispatch.json', dict(count=len(norms), method='forward_native'))
        old_workers = [tuple(w) for w in engine.llm.collective_rpc(install_worker_audit)]
        old_state = dict(workers=old_workers, observed=set(), forward_calls=0)
        if args.trace:
            audit = BoundaryAudit(workers[0].model_runner, args.output if args.trace_components else None)
        from vllm import SamplingParams
        with sync_vllm.SerialServer(('127.0.0.1', 0), engine) as server, ThreadPoolExecutor(max_workers=1) as pool:
            server.timeout = 650
            for index, (name, mode) in enumerate(plan):
                wire = cases[name]
                body = retained[name] if mode == 'old_reused' else json.loads(wire)
                generation = sync_vllm.validate_request(body, engine.card['id'])
                if audit:
                    audit.reset(True)
                engine.forward_calls = 0
                start = time.monotonic()
                if mode in {'old', 'old_reused'}:
                    begin_forward_audit(engine.llm, old_state)
                    signal.alarm(600)
                    try:
                        output = engine.llm.chat(body['messages'], sampling_params=SamplingParams(**generation),
                            use_tqdm=False, chat_template_kwargs={'enable_thinking': False})[0]
                    finally:
                        signal.alarm(0)
                    end_forward_audit(engine.llm, old_state, {})
                    generated = output.outputs[0]
                    record = dict(token_ids=list(generated.token_ids), text=generated.text,
                        finish_reason=generated.finish_reason, prompt_sha256=sync_vllm.digest(output.prompt_token_ids))
                else:
                    response = engine.complete(body, wire) if mode == 'wrapped' else http_call(server, pool, wire)
                    assert response['audit']['request_sha256'] == hashlib.sha256(wire).hexdigest()
                    generated = response['choices'][0]
                    record = dict(token_ids=generated['token_ids'], text=generated['message']['content'],
                        finish_reason=generated['finish_reason'], prompt_sha256=response['audit']['prompt_token_ids_sha256'])
                assert engine.forward_calls > 0
                assert json.dumps(body, separators=(',', ':')).encode() == wire, 'Request mutated during inference'
                record.update(index=index, case=name, mode=mode, captured=bool(audit),
                    input_sha256=sync_vllm.digest(dict(messages=body['messages'], generation=generation,
                        chat_template_kwargs={'enable_thinking': False})), wire_sha256=hashlib.sha256(wire).hexdigest(),
                    seconds=time.monotonic()-start, worker={**engine.worker, 'forward_calls':engine.forward_calls})
                if audit:
                    record.update(captured=True, boundaries=audit.rows,
                                  logits=[r for r in audit.logits.rows if not r['discarded']],
                                  discarded_prefill_logits=[r for r in audit.logits.rows if r['discarded']])
                delta = difference(references.setdefault(name, record), record)
                record['difference'] = delta
                write_json(args.output/'records'/f'{index:03d}.json', record)
                if audit:
                    assert len(record['logits']) == len(record['token_ids']), (len(record['logits']), len(record['token_ids']))
                rows.append(dict(index=index, case=name, mode=mode, tokens=len(record['token_ids']), **delta))
                write_json(args.output/'summary.json', rows)
                event(args.output, 'measured', model=args.model, completed=len(rows), planned=len(plan),
                      case=name, mode=mode, different=delta, seconds=record['seconds'])
        event(args.output, 'finished', responses=len(rows), differences=sum(r['tokens_changed'] for r in rows))
    except BaseException as exc:
        event(args.output, 'failed', error=repr(exc), responses=len(rows))
        raise
    finally:
        if audit:
            audit.close()
        if engine:
            engine.close()


def self_check():
    from test_e2e_sync import FakeEngine
    plan = schedule('cvbench:171')
    assert len(plan) == 31 and plan[:3] == [('cvbench:171', 'old_reused')]*3
    wire = json.dumps(dict(model='test', messages=[{'role':'user','content':'same'}], max_tokens=128)).encode()
    with sync_vllm.SerialServer(('127.0.0.1',0), FakeEngine('0')) as server, ThreadPoolExecutor(max_workers=1) as pool:
        assert http_call(server, pool, wire)['choices'][0]['token_ids'] == [34,248046]
    print('Same-thread HTTP transport and controlled schedule self-check passed')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', choices=['9B','27B','35B-A3B'])
    parser.add_argument('--profile', choices=['legacy','current'], default='current')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--target')
    parser.add_argument('--trace', action='store_true')
    parser.add_argument('--trace-components', action='store_true')
    parser.add_argument('--native-norm', action='store_true')
    parser.add_argument('--adjacent-only', action='store_true')
    parser.add_argument('--self-check', action='store_true')
    args = parser.parse_args()
    if args.self_check:
        self_check()
    else:
        assert args.model and args.output and args.output.is_relative_to('/runs')
        run(args)
