#!/usr/bin/env python3
"""Replay archived Agent requests with standard vLLM and audit pre/post-mask logits."""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time

from benchmark_qwen35_fp8 import digest, event, save
from confirm_single_process_mvagent import first_token_difference

SOURCES = {
    '9B': '/runs/devbox/inproc_mvagent_9b_20261011_r1',
    '27B': '/runs/devbox/inproc_mvagent_27b_20261011_r1',
    '35B-A3B': '/runs/devbox/inproc_mvagent_20261011_r1',
}


def compare(reference, current):
    assert reference['request_sha256'] == current['request_sha256']
    assert reference['prompt_sha256'] == current['prompt_sha256']
    first = first_token_difference(reference['token_ids'], current['token_ids'])
    result = dict(first_token_difference=first)
    if reference.get('prefill_layers') and current.get('prefill_layers'):
        a, b = reference['prefill_layers'], current['prefill_layers']
        assert [r['name'] for r in a] == [r['name'] for r in b]
        result['first_prefill_layer_difference'] = next((x['name'] for x, y in zip(a, b)
                                                        if x['outputs'] != y['outputs']), None)
    if reference['logits'] and current['logits']:
        # Only compare distributions conditioned on the same generated prefix.
        limit = min(first or len(reference['token_ids']), len(current['token_ids']))
        for field in ['raw_sha256', 'processed_sha256', 'mask_sha256']:
            result[field + '_first_difference'] = next((i + 1 for i, (a, b) in enumerate(
                zip(reference['logits'][:limit], current['logits'][:limit])) if a[field] != b[field]), None)
        if first is not None and first <= limit:
            result['at_token_difference'] = [reference['logits'][first - 1], current['logits'][first - 1]]
    return result


def self_check():
    base = dict(request_sha256='r', prompt_sha256='p', token_ids=[1, 2], logits=[
        dict(raw_sha256='a', processed_sha256='a', mask_sha256='m'),
        dict(raw_sha256='b', processed_sha256='b', mask_sha256='m')])
    changed = {**base, 'token_ids': [1, 3], 'logits': [base['logits'][0],
        dict(raw_sha256='c', processed_sha256='c', mask_sha256='m')]}
    delta = compare(base, changed)
    assert delta['first_token_difference'] == delta['raw_sha256_first_difference'] == 2
    assert delta['mask_sha256_first_difference'] is None
    assert compare(base, base)['first_token_difference'] is None
    base['prefill_layers'] = [dict(name='layers.0', outputs='a')]
    changed['prefill_layers'] = [dict(name='layers.0', outputs='b')]
    assert compare(base, changed)['first_prefill_layer_difference'] == 'layers.0'
    print('Logit comparison self-check passed')


class LogitAudit:
    def __init__(self, runner, trace_layers=False, gdn_layer=0):
        self.enabled, self.rows, self.pending = False, [], None
        self.layers, self.handles = [], []
        self.capture_directory = None
        self.runner = runner
        self.original_logits = runner.model.compute_logits
        self.original_sample = runner.sampler.sample

        def logits(*args, **kwargs):
            output = self.original_logits(*args, **kwargs)
            if self.enabled:
                assert self.pending is None
                self.pending = self.describe(output, 'raw')
            return output

        def sample(logits, *args, **kwargs):
            if self.enabled:
                assert self.pending is not None
                self.pending.update(self.describe(logits, 'processed'))
                self.rows.append(self.pending)
                self.pending = None
            return self.original_sample(logits, *args, **kwargs)

        runner.model.compute_logits = logits
        runner.sampler.sample = sample
        if trace_layers:
            def record(name):
                def hook(module, inputs, kwargs, output):
                    if self.enabled and not self.rows and self.pending is None:
                        if output is None:
                            output = kwargs.get('output')
                        self.layers.append(dict(name=name, outputs=self.tensor_hashes(output)))
                return hook
            model = runner.model.language_model.model
            for name, module in model.named_modules():
                # Capture each decoder boundary plus its immediate computational components.
                parts = name.split('.')
                if (name in ['embed_tokens', 'norm'] or (len(parts) in [2, 3] and parts[0] == 'layers')
                        or name.startswith(f'layers.{gdn_layer}.linear_attn.')):
                    self.handles.append(module.register_forward_hook(record(name), with_kwargs=True))
            gdn = model.layers[gdn_layer].linear_attn

            def capture_gdn(module, inputs, kwargs):
                if self.enabled and not self.rows and self.pending is None:
                    import torch
                    from vllm.forward_context import get_forward_context
                    assert not inputs
                    copied = {k: v.detach().clone().cpu() if isinstance(v, torch.Tensor) else v
                              for k, v in kwargs.items()}
                    self.layers.append(dict(name=f'layers.{gdn_layer}.linear_attn.chunk_inputs',
                                            outputs={k: self.tensor_hashes(v) for k, v in copied.items()}))
                    meta = get_forward_context().attn_metadata[gdn.prefix]
                    metadata = {k: getattr(meta, k) for k in ['num_prefills', 'num_decodes', 'has_initial_state',
                                'non_spec_state_indices_tensor', 'non_spec_query_start_loc']}
                    metadata = {k: v.cpu() if isinstance(v, torch.Tensor) else v for k, v in metadata.items()}
                    torch.save(dict(kwargs=copied, metadata=metadata), self.capture_directory / 'gdn_inputs.pt')

            self.handles.append(gdn.chunk_gated_delta_rule.register_forward_pre_hook(capture_gdn, with_kwargs=True))

    @staticmethod
    def tensor_hashes(value):
        import torch
        if isinstance(value, torch.Tensor):
            cpu = value.detach().contiguous().cpu()
            return dict(shape=list(cpu.shape), dtype=str(cpu.dtype),
                        sha256=hashlib.sha256(cpu.view(torch.uint8).numpy().tobytes()).hexdigest())
        if isinstance(value, (tuple, list)):
            return [LogitAudit.tensor_hashes(v) for v in value]
        if type(value) in [int, float, str, bool]:
            return value
        assert value is None, type(value)
        return None

    @staticmethod
    def describe(tensor, prefix):
        import numpy as np
        import torch
        assert tensor.ndim == 2 and tensor.shape[0] == 1, tensor.shape
        cpu = tensor.detach().contiguous().cpu()
        values = cpu.float().numpy()[0]
        top = np.argpartition(values, -8)[-8:]
        top = sorted(top.tolist(), key=lambda i: (-float(values[i]), i))
        result = {prefix + '_sha256': hashlib.sha256(cpu.view(torch.uint8).numpy().tobytes()).hexdigest(),
                  prefix + '_top8': [[i, float(values[i])] for i in top],
                  prefix + '_nan': int(np.isnan(values).sum()),
                  prefix + '_posinf': int(np.isposinf(values).sum())}
        if prefix == 'processed':
            mask = np.isneginf(values)
            result.update(mask_sha256=hashlib.sha256(mask.tobytes()).hexdigest(),
                          masked_tokens=int(mask.sum()))
        return result

    def close(self):
        for handle in self.handles:
            handle.remove()
        self.runner.model.compute_logits = self.original_logits
        self.runner.sampler.sample = self.original_sample


