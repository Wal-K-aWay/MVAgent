"""One-shot completion on modal-gpu; never submit or retry Actor jobs."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import modal

DEVBOX = Path.home() / 'wxu-evolve-agent/devbox'
sys.path.insert(0, str(DEVBOX))
import cpujob

RUNS = {
    '27B': ('pro9_ffmpeg_27b_20261016', 'sb-e6MsCkfOuVYAXDx09OccDo'),
    '35B-A3B': ('pro9_ffmpeg_35b_20261016', 'sb-JO6rzPmKd5Te3NUz4jtJLp'),
}


def log(model, phase):
    print(datetime.now(timezone.utc).isoformat(), model, phase, flush=True)


def release_when_done(item):
    model, (name, sandbox_id) = item
    state = DEVBOX / f'state-mvagent-{name.replace("_", "-")}.json'
    assert json.loads(state.read_text())['sandbox_id'] == sandbox_id
    sandbox = modal.Sandbox.from_id(sandbox_id)
    marker = f'/work/jobs/{name}_pipeline.pid'
    # Wait only for the existing job's lifecycle, without polling inference or metrics.
    command = (f'while test -e {marker}; do '
               f'kill -0 "$(cat {marker})" 2>/dev/null || break; sleep 30; done; '
               f'cat /runs/devbox/{name}/pipeline_progress.json')
    log(model, 'waiting for existing pipeline')
    process = sandbox.exec('bash', '-c', command, timeout=8 * 3600)
    output = process.stdout.read()
    assert process.wait() == 0, process.stderr.read()[-500:]
    phase = json.loads(output)['phase']
    # Sandbox termination flushes its mounted Volume before CPU readers start.
    sandbox.terminate(wait=True)
    assert sandbox.poll() is not None
    state.unlink()
    log(model, f'GPU released; pipeline={phase}')
    assert phase == 'judge_completed', (model, phase)
    return model, name


def main():
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(release_when_done, item) for item in RUNS.items()]
        completed = [future.result() for future in futures]
    with cpujob.app.run(environment_name='zheng-dev'):
        for model, name in completed:
            root = f'/runs/devbox/{name}'
            code = root + '/code/experiments/pro9_ffmpeg'
            command = (f'export PRO_MODEL={model}; mkdir -p {root}/analysis; '
                       f'{{ python {code}/evaluate.py && python {code}/judge.py report '
                       f'&& python {code}/finalize.py; }} > {root}/analysis/finalize.log 2>&1')
            rc, _, error = cpujob.job.remote(command)
            assert rc == 0, (model, rc, error[-500:], root + '/analysis/finalize.log')
            log(model, 'scoring and final checks completed')
        root = '/runs/devbox/pro9_ffmpeg_large_20261016'
        rc, _, error = cpujob.job.remote(
            f'mkdir -p {root}/analysis && python {root}/compare_models.py > {root}/analysis/comparison.log 2>&1')
        assert rc == 0, (rc, error[-500:], root + '/analysis/comparison.log')
        log('all', 'comparison completed')


if __name__ == '__main__':
    main()
