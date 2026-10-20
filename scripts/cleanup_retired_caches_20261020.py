"""Retire three approved media caches and consolidate identical retired dependencies."""
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile
import time

import modal
sys.path.insert(0, '/cleanup')
import cleanup_cache_repro_20261019 as shared

ROOT = Path('/runs/devbox')
AUDIT = ROOT/'retired_cache_cleanup_20261020'
MEDIA = [ROOT/p for p in (
    'external_upstream_nc80_20261015/prepared/media',
    'rsi_budget_20261015/prepared/media',
    'external_methods_20261014/media')]
REPRO = ROOT/'repro_expanded_session_20261012_r3'
ACTIVE = [ROOT/f'{method}_27b_32gpu_20261020-shard{i}'
          for method in ('lenswalk', 'rsi') for i in range(4)]
volume = modal.Volume.from_name('wxu-evolve-agent-runs-20261006')
app = modal.App('wxu-evolve-agent-retired-cache-cleanup-20261020')
read = lambda p: json.loads(p.read_text())
save = shared.save


def signature(root):
    root = root.resolve()
    rows = shared.inventory(root)
    assert not any(stat.S_ISLNK(r['mode']) for r in rows), 'Do not move trees with links'
    data = [(str(Path(r['path']).relative_to(root)), r['mode'],
             shared.file_sha(r['path']) if stat.S_ISREG(r['mode']) else None) for r in rows]
    return hashlib.sha256(json.dumps(data).encode()).hexdigest()


def references():
    refs = []
    def add(source, target, kind):
        target = shared.normalized_target(Path(target))
        if shared.within(target, MEDIA+[REPRO]):
            refs.append(dict(source=str(source), target=str(target), kind=kind))
    for parent, dirs, files in os.walk(ROOT, followlinks=False):
        directory = Path(parent)
        if shared.within(directory, MEDIA+[REPRO, AUDIT]):
            dirs[:] = []
            continue
        for name in dirs+files:
            path = directory/name
            if path.is_symlink():
                add(path, path, 'symlink')
            elif name == 'alternates' and '/.git/objects/info/' in str(path):
                for line in path.read_text().splitlines():
                    add(path, path.parent.parent/line, 'git_alternates')
    for root in ACTIVE:
        assert root.is_dir(), root
        progress = read(root/'progress.json')
        assert progress['phase'] in {'inference', 'judging', 'judge_loading', 'completed',
                                     'completed_with_errors'}, progress
        # Check current runtime sources and cached input metadata, not just manifests.
        for parent, dirs, files in os.walk(root, followlinks=True):
            dirs[:] = [d for d in dirs if d not in {
                'raw', 'records', 'episodes', 'lenswalk', 'rsi', 'judgements',
                'judge_cache', '.git', '__pycache__', 'media'}]
            for name in files:
                path = Path(parent)/name
                if path.suffix not in {'.json', '.jsonl', '.py', '.yaml', '.yml', '.sh'}:
                    continue
                body = path.read_text()
                for target in MEDIA+[REPRO]:
                    if str(target) in body or (path.suffix in {'.py', '.sh'} and
                                               target.relative_to(ROOT).parts[0] in body):
                        refs.append(dict(source=str(path), target=str(target), kind='active_input_or_source'))
    return refs


def retained_hashes():
    files = []
    for root in [p.parents[1] if p.parent.name == 'prepared' else p.parent for p in MEDIA]:
        for parent, dirs, names in os.walk(root, followlinks=False):
            directory = Path(parent)
            dirs[:] = [d for d in dirs if not (directory/d).is_symlink() and
                       not shared.within(directory/d, MEDIA) and
                       d not in {'frozen_repo', 'runtime_repo', 'support', '.git', '__pycache__'}]
            files.extend(directory/n for n in names if not (directory/n).is_symlink())
    # Also retain every repro file outside the dependency trees being consolidated.
    for parent, dirs, names in os.walk(REPRO, followlinks=False):
        dirs[:] = [d for d in dirs if d != 'driver_dependencies']
        files.extend(Path(parent)/n for n in names if not (Path(parent)/n).is_symlink())
    files = sorted(set(files))
    with ThreadPoolExecutor(max_workers=8) as pool:
        return dict(zip(map(str, files), pool.map(shared.file_sha, files)))


