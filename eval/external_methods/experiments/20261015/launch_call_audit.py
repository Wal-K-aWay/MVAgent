"""Invoke only on modal-gpu: CPU call audit followed by one disposable H100 smoke."""
import json
import os
from pathlib import Path
import subprocess
import sys

import modal

app=modal.App('wxu-sglang-baseline-gpu-test-external-call-audit-20261015')
if modal.is_local():
    sys.path.insert(0,os.path.expanduser('~/wxu-evolve-agent/modal'))
    from env_image import image as base
    image=base.add_local_dir(Path(__file__).resolve().parents[2],'/repo/eval/external_methods',ignore=['**/__pycache__'])
else:
    image=modal.Image.debian_slim()
runs=modal.Volume.from_name('wxu-evolve-agent-runs-20261006')
weights=modal.Volume.from_name('wxu-sgl-evolve-agent-weight-20261006')
volumes={'/runs':runs,'/weights':weights.with_mount_options(read_only=True)}
root=Path('/runs/devbox/external_call_audit_20261015_r2')


def execute(phase):
    source=(Path('/repo') if phase=='prepare' else root/'frozen_repo')
    try:
        subprocess.run([sys.executable,str(source/'eval/external_methods/experiments/20261015/call_audit.py'),phase],check=True)
    finally:
        runs.commit()
    return json.loads((root/('audit.json' if phase=='prepare' else 'smoke.json')).read_text())


@app.function(image=image,cpu=8,memory=32768,timeout=1200,volumes=volumes)
def prepare():
    return execute('prepare')


@app.function(image=image,gpu='H100!',cpu=8,memory=131072,timeout=2400,
              max_containers=1,scaledown_window=2,volumes=volumes)
def smoke():
    return execute('smoke')


@app.local_entrypoint()
def main():
    print(json.dumps(prepare.remote(),ensure_ascii=False))
    print(json.dumps(smoke.remote(),ensure_ascii=False))
