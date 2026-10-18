"""Devbox-only completion hook for the isolated temporary-media experiment."""
import base64
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import time

import modal

PREFIX = 'devbox/external_temp_media_20261018'
TERMINAL = {'completed', 'completed_with_errors', 'failed'}


def ready(states):
    return len(states) == 2 and all(s.get('phase') in TERMINAL for s in states)


def main():
    volume = modal.Volume.from_name('wxu-evolve-agent-runs-20261006', environment_name='zheng-dev')
    def read(name):
        return json.loads(b''.join(volume.read_file(PREFIX+'/'+name)))
    deadline = time.monotonic()+3*3600
    while True:
        states = [read(name) for name in ('progress.json', 'long_progress.json')]
        if ready(states):
            break
        if time.monotonic() >= deadline:
            raise TimeoutError(f'Existing trials did not reach terminal states: {states}')
        print(datetime.now(timezone.utc).isoformat(), [s['phase'] for s in states], flush=True)
        time.sleep(60)
    # The analysis source was already executed and saved in this experiment's volume.
    root = '/runs/'+PREFIX
    command = (f'set -e; export PYTHONDONTWRITEBYTECODE=1; '
               f'export PYTHONPATH={root}/frozen_repo/eval/external_methods:{root}/frozen_repo/src; '
               f'python {root}/analysis/analysis_source.py')
    started = datetime.now(timezone.utc).isoformat()
    subprocess.run([str(Path.home()/'.local/bin/modal'), 'run', '--env', 'zheng-dev', 'cpujob.py',
                    '--b64', base64.b64encode(command.encode()).decode()],
                   cwd=Path.home()/'wxu-evolve-agent/devbox', check=True)
    # cpujob's CLI exit status alone does not propagate the inner command status.
    summary = read('analysis/summary.json')
    assert summary['at'] > started, 'Final analysis did not persist a fresh result'
    print('Final summary persisted:', summary['at'], flush=True)


if __name__ == '__main__':
    assert ready([{'phase':'completed'}, {'phase':'failed'}])
    assert not ready([{'phase':'completed'}, {'phase':'preparing'}])
    assert not ready([])
    main()
