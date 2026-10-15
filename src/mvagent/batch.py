"""Public, question-isolated batch inference shared by evaluation and training."""
from collections import deque
from copy import deepcopy
from dataclasses import dataclass, field, asdict
import hashlib
import json
import math
import os
import multiprocessing as mp
from multiprocessing.connection import wait
from pathlib import Path
import shutil
import signal
import tempfile
import threading
import time
import subprocess
import urllib.request

import yaml

from models.execution import execution_scope, emit_event
from models.pool import Replica, PoolUnavailable, install_pools, prepare_pool, resolve_devices


@dataclass
class ExecutionConfig:
    model_pools: dict = field(default_factory=dict)
    question_workers: int | str = 'auto'
    max_prepared_requests: int | str = 'auto'
    question_timeout_sec: float = 1800
    question_retries: int = 1
    media_cache: dict | None = None

    def __post_init__(self):
        for name in ('question_workers', 'max_prepared_requests'):
            value = getattr(self, name)
            if value != 'auto' and (type(value) is not int or value < 1):
                raise ValueError(f'{name} must be auto or a positive integer')
        if not math.isfinite(self.question_timeout_sec) or self.question_timeout_sec <= 0:
            raise ValueError('question_timeout_sec must be finite and positive')
        if type(self.question_retries) is not int or self.question_retries < 0:
            raise ValueError('question_retries must be a nonnegative integer')
        self.model_pools = {name: {'replicas': [Replica(**r).to_dict() for r in spec['replicas']]}
                            for name, spec in self.model_pools.items()}
        if any(not spec['replicas'] for spec in self.model_pools.values()):
            raise ValueError('A configured model pool needs at least one replica')

    @classmethod
    def from_yaml(cls, path):
        return cls(**yaml.safe_load(Path(path).read_text()))

    def to_dict(self):
        return asdict(self)


def prepare_model_pools(config_data, execution):
    from .configs import MVAgentConfig
    config = MVAgentConfig.from_dict(config_data)
    references = {ref.model_type: ref for _, _, ref in config.model_roles()}
    for name in execution.model_pools:
        if name not in config.models or config.models[name].type != 'local_vllm':
            raise ValueError(f'Unknown/non-local model pool: {name}')
    required = {name for name in references if config.models[name].type == 'local_vllm'}
    if required - execution.model_pools.keys():
        raise ValueError(f'Missing model pools: {sorted(required - execution.model_pools.keys())}')
    replicas = resolve_devices({name: [Replica(**r) for r in spec['replicas']]
                                for name, spec in execution.model_pools.items()}) if execution.model_pools else {}
    pools, failures = {}, []
    for name, services in replicas.items():
        # Additional named local models may be explicitly used as judges.
        from .configs.agent_config import Agent_Model_Config
        ref = references.get(name) or Agent_Model_Config(model_type=name)
        pool, unavailable = prepare_pool(name, config.models[name].to_runtime_config(name, ref),
                                         services, config.runtime.cache_dir)
        pools[name] = pool
        failures.extend(unavailable)
    install_pools(pools)
    return pools, failures


def question_worker(connection, pools, media_slots, media_cache):
    os.setsid()  # Question-owned CPU subprocesses share this group; vLLM services do not.
    from .configs import MVAgentConfig
    from .engine import MVAgentEngine
    install_pools(pools)
    engine, config_key = None, None
    send_lock = threading.Lock()
    def send(value):
        with send_lock:
            connection.send(value)
    try:
        while True:
            job = connection.recv()
            if job is None:
                break
            try:
                with execution_scope(emit=lambda e: send(('event', e)), deadline=job['deadline'],
                                     media_cache=media_cache, media_slots=media_slots):
                    emit_event('worker_runtime', source_root=str(Path(__file__).resolve().parents[1]))
                    if config_key != job['config_key']:
                        if engine:
                            engine.close()
                        config = MVAgentConfig.from_dict(job['config_data'])
                        config.runtime.cache_dir = job['temporary']
                        engine = MVAgentEngine(config, logger=lambda _: None)
                        engine.resolve_models()
                        config_key = job['config_key']
                    engine.cache_dir = Path(job['temporary'])
                    result = engine.answer(videos=job['videos'], question=job['question'],
                                           output_dir=job['temporary'])
                send(('done', dict(status='ok', result=result)))
            except Exception as exc:
                send(('done', dict(status='error', result={}, error=str(exc))))
    except EOFError:
        pass
    finally:
        if engine:
            engine.close()
        connection.close()


