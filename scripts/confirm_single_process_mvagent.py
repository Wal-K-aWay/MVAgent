#!/usr/bin/env python3
"""Full MVAgent workload for confirm_single_process_gpu.py --mvagent.

Only the experiment's HTTP transport is replaced by a queue to the main-thread
vLLM engine. Runtime prompts, media construction and structured validation stay intact.
"""
from concurrent.futures import Future, ThreadPoolExecutor
from contextvars import copy_context
import hashlib
import json
import os
from pathlib import Path
from queue import Empty, Queue
import random
import signal
import threading
import time

from benchmark_qwen35_fp8 import digest, event, save
from confirm_bf16_mvagent import load_runner, token_trace, compare_traces

SOURCE = Path('/runs/devbox/independent_bf16_mvagent_20261011_budget32768/35B-A3B/reference/records')
ROOT = Path(__file__).resolve().parents[1]


def first_token_difference(a, b):
    if a == b:
        return None
    return next((i + 1 for i, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)) + 1)


def install_worker_audit(worker):
    import torch
    model = worker.model_runner.model
    worker._repro_identity = (os.getpid(), torch.cuda.current_device(),
                              str(next(model.parameters()).device), id(model))
    worker._repro_forward_calls = 0

    def forward(module, inputs):
        actual = (os.getpid(), torch.cuda.current_device(),
                  str(next(module.parameters()).device), id(module))
        assert actual == worker._repro_identity
        worker._repro_forward_calls += 1

    model.register_forward_pre_hook(forward)
    return worker._repro_identity


def reset_worker_audit(worker):
    worker._repro_forward_calls = 0


def read_worker_audit(worker):
    return dict(identity=worker._repro_identity, calls=worker._repro_forward_calls)


def begin_forward_audit(llm, state):
    if 'workers' in state:
        llm.collective_rpc(reset_worker_audit)
    state['observed'].clear()
    state['forward_calls'] = 0


def end_forward_audit(llm, state, audit):
    if 'workers' in state:
        workers = llm.collective_rpc(read_worker_audit)
        if 'cpu_group' in state:
            import torch.distributed as dist
            gathered = [None] * len(state['workers'])
            dist.all_gather_object(gathered, workers[0], group=state['cpu_group'])
            workers = gathered
        assert [tuple(w['identity']) for w in workers] == state['workers']
        assert all(w['calls'] > 0 for w in workers)
        state['observed'] = {tuple(w['identity']) for w in workers}
        state['forward_calls'] = sum(w['calls'] for w in workers)
        return workers
    identity = (audit['pid'], audit['gpu'], f"cuda:{audit['gpu']}", audit['model_object_id'])
    assert state['observed'] == {identity} and state['forward_calls'] > 0
    return [dict(identity=identity, calls=state['forward_calls'])]


def compare_rollouts(reference, current):
    changes = compare_traces(token_trace(reference['events']), token_trace(current['events']))
    for change in changes:
        if 'call' in change:
            a = token_trace(reference['events'])[change['scope']][change['call']]['token_ids']
            b = token_trace(current['events'])[change['scope']][change['call']]['token_ids']
            change['first_token_difference_1based'] = first_token_difference(a, b)
    semantic_keys = ['input', 'video_metadata', 'video_reports', 'watch_results', 'action_history',
                     'answer', 'trajectory', 'stop_reason']
    return dict(calls=changes, result_fields=[key for key in semantic_keys
                                            if reference['result'][key] != current['result'][key]])


def self_check():
    from confirm_bf16_mvagent import self_check as check_traces
    check_traces()
    assert first_token_difference([1, 2], [1, 3]) == 2
    assert first_token_difference([1], [1, 2]) == 2
    assert first_token_difference([1], [1]) is None
    print('Long-trajectory audit self-check passed')


