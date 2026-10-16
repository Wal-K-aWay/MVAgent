"""Launch only through modal-gpu; separate CPU preparation from the eight-GPU evaluation."""
import json
from pathlib import Path
import subprocess
import sys

import modal

image = None
if modal.is_local():
    from agentcvr_assets import image as prepared_image
    image = prepared_image.add_local_dir(str(Path.home() / 'wxu-evolve-agent/agentcvr_repo'), '/code',
                                         ignore=['.git', '__pycache__', '*.pyc'])
weights = modal.Volume.from_name('wxu-sgl-evolve-agent-weight-20261006')
assets = modal.Volume.from_name('wxu-evolve-agent-inf-asset-20261006')
runs = modal.Volume.from_name('wxu-evolve-agent-runs-20261006')
volumes = {'/weights': weights.with_mount_options(read_only=True),
           '/assets': assets.with_mount_options(read_only=True), '/runs': runs}
app = modal.App('wxu-sglang-baseline-gpu-test-agentcvr-20261016')
OUTPUT = '/runs/devbox/agentcvr_eval_20261016_r3'


@app.function(image=image, cpu=4, memory=16384, timeout=1800, volumes=volumes)
def prepare():
    root = Path('/code/eval/external_methods')
    subprocess.run([sys.executable, str(root / 'test_agentcvr.py')], check=True)
    subprocess.run([sys.executable, '-m', 'compileall', '-q', '/code/src', '/code/scripts',
                    '/code/eval/agent_eval', '/code/demo.py', str(root)], check=True)
    subprocess.run([sys.executable, str(root / 'agentcvr_eval.py'), 'prepare', '--output', OUTPUT], check=True)
    runs.commit()
    return json.loads((Path(OUTPUT) / 'progress.json').read_text())


@app.function(image=image, gpu='H200:8', cpu=32, memory=262144, timeout=86400,
              volumes=volumes, max_containers=1, scaledown_window=10)
def evaluate(smoke_only: bool = False):
    import os
    import tarfile
    output = Path(OUTPUT)
    assets_status = json.loads(Path('/runs/devbox/agentcvr_20261016/assets.json').read_text())
    assert assets_status['stage'] == 'completed'
    working = Path('/work/agentcvr')
    working.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output / 'frozen_source.tar.gz') as tar:
        tar.extractall(working, filter='data')
    subprocess.run(['nvidia-smi', '--query-gpu=name,memory.total', '--format=csv'], check=True)
    try:
        subprocess.run([sys.executable, str(working / 'eval/external_methods/agentcvr_eval.py'),
                        'smoke' if smoke_only else 'run', '--output', OUTPUT], check=True,
                       env=dict(os.environ, PYTHONPATH=str(working / 'src')))
    finally:
        runs.commit()
    return json.loads((output / 'progress.json').read_text())


@app.local_entrypoint()
def main(mode: str = 'prepare'):
    if mode in ('prepare', 'all'):
        print(prepare.remote())
    if mode in ('run', 'smoke', 'all'):
        while True:
            result = evaluate.remote(smoke_only=mode == 'smoke')
            print(result, flush=True)
            if result['phase'] != 'resume_required':
                break
    elif mode != 'prepare':
        raise ValueError(mode)
