"""Fixed Qwen3.5 BF16 execution profile and a serial OpenAI-compatible endpoint.

HTTP is only the transport. The standard vLLM engine and every model forward run
in this process's main thread, with one request at a time.
"""
from __future__ import annotations

import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import importlib.metadata
import json
import os
from pathlib import Path
import signal
import threading
import time
import traceback

def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f'.{path.name}.{os.getpid()}.{threading.get_ident()}.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)

PROFILE = 'qwen35-bf16-flashinfer-sync'
# Full 8192-token video answers can exceed ten minutes on a single H100.
REQUEST_TIMEOUT_SECONDS = 1800
ENVIRONMENT = dict(VLLM_ENABLE_V1_MULTIPROCESSING='0', VLLM_BATCH_INVARIANT='0',
    OMP_NUM_THREADS='1', MKL_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', TOKENIZERS_PARALLELISM='false',
    PYTORCH_ALLOC_CONF='expandable_segments:True')
VERSIONS = {'vllm': '0.19.1', 'torch': '2.10.0', 'transformers': '4.57.6',
            'xgrammar': '0.2.2', 'flashinfer-python': '0.6.6', 'triton': '3.6.0'}
# Leave room for 512-frame vision workspaces; the 35B panel exhausted memory at .95.
ENGINE_CONFIG = dict(dtype='bfloat16', kv_cache_dtype='auto', tensor_parallel_size=1,
    distributed_executor_backend='uni', seed=0, generation_config='vllm',
    max_model_len=131072, max_num_seqs=1, max_num_batched_tokens=32768,
    gpu_memory_utilization=.94, enable_prefix_caching=False, mm_processor_cache_gb=0,
    mm_encoder_tp_mode='weights',
    limit_mm_per_prompt={'image': {'count': 512, 'width': 448, 'height': 448}, 'video': 8},
    async_scheduling=False, enforce_eager=True, additional_config={'gdn_prefill_backend': 'flashinfer'},
    # GemmaRMSNorm compiles internally even in eager mode; changing shapes changes its numerics.
    compilation_config={'custom_ops': ['all', '-gemma_rms_norm']})


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def execution_profile():
    versions = {name: importlib.metadata.version(name) for name in VERSIONS}
    if any(versions[name].split('+')[0] != expected for name, expected in VERSIONS.items()):
        raise RuntimeError(f'This validated profile requires {VERSIONS}; installed: {versions}')
    return dict(profile=PROFILE, config=ENGINE_CONFIG, environment=ENVIRONMENT,
                versions=versions, source_sha256=sha256_file(Path(__file__)))


def validate_request(body, model):
    if not isinstance(body, dict):
        raise ValueError('The request must be a JSON object')
    allowed = {'model', 'messages', 'temperature', 'top_p', 'max_tokens', 'seed',
               'return_token_ids', 'chat_template_kwargs', 'stream', 'structured_outputs', 'media_io_kwargs'}
    if set(body) - allowed:
        raise ValueError(f'Unsupported request fields: {sorted(set(body) - allowed)}')
    if body.get('model') != model or not isinstance(body.get('messages'), list) or not body['messages']:
        raise ValueError('A served model and nonempty messages are required')
    temperature, seed = body.get('temperature', 0), body.get('seed', 0)
    if (type(temperature) not in (int, float) or temperature != 0 or type(seed) is not int or seed != 0
        or body.get('stream', False) is not False):
        raise ValueError('This endpoint requires temperature=0, seed=0 and non-streaming requests')
    chat = body.get('chat_template_kwargs', {'enable_thinking': False})
    if chat != {'enable_thinking': False}:
        raise ValueError('This endpoint requires enable_thinking=false')
    maximum = body.get('max_tokens')
    top_p = body.get('top_p', 1)
    if type(maximum) is not int or not 0 < maximum <= 8192:
        raise ValueError('max_tokens must be an integer in [1, 8192]')
    if type(top_p) not in (int, float) or not 0 < top_p <= 1:
        raise ValueError('top_p must be in (0, 1]')
    for key in ('structured_outputs', 'media_io_kwargs'):
        if key in body and not isinstance(body[key], dict):
            raise ValueError(f'{key} must be an object')
    return dict(temperature=temperature, top_p=top_p, max_tokens=maximum, seed=seed)


