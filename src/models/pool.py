"""Same-host model replicas and process-safe admission; no Agent state lives here."""
from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import hashlib
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import time
from urllib.parse import urlparse
import urllib.request

from .execution import current_scope, emit_event, remaining_timeout
from .utils import is_loopback_host


class PoolUnavailable(RuntimeError):
    pass


def canonical_endpoint(value):
    parsed = urlparse(value.rstrip('/'))
    if (parsed.scheme != 'http' or not is_loopback_host(parsed.hostname) or not parsed.port
            or parsed.path != '/v1' or parsed.query or parsed.fragment or parsed.username):
        raise ValueError(f'Model pool endpoint must be explicit loopback HTTP /v1: {value}')
    return f'http://127.0.0.1:{parsed.port}/v1'


@dataclass(frozen=True)
class Replica:
    endpoint: str
    gpus: tuple
    max_inflight: int = 2

    def __post_init__(self):
        object.__setattr__(self, 'endpoint', canonical_endpoint(self.endpoint))
        object.__setattr__(self, 'gpus', tuple(self.gpus))
        if not self.gpus or any(not (type(g) is int and g >= 0 or
                isinstance(g, str) and g.startswith('GPU-')) for g in self.gpus):
            raise ValueError('gpus must contain physical indexes or full GPU UUIDs')
        if len(set(self.gpus)) != len(self.gpus):
            raise ValueError('Duplicate GPU in a replica')
        if type(self.max_inflight) is not int or self.max_inflight < 1:
            raise ValueError('max_inflight must be a positive integer')

    def to_dict(self):
        return dict(endpoint=self.endpoint, gpus=list(self.gpus), max_inflight=self.max_inflight)


def gpu_inventory():
    output = subprocess.run(['nvidia-smi', '--query-gpu=index,uuid', '--format=csv,noheader,nounits'],
                            check=True, capture_output=True, text=True, timeout=10).stdout
    return {int(index.strip()): uuid.strip() for index, uuid in
            (line.split(',') for line in output.splitlines())}


def resolve_devices(pools):
    inventory = gpu_inventory()
    allowed = set(inventory.values())
    if 'CUDA_VISIBLE_DEVICES' in os.environ:
        # Probe in a disposable process: the parent and question workers stay CPU-only.
        code = ('import json,torch; print(json.dumps([str(torch.cuda.get_device_properties(i).uuid) '
                'for i in range(torch.cuda.device_count())]))')
        visible = json.loads(subprocess.run([sys.executable, '-c', code], check=True,
                            capture_output=True, text=True, timeout=30).stdout)
        allowed = {u for u in allowed if u in visible or u.removeprefix('GPU-') in visible}
    selected, endpoints, resolved = set(), set(), {}
    for name, replicas in pools.items():
        resolved[name] = []
        for replica in replicas:
            ids = tuple(inventory[g] if type(g) is int and g in inventory else g for g in replica.gpus)
            if any(g not in allowed for g in ids):
                raise ValueError(f'Unknown or disallowed GPU: {replica.gpus}')
            if selected.intersection(ids) or replica.endpoint in endpoints or len(set(ids)) != len(ids):
                raise ValueError('Model pools cannot repeat GPUs or endpoints')
            selected.update(ids)
            endpoints.add(replica.endpoint)
            resolved[name].append(Replica(replica.endpoint, ids, replica.max_inflight))
    return resolved


def _try_lock(path):
    handle = path.open('a+')
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return handle
    except BlockingIOError:
        handle.close()
        return None


@contextmanager
def _state(directory):
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / 'control.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = directory / 'state.json'
        state = json.loads(path.read_text()) if path.exists() else {}
        yield state
        temporary = directory / 'state.tmp'
        temporary.write_text(json.dumps(state))
        temporary.replace(path)


def _sweep(directory, state):
    """An unlocked sent slot is an orphan, not evidence of server cancellation."""
    for index, record in list(state.get('slots', {}).items()):
        handle = _try_lock(directory / f'{index}.lock')
        if handle is not None:
            handle.close()
            if record['sent']:
                state.update(quarantined=True, retry_at=time.time() + 30)
            del state['slots'][index]


class RequestLease:
    def __init__(self, directory, index, endpoint, handle):
        self.directory, self.index, self.endpoint, self.handle = directory, str(index), endpoint, handle

    def sent(self):
        with _state(self.directory) as state:
            state['slots'][self.index]['sent'] = True

    def complete(self, *, unhealthy=False):
        with _state(self.directory) as state:
            state['slots'][self.index]['sent'] = False
            if unhealthy:
                state.update(quarantined=True, retry_at=time.time() + 30)

    def close(self):
        with _state(self.directory) as state:
            record = state['slots'].pop(self.index)
            if record['sent']:
                state.update(quarantined=True, retry_at=time.time() + 30)
            self.handle.close()


