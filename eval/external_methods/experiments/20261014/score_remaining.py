"""One-off Modal scoring, invoked only from the modal-gpu dev box."""
import json
import os
from pathlib import Path
import subprocess
import sys

import modal

app = modal.App('wxu-sglang-baseline-gpu-test-external-score')
if modal.is_local():
    sys.path.insert(0, os.path.expanduser('~/wxu-evolve-agent/modal'))
    from env_image import image as base
    image = base.add_local_file(Path(__file__).with_name('finalize_remaining.py'), '/finalize_remaining.py')
else:
    image = modal.Image.debian_slim()
runs = modal.Volume.from_name('wxu-evolve-agent-runs-20261006')
weights = modal.Volume.from_name('wxu-sgl-evolve-agent-weight-20261006')


@app.function(image=image, gpu='H100!', cpu=8, memory=131072, timeout=2400,
              max_containers=1, scaledown_window=2,
              volumes={'/runs': runs, '/weights': weights.with_mount_options(read_only=True)})
def finish():
    root = Path('/runs/devbox/external_methods_20261014')
    env = dict(os.environ, PYTHONPATH=f'{root}/support/deps:{root}/r9/frozen_repo/src')
    source = Path('/finalize_remaining.py').read_text()
    (root/'finalize_remaining.py').write_text(source)
    try:
        with (root/'finalize_remaining.log').open('w') as log:
            subprocess.run([sys.executable,'/finalize_remaining.py'],env=env,stdout=log,stderr=subprocess.STDOUT,check=True)
        result = json.loads((root/'final_summary.json').read_text())
        assert set(result) == {'rsi','vam'} and all(x['attempted']==33 for x in result.values())
        return {method: {'valid': row['valid'], 'scored': row['scored']} for method,row in result.items()}
    finally:
        runs.commit()


@app.local_entrypoint()
def main():
    print(json.dumps(finish.remote()))
