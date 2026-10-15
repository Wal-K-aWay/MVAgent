"""Run on modal-gpu; freeze, submit one background VAM65 job, then exit."""
import base64
import json
import os
from pathlib import Path
import subprocess
import sys

import modal


def main():
    devbox=Path.home()/'wxu-evolve-agent/devbox'
    with (devbox/'launch-vam65-20261015.pid').open('x') as handle:
        handle.write(str(os.getpid()))
    source=Path(__file__).resolve().parents[4]
    template=(devbox/'cpujob.py').read_text()
    old='REPO = os.path.expanduser("~/wxu-evolve-agent/repo")'
    assert template.count(old)==1
    cpujob=devbox/'external_vam65_cpujob_20261015.py'
    cpujob.write_text(template.replace(old,'REPO = '+repr(str(source))))
    command='python /repo/eval/external_methods/experiments/20261015/vam_expanded.py prepare'
    subprocess.run([str(Path.home()/'.local/bin/modal'),'run','--env','zheng-dev',str(cpujob),
        '--b64',base64.b64encode(command.encode()).decode()],cwd=devbox,check=True)
    volume=modal.Volume.from_name('wxu-evolve-agent-runs-20261006',environment_name='zheng-dev')
    ready=json.loads(b''.join(volume.read_file('devbox/external_vam65_20261015/ready.json')))
    assert ready['samples']==65 and ready['vam_http_seconds']==240 and ready['rsi_current_http_seconds']==600
    env=dict(os.environ,DEVBOX_NAME='mvagent-external-vam65-20261015')
    subprocess.run([sys.executable,str(devbox/'devbox.py'),'up','--gpu','H100!:8',
                    '--hours','12','--idle','10','--no-pool'],cwd=devbox,env=env,check=True)
    root='/runs/devbox/external_vam65_20261015'
    command=(f'export PYTHONPATH=/runs/devbox/external_methods_20261014/support/deps:{root}/frozen_repo/src; '
             f'python {root}/frozen_repo/eval/external_methods/experiments/20261015/vam_expanded.py run')
    subprocess.run([sys.executable,str(devbox/'devbox.py'),'run','external_vam65_20261015',
                    '--b64',base64.b64encode(command.encode()).decode()],cwd=devbox,env=env,check=True)
    print('Submitted VAM65 with automatic scoring, paired report and model cleanup.',flush=True)


if __name__=='__main__':
    main()