def input_digest(body):
    value = dict(messages=body['messages'], generation=validate_request(body, body['model']),
                 chat_template_kwargs={'enable_thinking': False})
    value.update({k: body[k] for k in ('structured_outputs', 'media_io_kwargs') if k in body})
    return digest(value)


def validate_card(card):
    execution = card.get('execution', {})
    if (execution.get('profile') != PROFILE or execution.get('config') != ENGINE_CONFIG
        or execution.get('environment') != ENVIRONMENT
        or execution.get('source_sha256') != sha256_file(Path(__file__))
        or any(execution.get('versions', {}).get(k, '').split('+')[0] != v for k, v in VERSIONS.items())):
        raise RuntimeError('Endpoint does not match the validated execution profile')


def token_audit(data, wire):
    tokens = data['choices'][0].get('token_ids')
    prompt = data.get('prompt_token_ids')
    for values in [tokens, prompt]:
        if not isinstance(values, list) or any(type(v) is not int or v < 0 for v in values):
            raise ValueError('The endpoint must return complete output and prompt token IDs')
    if not prompt:
        raise ValueError('The endpoint returned an empty prompt token sequence')
    if (len(tokens) != data['usage']['completion_tokens'] or len(prompt) != data['usage']['prompt_tokens']
        or len(tokens)+len(prompt) != data['usage']['total_tokens']):
        raise ValueError('Token IDs do not match the reported usage')
    audit = data['audit']
    if (audit['request_sha256'] != hashlib.sha256(wire).hexdigest()
        or audit['prompt_token_ids_sha256'] != digest(prompt)
        or audit['input_sha256'] != input_digest(json.loads(wire))):
        raise ValueError('Response input hashes do not match the actual request or prompt tokens')
    if audit['worker']['forward_calls'] <= 0:
        raise ValueError('The endpoint did not report an actual model forward')
    rate = cache_hit_rate(data['usage'])
    if audit.get('cache_hit_rate') != rate:
        raise ValueError('Cache hit rate does not match the reported usage')
    return dict(token_ids=tokens, **audit)


def cache_hit_rate(usage):
    details = usage.get('prompt_tokens_details')
    cached = details.get('cached_tokens') if isinstance(details, dict) else None
    prompt = usage.get('prompt_tokens')
    if type(prompt) is not int or prompt <= 0 or type(cached) is not int or not 0 <= cached <= prompt:
        raise ValueError('A valid per-request cached_tokens count is required')
    return cached / prompt


