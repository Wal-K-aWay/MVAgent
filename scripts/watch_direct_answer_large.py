"""Host lifecycle for two isolated shards; release GPUs, then aggregate on Modal CPU."""
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import modal

HERE = Path.home()/'wxu-evolve-agent/devbox'
TAG = 'direct_answer_large_20261016'
ROOT = '/runs/devbox/'+TAG
SOURCE = ROOT+'/frozen_repo'
NAMES = [f'mvagent-direct-large-20261016-s{i}' for i in range(2)]


def log(**message):
    print(datetime.now(timezone.utc).isoformat(), json.dumps(message), flush=True)


def main():
    assert (HERE/'devbox.py').is_file()
    lock=(HERE/f'watch-{TAG}.lock').open('w')
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    (HERE/f'watch-{TAG}.pid').write_text(str(os.getpid()))
    volume=modal.Volume.from_name('wxu-evolve-agent-runs-20261006',environment_name='zheng-dev')
    def progress(shard):
        try:return json.loads(b''.join(volume.read_file(f'devbox/{TAG}/shard{shard}/progress.json')))
        except FileNotFoundError:return {}
    def start(shard):
        env={**os.environ,'DEVBOX_NAME':NAMES[shard]}
        with (HERE/f'{TAG}_s{shard}_launch.log').open('a') as stream:
            subprocess.run([sys.executable,str(HERE/'devbox.py'),'up','--gpu','H100!:8','--no-pool',
                            '--hours','10.5','--idle','20'],cwd=HERE,env=env,stdout=stream,stderr=subprocess.STDOUT,check=True)
            command=f'python {SOURCE}/scripts/run_direct_answer_large.py worker --shard {shard}'
            subprocess.run([sys.executable,str(HERE/'devbox.py'),'run',f'{TAG}_s{shard}','--b64',
                            base64.b64encode(command.encode()).decode()],cwd=HERE,env=env,
                            stdout=stream,stderr=subprocess.STDOUT,check=True)
        state=json.loads((HERE/f'state-{NAMES[shard]}.json').read_text())
        log(shard=shard,started=state['sandbox_id'])
        return modal.Sandbox.from_id(state['sandbox_id'])
    completed=set();sandboxes={};failures={};last={};started=time.monotonic()
    with ThreadPoolExecutor(max_workers=2) as pool:
        launches={i:pool.submit(start,i) for i in range(2)}
        try:
            while len(completed)<2:
                for shard,future in launches.items():
                    if shard in completed or not future.done():continue
                    if shard not in sandboxes:sandboxes[shard]=future.result()
                    sandbox=sandboxes[shard]
                    state=progress(shard)
                    key=(state.get('phase'),state.get('model'))
                    if key!=last.get(shard):
                        log(shard=shard,phase=key,models=state.get('models'));last[shard]=key
                    if state.get('phase') in {'completed','failed'}:
                        if sandbox.poll() is None:sandbox.terminate(wait=True)
                        completed.add(shard)
                        (HERE/f'state-{NAMES[shard]}.json').unlink(missing_ok=True)
                        log(shard=shard,released=True,phase=state['phase'])
                        if state['phase']=='failed':failures[shard]=state
                    elif sandbox.poll() is not None:
                        failures[shard]={'error':'Sandbox exited before completed','progress':state}
                        completed.add(shard)
                    elif time.monotonic()-started>10*3600:
                        sandbox.terminate(wait=True)
                        failures[shard]={'error':'Ten-hour wall-clock cap reached','progress':state}
                        completed.add(shard)
                if len(completed)<2:time.sleep(60)
            assert not failures,failures
            sys.path.insert(0,str(HERE))
            import cpujob
            command=f'python {SOURCE}/scripts/analyze_direct_answer_large.py > {ROOT}/analysis.log 2>&1'
            with cpujob.app.run(environment_name='zheng-dev'):
                rc,_,error=cpujob.job.remote(command)
            assert rc==0,(rc,error,ROOT+'/analysis.log')
            log(phase='completed',output=ROOT)
        finally:
            (HERE/f'watch-{TAG}.pid').unlink(missing_ok=True)


if __name__=='__main__':main()
