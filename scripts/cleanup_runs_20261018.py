"""Merge identical historical Git object stores; remove disposable old-run caches.

No compression, result deletion, dataset/model access, or active-run changes.
Only dated run roots from 2026-10-15 or earlier are eligible.
"""
import collections
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
import time

import modal

BASE = Path('/runs/devbox')
AUDIT = BASE / 'runs_cleanup_20261018'
app = modal.App('wxu-evolve-agent-runs-cleanup-20261018')
volume = modal.Volume.from_name('wxu-evolve-agent-runs-20261006')


def eligible(path):
    dates = re.findall(r'2026\d{4}', path.name)
    return bool(dates) and max(dates) <= '20261015' and not path.is_symlink()


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def tree(root):
    rows = []
    for parent, dirs, files in os.walk(root):
        for name in sorted(dirs + files):
            path = Path(parent) / name
            info = path.lstat()
            assert not path.is_symlink(), f'Preserve linked object store: {path}'
            if path.is_dir():
                rows.append((str(path.relative_to(root)), 'dir', stat.S_IMODE(info.st_mode)))
            elif path.is_file():
                rows.append((str(path.relative_to(root)), 'file', stat.S_IMODE(info.st_mode),
                             info.st_size, sha(path)))
            else:
                raise ValueError(path)
    rows.sort()
    return dict(sha256=hashlib.sha256(json.dumps(rows).encode()).hexdigest(),
                entries=len(rows), files=sum(r[1]=='file' for r in rows),
                bytes=sum(r[3] for r in rows if r[1]=='file'))


def git(gitdir, *args):
    return subprocess.check_output(['git', '--git-dir', str(gitdir), *args], text=True)


def identity(gitdir):
    objects = sorted(git(gitdir, 'cat-file', '--batch-all-objects',
                         '--batch-check=%(objectname)').splitlines())
    return dict(head=git(gitdir, 'rev-parse', 'HEAD').strip(), count=len(objects),
                object_ids_sha256=hashlib.sha256('\n'.join(objects).encode()).hexdigest())


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def discover():
    groups = collections.defaultdict(list)
    disposable = []
    roots = sorted(p for p in BASE.iterdir() if p.is_dir() and eligible(p))
    for root in roots:
        for parent, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if not (Path(parent)/d).is_symlink()]
            if '.git' in dirs:
                gitdir = Path(parent)/'.git'; dirs.remove('.git')
                objects = gitdir/'objects'
                if (objects.is_dir() and not objects.is_symlink()
                        and not (objects/'info/alternates').exists()
                        and (gitdir/'config').is_file()):
                    try:
                        info = tree(objects)
                    except AssertionError:
                        continue
                    if info['entries']:
                        groups[info['sha256']].append(dict(gitdir=str(gitdir), **info))
            for name in files:
                p = Path(parent)/name
                if name.endswith('.pyc') and not p.is_symlink():
                    source = (p.parent.parent/(name.split('.cpython-')[0]+'.py')
                              if p.parent.name == '__pycache__' else p.with_suffix('.py'))
                    if source.is_file():
                        disposable.append(dict(path=str(p), bytes=p.stat().st_size))
    duplicates = [items for items in groups.values() if len(items)>1]
    result = dict(at=time.time(), roots=[str(p) for p in roots], groups=duplicates,
                  pyc=disposable,
                  potential_entries=sum(sum(x['entries']-2 for x in group[1:]) for group in duplicates))
    print('PLAN', json.dumps({k:v for k,v in result.items() if k not in ('roots','pyc')}), flush=True)
    print('PYC',len(disposable),sum(x['bytes'] for x in disposable),flush=True)
    return result


def merge_one(target, canonical):
    objects = target/'objects'
    for child in list(objects.iterdir()):
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()
    # Git alternates leave future writes local while reading the retained store.
    (objects/'info').mkdir(exist_ok=True)
    (objects/'info/alternates').write_text(os.path.relpath(canonical/'objects', objects)+'\n')


def self_test():
    assert eligible(Path('/runs/devbox/old_20261015'))
    assert not eligible(Path('/runs/devbox/new_20261017'))
    assert not eligible(Path('/runs/devbox/undated'))
    with tempfile.TemporaryDirectory() as temp:
        root=Path(temp); repo=root/'repo'; repo.mkdir()
        subprocess.run(['git','init','-q',str(repo)],check=True)
        (repo/'sample').write_text('keep all objects\n')
        subprocess.run(['git','-C',str(repo),'add','sample'],check=True)
        subprocess.run(['git','-C',str(repo),'-c','user.name=test','-c','user.email=test@example.invalid',
                        'commit','-qm','fixture'],check=True)
        copy=root/'copied.git'; shutil.copytree(repo/'.git',copy)
        before=identity(copy)
        assert tree(copy/'objects') == tree(repo/'.git/objects')
        merge_one(copy,repo/'.git')
        assert identity(copy)==before
        assert git(copy,'show','HEAD:sample')=='keep all objects\n'
        subprocess.run(['git','--git-dir',str(copy),'fsck','--full'],check=True,capture_output=True)
    return {'self_test':'passed'}


