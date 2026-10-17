#!/usr/bin/env python3
"""Serve independent, serial Qwen3.5 BF16 replicas for the unchanged E2E API.

python eval/e2e_eval/serve.py --model /weights/Qwen3.5-9B --gpus 0-7 \
    --port 8100 --log-dir /runs/e2e/servers
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from harness.common import write_json
from models.vlm.local.sync_server import ENVIRONMENT, serve


def parse_gpus(value):
    devices = []
    for part in value.split(','):
        if '-' in part:
            first, last = map(int, part.split('-'))
            if first > last:
                raise ValueError('GPU ranges must be ascending')
            devices.extend(range(first, last+1))
        else:
            devices.append(int(part))
    if not devices or min(devices) < 0 or len(set(devices)) != len(devices):
        raise ValueError('GPU indices must be unique nonnegative integers')
    return devices


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--model', type=Path, required=True)
    p.add_argument('--gpus', default='0-7')
    p.add_argument('--port', type=int, default=8100, help='First endpoint port')
    p.add_argument('--log-dir', type=Path, required=True)
    p.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    args = p.parse_args()
    if args.worker:
        try:
            serve(args.model, args.port, args.log_dir)
        except KeyboardInterrupt:
            pass
        return
    devices = parse_gpus(args.gpus)
    if not 1 <= args.port <= 65536-len(devices):
        p.error('Endpoint ports must be in [1, 65535]')
    args.log_dir.mkdir(parents=True, exist_ok=True)
    if (args.log_dir / 'pool.json').exists():
        p.error('Use a fresh --log-dir for each server lifetime')
    signal.signal(signal.SIGTERM, signal.default_int_handler)
    processes, streams, replicas = [], [], []
    try:
        for rank, gpu in enumerate(devices):
            port = args.port+rank
            directory = args.log_dir / str(port)
            directory.mkdir()
            stream = (directory / 'server.log').open('w')
            streams.append(stream)
            command = [sys.executable, str(Path(__file__).resolve()), '--worker',
                       '--model', str(args.model), '--port', str(port), '--log-dir', str(directory)]
            proc = subprocess.Popen(command, env={**os.environ, **ENVIRONMENT, 'CUDA_VISIBLE_DEVICES': str(gpu)},
                                    stdout=stream, stderr=subprocess.STDOUT)
            processes.append(proc)
            replicas.append(dict(endpoint=f'http://127.0.0.1:{port}/v1', gpu=gpu, pid=proc.pid))
        write_json(args.log_dir / 'pool.json', replicas)
        while all(proc.poll() is None for proc in processes):
            time.sleep(1)
        raise RuntimeError('A worker exited; inspect the endpoint server.log')
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
        for stream in streams:
            stream.close()


if __name__ == '__main__':
    main()
