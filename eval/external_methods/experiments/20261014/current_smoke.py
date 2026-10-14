"""Current-input RSI/VAM smoke: three benchmarks, separate immutable run directory."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request


SUPPORT = Path('/runs/devbox/external_methods_20261014/support')


def run(command, log, env):
    with log.open('w') as stream:
        subprocess.run(command, env=env, stdout=stream, stderr=subprocess.STDOUT, check=True)


def prepare(output):
    output.mkdir(parents=True, exist_ok=False)
    source = Path(__file__).resolve().parents[4]
    env = dict(os.environ, PYTHONPATH=f'{SUPPORT}/deps:{source}/src')
    scripts = source/'eval/external_methods'
    for name in ('test_native_concat.py', 'test_contracts.py'):
        run([sys.executable, str(scripts/name)], output/(name+'.log'), env)
    run([sys.executable, '-m', 'compileall', '-q', 'src', 'scripts', 'eval/agent_eval', 'demo.py'],
        output/'compileall.log', env)
    run([sys.executable, str(scripts/'freeze.py'), '--output', str(output)], output/'freeze.log', env)
    old = Path('/runs/devbox/external_methods_native_20261014/prepared_r2/items.json')
    selected = {}
    for item in sorted(json.loads(old.read_text()), key=lambda row: row['duration']):
        sid = item['sample_id']
        dataset = 'cvbench' if sid.startswith('cvbench:') else 'mvu_eval' if sid.startswith('mvu_eval:') else 'crossvid'
        selected.setdefault(dataset, sid)
    assert len(selected) == 3, selected
    selection = output/'selection.json'
    selection.write_text(json.dumps(dict(sample_ids=list(selected.values()), source=str(old))))
    frozen = output/'frozen_repo'
    env['PYTHONPATH'] = f'{SUPPORT}/deps:{frozen}/src'
    run([sys.executable, str(frozen/'eval/external_methods/prepare.py'),
         '--selection', str(selection), '--output', str(output/'prepared')], output/'prepare.log', env)
    print(json.dumps(dict(prepared=selected, output=str(output))), flush=True)


def infer(output):
    frozen = output/'frozen_repo'
    env = dict(os.environ, PYTHONPATH=f'{SUPPORT}/deps:{frozen}/src')
    scripts = frozen/'eval/external_methods'
    processes, streams = [], []
    started = time.monotonic()
    try:
        commands = [
            ([sys.executable, str(frozen/'eval/e2e_eval/serve.py'), '--model', '/weights/Qwen3.5-35B-A3B',
              '--gpus', '0-5', '--port', '8100', '--log-dir', str(output/'servers')], env, 'actors.log'),
            ([sys.executable, str(scripts/'embedding_server.py'), '--source', str(frozen/'external_sources/Qwen3-VL-Embedding'),
              '--weights', str(SUPPORT/'Qwen3-VL-Embedding-8B'), '--output', str(output/'embedding')],
             dict(env, CUDA_VISIBLE_DEVICES='6'), 'embedding.log'),
        ]
        for command, child_env, name in commands:
            stream = (output/name).open('w')
            streams.append(stream)
            processes.append(subprocess.Popen(command, env=child_env, stdout=stream, stderr=subprocess.STDOUT))
        pending = {f'http://127.0.0.1:{port}/v1/models' for port in range(8100, 8106)}
        pending.add('http://127.0.0.1:8200/')
        deadline = time.monotonic()+1200
        while pending:
            if any(p.poll() is not None for p in processes) or time.monotonic() > deadline:
                raise RuntimeError(f'Model startup failed; pending={sorted(pending)}')
            for url in list(pending):
                try:
                    with urllib.request.urlopen(url, timeout=2) as response:
                        if response.status == 200:
                            pending.remove(url)
                except Exception:
                    pass
            time.sleep(5)
        print('Models ready; running both methods on three benchmarks.', flush=True)
        def batch(method, ports):
            run([sys.executable, str(scripts/'run_batch.py'), method, '--prepared', str(output/'prepared'),
                 '--output', str(output/method), '--ports', ports], output/(method+'.log'), env)
            return json.loads((output/method/'progress.json').read_text())
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = {method: pool.submit(batch, method, ports) for method, ports in
                       [('rsi', '8100,8101,8102'), ('vam', '8103,8104,8105')]}
            summary = {method: future.result() for method, future in futures.items()}
        (output/'summary.json').write_text(json.dumps(dict(methods=summary, seconds=time.monotonic()-started), indent=2))
        print(json.dumps(summary), flush=True)
    finally:
        for proc in reversed(processes):
            if proc.poll() is None:
                proc.terminate()
        for proc in processes:
            try:
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        for stream in streams:
            stream.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['prepare', 'infer'])
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    (prepare if args.phase == 'prepare' else infer)(args.output)
