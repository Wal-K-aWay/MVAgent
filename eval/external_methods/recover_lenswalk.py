"""Freeze a LensWalk recovery run; inherit model outcomes and retry only infrastructure gaps."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import shutil

from common import sha256, write
from lenswalk_full import ADAPTERS, EXPECTED, now, read


def inherit_record(path, output):
    row = read(path)
    if row['infrastructure_error']:
        return row['sample_id'], None
    target = output/'lenswalk'/path.parent.name/'record.json'
    target.parent.mkdir(parents=True)
    shutil.copy2(path, target)
    digest = sha256(path)
    assert sha256(target) == digest
    # Copy the record, not its directory: later CCQA scoring must not write into the old run.
    return row['sample_id'], dict(path=str(path), sha256=digest,
                                  raw_archive=row['raw_archive'])


def recover(previous, output):
    assert not output.exists(), 'Never overwrite a recovery or the original run'
    assert read(previous/'progress.json')['phase'] == 'failed'
    output.mkdir(parents=True)
    frozen = output/'frozen_repo'
    shutil.copytree(previous/'frozen_repo', frozen, ignore=shutil.ignore_patterns('__pycache__'))
    for name in ('prepare.py', 'lenswalk_full.py', 'recover_lenswalk.py', 'test_lenswalk_recovery.py',
                 'test_native_concat.py', 'test_contracts.py'):
        shutil.copy2(ADAPTERS/name, frozen/'eval/external_methods'/name)
    for name in ('media_cache', 'prepared/items', 'lenswalk', 'episodes'):
        (output/name).mkdir(parents=True, exist_ok=True)
    for path in (previous/'media_cache').glob('*.json'):
        shutil.copy2(path, output/'media_cache'/path.name)
    for name in ('samples.json', 'prepared/private_labels.json'):
        shutil.copy2(previous/name, output/name)
    (output/'client_environment.tar.gz').symlink_to(previous/'client_environment.tar.gz')
    paths = list((previous/'lenswalk').glob('*/record.json'))
    with ThreadPoolExecutor(max_workers=16) as pool:
        inherited = dict(pool.map(lambda p: inherit_record(p, output), paths))
    failures = sorted(sid for sid, evidence in inherited.items() if evidence is None)
    inherited = {sid: evidence for sid, evidence in inherited.items() if evidence is not None}
    ids = read(output/'samples.json')
    pending = [sid for sid in ids if sid not in inherited]
    assert len(ids) == sum(EXPECTED.values()) == len(set(ids))
    assert len(inherited)+len(pending) == len(ids)
    manifest = read(previous/'manifest.json')
    assert sha256(output/'samples.json') == manifest['samples_sha256']
    write(output/'recovery_manifest.json', dict(previous=str(previous), created_at=now(),
        inherited=inherited, retry_failures=failures, pending=pending,
        original_progress_sha256=sha256(previous/'progress.json'),
        original_manifest_sha256=sha256(previous/'manifest.json')))
    manifest.update(created_at=now(), recovery_from=str(previous),
        recovery_commit=(ADAPTERS.parents[1]/'.git/HEAD').read_text().strip(),
        driver_sha256=sha256(frozen/'eval/external_methods/lenswalk_full.py'),
        source_hashes={str(p.relative_to(frozen)): sha256(p) for p in frozen.rglob('*')
                       if p.is_file() and '__pycache__' not in p.parts})
    write(output/'manifest.json', manifest)
    write(output/'progress.json', dict(phase='prepared', expected=len(ids),
        completed=len(inherited), remaining=len(pending), updated_at=now()))
    print(dict(inherited=len(inherited), retry_failures=len(failures), pending=len(pending)), flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--previous', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    recover(args.previous, args.output)