def apply(plan):
    assert plan['potential_entries']>7000, 'Insufficient headroom; do not partially merge'
    actions=[]
    for group in plan['groups']:
        canonical=Path(group[0]['gitdir'])
        assert tree(canonical/'objects')['sha256']==group[0]['sha256']
        for item in group[1:]:
            target=Path(item['gitdir'])
            assert target.is_relative_to(BASE) and eligible(BASE/target.relative_to(BASE).parts[0])
            assert tree(target/'objects')['sha256']==item['sha256']
            before=identity(target)
            action=dict(target=str(target),canonical=str(canonical),before=before,**item)
            # Existing config is a durable intent journal even when new inodes are blocked.
            with (target/'config').open('a') as f:
                f.write('\n# MVAgent object-store merge 20261018: '+json.dumps(action)+'\n')
            volume.commit()
            print('MERGE_INTENT',json.dumps(action),flush=True)
            objects=target/'objects'
            for child in list(objects.iterdir()):
                if child.is_dir() and not child.is_symlink():shutil.rmtree(child)
                else:child.unlink()
            action['phase']='removed_duplicate_objects';actions.append(action)
            volume.commit()
    # All object bytes remain in committed canonical stores. Reconnect original Git paths.
    for action in actions:
        target=Path(action['target']);canonical=Path(action['canonical']);objects=target/'objects'
        (objects/'info').mkdir(exist_ok=True)
        (objects/'info/alternates').write_text(os.path.relpath(canonical/'objects',objects)+'\n')
        assert identity(target)==action['before'], target
        action['phase']='merged_verified'
    volume.commit()
    AUDIT.mkdir(exist_ok=True)
    write(AUDIT/'plan.json',plan)
    write(AUDIT/'merged.json',actions)
    volume.commit()
    removed=[]
    for item in plan['pyc']:
        path=Path(item['path'])
        if path.is_file() and not path.is_symlink():path.unlink();removed.append(item)
    empty=[]
    for name in plan['roots']:
        root=Path(name)
        for parent,dirs,files in os.walk(root,topdown=False):
            p=Path(parent)
            # Only bytecode directories and truly empty retired-run directories; keep Git internals/root.
            if p==root or '.git' in p.parts or p.is_symlink():continue
            if not any(p.iterdir()):p.rmdir();empty.append(str(p))
    report=dict(at=time.time(),merged=actions,pyc=removed,empty_directories=empty,
                removed_entries=sum(x['entries']-2 for x in actions)+len(removed)+len(empty),
                freed_bytes=sum(x['bytes'] for x in actions)+sum(x['bytes'] for x in removed),
                free_inodes=os.statvfs('/runs').f_ffree,total_inodes=os.statvfs('/runs').f_files)
    write(AUDIT/'completed.json',report);volume.commit()
    return {k:v for k,v in report.items() if k not in ('merged','pyc','empty_directories')}


@app.function(image=modal.Image.debian_slim().apt_install('git'),cpu=2,memory=2048,
              timeout=1800,volumes={'/runs':volume})
def job(phase):
    if phase=='test':return self_test()
    if phase=='plan':return discover()
    if phase=='apply':
        assert not (AUDIT/'completed.json').exists(), 'This cleanup already completed'
        return apply(discover())
    if phase=='verify':
        report=json.loads((AUDIT/'completed.json').read_text())
        for action in report['merged']:
            assert action['phase']=='merged_verified'
            target=Path(action['target']);canonical=Path(action['canonical'])
            assert (target/'objects/info/alternates').read_text().strip()==os.path.relpath(canonical/'objects',target/'objects')
            assert identity(target)==action['before'], target
        assert all(not Path(item['path']).exists() for item in report['pyc'])
        return dict(verified=True, merged=len(report['merged']),
                    canonical_stores=sorted({x['canonical'] for x in report['merged']}),
                    pyc_files=len(report['pyc']),empty_directories=len(report['empty_directories']),
                    removed_entries=report['removed_entries'],freed_bytes=report['freed_bytes'],
                    free_inodes=os.statvfs('/runs').f_ffree,total_inodes=os.statvfs('/runs').f_files)
    raise ValueError(phase)


@app.local_entrypoint()
def main(phase: str='test'):
    result=job.remote(phase)
    if phase=='plan':
        result={k:v for k,v in result.items() if k not in ('roots','pyc')}
    print('RESULT',json.dumps(result),flush=True)