class BatchExecutor:
    """Own CPU workers, never benchmark data, reference answers or scoring policy."""
    def __init__(self, execution, *, on_event=None, worker_target=question_worker,
                 pool_factory=prepare_model_pools):
        self.execution = execution
        self.on_event = on_event or (lambda event: None)
        self.worker_target, self.pool_factory = worker_target, pool_factory
        self.pools = None
        self.workers = []
        self.context = mp.get_context('spawn')
        self.lock = threading.Lock()
        self.control_dir = None
        self.required = set()

    def emit(self, kind, **fields):
        self.on_event(dict(time=time.time(), kind=kind, **fields))

    def prepare(self, config_data):
        model_config = config_data.get('models', {})
        if self.pools is not None:
            if model_config != self.model_config:
                raise ValueError('A BatchExecutor has fixed models; create a new executor to change them')
            return
        self.model_config = deepcopy(model_config)
        self.pools, failures = self.pool_factory(config_data, self.execution)
        from .configs import MVAgentConfig
        if self.pools:
            config = MVAgentConfig.from_dict(config_data)
            self.required = {ref.model_type for _, _, ref in config.model_roles()} & self.pools.keys()
        capacity = sum(r.max_inflight for name, p in self.pools.items()
                       if name in self.required for r in p.replicas) or 1
        self.worker_count = capacity if self.execution.question_workers == 'auto' else self.execution.question_workers
        prepared = 2 * capacity if self.execution.max_prepared_requests == 'auto' else self.execution.max_prepared_requests
        self.control_dir = tempfile.mkdtemp(prefix='mvagent-batch-')
        self.media_slots = dict(root=self.control_dir, limit=prepared)
        self.emit('batch_prepared', question_workers=self.worker_count, max_prepared_requests=prepared,
                  model_pools={n: [r.to_dict() for r in p.replicas] for n, p in self.pools.items()},
                  unavailable=failures)

    def _start(self):
        parent, child = self.context.Pipe()
        process = self.context.Process(target=self.worker_target,
                    args=(child, self.pools, self.media_slots, self.execution.media_cache), daemon=True)
        process.start()
        child.close()
        return dict(process=process, connection=parent, job=None)

    def _stop(self, worker):
        process = worker['process']
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        if process.is_alive():
            process.terminate()
        process.join(timeout=2)
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        if process.is_alive():
            process.kill()
            process.join()
        worker['connection'].close()
        if worker['job']:
            shutil.rmtree(worker['job']['temporary'], ignore_errors=True)

    def close(self):
        for worker in self.workers:
            self._stop(worker)
        self.workers.clear()
        if self.control_dir:
            shutil.rmtree(self.control_dir, ignore_errors=True)
        self.control_dir, self.pools = None, None
        self.required = set()
        install_pools({})

    def sample_resources(self):
        import psutil
        replicas = [r for pool in self.pools.values() for r in pool.replicas]
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for replica in replicas:
            try:
                with opener.open(replica.endpoint.removesuffix('/v1') + '/metrics', timeout=0.3) as response:
                    values = [line for line in response.read().decode().splitlines() if line.startswith(
                        ('vllm:num_requests_running', 'vllm:num_requests_waiting',
                         'vllm:request_queue_time_seconds_sum', 'vllm:request_prefill_time_seconds_sum',
                         'vllm:request_decode_time_seconds_sum'))]
                self.emit('service_metrics', endpoint=replica.endpoint, values=values)
            except (OSError, TimeoutError):
                self.emit('service_metrics_unavailable', endpoint=replica.endpoint)
        gpus = sorted({gpu for r in replicas for gpu in r.gpus})
        if gpus:
            try:
                result = subprocess.run(['nvidia-smi', '-i', ','.join(map(str, gpus)),
                    '--query-gpu=index,uuid,utilization.gpu,memory.used', '--format=csv,noheader,nounits'],
                    capture_output=True, text=True, timeout=2)
                self.emit('gpu_metrics', rows=result.stdout.splitlines())
            except (OSError, subprocess.TimeoutExpired):
                pass
        memory = psutil.Process().memory_info().rss
        for worker in self.workers:
            try:
                process = psutil.Process(worker['process'].pid)
                memory += process.memory_info().rss
                memory += sum(child.memory_info().rss for child in process.children(recursive=True))
            except psutil.NoSuchProcess:
                pass
        self.emit('batch_memory', rss_bytes=memory, available_bytes=psutil.virtual_memory().available)

    def run(self, jobs, config_data, *, on_complete):
        with self.lock:
            try:
                return self._run(jobs, config_data, on_complete)
            except BaseException:
                self.close()
                raise

    def _run(self, jobs, config_data, on_complete):
        jobs = list(jobs)
        ids = [job['sample_id'] for job in jobs]
        if len(ids) != len(set(ids)):
            raise ValueError('Duplicate sample IDs in a batch')
        if not jobs:
            return ()
        self.prepare(config_data)
        config_data = deepcopy(config_data)
        config_key = hashlib.sha256(json.dumps(config_data, sort_keys=True).encode()).hexdigest()
        pending = deque((job, 0) for job in jobs)
        while len(self.workers) < min(len(jobs), self.worker_count):
            self.workers.append(self._start())
        results, failures = {}, []
        next_metrics = time.monotonic() + 5
        while pending or any(w['job'] for w in self.workers):
            if time.monotonic() >= next_metrics:
                self.sample_resources()
                next_metrics = time.monotonic() + 5
            if any(not self.pools[name].has_capacity_service() for name in self.required):
                raise PoolUnavailable('Required model pool unavailable; completed results have been saved')
            for worker in self.workers:
                if worker['job'] is not None or not pending:
                    continue
                if not worker['process'].is_alive():
                    self._stop(worker)
                    worker.update(self._start())
                task, attempt = pending.popleft()
                job = dict(task, attempt=attempt, config_data=config_data, config_key=config_key,
                           temporary=tempfile.mkdtemp(prefix='mvagent-question-'), events=[],
                           deadline=time.monotonic() + self.execution.question_timeout_sec)
                worker['job'] = job
                worker['connection'].send({k: v for k, v in job.items() if k != 'events'})
                self.emit('question_start', sample_id=job['sample_id'], attempt=attempt,
                          worker_pid=worker['process'].pid)
            active = [w for w in self.workers if w['job']]
            ready = wait([w['connection'] for w in active], timeout=min(0.5, max(0,
                         min(w['job']['deadline'] for w in active) - time.monotonic())))
            for worker in active:
                job = worker['job']
                timed_out = time.monotonic() >= job['deadline']
                message = None
                if worker['connection'] in ready:
                    try:
                        message = worker['connection'].recv()
                    except (EOFError, OSError):
                        message = ('done', dict(status='error', result={}, error='Worker exited'))
                if timed_out:
                    message = ('done', dict(status='error', result={}, error='Question deadline exceeded'))
                elif message and message[0] == 'event':
                    event = dict(message[1], sample_id=job['sample_id'], attempt=job['attempt'])
                    job['events'].append(event)
                    self.on_event(event)
                    continue
                if message is None:
                    continue
                result = dict(message[1], sample_id=job['sample_id'], attempt=job['attempt'],
                              worker_pid=worker['process'].pid, events=job['events'])
                if result['status'] == 'ok':
                    on_complete(result)
                    results[job['sample_id']] = result
                    self.emit('question_done', sample_id=job['sample_id'], attempt=job['attempt'], status='ok')
                else:
                    self.emit('question_error', sample_id=job['sample_id'], attempt=job['attempt'], error=result['error'])
                    if job['attempt'] < self.execution.question_retries:
                        pending.append(({k: job[k] for k in ('sample_id', 'question', 'videos')}, job['attempt'] + 1))
                    else:
                        on_complete(result)
                        failures.append(job['sample_id'])
                # Kill before deleting files that the hung process might still be using.
                if timed_out or not worker['process'].is_alive():
                    self._stop(worker)
                    worker.update(self._start())
                shutil.rmtree(job['temporary'], ignore_errors=True)
                worker['job'] = None
        if failures:
            raise RuntimeError('Incomplete batch; completed questions are saved; failed: ' + ', '.join(failures))
        return tuple(results[sid] for sid in ids)
