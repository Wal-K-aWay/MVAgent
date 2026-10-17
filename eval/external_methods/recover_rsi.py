"""Recover the stopped RSI run, preserving all normal model outcomes and original settings."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import shutil

from common import sha256, write
from lenswalk_full import ADAPTERS, EXPECTED, media_key, now, read

MEDIA_SOURCE = Path('/runs/devbox/lenswalk_full_35b_recovery_20261017')
PATCH_FILES = ('prepare.py', 'lenswalk_full.py', 'recover_rsi.py', 'test_rsi_recovery.py',
               'test_native_concat.py', 'test_color_boundary.py')


def inherit_record(path):
    row = read(path)
    return row['sample_id'], row, dict(path=str(path), sha256=sha256(path), raw_archive=row['raw_archive'])


def recover(previous, output):
    assert not output.exists(), 'Never overwrite a run or recovery'
    progress = read(previous/'progress.json')
    assert progress['phase'] == 'failed', 'Only recover the confirmed stopped batch'
    original = read(previous/'manifest.json')
    assert original['method'] == 'rsi'
    ids = read(previous/'samples.json')
    assert len(ids) == len(set(ids)) == sum(EXPECTED.values())
    assert sha256(previous/'samples.json') == original['samples_sha256']
    paths = sorted((previous/'rsi').glob('*/record.json'))
    with ThreadPoolExecutor(max_workers=16) as pool:
        loaded = list(pool.map(inherit_record, paths))
    rows = {sid:row for sid,row,_ in loaded}
    assert len(rows) == len(loaded) == progress['completed'] and set(rows) <= set(ids)
    inherited = {sid:row for sid,row in rows.items() if not row['infrastructure_error']}
    pending = [sid for sid in ids if sid not in inherited]
    priority = [sid for sid in ('mvu_eval:OR:440', 'crossvid:NC:889') if sid in pending]
    schedule = priority+[sid for sid in pending if sid not in priority]

    output.mkdir(parents=True)
    frozen = output/'frozen_repo'
    shutil.copytree(previous/'frozen_repo', frozen, ignore=shutil.ignore_patterns('__pycache__'))
    for name in PATCH_FILES:
        shutil.copy2(ADAPTERS/name, frozen/'eval/external_methods'/name)
    commit = (ADAPTERS.parents[1]/'.git/HEAD').read_text().strip()
    (frozen/'.git').mkdir(exist_ok=True)
    (frozen/'.git/HEAD').write_text(commit+'\n')
    sources = [p for p in frozen.rglob('*') if p.is_file() and '__pycache__' not in p.parts]
    with ThreadPoolExecutor(max_workers=16) as pool:
        hashes = dict(zip((str(p.relative_to(frozen)) for p in sources), pool.map(sha256,sources)))
    allowed = {f'eval/external_methods/{name}' for name in PATCH_FILES} | {'.git/HEAD'}
    assert all(hashes.get(name)==digest for name,digest in original['source_hashes'].items() if name not in allowed)
    for name in ('samples.json', 'prepared/private_labels.json', 'client_environment.json'):
        destination = output/name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(previous/name, destination)
    for name in ('media_cache', 'prepared/items', 'rsi', 'episodes'):
        (output/name).mkdir(parents=True, exist_ok=True)
    write(output/'inherited_records.json', {sid.replace(':','_'):row for sid,row in inherited.items()})
    labels = read(previous/'prepared/private_labels.json')
    keys = {media_key(labels[sid]['sample']['videos']) for sid in pending}
    def copy_cache(key):
        for source in (previous, MEDIA_SOURCE):
            path = source/'media_cache'/f'{key}.json'
            if not path.is_file():
                continue
            value = read(path)
            assert Path(value['video_path']).is_file() and Path(value['timeline_path']).is_file()
            shutil.copy2(path, output/'media_cache'/path.name)
            return key, dict(source=str(path), sha256=sha256(path))
        return key, None
    with ThreadPoolExecutor(max_workers=16) as pool:
        caches = {key:value for key,value in pool.map(copy_cache, sorted(keys)) if value is not None}
    manifest = dict(original, created_at=now(), recovery_from=str(previous), recovery_order=schedule,
        recovery_commit=commit, source_snapshot=str(frozen), driver_commit=commit,
        driver_sha256=hashes['eval/external_methods/lenswalk_full.py'], source_hashes=hashes)
    assert manifest['method_settings'] == original['method_settings']
    write(output/'manifest.json', manifest)
    write(output/'recovery_manifest.json', dict(created_at=now(), previous=str(previous),
        original_progress_sha256=sha256(previous/'progress.json'), original_manifest_sha256=sha256(previous/'manifest.json'),
        inherited={sid:evidence for sid,_,evidence in loaded if sid in inherited},
        retry_failures=[sid for sid,row in rows.items() if row['infrastructure_error']],
        previously_unfinished=[sid for sid in ids if sid not in rows], pending=schedule,
        cache_sources=caches, preserved_source_files=len(original['source_hashes'])-len(set(original['source_hashes']) & allowed)))
    write(output/'progress.json', dict(phase='prepared', method='rsi', expected=len(ids),
        completed=len(inherited), remaining=len(pending), updated_at=now()))
    print(dict(inherited=len(inherited), remaining=len(pending), reused_media=len(caches), commit=commit), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--previous', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    recover(args.previous, args.output)
