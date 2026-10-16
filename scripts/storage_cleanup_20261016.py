"""Authorized, fixed-scope cleanup. Run only from modal-gpu with Modal CPU.

Phases: test, prepare, finalize. Archives must be persisted and checked
through the Volume API between prepare and finalize. No GPU or dataset writes.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import time

import modal

app = modal.App('wxu-evolve-agent-storage-cleanup-20261016')
runs = modal.Volume.from_name('wxu-evolve-agent-runs-20261006')
weights = modal.Volume.from_name('wxu-sgl-evolve-agent-weight-20261006')
BASE = Path('/runs')
AUDIT = BASE / 'devbox/storage_cleanup_20261016'
REPRO = 'devbox/repro_expanded_session_20261012_r3'
ARCHIVE_TARGETS = [REPRO + '/agent', REPRO + '/stress']
CACHE_ROOTS = ['devbox/e2e_full_20261012', REPRO,
               'devbox/external_vam65_20261015',
               'devbox/external_upstream_nc80_20261015']
ORIGINAL = Path('/weights/AgentCVR-8B-original')


def save(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(obj, indent=2) + '\n')
    tmp.replace(path)


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def inventory(root):
    """Include empty directories and links; never follow a symlink."""
    assert root.is_dir() and not root.is_symlink(), root
    rows = []
    def visit(path):
        info = path.lstat()
        kind = stat.S_IFMT(info.st_mode)
        assert kind in (stat.S_IFREG, stat.S_IFDIR, stat.S_IFLNK), path
        rows.append([str(path.relative_to(root)), kind, info.st_size,
                     info.st_mtime_ns, os.readlink(path) if path.is_symlink() else ''])
        if kind == stat.S_IFDIR:
            for child in sorted(path.iterdir()):
                visit(child)
    visit(root)
    return rows


def totals(rows):
    return dict(bytes=sum(r[2] for r in rows if r[1] == stat.S_IFREG),
                files=sum(r[1] == stat.S_IFREG for r in rows), entries=len(rows))


def compare(archive, base, source, expected):
    assert inventory(source) == expected, f'Source changed: {source}'
    # GNU tar compares every archived file's contents and link/metadata state.
    subprocess.run(['tar', '--blocking-factor=2048', '--compare',
                    '--use-compress-program=zstd', '--file', str(archive),
                    '--directory', str(base)], check=True)
    assert inventory(source) == expected, f'Source changed during comparison: {source}'


def self_test():
    with tempfile.TemporaryDirectory() as temp:
        base = Path(temp); source = base / 'sample'; source.mkdir()
        (source / 'empty').mkdir()
        (source / 'data').write_bytes(b'original')
        (source / 'link').symlink_to('data')
        before = inventory(source); archive = base / 'sample.tar.zst'
        subprocess.run(['tar', '--use-compress-program=zstd -T4 -1', '-cf', str(archive),
                        '-C', str(base), 'sample'], check=True)
        compare(archive, base, source, before)
        old = (source / 'data').stat()
        (source / 'data').write_bytes(b'changed!')
        os.utime(source / 'data', ns=(old.st_atime_ns, old.st_mtime_ns))
        try:
            compare(archive, base, source, before)
        except subprocess.CalledProcessError:
            pass
        else:
            raise AssertionError('Same-size, same-mtime corruption was not detected')
        assert source.exists()
        (source / 'extra').write_text('new')
        try:
            compare(archive, base, source, before)
        except AssertionError:
            pass
        else:
            raise AssertionError('Unarchived added file was not detected')
    return {'test': 'passed', 'checks': ['files/links/empty directories',
                                       'content corruption', 'unarchived addition']}


def prepare():
    assert not (AUDIT / 'prepared.json').exists(), 'Already prepared; do not repeat'
    AUDIT.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(__file__, AUDIT / 'cleanup_source.py')
    bytecode = AUDIT / 'bytecode.json'
    removed = json.loads(bytecode.read_text()) if bytecode.exists() else []
    if removed:
        assert all(not (BASE / p).exists() for p, _ in removed), 'Bytecode removal was incomplete'
    for rel in ([] if removed else CACHE_ROOTS):
        root = BASE / rel
        for parent, dirs, files in os.walk(root):
            # Only bytecode is disposable; preserve unexpected files in cache dirs.
            for name in files:
                path = Path(parent) / name
                if path.suffix != '.pyc' or path.is_symlink():
                    continue
                removed.append([str(path.relative_to(BASE)), path.stat().st_size])
        save(AUDIT / 'bytecode.json', removed)
        runs.commit()
        for relpath, _ in removed:
            (BASE / relpath).unlink(missing_ok=True)
        for parent, dirs, files in os.walk(root, topdown=False):
            p = Path(parent)
            if p.name == '__pycache__' and not p.is_symlink() and not any(p.iterdir()):
                p.rmdir()
        runs.commit()
    print('BYTECODE', len(removed), sum(x[1] for x in removed), flush=True)

    records = []
    for rel in ARCHIVE_TARGETS:
        source = BASE / rel
        assert source.resolve() == BASE.resolve() / rel, source
        rows = inventory(source)
        archive = source.with_name(source.name + '.tar.zst')
        partial = archive.with_name(archive.name + '.partial')
        assert not archive.exists(), archive
        discarded = []
        for scratch in [partial, source.with_name(source.name + '.tar.gz.partial')]:
            if not scratch.exists():
                continue
            discarded.append(dict(path=str(scratch), bytes=scratch.stat().st_size,
                                  reason='Unverified temporary archive; original source retained'))
            save(AUDIT / (source.name + '_interrupted_archives.json'), discarded)
            runs.commit()
            scratch.unlink()
        print('ARCHIVING', rel, totals(rows), flush=True)
        # Default 10 KiB tar reads were measured at only about 15 MB/s on this Volume.
        proc = subprocess.Popen(['tar', '--blocking-factor=2048',
                                 '--use-compress-program=zstd -T4 -1', '-cf', str(partial),
                                 '-C', str(BASE), rel])
        while proc.poll() is None:
            try:
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                print('ARCHIVE_BYTES', rel, partial.stat().st_size, flush=True)
        if proc.returncode:
            raise subprocess.CalledProcessError(proc.returncode, proc.args)
        print('COMPARING', rel, flush=True)
        compare(partial, BASE, source, rows)
        partial.rename(archive)
        record = dict(source=rel, archive=str(archive.relative_to(BASE)),
                      source_totals=totals(rows), archive_bytes=archive.stat().st_size,
                      archive_sha256=sha(archive), inventory=rows)
        save(AUDIT / (source.name + '.json'), record)
        records.append({k: v for k, v in record.items() if k != 'inventory'})
        runs.commit()
        print('ARCHIVED_VERIFIED', records[-1], flush=True)

    # Retain NC80: the live LensWalk cache points directly into this old run.
    protected = []
    for p in (BASE / 'devbox/lenswalk_full_35b_20261016/media_cache').glob('*.json'):
        if 'external_upstream_nc80_20261015' in p.read_text():
            protected.append(dict(manifest=str(p), data=json.loads(p.read_text())))
    result = dict(prepared_at=time.time(), archives=records,
                  bytecode_files=len(removed), bytecode_bytes=sum(x[1] for x in removed),
                  protected_nc80=protected)
    save(AUDIT / 'prepared.json', result)
    runs.commit()
    return result


def finalize():
    assert not (AUDIT / 'completed.json').exists(), 'Already completed'
    prepared = json.loads((AUDIT / 'prepared.json').read_text())
    actions = []
    for rel in ARCHIVE_TARGETS:
        source = BASE / rel
        record = json.loads((AUDIT / (source.name + '.json')).read_text())
        assert record['source'] == rel
        archive = BASE / record['archive']
        assert archive == source.with_name(source.name + '.tar.zst')
        assert archive.stat().st_size == record['archive_bytes']
        assert sha(archive) == record['archive_sha256']
        compare(archive, BASE, source, record['inventory'])
        save(AUDIT / (source.name + '_deletion_verified.json'),
             dict(verified_at=time.time(), archive_sha256=record['archive_sha256']))
        runs.commit()
        shutil.rmtree(source)
        source.with_name(source.name + '.ARCHIVED.md').write_text(
            f'Lossless archive: {archive}\nSHA256: {record["archive_sha256"]}\n'
            f'Restore only when this path is absent:\n'
            f'`tar --zstd -xf {archive} -C /runs`\n'
            f'Audit: {AUDIT}\n')
        actions.append(dict(action='archive', source=rel, **record['source_totals'],
                            archive_bytes=record['archive_bytes'],
                            freed_bytes=record['source_totals']['bytes']-record['archive_bytes']))
        save(AUDIT / 'actions.json', actions)
        runs.commit()
        print('REMOVED_VERIFIED_SOURCE', actions[-1], flush=True)

    assets = json.loads((BASE / 'devbox/agentcvr_20261016/assets.json').read_text())
    assert assets['stage'] == 'completed'
    merged = assets['merged']; assert merged['path'] == '/weights/AgentCVR-8B-merged'
    assert len(merged['files']) == 4
    for item in merged['files']:
        p = Path(merged['path']) / item['file']
        assert p.stat().st_size == item['bytes'] and sha(p) == item['sha256'], p
    commands = list((BASE / 'devbox/agentcvr_eval_h100_20261016/episodes').glob('*/*-command.json'))
    assert commands, 'No actual AgentCVR service command records'
    assert any('/weights/AgentCVR-8B-merged' in p.read_text() for p in commands)
    assert all('/weights/AgentCVR-8B-original' not in p.read_text() for p in commands)
    rows = inventory(ORIGINAL)
    original = assets['models']['xiaohua616/qwen8b_crossvidRL']
    assert original['revision'] == '0ca8538758507589a5bada39d2377847649adc09'
    for item in original['files']:
        p = ORIGINAL / item['file']
        assert p.stat().st_size == item['bytes'] and sha(p) == item['sha256'], p
    save(AUDIT / 'original_weight_provenance.json',
         dict(original=original, merged=merged, inventory=rows, totals=totals(rows),
              restore='Redownload the exact HF revision before rerunning the FSDP merger.'))
    runs.commit()
    assert inventory(ORIGINAL) == rows
    shutil.rmtree(ORIGINAL)
    weights.commit()
    actions.append(dict(action='delete_original_weights', source=str(ORIGINAL),
                        **totals(rows), freed_bytes=totals(rows)['bytes']))
    save(AUDIT / 'actions.json', actions)
    result = dict(completed_at=time.time(), actions=actions,
                  bytecode_files=prepared['bytecode_files'], bytecode_bytes=prepared['bytecode_bytes'],
                  total_freed_bytes=sum(a['freed_bytes'] for a in actions)+prepared['bytecode_bytes'],
                  protected_nc80=prepared['protected_nc80'])
    save(AUDIT / 'completed.json', result)
    runs.commit()
    return result


@app.function(image=modal.Image.debian_slim().apt_install('zstd'), cpu=4, memory=4096, timeout=7200,
              volumes={'/runs': runs, '/weights': weights})
def job(phase: str):
    if phase == 'test':
        return self_test()
    if phase == 'prepare':
        return prepare()
    if phase == 'finalize':
        return finalize()
    raise ValueError(phase)


@app.local_entrypoint()
def main(phase: str = 'test'):
    print(json.dumps(job.remote(phase)), flush=True)
