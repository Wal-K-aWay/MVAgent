"""On modal-gpu, wait for the current LensWalk run, then retry media failures once."""
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

PRIMARY = 'lenswalk_full_35b_recovery_20261017'
PATCH = 'lenswalk_boundary_fix_20261017'
TARGET = 'lenswalk_full_35b_media_final_20261017'
NAME = 'mvagent-lenswalk-media-final-35b-20261017'


def primary_finished(phase):
    if phase in {'failed', 'interrupted'}:
        raise RuntimeError(f'Primary run is {phase}; investigate before any new GPU submission')
    return phase in {'completed', 'completed_with_errors'}


def main():
    import modal
    here = Path.home()/'wxu-evolve-agent/devbox'
    lock = (here/f'watch-{TARGET}.chain.lock').open('w')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    (here/f'watch-{TARGET}.pid').write_text(str(os.getpid()))
    volume = modal.Volume.from_name('wxu-evolve-agent-runs-20261006', environment_name='zheng-dev')
    def read(path):
        return json.loads(b''.join(volume.read_file(path)))
    last_log = 0
    while True:
        state = read(f'devbox/{PRIMARY}/progress.json')
        if primary_finished(state['phase']):
            break
        if time.monotonic()-last_log > 900:
            print(datetime.now(timezone.utc).isoformat(), json.dumps(dict(
                action='waiting_primary', completed=state.get('completed'), phase=state['phase'])), flush=True)
            last_log = time.monotonic()
        time.sleep(60)
    command = shlex.join(['python', f'/runs/devbox/{PATCH}/frozen_repo/eval/external_methods/recover_lenswalk.py',
        '--previous', f'/runs/devbox/{PRIMARY}', '--output', f'/runs/devbox/{TARGET}'])
    subprocess.run([str(Path.home()/'.local/bin/modal'), 'run', '--env', 'zheng-dev',
        'cpujob.py', '--b64', base64.b64encode(command.encode()).decode()], cwd=here, check=True)
    prepared = read(f'devbox/{TARGET}/progress.json')
    if not prepared['remaining']:
        assert prepared['phase'] in {'completed', 'completed_with_errors'}
        print('No media failures remain; no GPU requested', flush=True)
        return
    assert prepared['phase'] == 'prepared'
    print('Media-only retry prepared', prepared, flush=True)
    os.execv(sys.executable, [sys.executable, '-u', str(here/'watch_full_mvagent.py'),
        '--devbox-name', NAME, '--tag', TARGET,
        '--driver', f'/runs/devbox/{TARGET}/frozen_repo/eval/external_methods/lenswalk_full.py'])


if __name__ == '__main__':
    main()
