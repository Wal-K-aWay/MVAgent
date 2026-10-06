"""Prepare and sequentially run frozen selector ablations, then fresh confirmation."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

if Path(__file__).name == 'suite.py':
    from controller import ROOT, prepare, file_fingerprint, write_json
else:
    from audit_skill_selector import ROOT, prepare, file_fingerprint, write_json
from selector_methods import METHODS


def suite(out):
    import fcntl
    lock = (out / 'suite.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    manifest = json.loads((out / 'suite_manifest.json').read_text())
    assert file_fingerprint(Path(__file__)) == manifest['suite_sha256']
    plan = [(m, 'dev', 0) for m in METHODS] + [('full_body_t03', 'dev', 1)]

    def execute(method, partition, repeat):
        write_json(out / 'suite_status.json', dict(stage='running', method=method, partition=partition, repeat=repeat))
        subprocess.run([sys.executable, str(out / 'controller.py'), 'run', '--output', str(out),
            '--method', method, '--partition', partition, '--repeat', str(repeat)], check=True)

    try:
        for m, p, r in plan:
            execute(m, p, r)
        reports = {m: json.loads((out / 'dev_full_0' / m / 'summary.json').read_text())['counts'] for m in METHODS}
        base = reports['current']
        def eligible(m):
            r = reports[m]
            return (r['all']['invalid'] == 0 and
                all(r[k]['correct'] >= base[k]['correct'] for k in ('global', 'video')) and
                r['all']['false_abstention'] + r['all']['wrong_card'] <=
                base['all']['false_abstention'] + base['all']['wrong_card'])
        ranked = sorted((m for m in METHODS if m not in ('current', 'full_body_t03')),
            key=lambda m: (not eligible(m), -reports[m]['all']['correct'], METHODS.index(m)))
        finalists = ranked[:2]
        write_json(out / 'finalists.json', dict(finalists=finalists, development=reports,
            eligible={m:eligible(m) for m in METHODS},
            rule='Prefer no role or positive-hit loss; then development agreement; fixed method order for ties. Nonqualifying finalists are diagnostic only. No automatic runtime deployment.'))
        for m in ['current', *finalists]:
            execute(m, 'confirm', 0)
        execute(finalists[0], 'confirm', 1)
        write_json(out / 'suite_status.json', dict(stage='completed', finalists=finalists))
    except Exception as exc:
        write_json(out / 'suite_status.json', dict(stage='failed', error=str(exc)))
        raise
    finally:
        lock.close()


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=['launch', 'run'])
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--cases', type=Path)
    a = p.parse_args(); out = a.output.resolve()
    if a.command == 'run':
        if a.cases is not None:
            p.error('run uses frozen cases; --cases is only accepted by launch')
        suite(out)
    else:
        if a.cases is None:
            p.error('launch requires --cases with a pre-labeled development/confirmation panel')
        prepare(out, a.cases)
        shutil.copyfile(__file__, out / 'suite.py')
        write_json(out / 'suite_manifest.json', dict(suite_sha256=file_fingerprint(out / 'suite.py'),
            methods=METHODS, protocol='All methods frozen before inference. Old221=development; fresh91=confirmation. Labels unchanged after responses.'))
        env = dict(os.environ, MVAGENT_PROJECT_ROOT=str(ROOT), NO_PROXY='127.0.0.1,localhost', no_proxy='127.0.0.1,localhost')
        with (out / 'suite.log').open('a') as log:
            child = subprocess.Popen([sys.executable, str(out / 'suite.py'), 'run', '--output', str(out)],
                env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        write_json(out / 'launch.json', dict(pid=child.pid))
        print(json.dumps(dict(pid=child.pid, output=str(out))))
