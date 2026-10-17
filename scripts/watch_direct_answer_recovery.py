"""Own one recovery Sandbox, release it before final CPU aggregation."""
import base64
from datetime import datetime,timezone
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import modal

HERE=Path.home()/'wxu-evolve-agent/devbox'
TAG='direct_answer_large_recovery_20261017'
NAME='mvagent-direct-large-recovery-20261017'
ROOT='/runs/devbox/'+TAG
SOURCE='/runs/devbox/direct_answer_large_20261016/frozen_repo'


def action(phase,alive,elapsed):
    if phase in {'judge_completed','completed','failed'}:return 'release'
    if not alive:return 'lost'
    if elapsed>=5*3600:return 'cap'
    return 'wait'


def main():
    lock=(HERE/f'watch-{TAG}.lock').open('w')
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    pid=HERE/f'watch-{TAG}.pid';pid.write_text(str(os.getpid()))
    volume=modal.Volume.from_name('wxu-evolve-agent-runs-20261006',environment_name='zheng-dev')
    env={**os.environ,'DEVBOX_NAME':NAME}
    statefile=HERE/f'state-{NAME}.json'
    sandbox=None
    def log(**value):print(datetime.now(timezone.utc).isoformat(),json.dumps(value),flush=True)
    def progress():return json.loads(b''.join(volume.read_file(f'devbox/{TAG}/progress.json')))
    try:
        assert progress()['phase']=='prepared','Do not duplicate or overwrite an existing recovery'
        with (HERE/f'{TAG}_launch.log').open('a') as stream:
            subprocess.run([sys.executable,str(HERE/'devbox.py'),'up','--gpu','H100!:8','--no-pool',
                '--hours','5.5','--idle','20'],cwd=HERE,env=env,stdout=stream,stderr=subprocess.STDOUT,check=True)
            sandbox=modal.Sandbox.from_id(json.loads(statefile.read_text())['sandbox_id'])
            command=f'PYTHONDONTWRITEBYTECODE=1 python {ROOT}/code/recover_direct_answer_large.py worker'
            subprocess.run([sys.executable,str(HERE/'devbox.py'),'run',TAG,'--b64',base64.b64encode(command.encode()).decode()],
                cwd=HERE,env=env,stdout=stream,stderr=subprocess.STDOUT,check=True)
        log(started=sandbox.object_id)
        started=time.monotonic();previous=None
        while True:
            state=progress();phase=state['phase']
            if (phase,state.get('model'))!=previous:
                log(phase=phase,model=state.get('model'),models=state.get('models'));previous=(phase,state.get('model'))
            next_action=action(phase,sandbox.poll() is None,time.monotonic()-started)
            if next_action!='wait':break
            time.sleep(45)
        if sandbox.poll() is None:sandbox.terminate(wait=True)
        statefile.unlink(missing_ok=True)
        log(released=sandbox.object_id,reason=next_action,phase=phase)
        assert phase=='judge_completed',(phase,state)
        sys.path.insert(0,str(HERE));import cpujob
        command=(f'export PYTHONDONTWRITEBYTECODE=1 PYTHONPATH={SOURCE}/scripts:{SOURCE}/src:{SOURCE}/eval/e2e_eval; '
            f'python {ROOT}/code/analyze_direct_answer_large.py --recovery-dir {ROOT} --report-dir {ROOT}/analysis '
            f'> {ROOT}/analysis.log 2>&1')
        with cpujob.app.run(environment_name='zheng-dev'):
            code,_,error=cpujob.job.remote(command)
        assert code==0,(code,error,ROOT+'/analysis.log')
        assert progress()['phase']=='completed'
        log(phase='completed',output=ROOT)
    finally:
        if sandbox is None and statefile.exists():
            sandbox=modal.Sandbox.from_id(json.loads(statefile.read_text())['sandbox_id'])
        if sandbox is not None and sandbox.poll() is None:
            sandbox.terminate(wait=True)
        statefile.unlink(missing_ok=True);pid.unlink(missing_ok=True)


if __name__=='__main__':
    if '--self-check' in sys.argv:
        assert action('inference',True,1)=='wait'
        assert action('failed',True,1)=='release'
        assert action('judge_completed',False,1)=='release'
        assert action('inference',False,1)=='lost'
        assert action('inference',True,18000)=='cap'
        print('Recovery lifecycle checks passed')
    else:main()
