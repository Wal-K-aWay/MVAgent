"""Run on modal-gpu: freeze the native-image protocol and submit its self-finalizing GPU job."""
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

import modal


def main():
    devbox = Path.home()/'wxu-evolve-agent/devbox'
    with (devbox/'launch-original-images-20261015.pid').open('x') as stream:
        stream.write(str(os.getpid()))
    source = devbox/'external-original-images-source-20261015'
    source.mkdir(exist_ok=False)
    shutil.copytree(devbox.parent/'repo/eval/external_methods', source/'eval/external_methods',
                    ignore=shutil.ignore_patterns('__pycache__'))
    (source/'source_manifest.json').write_text(json.dumps({str(p.relative_to(source)):
        hashlib.sha256(p.read_bytes()).hexdigest() for p in source.rglob('*') if p.is_file()},indent=2))
    cpujob = devbox/'external_original_images_cpujob_20261015.py'
    template = (devbox/'cpujob.py').read_text()
    setting = 'REPO = os.path.expanduser("~/wxu-evolve-agent/repo")'
    assert template.count(setting) == 1
    cpujob.write_text(template.replace(setting,'REPO = '+repr(str(source))))
    command = 'python /repo/eval/external_methods/experiments/20261015/original_images.py prepare'
    subprocess.run([str(Path.home()/'.local/bin/modal'),'run','--env','zheng-dev',str(cpujob),
        '--b64',base64.b64encode(command.encode()).decode()],cwd=devbox,check=True)
    volume = modal.Volume.from_name('wxu-evolve-agent-runs-20261006',environment_name='zheng-dev')
    for attempt in range(6):
        try:
            ready = json.loads(b''.join(volume.read_file('devbox/external_original_images_20261015/ready.json')))
            break
        except modal.exception.ResourceExhaustedError:
            if attempt == 5:
                raise
            time.sleep(60)
    assert ready['rsi_image_width']==768 and ready['vam_image_pixels']==1280*1280
    assert ready['embedding_image_pixels']==1800*32*32 and ready['rsi_http_timeout_seconds']==600
    env = dict(os.environ,DEVBOX_NAME='mvagent-external-native-images-20261015')
    subprocess.run([sys.executable,str(devbox/'devbox.py'),'up','--gpu','H100!:8',
        '--hours','8','--idle','10','--no-pool'],cwd=devbox,env=env,check=True)
    root = '/runs/devbox/external_original_images_20261015'
    command = (f'export PYTHONPATH=/runs/devbox/external_methods_20261014/support/deps:{root}/frozen_repo/src; '
               f'python {root}/frozen_repo/eval/external_methods/experiments/20261015/original_images.py infer')
    subprocess.run([sys.executable,str(devbox/'devbox.py'),'run','external_original_images_20261015',
        '--b64',base64.b64encode(command.encode()).decode()],cwd=devbox,env=env,check=True)
    print('Submitted native-image RSI65 + VAM3; controller scores, summarizes and stops its models.',flush=True)


if __name__ == '__main__':
    main()
