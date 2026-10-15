"""Local Qwen transport that preserves external methods' explicit sampling parameters."""
import argparse
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from models.vlm.local import sync_server as base

PROFILE = 'qwen35-bf16-external-upstream'


def configure():
    if base.PROFILE == PROFILE:
        return base
    original_validate = base.validate_request
    original_profile = base.execution_profile

    def validate(body, model):
        if not isinstance(body, dict):
            raise ValueError('Expected a request object')
        temperature = body.get('temperature', 0)
        if type(temperature) not in (int, float) or not math.isfinite(temperature) or not 0 <= temperature <= 2:
            raise ValueError('temperature must be finite and in [0, 2]')
        normalized = dict(body)
        if 'thinking' in normalized and normalized.pop('thinking') != {'type': 'disabled'}:
            raise ValueError('Only disabled thinking is supported by this local Qwen transport')
        normalized['temperature'] = 0
        generation = original_validate(normalized, model)
        generation['temperature'] = temperature
        return generation

    def profile():
        return dict(original_profile(), external_transport_sha256=base.sha256_file(Path(__file__)))

    base.PROFILE = PROFILE
    base.validate_request = validate
    base.execution_profile = profile
    return base


def validate_card(card):
    configure().validate_card(card)
    if card['execution'].get('external_transport_sha256') != base.sha256_file(Path(__file__)):
        raise RuntimeError('External-method transport source does not match the running server')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--port', type=int, default=8100)
    parser.add_argument('--log-dir', type=Path, required=True)
    parser.add_argument('--gpus', default='0')
    parser.add_argument('--worker', action='store_true')
    args = parser.parse_args()
    if args.worker:
        configure().serve(args.model, args.port, args.log_dir)
        return
    devices = [int(gpu) for gpu in args.gpus.split(',')]
    if not devices or min(devices) < 0 or len(set(devices)) != len(devices):
        parser.error('--gpus must contain distinct nonnegative device indices')
    args.log_dir.mkdir(parents=True, exist_ok=False)
    processes, replicas = [], []
    signal.signal(signal.SIGTERM, signal.default_int_handler)
    try:
        for rank, gpu in enumerate(devices):
            directory = args.log_dir/str(args.port+rank)
            directory.mkdir()
            with (directory/'server.log').open('w') as log:
                proc = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--worker',
                    '--model', str(args.model), '--port', str(args.port+rank), '--log-dir', str(directory)],
                    env={**os.environ, **base.ENVIRONMENT, 'CUDA_VISIBLE_DEVICES': str(gpu)},
                    stdout=log, stderr=subprocess.STDOUT)
            processes.append(proc)
            replicas.append(dict(gpu=gpu, pid=proc.pid, endpoint=f'http://127.0.0.1:{args.port+rank}/v1'))
        base.write_json(args.log_dir/'pool.json', replicas)
        while all(proc.poll() is None for proc in processes):
            time.sleep(1)
        raise RuntimeError('An external-method model worker exited')
    except KeyboardInterrupt:
        pass
    finally:
        for proc in processes:
            if proc.poll() is None:
                proc.terminate()
        for proc in processes:
            try:
                proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()


if __name__ == '__main__':
    main()