class ModelPool:
    def __init__(self, name, replicas, identity, *, root='/tmp/mvagent-model-pools', runtime_config=None):
        self.name, self.replicas, self.identity = name, tuple(replicas), identity
        self.root = Path(root)
        self.runtime_config = runtime_config

    def directory(self, replica):
        return self.root / hashlib.sha256(replica.endpoint.encode()).hexdigest()

    def register(self):
        for replica in self.replicas:
            directory = self.directory(replica)
            with _state(directory) as state:
                _sweep(directory, state)
                contract = dict(identity=self.identity, max_inflight=replica.max_inflight)
                if state and any(state[k] != v for k, v in contract.items()):
                    if state['slots'] or state['quarantined']:
                        raise ValueError(f'Active endpoint has a different model/capacity: {replica.endpoint}')
                    state.clear()
                if not state:
                    state.update(**contract, slots={}, quarantined=False, retry_at=0)

    def recover(self, replica):
        directory = self.directory(replica)
        with _state(directory) as state:
            _sweep(directory, state)
            if not state['quarantined'] or state['slots'] or time.time() < state['retry_at']:
                return
            state['retry_at'] = time.time() + 30  # One bounded probe, outside the control lock.
        try:
            if self.runtime_config is None:
                return  # Unverified, manually constructed pools cannot auto-rejoin a service.
            from dataclasses import replace
            from .vlm.local.service import VLLMServiceManager
            manager = VLLMServiceManager(replace(self.runtime_config, endpoint=replica.endpoint,
                                                 gpus=list(replica.gpus)), cache_dir=self.root)
            verify_local_service(manager, gpu_inventory())
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(replica.endpoint.removesuffix('/v1') + '/metrics', timeout=2) as response:
                lines = response.read().decode().splitlines()
            counters = [float(line.split()[-1]) for line in lines if line.startswith(
                ('vllm:num_requests_running', 'vllm:num_requests_waiting'))]
            if len(counters) < 2 or any(counters):
                return
            from .vlm.local.service import probe_vllm_inference, probe_vllm_server
            if self.name not in (probe_vllm_server(replica.endpoint, timeout_sec=2) or set()):
                return
            probe_vllm_inference(replica.endpoint, served_model_name=self.name, timeout_sec=5)
        except (OSError, RuntimeError, ValueError):
            return
        with _state(directory) as state:
            _sweep(directory, state)
            if not state['slots']:
                state['quarantined'] = False
        emit_event('service_recovered', endpoint=replica.endpoint)

    @contextmanager
    def acquire(self, timeout):
        started = time.monotonic()
        deadline = started + remaining_timeout(timeout)
        lease = None
        replicas = list(self.replicas)
        random.SystemRandom().shuffle(replicas)
        while lease is None:
            healthy = 0
            for replica in replicas:
                self.recover(replica)
                directory = self.directory(replica)
                with _state(directory) as state:
                    _sweep(directory, state)
                    if state['identity'] != self.identity or state['max_inflight'] != replica.max_inflight:
                        raise ValueError('Endpoint model/capacity changed during execution')
                    if state['quarantined']:
                        continue
                    healthy += 1
                    for index in range(replica.max_inflight):
                        handle = _try_lock(directory / f'{index}.lock')
                        if handle is not None:
                            state['slots'][str(index)] = dict(pid=os.getpid(), sent=False)
                            lease = RequestLease(directory, index, replica.endpoint, handle)
                            break
                if lease is not None:
                    break
            if not healthy:
                raise PoolUnavailable(f'No healthy service for {self.name}')
            if lease is None:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f'Request admission timed out for {self.name}')
                time.sleep(min(0.05, max(0, deadline - time.monotonic())))
        try:
            emit_event('request_admitted', endpoint=lease.endpoint, model=self.name,
                       gpus=list(replica.gpus), queue_seconds=time.monotonic() - started)
            yield lease
        finally:
            lease.close()

    def has_capacity_service(self):
        healthy = False
        for replica in self.replicas:
            self.recover(replica)
            with _state(self.directory(replica)) as state:
                _sweep(self.directory(replica), state)
                healthy |= not state['quarantined']
        return healthy


_pools = {}


def install_pools(pools):
    global _pools
    _pools = dict(pools)


