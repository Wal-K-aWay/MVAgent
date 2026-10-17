"""Submit through modal-gpu: CPU preparation, 8 H100 native CrossVid inference, CCQA Judge."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile

import modal

image = None
if modal.is_local():
    from agentcvr_assets import image as prepared_image
    image = prepared_image.add_local_dir(str(Path.home() / 'wxu-evolve-agent/agentcvr_crossvid_repo'), '/code',
                                         ignore=['.git', '__pycache__', '*.pyc'])
weights = modal.Volume.from_name('wxu-sgl-evolve-agent-weight-20261006')
assets = modal.Volume.from_name('wxu-evolve-agent-inf-asset-20261006')
runs = modal.Volume.from_name('wxu-evolve-agent-runs-20261006')
volumes = {'/weights': weights.with_mount_options(read_only=True),
           '/assets': assets.with_mount_options(read_only=True), '/runs': runs}
app = modal.App('wxu-sglang-baseline-gpu-test-agentcvr-crossvid-20261017')
OUTPUT = '/runs/devbox/agentcvr_crossvid_20261017'


@app.function(image=image, cpu=4, memory=16384, timeout=1800, volumes=volumes)
def prepare():
    root = Path('/code/eval/external_methods')
    env = dict(os.environ, PYTHONPATH='/code/src')
    subprocess.run([sys.executable, str(root / 'test_agentcvr.py')], check=True, env=env)
    subprocess.run([sys.executable, str(root / 'test_agentcvr_crossvid.py')], check=True, env=env)
    subprocess.run([sys.executable, '-m', 'compileall', '-q', '/code/src', '/code/scripts',
                    '/code/eval/agent_eval', '/code/demo.py', str(root)], check=True)
    subprocess.run([sys.executable, str(root / 'agentcvr_eval.py'), 'prepare', '--output', OUTPUT,
                    '--benchmark', 'crossvid'], check=True, env=env)
    assert Path('/weights/AgentCVR-8B-merged/config.json').exists()
    assert Path('/weights/Qwen3-VL-8B-Thinking/config.json').exists()
    runs.commit()
    return json.loads((Path(OUTPUT) / 'progress.json').read_text())


@app.function(image=image, gpu='H100!:8', cpu=32, memory=262144, timeout=86400,
              volumes=volumes, max_containers=1, scaledown_window=10)
def evaluate():
    output = Path(OUTPUT)
    working = Path('/work/agentcvr-crossvid')
    working.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output / 'frozen_source.tar.gz') as archive:
        archive.extractall(working, filter='data')
    root = working / 'eval/external_methods'
    hardware = subprocess.check_output(['nvidia-smi', '--query-gpu=name,uuid,memory.total', '--format=csv,noheader'], text=True)
    assert len(hardware.strip().splitlines()) == 8 and all('H100' in s for s in hardware.strip().splitlines())
    (output / 'hardware.txt').write_text(hardware)
    env = dict(os.environ, PYTHONPATH=str(working / 'src'))
    try:
        subprocess.run([sys.executable, str(root / 'agentcvr_eval.py'), 'run', '--output', OUTPUT], env=env, check=True)
        state = json.loads((output / 'progress.json').read_text())
        if state['phase'] == 'inference_completed':
            subprocess.run([sys.executable, str(root / 'agentcvr_crossvid.py'), 'judge', '--output', OUTPUT], env=env, check=True)
    finally:
        runs.commit()
    return json.loads((output / 'progress.json').read_text())


@app.local_entrypoint()
def main(mode: str = 'prepare'):
    if mode in ('prepare', 'all'):
        print(prepare.remote(), flush=True)
    if mode in ('run', 'all'):
        while True:
            result = evaluate.remote()
            print(result, flush=True)
            if result['phase'] != 'resume_required':
                break
