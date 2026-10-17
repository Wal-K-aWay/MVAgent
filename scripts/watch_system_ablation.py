"""Modal dev-host owner for the two independent System trials; never touches other jobs."""
import base64
from concurrent.futures import ThreadPoolExecutor
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
TAG='system_ablation_20261017'
ARMS=('global_short','video_rules')


def log(**values):
    print(datetime.now(timezone.utc).isoformat(),json.dumps(values),flush=True)


def finished_or_expired(phase,alive,elapsed):
    return phase in {'completed','failed'} or not alive or elapsed>6900


def main():
    lock=(HERE/f'watch-{TAG}.lock').open('w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    pid=HERE/f'watch-{TAG}.pid';pid.write_text(str(os.getpid()))
    volume=modal.Volume.from_name('wxu-evolve-agent-runs-20261006',environment_name='zheng-dev')
    def progress(arm):
        return json.loads(b''.join(volume.read_file(f'devbox/{TAG}/{arm}/progress.json')))
    def start(arm):
        name=f'mvagent-system-{arm}-20261017';env={**os.environ,'DEVBOX_NAME':name}
        with (HERE/f'{TAG}_{arm}_launch.log').open('a') as stream:
            subprocess.run([sys.executable,str(HERE/'devbox.py'),'up','--gpu','H100!:8','--no-pool',
                '--hours','2','--idle','15'],cwd=HERE,env=env,stdout=stream,stderr=subprocess.STDOUT,check=True)
            command=f'python /repo/scripts/run_system_ablation.py worker --arm {arm}'
            subprocess.run([sys.executable,str(HERE/'devbox.py'),'run',f'{TAG}_{arm}','--b64',
                base64.b64encode(command.encode()).decode()],cwd=HERE,env=env,stdout=stream,stderr=subprocess.STDOUT,check=True)
        path=HERE/f'state-{name}.json';state=json.loads(path.read_text());sb=modal.Sandbox.from_id(state['sandbox_id'])
        log(arm=arm,sandbox=state['sandbox_id']);return sb,path
    owned={};finished=set();last={};start_time=time.monotonic()
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures={arm:pool.submit(start,arm) for arm in ARMS}
            while len(finished)<len(ARMS):
                for arm,future in futures.items():
                    if arm in finished or not future.done():continue
                    if arm not in owned:
                        try:owned[arm]=future.result()
                        except Exception as exc:
                            path=HERE/f'state-mvagent-system-{arm}-20261017.json'
                            if path.exists():
                                sb=modal.Sandbox.from_id(json.loads(path.read_text())['sandbox_id'])
                                if sb.poll() is None:sb.terminate(wait=True)
                                path.unlink()
                            log(arm=arm,launch_error=repr(exc));finished.add(arm);continue
                    sb,path=owned[arm];state=progress(arm)
                    key=(state.get('phase'),state.get('model'))
                    if last.get(arm)!=key:log(arm=arm,phase=key,models=state.get('models'));last[arm]=key
                    alive=sb.poll() is None
                    if finished_or_expired(state.get('phase'),alive,time.monotonic()-start_time):
                        if alive:sb.terminate(wait=True)
                        path.unlink(missing_ok=True);finished.add(arm)
                        log(arm=arm,released=True,final=state)
                if len(finished)<len(ARMS):time.sleep(45)
        sys.path.insert(0,str(HERE));import cpujob
        command=(f'mkdir -p /tmp/{TAG} && tar xzf /runs/devbox/{TAG}/source.tar.gz -C /tmp/{TAG} && '
                 f'python /tmp/{TAG}/scripts/run_system_ablation.py analyze > /runs/devbox/{TAG}/analysis.log 2>&1')
        with cpujob.app.run(environment_name='zheng-dev'):
            rc,_,error=cpujob.job.remote(command)
        assert rc==0,(rc,error)
        log(phase='analysis_completed')
    finally:
        for sb,path in owned.values():
            if sb.poll() is None:sb.terminate(wait=True)
            path.unlink(missing_ok=True)
        pid.unlink(missing_ok=True)


if __name__=='__main__':
    if '--self-check' in sys.argv:
        assert finished_or_expired('completed',True,1)
        assert finished_or_expired('failed',True,1)
        assert finished_or_expired('inference',False,1)
        assert finished_or_expired('inference',True,6901)
        assert not finished_or_expired('inference',True,10)
        print('Owned lifecycle completion/failure/expiry checks passed')
    else:main()
