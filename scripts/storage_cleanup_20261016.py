"""User-authorized deletion only; no compression. Run via modal-gpu on Modal CPU."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
import time

import modal

app = modal.App('wxu-evolve-agent-storage-cleanup-20261016')
runs = modal.Volume.from_name('wxu-evolve-agent-runs-20261006')
weights = modal.Volume.from_name('wxu-sgl-evolve-agent-weight-20261006')
BASE = Path('/runs')
AUDIT = BASE / 'devbox/storage_cleanup_20261016'
REPRO = BASE / 'devbox/repro_expanded_session_20261012_r3'
ORIGINAL = Path('/weights/AgentCVR-8B-original')


def save(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(obj, indent=2) + '\n')
    tmp.replace(path)


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def check_files(root, items, hashes=True):
    assert root.is_dir() and not root.is_symlink(), root
    for item in items:
        relative = Path(item['file'])
        assert not relative.is_absolute() and '..' not in relative.parts
        path = root / relative
        assert path.resolve().is_relative_to(root.resolve()), path
        assert path.stat().st_size == item['bytes'], path
        if hashes:
            assert sha(path) == item['sha256'], path


def inventory(root):
    assert root.is_dir() and not root.is_symlink(), root
    rows = []
    for parent, dirs, files in os.walk(root):
        for name in dirs + files:
            path = Path(parent) / name
            info = path.lstat()
            rows.append(dict(path=str(path.relative_to(root)), kind=stat.S_IFMT(info.st_mode),
                             bytes=info.st_size, mtime_ns=info.st_mtime_ns))
    return sorted(rows, key=lambda row: row['path'])


def self_test():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); (root / 'data').write_bytes(b'original')
        items = [dict(file='data', bytes=8, sha256=sha(root / 'data'))]
        check_files(root, items)
        (root / 'data').write_bytes(b'changed!')
        try:
            check_files(root, items)
        except AssertionError:
            pass
        else:
            raise AssertionError('Corruption must prevent deletion')
        try:
            check_files(root, [dict(file='../outside', bytes=0)])
        except AssertionError:
            pass
        else:
            raise AssertionError('Path traversal must be rejected')
    return dict(test='passed', checks=['valid retained file', 'corruption', 'path traversal'])


def clean():
    assert not (AUDIT / 'completed.json').exists(), 'Already completed'
    AUDIT.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(__file__, AUDIT / 'cleanup_source_final.py')
    temporary = []
    for name in ['agent', 'stress']:
        assert (REPRO / name).is_dir() and not (REPRO / name).is_symlink()
        for suffix in ['.tar.gz.partial', '.tar.zst.partial']:
            path = REPRO / (name + suffix)
            if path.exists():
                assert path.is_file() and not path.is_symlink()
                temporary.append(dict(path=str(path), bytes=path.stat().st_size))
    save(AUDIT / 'cancelled_archiving.json', dict(at=time.time(),
         reason='User requested deletion only, no compression', temporary=temporary,
         source_trees_retained=['agent', 'stress']))
    runs.commit()
    for item in temporary:
        Path(item['path']).unlink()
    runs.commit()
    print('REMOVED_OWN_TEMPORARY', temporary, flush=True)

    assets = json.loads((BASE / 'devbox/agentcvr_20261016/assets.json').read_text())
    assert assets['stage'] == 'completed'
    merged = assets['merged']
    assert merged['path'] == '/weights/AgentCVR-8B-merged' and len(merged['files']) == 4
    print('VERIFYING_RETAINED_MERGED_WEIGHTS', flush=True)
    check_files(Path(merged['path']), merged['files'])
    commands = list((BASE / 'devbox/agentcvr_eval_h100_20261016/episodes').glob('*/*-command.json'))
    assert commands, 'No actual AgentCVR service command records'
    assert any('/weights/AgentCVR-8B-merged' in p.read_text() for p in commands)
    assert all('/weights/AgentCVR-8B-original' not in p.read_text() for p in commands)
    original = assets['models']['xiaohua616/qwen8b_crossvidRL']
    assert original['revision'] == '0ca8538758507589a5bada39d2377847649adc09'
    check_files(ORIGINAL, original['files'], hashes=False)
    rows = inventory(ORIGINAL)
    original_bytes = sum(r['bytes'] for r in rows if r['kind'] == stat.S_IFREG)
    save(AUDIT / 'original_weight_provenance.json', dict(original=original, merged=merged,
         merged_sha256_verified=True, original_checksums_from_download_manifest=True,
         inventory=rows, bytes=original_bytes,
         restore='Redownload the pinned HF revision before rerunning the FSDP merger.'))
    runs.commit()
    assert inventory(ORIGINAL) == rows, 'Original directory changed during validation'
    shutil.rmtree(ORIGINAL)
    weights.commit()
    assert not ORIGINAL.exists()
    bytecode = json.loads((AUDIT / 'bytecode.json').read_text())
    result = dict(completed_at=time.time(), compression=False,
                  original_weight_bytes=original_bytes,
                  original_weight_files=sum(r['kind'] == stat.S_IFREG for r in rows),
                  bytecode_files=len(bytecode), bytecode_bytes=sum(x[1] for x in bytecode),
                  total_freed_bytes=original_bytes+sum(x[1] for x in bytecode),
                  own_temporary_removed_bytes=sum(x['bytes'] for x in temporary),
                  retained=['repro_expanded_session_20261012_r3/agent',
                            'repro_expanded_session_20261012_r3/stress',
                            'external_upstream_nc80_20261015/prepared/media'])
    save(AUDIT / 'completed.json', result)
    runs.commit()
    return result


@app.function(image=modal.Image.debian_slim(), cpu=2, memory=1024, timeout=1800,
              volumes={'/runs': runs, '/weights': weights})
def job(phase: str):
    if phase == 'test':
        return self_test()
    if phase == 'clean':
        return clean()
    raise ValueError(phase)


@app.local_entrypoint()
def main(phase: str = 'test'):
    print(json.dumps(job.remote(phase)), flush=True)