class Engine:
    def __init__(self, model: Path, log_dir: Path, served_model_name=None):
        if threading.current_thread() is not threading.main_thread():
            raise RuntimeError('The inference engine must be created on the main thread')
        os.environ.update(ENVIRONMENT)
        execution = execution_profile()
        model = model.absolute()
        config = json.loads((model / 'config.json').read_text())
        if config.get('model_type') not in {'qwen3_5', 'qwen3_5_moe'} or any(
            value.get('quantization_config') for value in [config, config.get('text_config', {})]
        ):
            raise ValueError('This profile requires an unquantized Qwen3.5 checkpoint')
        weights = dict(files={p.name: sha256_file(p) for p in sorted(model.iterdir())
                              if p.is_file() and p.suffix in {'.json', '.jinja', '.txt'}},
                       shards=[(p.name, p.stat().st_size, p.stat().st_mtime_ns)
                               for p in sorted(model.glob('*.safetensors'))])
        if not weights['shards']:
            raise ValueError(f'No safetensors weights in {model}')
        import torch
        from vllm import LLM

        if torch.cuda.device_count() != 1:
            raise RuntimeError('Expose exactly one GPU per endpoint using CUDA_VISIBLE_DEVICES')
        self.llm = LLM(model=str(model), **ENGINE_CONFIG)
        workers = []
        self.llm.collective_rpc(lambda worker: workers.append(worker))
        if len(workers) != 1 or type(self.llm.llm_engine.engine_core).__name__ != 'InprocClient':
            raise RuntimeError('Expected one in-process vLLM worker')
        actual_model = workers[0].model_runner.model
        self.worker = dict(pid=os.getpid(), cuda_visible_devices=os.environ['CUDA_VISIBLE_DEVICES'],
            gpu_uuid=str(torch.cuda.get_device_properties(0).uuid), gpu_name=torch.cuda.get_device_name(0),
            model_object_id=id(actual_model))
        self.forward_calls = 0

        def forward(module, inputs):
            if (os.getpid() != self.worker['pid'] or id(module) != self.worker['model_object_id']
                or torch.cuda.current_device() != 0 or str(next(module.parameters()).device) != 'cuda:0'
                or threading.current_thread() is not threading.main_thread()):
                raise RuntimeError('The model forward moved outside the fixed worker')
            self.forward_calls += 1

        norms = [m for m in actual_model.modules() if type(m).__name__ == 'GemmaRMSNorm']
        if not norms or any(m._forward_method.__name__ != 'forward_native' for m in norms):
            raise RuntimeError('The validated profile requires native GemmaRMSNorm')
        actual_model.register_forward_pre_hook(forward)
        self.card = dict(id=served_model_name or str(model), object='model', created=0, owned_by='local', root=str(model),
            max_model_len=ENGINE_CONFIG['max_model_len'], execution=execution,
            weights_manifest=weights, worker=self.worker)
        self.log_dir = log_dir
        log_dir.mkdir(parents=True, exist_ok=True)
        write_json(log_dir / 'manifest.json', self.card)
        (log_dir / 'runtime_source.py').write_bytes(Path(__file__).read_bytes())

    def complete(self, body, wire):
        from vllm import SamplingParams
        generation = validate_request(body, self.card['id'])
        self.forward_calls = 0
        started = time.monotonic()
        signal.alarm(REQUEST_TIMEOUT_SECONDS)
        try:
            if 'structured_outputs' in body or 'media_io_kwargs' in body:
                from vllm import RequestOutput
                from vllm.sampling_params import StructuredOutputsParams
                from vllm.renderers.params import ChatParams
                params = SamplingParams(**generation, structured_outputs=(
                    StructuredOutputsParams(**body['structured_outputs']) if body.get('structured_outputs') else None))
                chat = ChatParams(chat_template_kwargs=dict(enable_thinking=False, add_generation_prompt=True,
                    continue_final_message=False, tools=None, tokenize=False), media_io_kwargs=body.get('media_io_kwargs'))
                _, prompts = self.llm.renderer.render_chat([body['messages']], chat,
                    self.llm.renderer.default_chat_tok_params, prompt_extras={'mm_processor_kwargs': None})
                output = self.llm._render_and_run_requests(iter(prompts), [params], RequestOutput, use_tqdm=False)[0]
            else:
                output = self.llm.chat(body['messages'], sampling_params=SamplingParams(**generation),
                    use_tqdm=False, chat_template_kwargs={'enable_thinking': False})[0]
        finally:
            signal.alarm(0)
        if self.forward_calls <= 0:
            raise RuntimeError('No real model forward was observed')
        generated = output.outputs[0]
        audit = dict(request_sha256=hashlib.sha256(wire).hexdigest(),
            input_sha256=input_digest(body),
            prompt_token_ids_sha256=digest(output.prompt_token_ids),
            worker={**self.worker, 'forward_calls': self.forward_calls},
            inference_seconds=time.monotonic()-started)
        # LLM has no OpenAI frontend flag; expose its actual prefix-hit counter directly.
        usage = dict(prompt_tokens=len(output.prompt_token_ids), completion_tokens=len(generated.token_ids),
            total_tokens=len(output.prompt_token_ids)+len(generated.token_ids),
            prompt_tokens_details=dict(cached_tokens=output.num_cached_tokens))
        audit['cache_hit_rate'] = cache_hit_rate(usage)
        response = dict(id=f'chatcmpl-{os.getpid()}-{output.request_id}', object='chat.completion',
            created=int(time.time()), model=self.card['id'], prompt_token_ids=list(output.prompt_token_ids),
            choices=[dict(index=0, message=dict(role='assistant', content=generated.text),
                          finish_reason=generated.finish_reason, token_ids=list(generated.token_ids))],
            usage=usage, audit=audit)
        with (self.log_dir / 'requests.jsonl').open('a') as handle:
            handle.write(json.dumps(dict(id=response['id'], generation=generation, usage=usage, **audit,
                token_ids=list(generated.token_ids), finish_reason=generated.finish_reason))+'\n')
        return response

    def close(self):
        from vllm.distributed.parallel_state import cleanup_dist_env_and_memory
        self.llm.llm_engine.engine_core.shutdown()
        cleanup_dist_env_and_memory()


