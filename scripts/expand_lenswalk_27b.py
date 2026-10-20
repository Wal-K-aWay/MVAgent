"""Run once on modal-gpu: drain 27B, preserve outcomes, start two disjoint eight-H100 groups."""
import asyncio
import base64
import fcntl
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import modal

BASE = Path('/tmp/lenswalk-27b-parallel-20261020')
HERE = Path.home()/'wxu-evolve-agent/devbox'
OLD = 'lenswalk_full_27b_20261019'
NEW = 'lenswalk_27b_parallel_20261020'


def main():
    lock = (BASE/'transition.lock').open('w')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    volume = modal.Volume.from_name('wxu-evolve-agent-runs-20261006', environment_name='zheng-dev')
    def read(name): return json.loads(b''.join(volume.read_file('devbox/'+name)))
    def cpu(command):
        subprocess.run([str(Path.home()/'.local/bin/modal'), 'run', '--env', 'zheng-dev', str(BASE/'cpu.py'),
                        '--b64', base64.b64encode(('set -e; '+command).encode()).decode()], check=True)
    def execute(box, code, *args, timeout=120):
        process = box.exec('python', '-c', code, *args, timeout=timeout)
        for line in process.stdout: print(line, end='', flush=True)
        print(process.stderr.read(), flush=True)
        assert process.wait() == 0, 'Keep old execution suspended and inspect the saved failure'
    assert read(OLD+'/manifest.json')['model'] == '27B'
    assert not (BASE/'master.pid').exists(), 'Expansion already launched'
    deadline = time.monotonic()+900
    while '\nrc 0\n' not in (BASE/'checks.log').read_text():
        assert '\nrc 1\n' not in (BASE/'checks.log').read_text(), 'CPU check failed'
        assert time.monotonic() < deadline, 'CPU checks did not finish'
        time.sleep(10)
    print('CPU_CHECKS_PASSED', flush=True)
    state = HERE/'state-mvagent-lenswalk-27b-parallel-20261020-shard1.json'
    extra = modal.Sandbox.from_id(json.loads(state.read_text())['sandbox_id'])
    async def ready():
        try:
            await asyncio.wait_for(extra._get_task_id.aio(raise_if_task_complete=True), 5)
            return True
        except asyncio.TimeoutError:
            return False
    # Keep the original evaluation advancing while the extra allocation is queued.
    while not asyncio.run(ready()):
        assert extra.poll() is None, 'Additional allocation ended before handoff'
        print('WAIT_EXTRA_GPU_OLD_EVALUATION_CONTINUES', flush=True)
        time.sleep(30)
    execute(extra, "import subprocess; x=subprocess.check_output(['nvidia-smi','--query-gpu=name','--format=csv,noheader'],text=True).splitlines(); assert len(x)==8 and all('H100' in n for n in x); print('EXTRA_8_H100_READY')")
    old_state = json.loads((HERE/'state-mvagent-lenswalk-27b-20261019.json').read_text())
    old = modal.Sandbox.from_id(old_state['sandbox_id'])
    assert old.poll() is None
    pidfile = HERE/f'watch-{OLD}.pid'; pid = int(pidfile.read_text())
    assert OLD.encode() in Path(f'/proc/{pid}/cmdline').read_bytes()
    os.kill(pid, signal.SIGSTOP)
    print('OLD_WATCHER_SUSPENDED', pid, old.object_id, flush=True)
    execute(old, (BASE/'repo/eval/external_methods/drain_lenswalk.py').read_text(),
            '--output', '/runs/devbox/'+OLD, timeout=3600)
    execute(old, "import modal;modal.Volume.from_name('wxu-evolve-agent-runs-20261006',environment_name='zheng-dev').commit();print('HANDOFF_COMMITTED')")
    cpu("python - <<'PY'\n"
        "import sys,json;from pathlib import Path\n"
        "sys.path.insert(0,'/repo/eval/external_methods');from common import sha256,write\n"
        f"r=Path('/runs/devbox/{OLD}');read=lambda p:json.loads(p.read_text())\n"
        "s=read(r/'handoff_snapshot.json');d=read(r/'handoff_drained.json')\n"
        "for name,h in s['old_records'].items():assert sha256(r/'records'/name)==h\n"
        "for sid in d['preserved_inflight']:\n"
        " row=read(r/'records'/(sid.replace(':','_')+'.json'));a=row['raw_archive'];assert sha256(a['path'])==a['sha256']\n"
        "n=len(list((r/'records').glob('*.json')));assert n==len(s['old_records'])+len(d['preserved_inflight'])\n"
        "write(r/'handoff_persisted.json',dict(records=n,preserved_inflight=d['preserved_inflight'],original_unchanged=len(s['old_records']),inference_retries=0))\n"
        "print('PERSISTED',n)\nPY")
    persisted = read(OLD+'/handoff_persisted.json')
    old.terminate()
    while old.poll() is None: time.sleep(1)
    assert OLD.encode() in Path(f'/proc/{pid}/cmdline').read_bytes()
    os.kill(pid, signal.SIGKILL)
    pidfile.unlink()
    receipt = dict(sandbox_id=old.object_id, sandbox_exit_code=old.poll(), host_pid=pid,
                   retired_for=NEW, stopped_epoch=time.time(), persisted_records=persisted['records'])
    with volume.batch_upload(force=True) as batch:
        batch.put_file(io.BytesIO(json.dumps(receipt).encode()), 'devbox/'+OLD+'/SCHEDULING_STOPPED.json')
    print('OLD_EXECUTOR_STOPPED', json.dumps(receipt), flush=True)
    cpu(f'python eval/external_methods/lenswalk_partition.py initialize --previous /runs/devbox/{OLD} --output /runs/devbox/{NEW}')
    assert read(NEW+'/progress.json')['phase'] == 'prepared'
    manifest = read(NEW+'/manifest.json'); assert manifest['model'] == '27B'
    assert sum(c['inherited'] for c in manifest['children']) == persisted['records']
    with (BASE/'controller.log').open('a') as log:
        master = subprocess.Popen([sys.executable, '-u', str(BASE/'repo/scripts/watch_lenswalk_partition.py'),
                  '--tag', NEW, '--cpu-helper', str(BASE/'cpu.py')], cwd=HERE,
                  stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    (BASE/'master.pid').write_text(str(master.pid))
    print('TWO_GROUP_MASTER_STARTED', master.pid, flush=True)


if __name__ == '__main__':
    main()
