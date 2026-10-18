"""Resume paused external evaluations using per-question local media; keep original outcomes."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import shutil

from common import sha256, write
from lenswalk_full import ADAPTERS, EXPECTED, now, read


def patch_driver(source):
    changes = [
        ('import argparse\n', 'import argparse\nfrom contextlib import ExitStack\nfrom temporary_media import temporary_item\n'),
        ("    media_locks={", "    media_gate=threading.Semaphore(2)\n    media_locks={"),
        ('prep_started=time.monotonic();prep_seconds=0;started=None;client=None;restart_needed=False',
         'prep_started=time.monotonic();prep_seconds=0;started=None;client=None;restart_needed=False;media=ExitStack()'),
        ('                    item=prepare_item(output,record,media_locks[media_key(record.sample.videos)])',
         '                    with media_gate:\n'
         '                        item=media.enter_context(temporary_item(prepare_item,record,attempt,media_locks[media_key(record.sample.videos)]))'),
        ('                finally:\n                    stop(client)\n',
         '                finally:\n                    stop(client)\n                    media.close()\n'),
        ('            validate_card(card)\n',
         "            validate_card(card)\n"
         "            expected=read(SOURCE.parent/'expected_service.json')\n"
         "            assert card['execution']==expected['execution'] and card['weights_manifest']==expected['weights_manifest']\n"),
        ("    assert manifest['driver_sha256']==sha256(Path(__file__))\n",
         "    assert manifest['driver_sha256']==sha256(Path(__file__))\n"
         "    assert sha256(ADAPTERS/'temporary_media.py')==manifest['source_hashes']['eval/external_methods/temporary_media.py']\n"),
    ]
    for before, after in changes:
        assert source.count(before) == 1, f'Unexpected frozen driver: {before!r}'
        source = source.replace(before, after)
    compile(source, '<patched frozen driver>', 'exec')
    return source


def load_rows(previous, method):
    bulk = previous/'inherited_records.json'
    rows = {r['sample_id']:r for r in read(bulk).values()}
    bulk_sha = sha256(bulk)
    evidence = {sid:dict(path=str(bulk), sha256=bulk_sha) for sid in rows}
    def one(path):
        row = read(path)
        return row['sample_id'], row, dict(path=str(path), sha256=sha256(path))
    with ThreadPoolExecutor(max_workers=16) as pool:
        for sid, row, source in pool.map(one, sorted((previous/method).glob('*/record.json'))):
            rows[sid] = row
            evidence[sid] = source
    return rows, evidence


def recover(previous, output, method):
    assert not output.exists(), 'Never overwrite an old run'
    assert (previous/'USER_PAUSED.json').is_file(), 'This entrypoint resumes the explicitly paused batch'
    original = read(previous/'manifest.json')
    progress = read(previous/'progress.json')
    assert original.get('method', 'lenswalk') == method
    ids = read(previous/'samples.json')
    assert len(ids) == len(set(ids)) == sum(EXPECTED.values())
    assert sha256(previous/'samples.json') == original['samples_sha256']
    rows, evidence = load_rows(previous, method)
    assert len(rows) == progress['completed'] and set(rows) <= set(ids)
    inherited = {sid:row for sid,row in rows.items() if not row['infrastructure_error']}
    pending = [sid for sid in ids if sid not in inherited]
    # Preserve complete but uncommitted attempts for inspection; never silently overwrite them.
    unfinished_attempts = [str(p) for p in (previous/method).glob('*/attempt-*/result.json')
                           if read(p)['sample_id'] not in rows]
    assert not unfinished_attempts, f'Complete attempts need recovery first: {unfinished_attempts}'

    output.mkdir(parents=True)
    frozen = output/'frozen_repo'
    shutil.copytree(previous/'frozen_repo', frozen, ignore=shutil.ignore_patterns('__pycache__'))
    driver = frozen/'eval/external_methods/lenswalk_full.py'
    driver.write_text(patch_driver(driver.read_text()))
    names = ('temporary_media.py', 'recover_temp_media.py', 'test_temporary_media.py')
    for name in names:
        shutil.copy2(ADAPTERS/name, frozen/'eval/external_methods'/name)
    commit = (ADAPTERS.parents[1]/'.git/HEAD').read_text().strip()
    (frozen/'.git/HEAD').write_text(commit+'\n')
    files = [p for p in frozen.rglob('*') if p.is_file() and '__pycache__' not in p.parts]
    with ThreadPoolExecutor(max_workers=16) as pool:
        hashes = dict(zip((str(p.relative_to(frozen)) for p in files), pool.map(sha256,files)))
    allowed = {'eval/external_methods/'+name for name in names} | {'.git/HEAD', 'eval/external_methods/lenswalk_full.py'}
    assert all(hashes.get(name)==digest for name,digest in original['source_hashes'].items() if name not in allowed)
    for name in ('samples.json', 'prepared/private_labels.json'):
        (output/name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(previous/name, output/name)
    client = 'client_environment.json' if method=='rsi' else 'client_environment.tar.gz'
    (output/client).symlink_to((previous/client).resolve())
    for name in (method, 'episodes'):
        (output/name).mkdir()
    card = next(iter(read(Path(progress['episode'])/'pool_verification.json').values()))
    write(output/'expected_service.json', {k:card[k] for k in ('execution','weights_manifest')})
    write(output/'inherited_records.json', {sid.replace(':','_'):r for sid,r in inherited.items()})
    write(output/'manifest.json', dict(original, created_at=now(), recovery_from=str(previous),
          recovery_order=pending, recovery_commit=commit, source_snapshot=str(frozen),
          driver_sha256=hashes['eval/external_methods/lenswalk_full.py'], source_hashes=hashes,
          media_storage='Per-question local temporary directory; delete after client stops; no persistent media cache',
          simultaneous_media_preparations=2))
    write(output/'recovery_manifest.json', dict(created_at=now(), previous=str(previous),
          original_progress_sha256=sha256(previous/'progress.json'), original_manifest_sha256=sha256(previous/'manifest.json'),
          inherited={sid:evidence[sid] for sid in inherited},
          retry_failures=[sid for sid in ids if sid in rows and rows[sid]['infrastructure_error']],
          previously_unfinished=[sid for sid in ids if sid not in rows], pending=pending,
          changed_existing_source_files=['eval/external_methods/lenswalk_full.py', '.git/HEAD'],
          original_source_files_preserved=len(set(original['source_hashes'])-allowed)))
    write(output/'progress.json', dict(phase='prepared', expected=len(ids), completed=len(inherited),
          remaining=len(pending), updated_at=now()))
    unique = {v['path']:v['sha256'] for v in evidence.values()}
    with ThreadPoolExecutor(max_workers=16) as pool:
        assert all(pool.map(lambda pair:sha256(Path(pair[0]))==pair[1], unique.items()))
    print(dict(method=method, inherited=len(inherited), remaining=len(pending), output=str(output), commit=commit), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--previous', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--method', choices=['rsi','lenswalk'], required=True)
    args = parser.parse_args()
    recover(args.previous, args.output, args.method)
