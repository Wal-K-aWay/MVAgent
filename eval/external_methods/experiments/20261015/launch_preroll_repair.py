"""Run on modal-gpu: freeze and execute NC80/VAM repairs, then finalize on CPU."""
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import modal


def main():
    devbox = Path.home()/'wxu-evolve-agent/devbox'
    lock = devbox/'launch-preroll-repair-20261015.pid'
    with lock.open('x') as stream:
        stream.write(str(os.getpid()))
    volume = modal.Volume.from_name('wxu-evolve-agent-runs-20261006', environment_name='zheng-dev')
    def read_json(path):
        for attempt in range(6):
            try:
                return json.loads(b''.join(volume.read_file(path)))
            except modal.exception.ResourceExhaustedError:
                if attempt == 5:
                    raise
                time.sleep(60)
    prefix = 'devbox/external_upstream_nc80_20261015'
    deadline = time.monotonic()+7200
    while True:
        try:
            items = read_json(prefix+'/prepared/items.json')
            assert len(items) == 1 and items[0]['sample_id'] == 'crossvid:NC:80'
            main = read_json('devbox/external_upstream_20261015/progress.json')
            if main['phase'].startswith('failed'):
                raise RuntimeError(f'Original controller failed: {main}')
            if main['phase'] in ('completed','completed_with_errors'):
                break
        except (FileNotFoundError, modal.exception.NotFoundError):
            pass
        if time.monotonic() > deadline:
            raise TimeoutError('Original run or NC80 preparation did not finish; no repair GPU was allocated')
        time.sleep(60)
    env = dict(os.environ, DEVBOX_NAME='mvagent-external-upstream-nc80-20261015')
    command = ('export PYTHONPATH=/repo/src; '
               'python /repo/eval/external_methods/experiments/20261015/repair_preroll.py freeze_runtime')
    subprocess.run([str(Path.home()/'.local/bin/modal'),'run','--env','zheng-dev',str(devbox/'cpujob.py'),
        '--b64',base64.b64encode(command.encode()).decode()],cwd=devbox,check=True)
    # cpujob reports child exit codes in stdout, so require its expected output before allocating GPUs.
    ready = read_json(prefix+'/runtime_ready.json')
    assert ready['actor_image_pixels'] == ready['embedding_image_pixels'] == 448*448
    assert ready['rsi_http_timeout_seconds'] == 1860
    subprocess.run([sys.executable,str(devbox/'devbox.py'),'up','--gpu','H100!:4',
        '--hours','4','--idle','5','--no-pool'],env=env,cwd=devbox,check=True)
    root = '/runs/'+prefix
    command = (f'export PYTHONPATH=/runs/devbox/external_methods_20261014/support/deps:{root}/runtime_repo/src; '
               f'python {root}/runtime_repo/eval/external_methods/experiments/20261015/repair_preroll.py infer')
    subprocess.run([sys.executable,str(devbox/'devbox.py'),'run','external_upstream_nc80_20261015',
        '--b64',base64.b64encode(command.encode()).decode()],env=env,cwd=devbox,check=True)
    # This is a finite pipeline dependency wait; no periodic user notifications or duplicate submissions.
    command = ('export PYTHONPATH=/repo/src; '
               'python /repo/eval/external_methods/experiments/20261015/repair_preroll.py finalize')
    subprocess.run([str(Path.home()/'.local/bin/modal'),'run','--env','zheng-dev',str(devbox/'cpujob.py'),
        '--b64',base64.b64encode(command.encode()).decode()],cwd=devbox,check=True)
    final = read_json('devbox/external_upstream_20261015/final_analysis.json')
    print('Canonical summary saved:', final['status'], flush=True)


if __name__ == '__main__':
    main()
