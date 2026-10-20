"""Run on modal-gpu: preserve two live 27B groups and expand each method to four."""
import asyncio
import base64
from concurrent.futures import ThreadPoolExecutor
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

import modal

BASE = Path('/tmp/external27-expand-32gpu-20261020')
HERE = Path.home()/'wxu-evolve-agent/devbox'
PREVIOUS = {'lenswalk': 'lenswalk_27b_parallel_20261020', 'rsi': 'rsi_27b_16gpu_20261020'}


def execute(sandbox, code, *args, timeout=120):
    proc = sandbox.exec('python', '-c', code, *args, timeout=timeout)
    for line in proc.stdout:
        print(sandbox.object_id, line.rstrip(), flush=True)
    error = proc.stderr.read()
    assert proc.wait() == 0, error


def cpu(command):
    subprocess.run([str(Path.home()/'.local/bin/modal'), 'run', '--env', 'zheng-dev', str(BASE/'cpu.py'),
                    '--b64', base64.b64encode(('set -e; '+command).encode()).decode()], check=True)


def state(tag):
    path = HERE/('state-mvagent-'+tag.replace('_', '-')+'.json')
    data = json.loads(path.read_text())
    return path, data, modal.Sandbox.from_id(data['sandbox_id'])


async def ready(sandbox):
    try:
        await asyncio.wait_for(sandbox._get_task_id.aio(raise_if_task_complete=True), 5)
        return True
    except asyncio.TimeoutError:
        return False


def owner(tag):
    path = HERE/f'watch-{tag}.pid'
    pid = int(path.read_text())
    assert tag.encode() in Path(f'/proc/{pid}/cmdline').read_bytes()
    return path, pid


def expand(method):
    previous = PREVIOUS[method]
    new = method+'_27b_32gpu_20261020'
    old = [state(previous+'-shard'+str(i)) for i in (0, 1)]
    extra = [state(new+'-shard'+str(i))[2] for i in (2, 3)]
    while not all(asyncio.run(ready(s)) for s in extra):
        assert all(s.poll() is None for s in extra)
        print(method, 'WAIT_EXTRA_GPU_OLD_WORK_CONTINUES', flush=True)
        time.sleep(30)
    for sandbox in extra:
        execute(sandbox, "import subprocess;x=subprocess.check_output(['nvidia-smi','--query-gpu=name','--format=csv,noheader'],text=True).splitlines();assert len(x)==8 and all('H100' in n for n in x);print('EIGHT_H100_READY')")
    stopped = threading.Event()
    def keep_alive():
        while not stopped.wait(30):
            for sandbox in extra + [item[2] for item in old]:
                assert sandbox.exec('touch', '/work/heartbeat', timeout=30).wait() == 0
    heartbeat = threading.Thread(target=keep_alive, daemon=True)
    heartbeat.start()
    parents = [owner(previous)] + [owner(previous+'-shard'+str(i)) for i in (0, 1)]
    for _, pid in parents:
        os.kill(pid, signal.SIGSTOP)
    print(method, 'OLD_DISPATCH_OWNERS_SUSPENDED', parents, flush=True)
    drain = (BASE/'repo/eval/external_methods/drain_external.py').read_text()
    def one(item):
        index, (_, _, sandbox) = item
        execute(sandbox, drain, '--output', '/runs/devbox/'+previous+'-shard'+str(index),
                '--method', method, timeout=7600)
    # Started clients finish under their original budget; no replacement model request is made.
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(one, enumerate(old)))
    cpu(f'python eval/external_methods/expand_external.py initialize --method {method} '
        f'--previous /runs/devbox/{previous} --output /runs/devbox/{new}')
    finish(method)
    stopped.set()


def finish(method):
    """Finish a committed handoff; an expired idle node needs an allocated replacement."""
    previous = PREVIOUS[method]
    new = method+'_27b_32gpu_20261020'
    assert not (BASE/(method+'-master.pid')).exists(), 'A new owner already exists'
    parents = [owner(previous)] + [owner(previous+'-shard'+str(i)) for i in (0, 1)]
    old = [state(previous+'-shard'+str(i)) for i in (0, 1)]
    volume = modal.Volume.from_name('wxu-evolve-agent-runs-20261006', environment_name='zheng-dev')
    manifest = json.loads(b''.join(volume.read_file('devbox/'+new+'/manifest.json')))
    assert manifest['model'] == '27B' and manifest['total_gpus'] == 32
    cleanup = """
import json,os,signal,time
from pathlib import Path
root=Path(__import__('sys').argv[1]);read=lambda p:json.loads(p.read_text())
d=read(root/'handoff_drained.json');p=read(root/'progress.json')
cards=read(Path(p['episode'])/'pool_verification.json')
pids=[c['worker']['pid'] for c in cards.values()]
for sig in (signal.SIGTERM,signal.SIGKILL):
 for pid in pids:
  cmd=Path('/proc')/str(pid)/'cmdline'
  if cmd.exists() and cmd.read_bytes():
   assert str(root).encode() in cmd.read_bytes()
   try:os.kill(pid,sig)
   except ProcessLookupError:pass
 time.sleep(3)
try:os.killpg(d['dispatcher_pid'],signal.SIGKILL)
except ProcessLookupError:pass
print('OLD_MODELS_STOPPED_DATA_PRESERVED')
"""
    for index, (path, data, sandbox) in enumerate(old):
        target = HERE/('state-mvagent-'+(new+'-shard'+str(index)).replace('_', '-')+'.json')
        if sandbox.poll() is None:
            assert not target.exists()
            execute(sandbox, cleanup, '/runs/devbox/'+previous+'-shard'+str(index))
            target.write_text(json.dumps(data))
        else:
            replacement = state(new+'-shard'+str(index))[2]
            assert replacement.object_id != sandbox.object_id and replacement.poll() is None
            execute(replacement, "import subprocess;x=subprocess.check_output(['nvidia-smi','--query-gpu=name','--format=csv,noheader'],text=True).splitlines();assert len(x)==8 and all('H100' in n for n in x);print('REPLACEMENT_EIGHT_H100_READY')")
        path.unlink()
    for path, pid in parents:
        assert previous.encode() in Path(f'/proc/{pid}/cmdline').read_bytes()
        os.kill(pid, signal.SIGKILL)
        path.unlink()
    with (BASE/(method+'-controller.log')).open('a') as log:
        master = subprocess.Popen([sys.executable, '-u', str(BASE/'repo/scripts/watch_lenswalk_partition.py'),
            '--tag', new, '--cpu-helper', str(BASE/'cpu.py'), '--merge-script', 'eval/external_methods/expand_external.py'],
            cwd=HERE, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    (BASE/(method+'-master.pid')).write_text(str(master.pid))
    print(method, 'FOUR_GROUP_MASTER_STARTED', master.pid, flush=True)


def main():
    lock = (BASE/'expand.lock').open('w')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    assert not list(BASE.glob('*-master.pid')), 'Expansion already launched'
    cpu('python3 -m compileall -q src scripts eval/agent_eval demo.py; '
        'python eval/external_methods/test_expand_external.py')
    print('CPU_CHECKS_PASSED', flush=True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(expand, ('lenswalk', 'rsi')))


if __name__ == '__main__':
    main()
