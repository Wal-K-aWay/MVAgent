"""Separate protocol-changing probe: cap RSI visual reports at 2048 tokens."""
import argparse
import difflib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

BASE = Path('/runs/devbox/external_methods_current_20261014_r2/frozen_repo')


def main(root):
    deadline = time.monotonic()+1200
    while True:
        path = root/'e2e_measurements.json'
        if path.exists() and len(json.loads(path.read_text())) == 8:
            break
        if time.monotonic() > deadline:
            raise RuntimeError('Paired timing still owns the model endpoint')
        time.sleep(5)
    output = root/'budget_probe'
    output.mkdir(exist_ok=False)
    source = output/'source'
    source.mkdir()
    before = (BASE/'eval/external_methods/rsi.py').read_text()
    old = 'self.client.chat(messages, max_tokens=8192)'
    assert before.count(old) == 1
    after = before.replace(old, 'self.client.chat(messages, max_tokens=2048 if role == "qwen" else 8192)')
    (source/'rsi.py').write_text(after)
    shutil.copyfile(BASE/'eval/external_methods/common.py', source/'common.py')
    (output/'change.patch').write_text(''.join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
        fromfile='a/rsi.py', tofile='b/rsi.py')))
    env = dict(os.environ, PYTHONPATH=f'/runs/devbox/external_methods_20261014/support/deps:{BASE}/src')
    started = time.monotonic()
    with (output/'job.log').open('w') as log:
        proc = subprocess.run([sys.executable, str(source/'rsi.py'), '--source', str(BASE/'external_sources/Video-RSI'),
            '--item', '/runs/devbox/external_methods_current_20261014_r2/prepared/items/mvu_eval_TR_1585.json',
            '--output', str(output/'result'), '--endpoint', 'http://127.0.0.1:8100/v1'], env=env,
            stdout=log, stderr=subprocess.STDOUT, timeout=1200)
    summary = dict(returncode=proc.returncode, seconds=time.monotonic()-started,
                   protocol_change='Qwen visual reports 8192 -> 2048; planner stays 8192')
    result = output/'result/result.json'
    if result.exists():
        summary.update(json.loads(result.read_text()))
    (output/'summary.json').write_text(json.dumps(summary, indent=2))
    print(json.dumps({k: summary.get(k) for k in ('returncode', 'seconds', 'answer', 'usage', 'protocol_change')}), flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    main(p.parse_args().output)