def get_pool(name, endpoint=None):
    if name in _pools:
        return _pools[name]
    if endpoint and is_loopback_host(urlparse(endpoint).hostname):
        endpoint = canonical_endpoint(endpoint)
        for pool in _pools.values():
            if any(r.endpoint == endpoint for r in pool.replicas):
                if pool.name != name:
                    raise ValueError(f'Endpoint serves {pool.name}, not {name}')
                return pool
    return None


def verify_local_service(manager, inventory):
    """Check the actual listener, not just a potentially reused served-model alias."""
    import psutil
    port = urlparse(manager.cfg.endpoint).port
    pids = {c.pid for c in psutil.net_connections(kind='tcp')
            if c.status == 'LISTEN' and c.laddr.port == port and c.pid}
    if not pids:
        raise ValueError(f'Cannot verify local service process: {manager.cfg.endpoint}')
    expected = manager.build_start_command()
    for pid in pids:
        process = psutil.Process(pid)
        actual = process.cmdline()
        if 'serve' not in actual or actual[actual.index('serve') + 1] != manager.cfg.model_name:
            raise ValueError(f'Wrong model process at {manager.cfg.endpoint}')
        for flag in ('--served-model-name', '--dtype', '--tensor-parallel-size',
                     '--max-model-len', '--limit-mm-per-prompt.video', '--generation-config',
                     '--mm-processor-cache-gb', '--gpu-memory-utilization', '--reasoning-parser',
                     '--default-chat-template-kwargs'):
            wanted = expected[expected.index(flag) + 1] if flag in expected else None
            found = actual[actual.index(flag) + 1] if flag in actual else None
            if flag == '--default-chat-template-kwargs':
                wanted, found = json.loads(wanted or '{}'), json.loads(found or '{}')
            if wanted != found:
                raise ValueError(f'Service configuration mismatch at {manager.cfg.endpoint}: {flag}')
        visible = process.environ().get('CUDA_VISIBLE_DEVICES', '').split(',')
        actual_gpus = [inventory.get(int(g)) if g.isdigit() else g for g in visible]
        if actual_gpus != list(manager.cfg.gpus):
            raise ValueError(f'Service GPU binding mismatch at {manager.cfg.endpoint}')


def prepare_pool(name, model_config, replicas, cache_dir):
    from dataclasses import replace
    from .vlm.local.service import VLLMServiceManager, VLLMServiceError, probe_vllm_server
    healthy, failures = [], []
    inventory = gpu_inventory()
    identity = None
    for replica in replicas:
        cfg = replace(model_config, endpoint=replica.endpoint, gpus=list(replica.gpus))
        manager = VLLMServiceManager(cfg, cache_dir=cache_dir)
        launch = manager.build_start_command()
        for flag in ('--host', '--port', '--tensor-parallel-size'):
            index = launch.index(flag)
            del launch[index:index + 2]
        identity = hashlib.sha256(json.dumps(launch).encode()).hexdigest()
        try:
            existing = probe_vllm_server(replica.endpoint)
        except VLLMServiceError as exc:
            raise ValueError(f'Cannot verify endpoint identity: {replica.endpoint}') from exc
        if existing is not None:
            verify_local_service(manager, inventory)
        single = ModelPool(name, [replica], identity, runtime_config=model_config)
        single.register()
        try:
            # Readiness inference also shares admission with concurrent batch runs.
            with single.acquire(cfg.startup_timeout_sec) as lease:
                lease.sent()
                manager.ensure_running()
                lease.complete()
            verify_local_service(manager, inventory)
        except (VLLMServiceError, PoolUnavailable) as exc:
            failures.append(dict(endpoint=replica.endpoint, error=str(exc)))
            continue
        healthy.append(replica)
    if not healthy:
        raise PoolUnavailable(f'No usable service for {name}: {failures}')
    return ModelPool(name, healthy, identity, runtime_config=model_config), failures


@contextmanager
def media_preparation_slot():
    scope = current_scope()
    settings = scope and scope.get('media_slots')
    if not settings:
        yield
        return
    root, limit = Path(settings['root']), settings['limit']
    root.mkdir(parents=True, exist_ok=True)
    started, handle = time.monotonic(), None
    while handle is None:
        remaining_timeout(1)
        for index in range(limit):
            handle = _try_lock(root / f'{index}.lock')
            if handle is not None:
                break
        if handle is None:
            time.sleep(remaining_timeout(0.05))
    try:
        emit_event('media_preparation_admitted', queue_seconds=time.monotonic() - started)
        yield
    finally:
        handle.close()
