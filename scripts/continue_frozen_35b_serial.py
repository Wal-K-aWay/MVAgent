"""Dev-box owner: finish the interrupted 35B partition using only one GPU pool at a time."""
import fcntl
import json
from pathlib import Path
import signal
import subprocess
import sys
import time


def ready(progress, gpu_exit):
    assert progress['phase'] != 'failed', 'First 35B partition failed; inspect before continuing'
    return progress['phase'] == 'completed' and gpu_exit is not None


def main():
    import modal
    base=Path('/tmp/mvagent-27b-results-20261019')
    lock=(base/'serial-35b.lock').open('w')
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    volume=modal.Volume.from_name('wxu-evolve-agent-runs-20261006',environment_name='zheng-dev')
    first=modal.Sandbox.from_id('sb-vgVxKqWaY20PaHrNRgZ5SO')
    first_state=Path.home()/'wxu-evolve-agent/devbox/state-mvagent-frozen-full-final-20261019-shard0.json'
    old_second=modal.Sandbox.from_id('sb-Y0XVuj0BJZZs6VARWeEcBg')
    child=None
    def stop(signum,frame):
        if child is not None and child.poll() is None: child.terminate()
        raise InterruptedError('Serial continuation owner stopped')
    signal.signal(signal.SIGTERM,stop)
    signal.signal(signal.SIGINT,stop)
    try:
        while True:
            progress=json.loads(b''.join(volume.read_file('devbox/frozen_full_final_20261019/shard0/progress.json')))
            if ready(progress,None if first_state.exists() else first.poll()): break
            print('WAIT_FIRST_POOL_RELEASE',progress['phase'],progress['models'].get('35B-A3B'),flush=True)
            time.sleep(45)
        assert old_second.poll() is not None, 'Never overlap the withdrawn eight-GPU pool'
        state=Path.home()/'wxu-evolve-agent/devbox/state-mvagent-frozen-full-recovery-20261019-shard1.json'
        assert not state.exists(), 'An existing owner must be inspected'
        # Resume the original frozen source, including all completed records and partial attempts.
        source=Path('/tmp/mvagent-frozen-full-recovery-20261019/source/scripts/run_full_mvagent.py')
        with (base/'serial-35b-worker.log').open('a') as log:
            child=subprocess.Popen([sys.executable,str(source),'host','--shard','1'],stdout=log,stderr=subprocess.STDOUT)
            print('ONLY_POOL_STARTED',child.pid,flush=True)
            assert child.wait()==0,'Remaining partition did not complete'
        for shard,root in [(0,'frozen_full_final_20261019'),(1,'frozen_full_recovery_20261019')]:
            progress=json.loads(b''.join(volume.read_file(f'devbox/{root}/shard{shard}/progress.json')))
            assert progress['phase']=='completed',progress
        sys.path.insert(0,str(Path.home()/'wxu-evolve-agent/devbox'))
        import frozen_full_final_cpu as cpu
        with cpu.app.run(environment_name='zheng-dev'):
            rc,out,err=cpu.job.remote('python scripts/run_full_mvagent.py analyze')
        print(out,err,flush=True)
        assert rc==0,rc
        print('ALL_MODELS_COMPLETED',flush=True)
    finally:
        if child is not None and child.poll() is None:
            child.terminate()
            child.wait()


if __name__=='__main__':
    if sys.argv[1:]==['self-check']:
        assert not ready({'phase':'inference'},None)
        assert not ready({'phase':'completed'},None)
        assert ready({'phase':'completed'},137)
        try: ready({'phase':'failed'},137)
        except AssertionError: pass
        else: raise AssertionError('Failure must not allocate the next pool')
        print('Serial allocation guard passed')
    else:
        assert not sys.argv[1:]
        main()
