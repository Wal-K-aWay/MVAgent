"""Upstream settings: expanded RSI panel and three-benchmark VAM smoke, with timing."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
import signal
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from common import write


SUPPORT = Path('/runs/devbox/external_methods_20261014/support')


def run(command, log, env):
    with log.open('w') as stream:
        subprocess.run(command, env=env, stdout=stream, stderr=subprocess.STDOUT, check=True)


def stop(process):
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()


def prepare(output):
    output.mkdir(parents=True, exist_ok=False)
    source = Path(__file__).resolve().parents[4]
    env = dict(os.environ, PYTHONPATH=f'{SUPPORT}/deps:{source}/src')
    scripts = source/'eval/external_methods'
    for name in ('test_contracts.py', 'test_transport_audit.py'):
        run([sys.executable, str(scripts/name)], output/(name+'.log'), env)
    run([sys.executable, '-m', 'compileall', '-q', 'src', 'scripts', 'eval/agent_eval', 'eval/external_methods', 'demo.py'],
        output/'compileall.log', env)
    run([sys.executable, str(scripts/'freeze.py'), '--output', str(output)], output/'freeze.log', env)
    old = Path('/runs/devbox/rsi_budget_20261015_r2/prepared/items.json')
    all_items = json.loads(old.read_text())
    selected = {}
    for item in sorted(all_items, key=lambda row: row['duration']):
        sid = item['sample_id']
        dataset = 'cvbench' if sid.startswith('cvbench:') else 'mvu_eval' if sid.startswith('mvu_eval:') else 'crossvid'
        selected.setdefault(dataset, sid)
    assert len(selected) == 3, selected
    selection = output/'selection.json'
    ids = list(selected.values()) + [item['sample_id'] for item in all_items if item['sample_id'] not in selected.values()]
    assert len(ids) == len(set(ids)) == 65
    selection.write_text(json.dumps(dict(sample_ids=ids, source=str(old), seed=0,
        excluded={'crossvid:NC:808':'previously documented mixed-codec preparation time limit'},
        order='three shortest benchmark anchors first; no resampling')))
    frozen = output/'frozen_repo'
    env['PYTHONPATH'] = f'{SUPPORT}/deps:{frozen}/src'
    run([sys.executable, str(frozen/'eval/external_methods/prepare.py'),
         '--selection', str(selection), '--output', str(output/'prepared')], output/'prepare.log', env)
    print(json.dumps(dict(smoke=selected, expanded=65, output=str(output))), flush=True)


def infer(output):
    frozen = output/'frozen_repo'
    env = dict(os.environ, PYTHONPATH=f'{SUPPORT}/deps:{frozen}/src')
    scripts = frozen/'eval/external_methods'
    processes, streams = [], []
    started = time.monotonic()
    state = dict(phase='starting_models', started_at=datetime.now(timezone.utc).isoformat(),
                 expected=dict(rsi=65, vam=3), protocol='upstream parameters with approved adapters')
    write(output/'progress.json', state)
    try:
        commands = [
            ([sys.executable, str(scripts/'native_server.py'), '--model', '/weights/Qwen3.5-35B-A3B',
              '--gpus', '0,1,2,3,4,5,6', '--port', '8100', '--log-dir', str(output/'servers')], env, 'actors.log'),
            ([sys.executable, str(scripts/'embedding_server.py'), '--source', str(frozen/'external_sources/Qwen3-VL-Embedding'),
              '--weights', str(SUPPORT/'Qwen3-VL-Embedding-8B'), '--output', str(output/'embedding')],
             dict(env, CUDA_VISIBLE_DEVICES='7'), 'embedding.log'),
        ]
        for command, child_env, name in commands:
            stream = (output/name).open('w')
            streams.append(stream)
            processes.append(subprocess.Popen(command, env=child_env, stdout=stream, stderr=subprocess.STDOUT,
                                               start_new_session=True))
        pending = {f'http://127.0.0.1:{port}/v1/models' for port in range(8100, 8107)}
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
        state.update(phase='running', model_startup_seconds=time.monotonic()-started)
        write(output/'progress.json', state)
        inference_started = time.monotonic()
        print('Models ready; RSI 65 questions and VAM three benchmark anchors.', flush=True)
        def batch(method, ports):
            command = [sys.executable, str(scripts/'run_batch.py'), method, '--prepared', str(output/'prepared'),
                       '--output', str(output/method), '--ports', ports]
            if method == 'vam':
                command.append('--smoke')
            run(command, output/(method+'.log'), env)
            return json.loads((output/method/'progress.json').read_text())
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = {method: pool.submit(batch, method, ports) for method, ports in
                       [('rsi', '8100,8101,8102,8103,8104,8105'), ('vam', '8106')]}
            summary = {method: future.result() for method, future in futures.items()}
        state.update(phase='inference_completed', inference_seconds=time.monotonic()-inference_started,
                     methods={method:{key:value[key] for key in ('expected','successful','failed','batch_seconds')}
                              for method,value in summary.items()})
        write(output/'progress.json', state)
        write(output/'summary.json', dict(methods=summary, seconds=time.monotonic()-started,
            model_startup_seconds=state['model_startup_seconds'], inference_seconds=state['inference_seconds']))
        print(json.dumps(summary), flush=True)
    except BaseException as exc:
        state.update(phase='failed', error=repr(exc))
        write(output/'progress.json', state)
        raise
    finally:
        for proc in reversed(processes):
            stop(proc)
        for stream in streams:
            stream.close()


def score(output):
    frozen = output/'frozen_repo'
    scripts = frozen/'eval/external_methods'
    env = dict(os.environ, PYTHONPATH=f'{SUPPORT}/deps:{frozen}/src')
    state = json.loads((output/'progress.json').read_text())
    labels = json.loads((output/'prepared/private_labels.json').read_text())
    needs_judge = any(json.loads(path.read_text())['success'] and
        labels[json.loads(path.read_text())['sample_id']]['sample']['task']=='open_qa'
        for method in ('rsi','vam') for path in (output/method).glob('*/execution.json'))
    judge = None
    started = time.monotonic()
    try:
        if needs_judge:
            state['phase'] = 'starting_judge'
            write(output/'progress.json', state)
            with (output/'judge.log').open('w') as log:
                judge = subprocess.Popen(['vllm','serve','/weights/Qwen3-30B-A3B-Instruct-2507',
                    '--served-model-name','Qwen3-30B-A3B-Instruct-2507','--host','127.0.0.1','--port','8110',
                    '--max-model-len','32768','--gpu-memory-utilization','0.9','--generation-config','vllm'],
                    env=dict(env,CUDA_VISIBLE_DEVICES='0'),stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            deadline = time.monotonic()+1200
            while True:
                if judge.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError('Judge startup failed')
                try:
                    with urllib.request.urlopen('http://127.0.0.1:8110/v1/models', timeout=3) as response:
                        write(output/'judge_card.json', json.load(response))
                    break
                except OSError:
                    time.sleep(5)
        state.update(phase='scoring', judge_startup_seconds=time.monotonic()-started)
        write(output/'progress.json', state)
        scoring_started = time.monotonic()
        for method in ('rsi','vam'):
            command = [sys.executable,str(scripts/'score.py'),'--prepared',str(output/'prepared'),
                       '--run',str(output/method)]
            if needs_judge:
                command += ['--judge-endpoint','http://127.0.0.1:8110/v1']
            run(command, output/(method+'_score.log'), env)
        state.update(phase='scored', scoring_seconds=time.monotonic()-scoring_started)
        write(output/'progress.json', state)
        run([sys.executable,str(scripts/'experiments/20261014/summarize_current.py'),'--output',str(output)],
            output/'analysis.log',env)
        state.update(phase='completed_with_errors' if any(v['failed'] for v in state['methods'].values()) else 'completed',
                     finished_at=datetime.now(timezone.utc).isoformat())
    except BaseException as exc:
        state.update(phase='failed_scoring_or_analysis', error=repr(exc))
        raise
    finally:
        if judge is not None:
            stop(judge)
        write(output/'progress.json', state)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['prepare', 'infer'])
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    (prepare if args.phase == 'prepare' else infer)(args.output)
    if args.phase == 'infer':
        score(args.output)
