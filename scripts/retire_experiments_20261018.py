"""Delete explicitly retired experiments after preserving their design/conclusion docs."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
import time

import modal

ROOT=Path('/runs/devbox')
AUDIT=ROOT/'retired_experiments_20261018'
GROUPS={
 'tp8': ['tp8_cache_20261014','tp8_cache_20261014_r2','tp8_cache_20261014_r3'],
 'budget': ['output_budget_20261013','output_budget_loading_20261013'],
 'field_order_summary': ['output_stability_20261013','output_stability_loading_20261013',
                         'output_stability_plain_20261013','output_stability_full_20261013'],
 'reason_continuation': ['reason_boundary_20261013','reason_boundary_control_20261013'],
 'penalty_sampling': ['presence_repro_20261013','sampling_20261013'],
 'terminal_answer': ['terminal_answer_smoke_20261016','terminal_answer_smoke_20261016_r2'],
 'pro9_rollback': ['pro9_ffmpeg_20261016','pro9_ffmpeg_20261016_shard0',
                  'pro9_ffmpeg_20261016_shard1','pro9_ffmpeg_20261016_judge',
                  'pro9_ffmpeg_27b_20261016','pro9_ffmpeg_35b_20261016',
                  'pro9_ffmpeg_27b_retry_20261016','pro9_ffmpeg_large_20261016',
                  'pro9_ffmpeg_27b_20261016_pipeline','pro9_ffmpeg_35b_20261016_pipeline',
                  'pro9_ffmpeg_27b_retry_20261016_pipeline'],
}
TARGETS=[ROOT/name for names in GROUPS.values() for name in names]
# The preceding cleanup made this old repository a shared dependency of retained runs.
PROTECTED=[ROOT/'tp8_cache_20261014/freeze_setup_failed/.git']
ACTIVE_ROOTS=['video_context_20261018','lenswalk_full_35b_audit_recovery_20261017',
              'rsi_full_35b_recovery_20261017','agentcvr_crossvid_20261017_r2']
app=modal.App('wxu-evolve-agent-retire-experiments-20261018')
volume=modal.Volume.from_name('wxu-evolve-agent-runs-20261006')
image=modal.Image.debian_slim().add_local_dir(
    str(Path(__file__).resolve().parent/'retired_experiment_docs'),'/retirement_docs')


def within(path,roots):
    return any(path==root or root in path.parents for root in roots)


def normalized_target(path):
    resolved=path.resolve();base=ROOT.resolve()
    return ROOT/resolved.relative_to(base) if resolved.is_relative_to(base) else resolved


def deletions(root,protected):
    if any(root==p or p in root.parents for p in protected):return []
    if not any(root in p.parents for p in protected):return [root]
    assert root.is_dir() and not root.is_symlink()
    return [p for child in sorted(root.iterdir()) for p in deletions(child,protected)]


def inventory(root):
    rows=[];stack=[root]
    while stack:
        p=stack.pop();s=p.lstat()
        row=dict(path=str(p),mode=s.st_mode,size=s.st_size,mtime_ns=s.st_mtime_ns)
        if stat.S_ISLNK(s.st_mode):row['link']=os.readlink(p)
        elif stat.S_ISDIR(s.st_mode):stack.extend(sorted(p.iterdir()))
        else:assert stat.S_ISREG(s.st_mode),p
        rows.append(row)
    return sorted(rows,key=lambda r:r['path'])


def totals(rows):
    return dict(entries=len(rows),files=sum(stat.S_ISREG(r['mode']) for r in rows),
                bytes=sum(r['size'] for r in rows if stat.S_ISREG(r['mode'])))


def save(path,value):
    path.write_text(json.dumps(value,indent=2)+'\n')


def prepare():
    assert not (AUDIT/'plan.json').exists(), 'Do not overwrite an existing plan'
    protected=list(PROTECTED);references=[]
    # Find inbound symlinks and Git alternates without reading result payloads.
    for parent,dirs,files in os.walk(ROOT,followlinks=False):
        directory=Path(parent)
        if within(directory,TARGETS):dirs[:]=[];continue
        for name in dirs+files:
            p=directory/name
            if p.is_symlink():
                dest=normalized_target(p)
                if within(dest,TARGETS):
                    protected.append(dest);references.append(dict(source=str(p),target=str(dest)))
            elif name=='alternates' and '/.git/objects/info/' in str(p):
                for line in p.read_text().splitlines():
                    dest=normalized_target(p.parent.parent/line)
                    if within(dest,TARGETS):
                        protected.append(dest);references.append(dict(source=str(p),target=str(dest)))
    # Operational manifests of current jobs must not load retired inputs.
    hits=[]
    for name in ACTIVE_ROOTS:
        active=ROOT/name
        if not active.exists():continue
        paths=list(active.glob('*.json'))+list((active/'media_cache').glob('*.json'))
        paths+=list((active/'prepared').glob('*.json'))
        for p in paths:
            if p.is_symlink() or p.stat().st_size>8*1024*1024:continue
            text=p.read_text()
            for target in TARGETS:
                if str(target)+'/' in text:hits.append(dict(source=str(p),target=str(target)))
    assert not hits, f'Current task references need review: {hits}'
    AUDIT.mkdir(exist_ok=True)
    shutil.copytree('/retirement_docs',AUDIT/'documentation',dirs_exist_ok=True)
    documentation={str(p.relative_to(AUDIT/'documentation')):hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in (AUDIT/'documentation').rglob('*') if p.is_file()}
    plan=[]
    for target in TARGETS:
        if not target.exists():continue
        assert not target.is_symlink(),target
        paths=deletions(target,protected)
        rows=[row for p in paths for row in inventory(p)]
        plan.append(dict(root=str(target),delete=[str(p) for p in paths],inventory=rows,**totals(rows)))
        print('PLANNED',target.name,totals(rows),flush=True)
    record=dict(at=time.time(),groups=GROUPS,plan=plan,protected=sorted(set(map(str,protected))),
                inbound_references=references,documentation= documentation)
    save(AUDIT/'plan.json',record);volume.commit()
    return dict(roots=len(plan),entries=sum(p['entries'] for p in plan),
                files=sum(p['files'] for p in plan),bytes=sum(p['bytes'] for p in plan),
                protected=record['protected'],references=references,documentation=documentation)


def apply():
    assert not (AUDIT/'completed.json').exists(), 'Already completed'
    plan=json.loads((AUDIT/'plan.json').read_text())
    for name,digest in plan['documentation'].items():
        assert hashlib.sha256((AUDIT/'documentation'/name).read_bytes()).hexdigest()==digest
    completed=[]
    for item in plan['plan']:
        root=Path(item['root']);assert root in TARGETS and not root.is_symlink()
        paths=[Path(p) for p in item['delete']]
        assert paths==deletions(root,[Path(p) for p in plan['protected']])
        assert [r for p in paths for r in inventory(p)]==item['inventory'],f'Changed: {root}'
        for p in paths:
            if p.is_symlink() or p.is_file():p.unlink()
            else:shutil.rmtree(p)
        completed.append({k:item[k] for k in ('root','entries','files','bytes')})
        save(AUDIT/'progress.json',dict(completed=completed,phase='deleting'))
        volume.commit()
        print('DELETED',completed[-1],flush=True)
    assert all(Path(p).exists() for p in plan['protected'])
    report=dict(at=time.time(),completed=completed,protected=plan['protected'],compression=False,
                entries=sum(x['entries'] for x in completed),files=sum(x['files'] for x in completed),
                bytes=sum(x['bytes'] for x in completed),free_inodes=os.statvfs('/runs').f_ffree)
    save(AUDIT/'completed.json',report);volume.commit()
    return report


def self_test():
    with tempfile.TemporaryDirectory() as temp:
        root=Path(temp)/'old';keep=root/'frozen/.git';keep.mkdir(parents=True)
        (keep/'object').write_text('retain')
        (root/'result.json').write_text('retire')
        (root/'outside_link').symlink_to('/tmp')
        selected=deletions(root,[keep]);assert keep not in selected
        rows=[r for p in selected for r in inventory(p)]
        assert len(rows)==2 and totals(rows)['files']==1
        for p in selected:p.unlink()
        assert (keep/'object').read_text()=='retain'
    return dict(test='passed',checks=['protected subtree','no symlink traversal','inventory counts'])


@app.function(image=image,cpu=2,memory=2048,timeout=1800,volumes={'/runs':volume})
def job(phase):
    if phase=='test':return self_test()
    if phase=='prepare':return prepare()
    if phase=='apply':return apply()
    if phase=='verify':
        plan=json.loads((AUDIT/'plan.json').read_text())
        report=json.loads((AUDIT/'completed.json').read_text())
        assert len(report['completed'])==len(plan['plan'])
        for item in plan['plan']:
            assert all(not Path(p).exists() and not Path(p).is_symlink() for p in item['delete'])
        assert all(Path(p).exists() for p in plan['protected'])
        return dict(verified=True,entries=report['entries'],bytes=report['bytes'],
                    free_inodes=os.statvfs('/runs').f_ffree,total_inodes=os.statvfs('/runs').f_files)
    raise ValueError(phase)


@app.local_entrypoint()
def main(phase: str='test'):
    print('RESULT',json.dumps(job.remote(phase)),flush=True)
