"""Paired visual-token experiment: same GPU per pair, alternating order, official scoring."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import random
import signal
import subprocess
import sys
import time
import urllib.request

ADAPTERS = Path(__file__).resolve().parents[2]
FROZEN = ADAPTERS.parents[1]
sys.path.insert(0, str(ADAPTERS))
from common import sha256, write


def now():
    return datetime.now(timezone.utc).isoformat()


def wait_ready(process, ports):
    cards = {}
    deadline = time.monotonic() + 1200
    while len(cards) < len(ports):
        if process.poll() is not None:
            raise RuntimeError(f'Model service exited with {process.returncode}')
        for port in ports:
            if port in cards:
                continue
            try:
                with urllib.request.urlopen(f'http://127.0.0.1:{port}/v1/models', timeout=3) as response:
                    cards[port] = json.load(response)['data'][0]
            except OSError:
                pass
        if time.monotonic() > deadline:
            raise TimeoutError(f'Model startup: ready ports {list(cards)}')
        time.sleep(2)
    return cards


def stop(process):
    if process is None or process.poll() is not None:
        return
    os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=40)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()


def main(root):
    prepared = root/'prepared'
    items = json.loads((prepared/'items.json').read_text())
    hashes = json.loads((prepared/'input_hashes.json').read_text())
    random.Random(0).shuffle(items)
    assert len(items) == 66
    state = dict(phase='starting_actor', started_at=now(), completed=0, successful=0,
                 expected=132, pairs=[], inference_seed=0, selection_seed=0)
    if (root/'progress.json').exists():
        raise FileExistsError('Refusing to overwrite an experiment')
    write(root/'progress.json', state)
    actor = judge = telemetry = None
    try:
        with (root/'actor.log').open('w') as log:
            actor = subprocess.Popen([sys.executable, str(FROZEN/'eval/e2e_eval/serve.py'),
                '--model', '/weights/Qwen3.5-35B-A3B', '--gpus', '0-7', '--port', '8100',
                '--log-dir', str(root/'servers')], stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        cards = wait_ready(actor, list(range(8100, 8108)))
        from models.vlm.local.sync_server import validate_card
        for card in cards.values():
            validate_card(card)
            assert card['execution']['profile'] == 'qwen35-bf16-flashinfer-sync'
        write(root/'service_cards.json', cards)
        with (root/'gpu.csv').open('w') as log:
            telemetry = subprocess.Popen(['nvidia-smi', '--query-gpu=timestamp,index,utilization.gpu,memory.used,power.draw',
                '--format=csv,noheader,nounits', '-l', '5'], stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        # One submitted worker per card pulls whole pairs; no concurrent requests on a card.
        import queue
        jobs = queue.Queue()
        for index, item in enumerate(items):
            jobs.put((index, item))
        state.update(phase='running_actor', inference_started_at=now(), inference_started_epoch=time.time())
        write(root/'progress.json', state)

        def worker(gpu):
            rows = []
            while True:
                try:
                    index, item = jobs.get_nowait()
                except queue.Empty:
                    return rows
                sid = item['sample_id']
                item_path = prepared/'items'/(sid.replace(':', '_')+'.json')
                assert sha256(item_path) == hashes[sid]['item_sha256']
                assert sha256(item['video_path']) == hashes[sid]['video_sha256']
                order = [8192, 2048] if index % 2 == 0 else [2048, 8192]
                pair = dict(sample_id=sid, gpu=gpu, order=order, index=index, runs=[])
                for cap in order:
                    output = root/f'cap{cap}'/sid.replace(':', '_')
                    output.mkdir(parents=True, exist_ok=False)
                    started = time.time()
                    row = dict(sample_id=sid, cap=cap, gpu=gpu, pair_index=index,
                        started_epoch=started, endpoint=f'http://127.0.0.1:{8100+gpu}/v1', input_hashes=hashes[sid])
                    try:
                        with (output/'job.log').open('w') as log:
                            proc = subprocess.run([sys.executable, str(ADAPTERS/'rsi.py'),
                                '--source', str(FROZEN/'external_sources/Video-RSI'), '--item', str(item_path),
                                '--output', str(output), '--endpoint', row['endpoint'],
                                '--vision-max-tokens', str(cap)], stdout=log, stderr=subprocess.STDOUT, timeout=7200)
                        result = json.loads((output/'result.json').read_text()) if (output/'result.json').exists() else {}
                        row.update(success=proc.returncode == 0, returncode=proc.returncode, answer=result.get('answer'))
                    except Exception as exc:
                        row.update(success=False, error=repr(exc))
                    row.update(finished_epoch=time.time(), seconds=time.time()-started)
                    write(output/'execution.json', row)
                    pair['runs'].append(row)
                    print(json.dumps(row, ensure_ascii=False), flush=True)
                write(root/'pairs'/(sid.replace(':', '_')+'.json'), pair)
                rows.append(pair)

        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(worker, gpu) for gpu in range(8)]
            while any(not future.done() for future in futures):
                records = [json.loads(p.read_text()) for p in root.glob('cap*/*/execution.json')]
                state.update(completed=len(records), successful=sum(r['success'] for r in records))
                write(root/'progress.json', state)
                time.sleep(10)
            state['pairs'] = [pair for future in futures for pair in future.result()]
        state.update(completed=132, successful=sum(r['success'] for p in state['pairs'] for r in p['runs']),
                     inference_finished_epoch=time.time(), phase='starting_judge')
        write(root/'progress.json', state)
        stop(telemetry)
        stop(actor)
        with (root/'judge.log').open('w') as log:
            judge = subprocess.Popen(['vllm', 'serve', '/weights/Qwen3-30B-A3B-Instruct-2507',
                '--served-model-name', 'Qwen3-30B-A3B-Instruct-2507', '--host', '127.0.0.1', '--port', '8110',
                '--max-model-len', '32768', '--gpu-memory-utilization', '0.9', '--generation-config', 'vllm'],
                env={**os.environ, 'CUDA_VISIBLE_DEVICES': '0'}, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        write(root/'judge_card.json', wait_ready(judge, [8110]))
        state['phase'] = 'scoring'
        write(root/'progress.json', state)
        for cap in (8192, 2048):
            subprocess.run([sys.executable, str(ADAPTERS/'score.py'), '--prepared', str(prepared),
                '--run', str(root/f'cap{cap}'), '--judge-endpoint', 'http://127.0.0.1:8110/v1'], check=True)
        state.update(phase='completed' if state['successful']==132 else 'completed_with_errors', finished_at=now())
    except BaseException as exc:
        state.update(phase='failed', error=repr(exc), finished_at=now())
        raise
    finally:
        stop(telemetry)
        stop(actor)
        stop(judge)
        write(root/'progress.json', state)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    main(parser.parse_args().output)