def prepare():
    assert not AUDIT.exists(), 'Never overwrite an existing cleanup audit'
    refs = references()
    protected = [Path(r['target']) for r in refs]
    plan = []
    for root in MEDIA:
        assert root.is_dir() and not root.is_symlink()
        paths = shared.deletions(root, protected)
        rows = [r for p in paths for r in shared.inventory(p)]
        plan.append(dict(root=str(root), delete=list(map(str, paths)),
                         inventory=rows, **shared.totals(rows)))
    groups = defaultdict(list)
    for parent, dirs, _ in os.walk(REPRO, followlinks=False):
        if 'driver_dependencies' in dirs:
            path = Path(parent)/'driver_dependencies'
            dirs.remove('driver_dependencies')
            assert not path.is_symlink()
            if any(shared.within(p, [path]) or shared.within(path, [p]) for p in protected):
                continue
            groups[signature(path)].append(path)
    AUDIT.mkdir()
    copies = []
    for digest, paths in groups.items():
        if len(paths) < 2:
            continue
        canonical = AUDIT/'shared_dependencies'/digest
        shutil.copytree(paths[0], canonical)
        assert signature(canonical) == digest
        copies.append(dict(sha256=digest, canonical=str(canonical),
                           canonical_totals=shared.totals(shared.inventory(canonical)),
                           sources=[dict(path=str(p), inventory=shared.inventory(p)) for p in paths]))
    (AUDIT/'README.md').write_text(
        'Approved retired media cleanup; formal answers, scores and trajectories are retained.\n'
        'Identical driver_dependencies share canonical trees; old source paths remain readable.\n'
        'Do not delete shared_dependencies while old paths reference it. No compression.\n'
        'Historical experiment designs: devbox/cache_repro_cleanup_20261019/documentation/.\n')
    hashes = retained_hashes()
    save(AUDIT/'plan.json', dict(at=time.time(), media=plan, copies=copies,
                                references=refs, retained=hashes))
    volume.commit()
    return dict(media=[{k:p[k] for k in ('root','bytes','files','entries')} for p in plan],
                dependency_groups=len(copies), dependency_copies=sum(len(g['sources']) for g in copies),
                retained_files=len(hashes), references=refs[:15])


def verify_retained(plan):
    with ThreadPoolExecutor(max_workers=8) as pool:
        for (path, expected), actual in zip(plan['retained'].items(),
                                           pool.map(shared.file_sha, plan['retained'])):
            assert expected == actual, path


def extend_runtime():
    """Consolidate runtime/src while preserving distinct per-rank input configurations."""
    assert not (AUDIT/'plan_before_runtime_src.json').exists()
    plan = read(AUDIT/'plan.json')
    protected = [Path(r['target']) for r in plan['references']]
    groups = defaultdict(list)
    for parent, dirs, _ in os.walk(REPRO, followlinks=False):
        if Path(parent).name != 'runtime' or 'src' not in dirs:
            continue
        path = Path(parent)/'src'
        dirs.remove('src')
        assert not path.is_symlink()
        if any(shared.within(p, [path]) or shared.within(path, [p]) for p in protected):
            continue
        rows = shared.inventory(path)
        assert not any(stat.S_ISLNK(r['mode']) for r in rows)
        content = [(str(Path(r['path']).relative_to(path)), r['mode'],
                    plan['retained'][r['path']] if stat.S_ISREG(r['mode']) else None) for r in rows]
        digest = hashlib.sha256(json.dumps(content).encode()).hexdigest()
        groups[digest].append(dict(path=str(path), inventory=rows))
    save(AUDIT/'plan_before_runtime_src.json', plan)
    added = []
    for digest, rows in groups.items():
        if len(rows) < 2:
            continue
        canonical = AUDIT/'shared_dependencies'/digest
        shutil.copytree(rows[0]['path'], canonical)
        assert signature(canonical) == digest
        group = dict(sha256=digest, canonical=str(canonical),
                     canonical_totals=shared.totals(shared.inventory(canonical)), sources=rows)
        plan['copies'].append(group)
        added.append(dict(copies=len(rows), sha256=digest, canonical=group['canonical_totals']))
    save(AUDIT/'plan.json', plan)
    volume.commit()
    return dict(runtime_groups=added, total_groups=len(plan['copies']),
                total_copies=sum(len(g['sources']) for g in plan['copies']))


