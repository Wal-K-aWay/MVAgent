"""One-time handoff: suspend the old dispatcher, finish its independent clients, save outcomes.

The original driver has no drain signal. Only its parent is suspended; already
launched clients and model servers keep running with their original question budget.
Unfinished media preparation can restart, but a started inference is never retried.
"""
import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import signal
import sys
import tarfile
import time


def read(path):
    return json.loads(Path(path).read_text())


def process(pid):
    try:
        fields = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
        return dict(state=fields[0], started_epoch=time.time()-(time.monotonic()-int(fields[19])/os.sysconf('SC_CLK_TCK')))
    except FileNotFoundError:
        return None


def main(output, method):
    assert method in ('lenswalk', 'rsi')
    question_timeout = 1800 if method == 'lenswalk' else 7200
    driver = output/'frozen_repo/eval/external_methods/lenswalk_full.py'
    sys.path[:0] = [str(driver.parent), str(driver.parents[2]/'src'), str(driver.parents[2])]
    spec = importlib.util.spec_from_file_location('frozen_drain_driver', driver)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    from common import write, sha256
    inspect = importlib.import_module(method+'_outcome').inspect
    from skill_evolution.infra.benchmarks.catalog import load_multibench_records
    assert read(output/'manifest.json')['driver_sha256'] == sha256(driver)
    snapshot_path = output/'handoff_snapshot.json'
    if snapshot_path.exists():
        snapshot = read(snapshot_path)
        pid = snapshot['driver_pid']
        assert process(pid) is not None and process(pid)['state'] in ('T', 't')
    else:
        pid = int(Path('/work/jobs/'+output.name+'.pid').read_text())
        assert b'lenswalk_full.py' in Path(f'/proc/{pid}/cmdline').read_bytes()
        os.kill(pid, signal.SIGSTOP)
        try:
            deadline = time.monotonic()+10
            while process(pid)['state'] not in ('T', 't'):
                assert time.monotonic()<deadline
                time.sleep(.05)
            progress = read(output/'progress.json')
            assert progress['phase']=='inference'
            clients = {}
            for path in Path('/proc').glob('[0-9]*/cmdline'):
                try:
                    argv = [part.decode() for part in path.read_bytes().split(b'\0') if part]
                except (FileNotFoundError, ProcessLookupError):
                    continue
                if len(argv)<2 or not argv[1].endswith('/'+method+'.py') or '--output' not in argv:
                    continue
                attempt = Path(argv[argv.index('--output')+1])
                if output/method not in attempt.parents:
                    continue
                child = int(path.parent.name)
                clients[attempt.parent.name] = dict(pid=child, attempt=str(attempt), **process(child))
            snapshot = dict(driver_pid=pid, progress=progress, clients=clients,
                            frozen_at=module.now(), old_records={p.name:sha256(p) for p in (output/'records').glob('*.json')})
            assert set(clients) <= {a['sample_id'].replace(':', '_') for a in progress['active'].values()}, 'Unrecorded active client; inspect before handing off'
            write(snapshot_path, snapshot)
        except BaseException:
            os.kill(pid, signal.SIGCONT)
            raise
    print(json.dumps(dict(event='dispatcher_suspended', clients=snapshot['clients'],
                          active=snapshot['progress']['active'])), flush=True)
    client_results = {}
    timed_out_keys = set()
    while len(client_results)<len(snapshot['clients']):
        for key, client in snapshot['clients'].items():
            if key in client_results:
                continue
            info = process(client['pid'])
            assert info is not None, 'Paused parent cannot reap its child; inspect before recovery'
            timed_out = time.time()-client['started_epoch']>question_timeout and info['state']!='Z'
            if timed_out:
                timed_out_keys.add(key)
                os.killpg(client['pid'], signal.SIGTERM)
                time.sleep(2)
                if process(client['pid'])['state']!='Z':
                    os.killpg(client['pid'], signal.SIGKILL)
                continue
            if info['state']=='Z':
                # gVisor exposes a zero exit-code field even for failures; only the paused parent can waitpid.
                client_results[key] = dict(returncode=None, question_timeout=key in timed_out_keys,
                                           observed_finished_epoch=time.time())
                print(json.dumps(dict(event='client_finished', key=key, **client_results[key])), flush=True)
        time.sleep(1)
    active = snapshot['progress']['active']
    ids = [item['sample_id'] for item in active.values()]
    records = load_multibench_records('/assets', ids)
    kept, preparation_only = [], []
    for item in active.values():
        sid = item['sample_id']; key = sid.replace(':', '_')
        destination = output/'records'/(key+'.json')
        if destination.exists():
            continue
        directory = output/method/key
        attempts = sorted(directory.glob('attempt-*')) if directory.exists() else []
        folders = [p for p in attempts if p.is_dir()]
        archives = [p for p in attempts if p.name.endswith('.tar')]
        archives += list((output/'raw').glob(key+'-attempt-*.tar'))
        if not folders and archives:
            archive = max(archives, key=lambda p:p.stat().st_mtime)
            directory.mkdir(exist_ok=True)
            with tarfile.open(archive) as stream:
                stream.extractall(directory, filter='tar')
            folders = list(directory.glob('attempt-*'))
        if not folders:
            preparation_only.append(sid)
            continue
        attempt = max(folders, key=lambda p:p.name)
        started = read(attempt/'started.json')
        if not (attempt/'requests.jsonl').exists() and not (attempt/'result.json').exists() and key not in snapshot['clients']:
            assert item['phase']=='preparing_media' or not (attempt/'effective_config.json').exists()
            preparation_only.append(sid)
            continue
        card = read(attempt/'service_card.json') if (attempt/'service_card.json').exists() else {'worker': started['worker']}
        outcome = inspect(attempt, card)
        result = read(attempt/'result.json') if (attempt/'result.json').exists() else None
        client = snapshot['clients'].get(key)
        completion = client_results.get(key, {})
        start_epoch = client['started_epoch'] if client else datetime.fromisoformat(item['started_at']).timestamp()
        finish_epoch = (attempt/'result.json').stat().st_mtime if result else completion.get('observed_finished_epoch', time.time())
        elapsed = max(0, finish_epoch-start_epoch)
        outcome.update(returncode=completion.get('returncode'), seconds=elapsed,
            question_timeout=completion.get('question_timeout', False), sample_id=sid,
            dataset=records[sid].dataset, task=records[sid].native_task, attempt=str(attempt),
            prepared_seconds=max(0, start_epoch-datetime.fromisoformat(started['started_at']).timestamp()),
            finished_at=datetime.fromtimestamp(finish_epoch, timezone.utc).isoformat(), worker=card['worker'],
            handoff_timing='Client process start to result-file completion; no additional inference; failure uses 1s polling',
            handoff_returncode='Unavailable to non-parent; raw result/request audit determines outcome as before',
            adapter_seconds=result.get('seconds') if result else None)
        if outcome['question_timeout']:
            outcome['infrastructure_error']=True
        outcome['score'] = None if outcome['infrastructure_error'] else module.closed_score(records[sid], outcome['answer'])
        archive_started = time.monotonic()
        outcome['raw_archive'] = (module.archive_attempt(attempt, compress=False) if method == 'rsi'
                                  else module.archive_attempt(attempt))
        archive = Path(outcome['raw_archive']['path'])
        target = output/'raw'/(key+'-'+archive.name)
        archive.replace(target)
        outcome['raw_archive']['path'] = str(target)
        outcome['archive_seconds'] = time.monotonic()-archive_started
        write(destination, outcome)
        kept.append(sid)
    for name, digest in snapshot['old_records'].items():
        assert sha256(output/'records'/name)==digest
    write(output/'handoff_drained.json', dict(preserved_inflight=kept, preparation_only=preparation_only,
          original_records_unchanged=len(snapshot['old_records']), finished_at=module.now(),
          inference_retries=0, dispatcher_pid=pid))
    os.kill(pid, signal.SIGKILL)
    print(json.dumps(read(output/'handoff_drained.json')), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--method', choices=['lenswalk', 'rsi'], required=True)
    args = parser.parse_args()
    main(args.output, args.method)
