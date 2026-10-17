"""Free inodes by losslessly archiving retired method artifacts, without compression."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import tarfile

ROOT = Path('/runs/devbox')
TARGETS = ('external_vam65_20261015/vam', 'external_methods_20261014/vam_remaining',
           'external_methods_20261014/meta_rest_run', 'external_methods_20261014/meta_early_run')


def digest(stream):
    value = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024*1024), b''):
        value.update(chunk)
    return value.hexdigest()


def inventory(root):
    rows = {}
    for path in [root, *root.rglob('*')]:
        info = path.lstat()
        row = dict(mode=stat.S_IMODE(info.st_mode), size=info.st_size, mtime_ns=info.st_mtime_ns)
        if stat.S_ISREG(info.st_mode):
            with path.open('rb') as stream:
                row.update(kind='file', sha256=digest(stream))
        elif stat.S_ISLNK(info.st_mode):
            row.update(kind='symlink', target=os.readlink(path))
        elif stat.S_ISDIR(info.st_mode):
            row.update(kind='directory')
        else:
            raise ValueError(f'Unsupported entry; preserve the source: {path}')
        rows[str(path.relative_to(root.parent))] = row
    return rows


def archive_tree(source, archive, commit):
    assert source.is_dir() and not source.is_symlink()
    assert not archive.exists() and not archive.with_suffix('.tmp').exists()
    before = inventory(source)
    temporary = archive.with_suffix('.tmp')
    with tarfile.open(temporary, 'w', dereference=False) as stream:
        stream.add(source, arcname=source.name)
    observed = set()
    with tarfile.open(temporary, 'r:') as stream:
        for member in stream:
            assert member.name in before and member.name not in observed
            expected = before[member.name]
            assert member.mode == expected['mode']
            if expected['kind'] == 'file':
                assert member.isfile() or member.islnk()
                with stream.extractfile(member) as payload:
                    assert digest(payload) == expected['sha256'], member.name
            elif expected['kind'] == 'symlink':
                assert member.issym() and member.linkname == expected['target']
            else:
                assert member.isdir()
            observed.add(member.name)
    assert observed == set(before)
    assert inventory(source) == before, 'Source changed during archiving; do not remove it'
    temporary.replace(archive)
    with archive.open('rb') as stream:
        archive_hash = digest(stream)
    report = dict(source=str(source), archive=str(archive), archive_sha256=archive_hash,
                  entries=before, compression='none', phase='verified')
    manifest = archive.with_suffix('.json')
    manifest.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    commit()  # Persist the verified replacement before deleting any loose originals.
    shutil.rmtree(source)
    report['phase'] = 'archived_and_loose_files_removed'
    manifest.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    commit()
    return dict(source=str(source), archive=str(archive), entries=len(before),
                files=sum(r['kind']=='file' for r in before.values()), bytes=archive.stat().st_size,
                archive_sha256=archive_hash)


def main():
    import modal
    volume = modal.Volume.from_name('wxu-evolve-agent-runs-20261006')
    output = ROOT/'lenswalk_storage_relief_20261017'
    output.mkdir(exist_ok=True)
    for tag in ('rsi_full_35b_20261016', 'lenswalk_full_35b_20261016',
                'lenswalk_full_35b_recovery_20261017'):
        for path in (ROOT/tag/'media_cache').glob('*.json'):
            entry = path.read_text()
            assert not any('/devbox/'+relative+'/' in entry for relative in TARGETS), path
    results = []
    for relative in TARGETS:
        (output/'progress.json').write_text(json.dumps(dict(phase='archiving', current=relative,
                                                          completed_archives=results)))
        result = archive_tree(ROOT/relative, output/(relative.replace('/', '__')+'.tar'), volume.commit)
        results.append(result)
        print(json.dumps(result), flush=True)
    stats = os.statvfs('/runs')
    report = dict(phase='completed', archives=results, free_inodes=stats.f_ffree,
                  inodes_total=stats.f_files)
    (output/'summary.json').write_text(json.dumps(report, indent=2))
    (output/'progress.json').write_text(json.dumps(report, indent=2))
    volume.commit()
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