def apply():
    assert not (AUDIT/'completed.json').exists()
    plan = read(AUDIT/'plan.json')
    assert {Path(p['root']) for p in plan['media']} == set(MEDIA)
    refs = references()
    protected = [Path(r['target']) for r in refs]
    # Finish every check before the first removal.
    for item in plan['media']:
        paths = list(map(Path, item['delete']))
        assert paths == shared.deletions(Path(item['root']), protected)
        assert [r for p in paths for r in shared.inventory(p)] == item['inventory']
    for group in plan['copies']:
        assert Path(group['canonical']).parent == AUDIT/'shared_dependencies'
        assert signature(Path(group['canonical'])) == group['sha256']
        for row in group['sources']:
            path = Path(row['path'])
            assert path.is_relative_to(REPRO) and (
                path.name == 'driver_dependencies' or (path.name == 'src' and path.parent.name == 'runtime'))
            assert not path.is_symlink() and shared.normalized_target(path) == path
            assert not any(shared.within(p, [path]) or shared.within(path, [p]) for p in protected)
            assert shared.inventory(path) == row['inventory']
    # Original hashes are frozen in the plan; verify preserved bytes on a fresh mount afterward.
    removed_bytes = removed_entries = 0
    for item in plan['media']:
        for name in item['delete']:
            p = Path(name)
            if p.is_symlink() or p.is_file():
                p.unlink()
            else:
                shutil.rmtree(p)
        removed_bytes += item['bytes']
        removed_entries += item['entries']
        print('MEDIA_REMOVED',item['root'],item['bytes'],flush=True)
    for group in plan['copies']:
        for row in group['sources']:
            path = Path(row['path'])
            size = shared.totals(row['inventory'])
            shutil.rmtree(path)
            path.symlink_to(os.path.relpath(group['canonical'], path.parent), target_is_directory=True)
            removed_bytes += size['bytes']
            removed_entries += size['entries']-1
        removed_bytes -= group['canonical_totals']['bytes']
        removed_entries -= group['canonical_totals']['entries']
    result = dict(at=time.time(), media_bytes=sum(p['bytes'] for p in plan['media']),
                  net_content_bytes_removed=removed_bytes, net_content_entries_removed=removed_entries,
                  dependency_groups=len(plan['copies']), compression=False)
    save(AUDIT/'completed.json', result)
    volume.commit()
    return result


def verify():
    plan = read(AUDIT/'plan.json')
    for item in plan['media']:
        for name in item['delete']:
            p = Path(name)
            assert not p.exists() and not p.is_symlink()
    for group in plan['copies']:
        canonical = Path(group['canonical'])
        assert signature(canonical) == group['sha256']
        for row in group['sources']:
            p = Path(row['path'])
            assert p.is_symlink() and p.resolve() == canonical.resolve()
    verify_retained(plan)
    fs = os.statvfs('/runs')
    result = dict(read(AUDIT/'completed.json'), verified=True, retained_files=len(plan['retained']),
                  free_entries=fs.f_ffree, total_entries=fs.f_files)
    save(AUDIT/'verified.json', result)
    volume.commit()
    return result


def test():
    shared.self_test()
    with tempfile.TemporaryDirectory() as tmp:
        a, b = Path(tmp)/'a', Path(tmp)/'b'
        a.mkdir(); (a/'source.py').write_text('print(1)\n')
        shutil.copytree(a,b)
        assert signature(a) == signature(b)
        (b/'source.py').write_text('print(2)\n')
        assert signature(a) != signature(b)
        (b/'link').symlink_to(a/'source.py')
        try:
            signature(b)
        except AssertionError:
            pass
        else:
            raise AssertionError('Linked dependencies must not be moved')
        shutil.rmtree(b);b.symlink_to(a,target_is_directory=True)
        assert signature(a) == signature(b)
    return dict(tests='passed')


@app.function(image=modal.Image.debian_slim().add_local_file(
                  str(Path(__file__).with_name('cleanup_cache_repro_20261019.py')),
                  '/cleanup/cleanup_cache_repro_20261019.py'),
              cpu=2, memory=2048, timeout=1800,
              volumes={'/runs':volume})
def job(phase):
    return globals()[phase]()


@app.local_entrypoint()
def main(phase: str='test'):
    assert phase in {'test','prepare','extend_runtime','apply','verify'}
    print('RESULT',json.dumps(job.remote(phase)),flush=True)
