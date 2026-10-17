"""Freeze a media fix and, after the primary run ends, retry only media failures."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import shutil

from common import sha256, write
from lenswalk_full import ADAPTERS, EXPECTED, media_key, now, read

PATCH_FILES = ('prepare.py', 'lenswalk_full.py', 'recover_lenswalk.py', 'test_lenswalk_recovery.py',
               'test_native_concat.py', 'test_color_boundary.py', 'test_contracts.py',
               'lenswalk_outcome.py', 'test_lenswalk_full.py', 'recover_lenswalk_stopped.py',
               'test_lenswalk_stopped.py')


def media_failure(row):
    return (row['infrastructure_error'] and row['terminal'] == 'execution_error'
            and row.get('calls') == 0 and row.get('seconds') == 0)


def inherit_record(path):
    row = read(path)
    evidence = dict(path=str(path), sha256=sha256(path), raw_archive=row['raw_archive'])
    return row['sample_id'], row, evidence


def freeze(previous, output):
    frozen = output/'frozen_repo'
    assert not frozen.exists(), 'Never change a published patch snapshot'
    shutil.copytree(previous/'frozen_repo', frozen, ignore=shutil.ignore_patterns('__pycache__'))
    for name in PATCH_FILES:
        shutil.copy2(ADAPTERS/name, frozen/'eval/external_methods'/name)
    commit = (ADAPTERS.parents[1]/'.git/HEAD').read_text().strip()
    (frozen/'.git').mkdir(exist_ok=True)
    (frozen/'.git/HEAD').write_text(commit+'\n')
    write(output/'patch_manifest.json', dict(created_at=now(), commit=commit,
        previous=str(previous), driver_sha256=sha256(frozen/'eval/external_methods/lenswalk_full.py'),
        source_hashes={str(p.relative_to(frozen)):sha256(p) for p in frozen.rglob('*')
                       if p.is_file() and '__pycache__' not in p.parts}))
    print('Frozen media patch', str(frozen), commit, flush=True)


def recover(previous, output):
    assert not output.exists(), 'Never overwrite a recovery or the original run'
    phase = read(previous/'progress.json')['phase']
    assert phase in {'completed', 'completed_with_errors'}, 'Wait for the primary run and Judge'
    source = ADAPTERS.parents[1]
    identity = read(source.parent/'patch_manifest.json')
    assert identity['driver_sha256'] == sha256(ADAPTERS/'lenswalk_full.py')
    output.mkdir(parents=True)
    (output/'frozen_repo').symlink_to(source)
    for name in ('media_cache', 'prepared/items', 'lenswalk', 'episodes'):
        (output/name).mkdir(parents=True, exist_ok=True)
    for name in ('samples.json', 'prepared/private_labels.json'):
        shutil.copy2(previous/name, output/name)
    (output/'client_environment.tar.gz').symlink_to(previous/'client_environment.tar.gz')
    paths = list((previous/'lenswalk').glob('*/record.json'))
    with ThreadPoolExecutor(max_workers=16) as pool:
        loaded = list(pool.map(inherit_record, paths))
    ids = read(output/'samples.json')
    rows = {sid:row for sid,row,_ in loaded}
    assert len(rows) == len(ids) == sum(EXPECTED.values()) == len(set(ids))
    assert set(rows) == set(ids)
    pending = [sid for sid in ids if media_failure(rows[sid])]
    inherited = {sid:evidence for sid,row,evidence in loaded if sid not in pending}
    # One index keeps inherited records immutable without thousands of duplicate directories.
    write(output/'inherited_records.json', {sid.replace(':','_'):row for sid,row in rows.items()
                                           if sid not in pending})
    labels = read(previous/'prepared/private_labels.json')
    for sid in pending:
        key = media_key(labels[sid]['sample']['videos'])
        cache = previous/'media_cache'/f'{key}.json'
        if cache.exists():
            shutil.copy2(cache, output/'media_cache'/cache.name)
    manifest = read(previous/'manifest.json')
    assert sha256(output/'samples.json') == manifest['samples_sha256']
    write(output/'recovery_manifest.json', dict(previous=str(previous), created_at=now(),
        inherited=inherited, retry_failures=pending, pending=pending,
        retained_infrastructure_failures=[sid for sid in inherited if rows[sid]['infrastructure_error']],
        original_progress_sha256=sha256(previous/'progress.json'),
        original_manifest_sha256=sha256(previous/'manifest.json')))
    manifest.update(created_at=now(), recovery_from=str(previous), recovery_order=pending,
        source_snapshot=str(source), recovery_commit=identity['commit'],
        driver_sha256=identity['driver_sha256'], source_hashes=identity['source_hashes'])
    write(output/'manifest.json', manifest)
    if not pending:
        shutil.copy2(previous/'summary.json', output/'summary.json')
    write(output/'progress.json', dict(phase='prepared' if pending else phase, expected=len(ids),
        completed=len(inherited), remaining=len(pending), updated_at=now()))
    print(dict(inherited=len(inherited), retry_media_failures=len(pending)), flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--previous', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--freeze', action='store_true')
    args = p.parse_args()
    (freeze if args.freeze else recover)(args.previous, args.output)
