"""Paired baseline/candidate timing on CVBench 764 with fixed local model replicas."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import difflib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.request

BASE = Path('/runs/devbox/external_methods_current_20261014_r2/frozen_repo')
ITEM = Path('/runs/devbox/external_methods_current_20261014_r2/prepared/items/cvbench_764.json')


def main(root):
    assert (root/'media_r2/summary.json').is_file(), 'Run the paired image-byte checks first'
    root.joinpath('e2e').mkdir(exist_ok=False)
    candidate = root/'sources/Visual-Agentic-Memory'
    shutil.copytree(BASE/'external_sources/Visual-Agentic-Memory', candidate)
    video = candidate/'vam/video.py'
    before = video.read_text()
    old_input = '                "-i",\n                video_path,'
    old_output = '                "2",\n                pattern,'
    assert before.count(old_input) == before.count(old_output) == 1
    after = before.replace(old_input, '                "-threads", "2",\n'+old_input)
    after = after.replace(old_output, '                "2",\n                "-threads", "1", "-filter_threads", "1",\n                pattern,')
    video.write_text(after)
    (root/'vam_threads.patch').write_text(''.join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
        fromfile='a/vam/video.py', tofile='b/vam/video.py')))
    sys.path.insert(0, str(BASE/'src'))
    from models.vlm.local.sync_server import validate_card
    cards = []
    for port in (8100, 8101):
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/v1/models', timeout=10) as response:
            card = json.load(response)['data'][0]
        validate_card(card)
        cards.append(card)
    (root/'service_cards.json').write_text(json.dumps(cards, indent=2))
    env = dict(os.environ, PYTHONPATH=f'/runs/devbox/external_methods_20261014/support/deps:{BASE}/src')
    rows = []
    for repeat, variants in enumerate((('baseline', 'candidate'), ('candidate', 'baseline'))):
        for variant in variants:
            def one(method, port):
                directory = root/'e2e'/f'{repeat}_{variant}'/method
                directory.mkdir(parents=True)
                source = (BASE/'external_sources'/('Video-RSI' if method == 'rsi' else 'Visual-Agentic-Memory'))
                if variant == 'candidate':
                    source = root/'media_r2/sources/rsi' if method == 'rsi' else candidate
                started = time.monotonic()
                with (directory/'job.log').open('w') as stream:
                    proc = subprocess.run([sys.executable, str(BASE/f'eval/external_methods/{method}.py'),
                        '--source', str(source), '--item', str(ITEM), '--output', str(directory),
                        '--endpoint', f'http://127.0.0.1:{port}/v1'], env=env, stdout=stream,
                        stderr=subprocess.STDOUT, timeout=1200)
                result = json.loads((directory/'result.json').read_text()) if (directory/'result.json').exists() else {}
                return dict(method=method, variant=variant, repeat=repeat, seconds=time.monotonic()-started,
                    returncode=proc.returncode, answer=result.get('answer'),
                    index_seconds=result.get('index_seconds'), query_seconds=result.get('query_seconds'))
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(one, method, port) for method, port in (('rsi', 8100), ('vam', 8101))]
                for future in futures:
                    row = future.result()
                    rows.append(row)
                    print(json.dumps(row), flush=True)
            (root/'e2e_measurements.json').write_text(json.dumps(rows, indent=2))
    assert all(r['returncode'] == 0 and r['answer'] for r in rows), rows
    print('Paired E2E timings complete; compare request hashes before interpreting speedups.', flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    main(p.parse_args().output)