def run(args):
    os.environ.update(VLLM_ENABLE_V1_MULTIPROCESSING='0', VLLM_BATCH_INVARIANT='0',
                      OMP_NUM_THREADS='1', MKL_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1',
                      TOKENIZERS_PARALLELISM='false')
    import torch
    from vllm import LLM, SamplingParams, RequestOutput
    from vllm.renderers.params import ChatParams
    from vllm.sampling_params import StructuredOutputsParams

    def timeout(signum, frame):
        raise TimeoutError('Diagnostic request exceeded 600 seconds')
    signal.signal(signal.SIGALRM, timeout)
    args.output.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(__file__, args.output / 'source.py')
    source = Path(SOURCES[args.model])
    model_root = source / args.model
    manifest = json.loads((source / 'manifest.json').read_text())
    config = dict(manifest['config'])
    config.pop('load_format')  # Use the standard loader, without GPU migration customizations.
    config.update(distributed_executor_backend='uni')
    config['additional_config'] = {**config['additional_config'], 'gdn_prefill_backend': args.gdn_backend}
    save(args.output / 'manifest.json', dict(model=args.model, config=config,
        source=str(source), source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        trace_layers=args.trace_layers, gdn_layer=args.gdn_layer, adjacent_only=args.adjacent_only,
        versions={k: importlib.metadata.version(k) for k in ['vllm', 'torch', 'transformers', 'xgrammar']},
        commit=subprocess.check_output(['git', '-c', 'safe.directory=/repo', 'rev-parse', 'HEAD'], text=True).strip(),
        gpu_inventory=subprocess.check_output(['nvidia-smi', '--query-gpu=index,name,uuid,driver_version', '--format=csv'], text=True),
        pid=os.getpid(), cuda_visible_devices=os.environ.get('CUDA_VISIBLE_DEVICES'), scoring_requested=False))
    assert torch.cuda.device_count() == 1
    histories, firsts = {}, {}
    for directory in sorted((model_root / 'A_initial_repeat0/records').iterdir()):
        calls = [json.loads(line) for line in (directory / 'calls.jsonl').read_text().splitlines()]
        histories[directory.name] = [c['request_sha256'] for c in calls]
        firsts[directory.name] = calls[0]['request_sha256']
    target = 'crossvid:FSA:121' if args.model == '27B' else 'cvbench:664'
    event(args.output, 'loading', model=args.model)
    llm = LLM(model='/weights/Qwen3.5-' + args.model, **config)
    workers = []
    llm.collective_rpc(lambda worker: workers.append(worker))
    assert len(workers) == 1 and type(llm.llm_engine.engine_core).__name__ == 'InprocClient'
    runner = workers[0].model_runner
    audit = LogitAudit(runner, args.trace_layers, args.gdn_layer)
    identity = dict(pid=os.getpid(), gpu=torch.cuda.current_device(), model_object_id=id(runner.model))
    save(args.output / 'identity.json', identity)
    refs, captured_refs, records = {}, {}, []
    try:
        # Uninstrumented calls establish whether auditing itself changes the observed behavior.
        schedule = [('adjacent_plain', firsts[target], False)] * 3
        schedule += [('adjacent_audit', firsts[target], True)] * 3
        for name in firsts:
            schedule += [('other_global:' + name, firsts[name], False), ('after_global', firsts[target], True)]
        for name in ['cvbench:199', target]:
            schedule += [('history:' + name, sha, False) for sha in histories[name]]
            schedule += [('after_history:' + name, firsts[target], True)] * 2
        if args.adjacent_only:
            schedule = schedule[:6]
        if args.trace_layers:
            schedule += [('after_audit_plain', firsts[target], False)] * 3
        for index, (phase, request_hash, capture) in enumerate(schedule):
            event(args.output, 'request', model=args.model, index=index, total=len(schedule), phase_name=phase)
            body = (model_root / 'requests' / (request_hash + '.json')).read_bytes()
            assert hashlib.sha256(body).hexdigest() == request_hash
            payload = json.loads(body)
            save(args.output / 'request_sources' / (request_hash + '.json'),
                 dict(path=str(model_root / 'requests' / (request_hash + '.json')), sha256=request_hash))
            params = SamplingParams(**{k: payload[k] for k in ['temperature', 'top_p', 'max_tokens', 'seed']},
                structured_outputs=StructuredOutputsParams(**payload['structured_outputs'])
                if payload.get('structured_outputs') else None)
            chat = ChatParams(chat_template_kwargs=dict(enable_thinking=False, add_generation_prompt=True,
                continue_final_message=False, tools=None, tokenize=False), media_io_kwargs=payload.get('media_io_kwargs'))
            audit.enabled, audit.rows, audit.pending, audit.layers = capture, [], None, []
            audit.capture_directory = args.output / 'captures' / f'{index:04d}'
            if capture and args.trace_layers:
                audit.capture_directory.mkdir(parents=True)
            started = time.perf_counter()
            signal.alarm(600)
            try:
                _, prompts = llm.renderer.render_chat([payload['messages']], chat,
                    llm.renderer.default_chat_tok_params, prompt_extras={'mm_processor_kwargs': None})
                output = llm._render_and_run_requests(iter(prompts), [params], RequestOutput, use_tqdm=False)[0]
            finally:
                signal.alarm(0)
            generated = output.outputs[0]
            row = dict(index=index, phase=phase, request_sha256=request_hash,
                prompt_sha256=hashlib.sha256(json.dumps(output.prompt_token_ids, separators=(',', ':')).encode()).hexdigest(),
                token_ids=list(generated.token_ids), text=generated.text, finish_reason=generated.finish_reason,
                seconds=time.perf_counter()-started, logits=audit.rows, prefill_layers=audit.layers, identity=identity)
            save(args.output / 'records' / f'{index:04d}.json', row)
            if capture:
                assert len(audit.rows) == len(row['token_ids']) and audit.pending is None
                assert all(r['raw_nan'] == r['raw_posinf'] == r['processed_nan'] == r['processed_posinf'] == 0 for r in audit.rows)
            reference = refs.setdefault(request_hash, row)
            delta = compare(reference, row)
            if capture:
                delta.update(compare(captured_refs.setdefault(request_hash, row), row))
                delta['plain_reference_token_difference'] = first_token_difference(reference['token_ids'], row['token_ids'])
            records.append(dict(index=index, phase=phase, tokens=len(row['token_ids']), seconds=row['seconds'],
                                request_sha256=request_hash, **delta))
            save(args.output / 'summary.json', records)
            event(args.output, 'measured', model=args.model, completed=len(records),
                  token_differences=sum(r['first_token_difference'] is not None for r in records),
                  latest_difference=delta, output_tokens=len(row['token_ids']))
        event(args.output, 'finished', model=args.model, responses=len(records),
              token_differences=sum(r['first_token_difference'] is not None for r in records))
    finally:
        audit.close()
        llm.llm_engine.engine_core.shutdown()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--model', choices=list(SOURCES))
    p.add_argument('--output', type=Path)
    p.add_argument('--self-check', action='store_true')
    p.add_argument('--trace-layers', action='store_true', help='Hash prefill decoder and component outputs')
    p.add_argument('--adjacent-only', action='store_true', help='Only run the six adjacent repeats')
    p.add_argument('--gdn-backend', choices=['triton', 'flashinfer'], default='triton')
    p.add_argument('--gdn-layer', type=int, default=0, help='GDN layer whose component inputs are captured')
    args = p.parse_args()
    if args.self_check:
        self_check()
        return
    if args.model is None or args.output is None or not str(args.output).startswith('/runs/') or (args.output / 'manifest.json').exists():
        p.error('Choose a model and a fresh /runs/ output directory')
    run(args)


if __name__ == '__main__':
    main()
