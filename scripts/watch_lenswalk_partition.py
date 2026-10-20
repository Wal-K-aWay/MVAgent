"""Run on modal-gpu: own disjoint external-method groups, then merge scored results on CPU."""
import argparse
import base64
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tag', required=True)
    parser.add_argument('--cpu-helper', type=Path, required=True)
    parser.add_argument('--merge-script', default='eval/external_methods/lenswalk_partition.py')
    args = parser.parse_args()
    here = Path.home()/'wxu-evolve-agent/devbox'
    lock = (here/f'watch-{args.tag}.lock').open('w')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    (here/f'watch-{args.tag}.pid').write_text(str(os.getpid()))
    import modal
    volume = modal.Volume.from_name('wxu-evolve-agent-runs-20261006', environment_name='zheng-dev')
    def read(path):
        return json.loads(b''.join(volume.read_file(path)))
    manifest = read('devbox/'+args.tag+'/manifest.json')
    children = []
    for group in manifest['children']:
        tag = Path(group['root']).name
        pidfile = here/f'watch-{tag}.pid'
        if pidfile.exists():
            pid = int(pidfile.read_text())
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                pass
            else:
                assert tag.encode() in Path(f'/proc/{pid}/cmdline').read_bytes()
                children.append((tag, pid))
                continue
        name = 'mvagent-'+tag.replace('_', '-')
        command = [sys.executable, '-u', str(here/'watch_full_mvagent.py'),
                   '--devbox-name', name, '--tag', tag,
                   '--driver', group['root']+'/frozen_repo/eval/external_methods/lenswalk_full.py']
        state = here/('state-'+name+'.json')
        if state.exists():
            sandbox = modal.Sandbox.from_id(json.loads(state.read_text())['sandbox_id'])
            if sandbox.poll() is None:
                command.append('--start-existing')
        with (here/f'watch-{tag}.log').open('a') as log:
            child = subprocess.Popen(command,
                    cwd=here, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        children.append((tag, child.pid))
    while True:
        states = [read('devbox/'+tag+'/progress.json') for tag, _ in children]
        print(datetime.now(timezone.utc).isoformat(), json.dumps([
            dict(tag=tag, pid=pid, phase=state['phase'], completed=state['completed'], expected=state['expected'])
            for (tag, pid), state in zip(children, states)]), flush=True)
        assert all(state['phase'] != 'failed' for state in states), 'Inspect saved failure; do not automatically repeat outcomes'
        if all(state['phase'] in ('completed', 'completed_with_errors') for state in states):
            break
        for (tag, pid), state in zip(children, states):
            if state['phase'] not in ('completed', 'completed_with_errors'):
                os.kill(pid, 0)
                assert tag.encode() in Path(f'/proc/{pid}/cmdline').read_bytes()
        time.sleep(60)
    # Each child controller releases its GPU allocation when scoring completes.
    command = 'set -e; cd /repo; python '+shlex.quote(args.merge_script)+' merge --output '+shlex.quote('/runs/devbox/'+args.tag)
    subprocess.run([str(Path.home()/'.local/bin/modal'), 'run', '--env', 'zheng-dev', str(args.cpu_helper),
                    '--b64', base64.b64encode(command.encode()).decode()], check=True, cwd=here)
    assert read('devbox/'+args.tag+'/progress.json')['phase'] in ('completed', 'completed_with_errors')
    print('Final combined result verified; 5321 unique questions', flush=True)


if __name__ == '__main__':
    main()