class SerialServer(HTTPServer):
    request_queue_size = 128

    def __init__(self, address, engine):
        super().__init__(address, Handler)
        self.engine, self.failed = engine, False


class Handler(BaseHTTPRequestHandler):
    # Closing each connection avoids an idle keepalive client blocking the serial worker.
    protocol_version = 'HTTP/1.0'

    def setup(self):
        super().setup()
        self.connection.settimeout(900)

    def log_message(self, format, *args):
        pass

    def respond(self, status, payload):
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        if self.path == '/v1/models':
            self.respond(200, dict(object='list', data=[self.server.engine.card]))
        elif self.path == '/metrics':
            # GET is served between forwards, so both counters are zero here.
            data = b'vllm:num_requests_running 0\nvllm:num_requests_waiting 0\n'
            self.send_response(200)
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass
        elif self.path == '/health':
            self.respond(200, dict(status='ok'))
        else:
            self.respond(404, dict(error=dict(message='Unknown endpoint')))

    def do_POST(self):
        if self.path != '/v1/chat/completions':
            self.respond(404, dict(error=dict(message='Unknown endpoint')))
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 512*1024*1024:
                raise ValueError('Request body must be between 1 byte and 512 MiB')
            wire = self.rfile.read(length)
            if len(wire) != length:
                raise ValueError('Incomplete request body')
            body = json.loads(wire)
            validate_request(body, self.server.engine.card['id'])
        except (ValueError, TimeoutError) as exc:
            self.respond(400, dict(error=dict(message=str(exc))))
            return
        try:
            response = self.server.engine.complete(body, wire)
        except Exception as exc:
            traceback.print_exc()
            self.server.failed = True
            self.respond(503, dict(error=dict(message=str(exc))))
            return
        self.respond(200, response)


def serve(model, port, log_dir, served_model_name=None):
    def timeout(signum, frame):
        raise TimeoutError(f'Model request exceeded {REQUEST_TIMEOUT_SECONDS} seconds')
    signal.signal(signal.SIGALRM, timeout)
    signal.signal(signal.SIGTERM, signal.default_int_handler)
    engine = Engine(model, log_dir, served_model_name)
    try:
        with SerialServer(('127.0.0.1', port), engine) as server:
            server.timeout = 1
            print(f'READY {port} {json.dumps(engine.worker)}', flush=True)
            while not server.failed:
                server.handle_request()
            raise RuntimeError('Inference worker failed; restart this endpoint explicitly')
    finally:
        engine.close()


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--served-model-name')
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--log-dir', type=Path, required=True)
    args = parser.parse_args()
    try:
        serve(args.model, args.port, args.log_dir, args.served_model_name)
    except KeyboardInterrupt:
        pass