class MVAgentProbe:
    def __init__(self, output):
        self.output = output
        candidates = []
        for path in SOURCE.rglob('result.json'):
            row = json.loads(path.read_text())
            calls = [e for e in row['events'] if e['kind'] == 'model_response']
            if row['status'] == 'ok':
                candidates.append(dict(name=row['sample_id'], old_calls=len(calls),
                    old_output_tokens=sum(len(e['token_ids']) for e in calls),
                    source=str(path), source_sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
        self.cases = []
        for benchmark in ['cvbench', 'mvu_eval', 'crossvid']:
            ranked = sorted([r for r in candidates if r['name'].startswith(benchmark + ':')],
                            key=lambda r: (-r['old_calls'], -r['old_output_tokens'], r['name']))
            assert len(ranked) >= 2
            self.cases.extend(ranked[:2])
        assert len(self.cases) == 6 and all(c['old_calls'] >= 12 for c in self.cases)
        save(output / 'inputs.json', self.cases)
        (output / 'mvagent_probe_source.py').write_bytes(Path(__file__).read_bytes())
        (output / 'trajectory_helpers.py').write_bytes(Path(__file__).with_name('confirm_bf16_mvagent.py').read_bytes())
        self.requests = Queue()
        self.references = {}

    def prepare_model(self, root, model, max_steps=5, gpu_memory_utilization=.95):
        import yaml
        self.root, self.model = root, model
        self.references = {}
        cfg = yaml.safe_load((ROOT / 'configs/inference/modal_qwen35_35b_a3b_no_skill.yaml').read_text())
        model_cfg = next(iter(cfg['models'].values()))
        model_cfg.pop('execution_profile', None)  # This diagnostic supplies its own engine configuration.
        model_cfg.update(model_name='/weights/Qwen3.5-' + model, dtype='bfloat16',
                         gpu_memory_utilization=gpu_memory_utilization, max_model_len=131072, reasoning_parser=None,
                         timeout_sec=600, max_retries=1)
        cfg['models'] = {'bench': model_cfg}
        cfg['agents']['global_agent']['model']['model_type'] = 'bench'
        for role in ['global_agent', 'video_agent']:
            cfg['agents'][role]['max_steps'] = max_steps
        for name in ['planner', 'observer']:
            cfg['agents']['video_agent'][name]['model_type'] = 'bench'
        cfg['runtime']['cache_dir'] = str(root / 'runtime_cache')
        config_path = root / 'config.yaml'
        config_path.write_text(yaml.safe_dump(cfg, sort_keys=False))
        runner = load_runner()
        _, configs, engines, self.records, self.runtime_manifest = runner._prepare_output(
            output_dir=root / 'runtime', config_path=config_path, dataset_root=Path('/assets'),
            sample_ids=tuple(c['name'] for c in self.cases), judge_model=None,
            resume=False, defer_open_qa_judge=True)
        self.cfg = configs.MVAgentConfig.from_dict(cfg)
        self.engine_class = engines.MVAgentEngine
        save(root / 'public_inputs.json', {sid: dict(question=r.sample.question, videos=dict(r.sample.videos))
                                           for sid, r in self.records.items()})
        (root / 'requests').mkdir()

    def infer(self, llm, state, audit, body):
        from vllm import SamplingParams, RequestOutput
        from vllm.sampling_params import StructuredOutputsParams
        from vllm.renderers.params import ChatParams
        assert threading.current_thread() is threading.main_thread()
        payload = json.loads(body)
        allowed = {'model', 'messages', 'temperature', 'top_p', 'max_tokens', 'seed',
                   'return_token_ids', 'structured_outputs', 'media_io_kwargs'}
        assert not set(payload).difference(allowed), set(payload).difference(allowed)
        assert payload['seed'] == 0 and payload['temperature'] == 0 and payload['max_tokens'] == 2048
        request_hash = hashlib.sha256(body).hexdigest()
        path = self.root / 'requests' / (request_hash + '.json')
        if not path.exists():
            path.write_bytes(body)
        params = SamplingParams(**{k: payload[k] for k in ['temperature', 'top_p', 'max_tokens', 'seed']},
            structured_outputs=(StructuredOutputsParams(**payload['structured_outputs'])
                                if payload.get('structured_outputs') else None))
        chat = ChatParams(chat_template_kwargs=dict(enable_thinking=False, add_generation_prompt=True,
            continue_final_message=False, tools=None, tokenize=False), media_io_kwargs=payload.get('media_io_kwargs'))
        state['observed'].clear()
        state['forward_calls'] = 0
        started = time.perf_counter()
        signal.alarm(600)
        try:
            _, prompts = llm.renderer.render_chat([payload['messages']], chat,
                llm.renderer.default_chat_tok_params, prompt_extras={'mm_processor_kwargs': None})
            output = llm._render_and_run_requests(iter(prompts), [params], RequestOutput, use_tqdm=False)[0]
        finally:
            signal.alarm(0)
        generated = output.outputs[0]
        identity = (audit['pid'], audit['gpu'], f"cuda:{audit['gpu']}", audit['model_object_id'])
        assert state['observed'] == {identity} and state['forward_calls'] > 0
        return dict(text=generated.text, token_ids=list(generated.token_ids),
            prompt_token_ids_sha256=hashlib.sha256(json.dumps(output.prompt_token_ids, separators=(',', ':')).encode()).hexdigest(),
            request_sha256=request_hash, finish_reason=generated.finish_reason,
            usage=dict(prompt_tokens=len(output.prompt_token_ids), completion_tokens=len(generated.token_ids)),
            seconds=time.perf_counter() - started, pid=audit['pid'], gpu=audit['gpu'],
            model_object_id=audit['model_object_id'], forward_identity=sorted(state['observed']),
            forward_calls=state['forward_calls'], request_id=f'inproc-{os.getpid()}-{output.request_id}')

    def run_stage(self, llm, state, audit):
        from models.execution import execution_scope, emit_event
        from models.pool import ModelPool, Replica, install_pools
        from models.vlm.api.providers.openai_compatible import OpenAICompatibleProvider
        stage = audit['stage']
        # The endpoint is only an admission identifier; no HTTP server is involved.
        pool = ModelPool('bench', [Replica('http://127.0.0.1:18123/v1', (audit['gpu'],), 1)],
                         digest(audit), root=str(self.root / stage / 'admission'))
        pool.register()
        install_pools({'bench': pool})
        original = OpenAICompatibleProvider._chat

        def queued_chat(provider, request, endpoint, body, lease):
            assert provider.pool is pool and lease is not None
            future = Future()
            lease.sent()
            self.requests.put((body, future))
            try:
                response = future.result(timeout=610)
            finally:
                lease.complete()
            emit_event('model_response', schema=request.schema_name, model='bench', **response)
            return response['text']

        OpenAICompatibleProvider._chat = queued_chat
        engine = self.engine_class(self.cfg, logger=lambda _: None)
        passes = []
        try:
            for repeat in range(2 if stage == 'A_initial' else 1):
                directory = self.root / f'{stage}_repeat{repeat}'
                directory.mkdir()
                rows, differences = [], []
                order = list(self.cases)
                random.Random(20261011 + repeat).shuffle(order)
                started = time.perf_counter()
                for case in order:
                    sid = case['name']
                    record_dir = directory / 'records' / sid
                    record_dir.mkdir(parents=True)
                    events, result, error = [], None, None
                    lock = threading.Lock()
                    with (record_dir / 'events.jsonl').open('a', buffering=1) as stream:
                        def emit(e):
                            with lock:
                                events.append(e)
                                stream.write(json.dumps(e) + '\n')

                        def answer():
                            record = self.records[sid]
                            with execution_scope(emit=emit, deadline=time.monotonic() + 1800):
                                return engine.answer(question=record.sample.question, videos=dict(record.sample.videos),
                                                     output_dir=str(record_dir / 'runtime'))

                        event(self.output, 'mvagent_question', model=self.model, stage=stage,
                              repeat=repeat, case=sid, completed=len(rows), pid=audit['pid'], gpu=audit['gpu'])
                        try:
                            with ThreadPoolExecutor(max_workers=1) as executor:
                                workflow = executor.submit(copy_context().run, answer)
                                while not workflow.done():
                                    try:
                                        body, future = self.requests.get(timeout=.05)
                                    except Empty:
                                        continue
                                    try:
                                        response = self.infer(llm, state, audit, body)
                                        with (record_dir / 'calls.jsonl').open('a') as raw:
                                            raw.write(json.dumps(response) + '\n')
                                        future.set_result(response)
                                    except Exception as exc:
                                        future.set_exception(exc)
                                result = workflow.result()
                        except Exception as exc:
                            error = repr(exc)
                        row = dict(case=sid, stage=stage, repeat=repeat, result=result, events=events, error=error)
                        save(record_dir / 'result.json', row)
                    if error:
                        raise RuntimeError(f'{sid}: {error}')
                    trace = token_trace(events)
                    assert trace
                    reference = self.references.setdefault(sid, row)
                    delta = compare_rollouts(reference, row)
                    if delta['calls'] or delta['result_fields']:
                        differences.append(dict(case=sid, **delta))
                    calls = [e for e in events if e['kind'] == 'model_response']
                    rows.append(dict(case=sid, calls=len(calls), output_tokens=sum(len(e['token_ids']) for e in calls),
                                     global_rounds=max((e.get('global_round') or 0 for e in calls), default=0),
                                     seconds=result['time'], result_path=str(record_dir / 'result.json')))
                    event(self.output, 'mvagent_measuring', model=self.model, stage=stage, repeat=repeat,
                          rollouts=len(rows), model_calls=sum(r['calls'] for r in rows),
                          differences=len(differences), case=sid, pid=audit['pid'], gpu=audit['gpu'])
                summary = dict(stage=stage, repeat=repeat, gpu=audit['gpu'], rollouts=len(rows),
                    responses=sum(r['calls'] for r in rows), rows=rows, differences=differences,
                    started_monotonic=started, ended_monotonic=time.perf_counter(),
                    seconds=time.perf_counter() - started)
                passes.append(summary)
                save(directory / 'summary.json', summary)
        finally:
            engine.close()
            OpenAICompatibleProvider._chat = original
            install_pools({})
        return passes


if __name__ == '__main__':
    self_check()
