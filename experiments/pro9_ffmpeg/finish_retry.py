"""Finish this recovery after its existing GPU pipeline; never resubmit Actor."""
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

import modal

DEVBOX=Path.home()/'wxu-evolve-agent/devbox'
sys.path.insert(0,str(DEVBOX))
import cpujob

NAME='pro9_ffmpeg_27b_retry_20261016'
SID='sb-r7uGenacmq2vj4bh4jGnmx'
ROOT='/runs/devbox/'+NAME


def log(message):
    print(datetime.now(timezone.utc).isoformat(),message,flush=True)


def read_status(volume):
    try:
        return json.loads(b''.join(volume.read_file(f'devbox/{NAME}/pipeline_progress.json')))
    except FileNotFoundError:
        return {}


def main():
    state=DEVBOX/'state-mvagent-pro9-ffmpeg-27b-retry-20261016.json'
    assert json.loads(state.read_text())['sandbox_id']==SID
    volume=modal.Volume.from_name('wxu-evolve-agent-runs-20261006',environment_name='zheng-dev')
    sandbox=modal.Sandbox.from_id(SID)
    log('Waiting for the existing Actor/Judge pipeline; no service or metrics polling')
    while True:
        status=read_status(volume)
        if status.get('phase') in {'judge_completed','failed'}:break
        if sandbox.poll() is not None:
            raise RuntimeError(f'Sandbox exited before pipeline completion: {status}')
        time.sleep(30)
    if sandbox.poll() is None:sandbox.terminate(wait=True)
    assert sandbox.poll() is not None
    state.unlink()
    log('GPU released; '+json.dumps(status))
    assert status['phase']=='judge_completed',status
    code=ROOT+'/code/experiments/pro9_ffmpeg'
    command=(f'export PRO_MODEL=27B PRO_RUN_ROOT={ROOT}; mkdir -p {ROOT}/analysis; '
             f'{{ python {code}/evaluate.py && python {code}/judge.py report '
             f'&& python {code}/recovery.py audit && python {code}/finalize.py; }} '
             f'> {ROOT}/analysis/finalize.log 2>&1')
    with cpujob.app.run(environment_name='zheng-dev'):
        rc,_,error=cpujob.job.remote(command)
        assert rc==0,(rc,error[-500:],ROOT+'/analysis/finalize.log')
    completed=json.loads(b''.join(volume.read_file(f'devbox/{NAME}/progress.json')))
    assert completed['phase']=='completed',completed
    log('Recovery scoring and audits completed: '+json.dumps(completed))


if __name__=='__main__':main()
