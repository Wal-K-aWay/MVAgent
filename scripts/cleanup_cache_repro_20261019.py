"""Delete explicitly retired experiments after preserving their design/conclusion docs."""
from concurrent.futures import ThreadPoolExecutor
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
AUDIT=ROOT/'cache_repro_cleanup_20261019'
CACHES=['mvagent_full_20261013/media','mvagent_full_35b_parallel_20261015/media',
        'direct_answer_random_20261015/media','direct_answer_large_20261016/shard0/media',
        'direct_answer_large_20261016/shard1/media','e2e_full_20261012/media']
REPRO=['e2e_sync_norm_20261012','repro_expanded_panel_20261012','repro_expanded_panel_20261012_r2',
       'repro_expanded_agent_20261012','repro_expanded_e2e_cached_20261012',
       'repro_targeted_rotation_9b_20261012','repro_targeted_rotation_27b_20261012',
       'formal_repro_integration_20261012','formal_repro_integration_20261012_r2',
       'formal_repro_final_io_20261012','repro_expanded_session_20261012',
       'repro_expanded_session_20261012_r2','repro_expanded_session_20261012_r3',
       'independent_bf16_e2e_20261011_r1','independent_bf16_mvagent_20261011_budget32768',
       'inproc_mvagent_9b_20261011_r1','inproc_mvagent_27b_20261011_r1','inproc_mvagent_20261011_r1',
       'tp_compare_9b_tp1_single_20261011','tp_compare_35b_tp1_single_20261011',
       'tp_compare_27b_tp1_single_20261011','repro_agent_flashinfer_9b_20261011_p1',
       'repro_agent_flashinfer_9b_20261011_extra','repro_agent_flashinfer_35b_20261011_p1',
       'repro_agent_flashinfer_35b_20261011_extra','repro_agent_flashinfer_27b_20261011_p1',
       'repro_agent_flashinfer_27b_20261011_extra','agent_replica_repro_20261011']
GROUPS=dict(caches=CACHES,repro=REPRO)
TARGETS=[ROOT/n for ns in GROUPS.values() for n in ns]
PROTECTED=[]
ALIASES={'mvagent_full_20261014_transport/media':'mvagent_full_20261013/media',
         'e2e_full_20261013_timeout/media':'e2e_full_20261012/media'}
ALIASES.update({f'mvu_instruction_after_20261014/media/rank{i}/code-806a8aa13418/mvu_eval_frames':
                f'e2e_full_20261012/media/rank{i}/code-806a8aa13418/mvu_eval_frames' for i in range(8)})
ACTIVE_ROOTS=['frozen_full_20261018','frozen_full_recovery_20261019',
              'rsi_full_35b_parallel_media_20261018','lenswalk_full_9b_20261019','lenswalk_full_27b_20261019']
KEEP_DIRS={'.git','frozen_repo','frozen','source','source_cached','src','scripts','configs','eval'}
KEEP_SUFFIX={'.py','.sh','.yaml','.yml','.toml','.md'}
app=modal.App('wxu-evolve-agent-cache-repro-cleanup-20261019')
volume=modal.Volume.from_name('wxu-evolve-agent-runs-20261006')
image=modal.Image.debian_slim().add_local_dir(
    str(Path(__file__).resolve().parent/'cache_repro_docs'),'/retirement_docs')


def within(path,roots):
    ancestors={path,*path.parents}
    return any(root in ancestors for root in roots)


def normalized_target(path):
    resolved=path.resolve();base=ROOT.resolve()
    return ROOT/resolved.relative_to(base) if resolved.is_relative_to(base) else resolved


def deletions(root,protected):
    keep=set(protected)
    ancestors={parent for p in keep for parent in p.parents}
    def walk(p):
        if any(a in keep for a in (p,*p.parents)):return []
        if p not in ancestors:return [p]
        assert p.is_dir() and not p.is_symlink()
        return [item for child in sorted(p.iterdir()) for item in walk(child)]
    return walk(root)


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


def protected_sources():
    result=[]
    for name in REPRO:
        root=ROOT/name
        if not root.exists():continue
        for parent,dirs,files in os.walk(root,followlinks=False):
            for d in list(dirs):
                if d in KEEP_DIRS or d.startswith('frozen_'):
                    result.append(Path(parent)/d);dirs.remove(d)
            for f in files:
                p=Path(parent)/f
                if p.suffix in KEEP_SUFFIX or (f.startswith('source') and '.tar' in f):result.append(p)
                elif Path(parent)==root and f in {'manifest.json','selection.json','samples.json','audit.json','report.json','summary.json'}:
                    if p.stat().st_size<4*1024**2:result.append(p)
    return result


def result_files(extra_owners=()):
    selected=[]
    for name in sorted({p.split('/')[0] for p in CACHES}|set(extra_owners)):
        for parent,dirs,files in os.walk(ROOT/name,followlinks=False):
            directory=Path(parent)
            dirs[:]=[d for d in dirs if d not in KEEP_DIRS and not within(directory/d,TARGETS)]
            for f in files:
                p=directory/f
                if p.is_symlink():continue
                if (f=='result.json' and 'records' in p.parts) or f in {'summary.json','manifest.json','selection.json'} or (
                    p.suffix in {'.json','.jsonl'} and any(x in {'raw','scored','judge','judge_cache','judgements'} for x in p.parts)):
                    selected.append(p)
    return selected


def file_sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(8*1024**2),b''):h.update(chunk)
    return h.hexdigest()


def check_retained(plan):
    with ThreadPoolExecutor(max_workers=32) as pool:
        for (path,wanted),actual in zip(plan['retained_results'].items(),pool.map(file_sha,plan['retained_results'])):
            assert actual==wanted,path


def prepare():
    assert not (AUDIT/'plan.json').exists(), 'Do not overwrite an existing plan'
    protected=protected_sources();references=[]
    # Resolve links before deletion. Do not follow directory links during the walk.
    stack=[ROOT];scanned=0
    while stack:
        directory=stack.pop()
        if within(directory,TARGETS):continue
        with os.scandir(directory) as entries:
            for entry in entries:
                p=Path(entry.path)
                if entry.is_symlink():
                    dest=normalized_target(p)
                    if within(dest,TARGETS):
                        protected.append(dest);references.append(dict(source=str(p),target=str(dest)))
                elif entry.is_dir(follow_symlinks=False):stack.append(p)
                elif entry.name=='alternates' and '/.git/objects/info/' in str(p):
                    for line in p.read_text().splitlines():
                        dest=normalized_target(p.parent.parent/line)
                        if within(dest,TARGETS):
                            protected.append(dest);references.append(dict(source=str(p),target=str(dest)))
        scanned+=1
        if scanned%20000==0:print('SCANNED directories',scanned,flush=True)
    # Keep referenced inputs of running/new runs, including inherited baseline records.
    def protect_refs(v,source):
        if isinstance(v,dict):
            for x in v.values():protect_refs(x,source)
        elif isinstance(v,list):
            for x in v:protect_refs(x,source)
        elif isinstance(v,str) and v.startswith('/runs/'):
            dest=Path(os.path.normpath(v))
            if within(dest,TARGETS) and dest.exists():
                protected.append(dest);references.append(dict(source=str(source),target=str(dest)))
    for name in ACTIVE_ROOTS:
        root=ROOT/name
        paths=list(root.glob('*.json'))+list(root.glob('shard*/*.json'))
        for p in paths:
            if p.is_file() and p.stat().st_size<32*1024**2:protect_refs(json.loads(p.read_text()),p)
    protected=sorted(set(protected))
    AUDIT.mkdir(exist_ok=True)
    shutil.copytree('/retirement_docs',AUDIT/'documentation',dirs_exist_ok=True)
    documentation={str(p.relative_to(AUDIT/'documentation')):file_sha(p)
                   for p in (AUDIT/'documentation').rglob('*') if p.is_file()}
    plan=[]
    for target in TARGETS:
        if not target.exists():continue
        assert not target.is_symlink(),target
        paths=deletions(target,protected)
        rows=[row for p in paths for row in inventory(p)]
        plan.append(dict(root=str(target),delete=[str(p) for p in paths],inventory=rows,**totals(rows)))
        print('PLANNED',str(target.relative_to(ROOT)),totals(rows),flush=True)
    paths=result_files()
    deleting={Path(x) for item in plan for x in item['delete']}
    assert paths and all(not any(a in deleting for a in (p,*p.parents)) for p in paths)
    print('HASHING_RETAINED_RESULTS',len(paths),flush=True)
    with ThreadPoolExecutor(max_workers=32) as pool:hashes=dict(zip(map(str,paths),pool.map(file_sha,paths)))
    record=dict(at=time.time(),groups=GROUPS,plan=plan,protected=list(map(str,protected)),
                inbound_references=references,documentation=documentation,retained_results=hashes)
    save(AUDIT/'plan.json',record);volume.commit()
    return dict(roots=len(plan),entries=sum(p['entries'] for p in plan),
                files=sum(p['files'] for p in plan),bytes=sum(p['bytes'] for p in plan),
                protected_paths=len(protected),references=references[:20],retained_result_files=len(hashes))


def include_inactive_aliases():
    plan=json.loads((AUDIT/'plan.json').read_text())
    assert not (AUDIT/'plan_before_alias_review.json').exists()
    cache_roots=[ROOT/'mvagent_full_20261013/media',ROOT/'e2e_full_20261012/media']
    for ref in plan['inbound_references']:
        if within(Path(ref['target']),cache_roots):assert ref['source'] in [str(ROOT/n) for n in ALIASES],ref
    aliases=[]
    for name,target in ALIASES.items():
        path=ROOT/name;cache=ROOT/target
        assert path.is_symlink() and normalized_target(path)==cache
        state=json.loads((ROOT/name.split('/')[0]/'progress.json').read_text())
        assert state['phase'] in {'failed','completed','completed_with_recorded_failures'},state['phase']
        aliases.append(dict(path=str(path),link=os.readlink(path),target=str(cache),owner_phase=state['phase']))
    for name in ACTIVE_ROOTS:
        root=ROOT/name
        for p in list(root.glob('*.json'))+list(root.glob('shard*/*.json')):
            if p.is_file() and p.stat().st_size<32*1024**2:
                body=p.read_text()
                assert not any(str(ROOT/a) in body or str(ROOT/t) in body for a,t in ALIASES.items()),p
    save(AUDIT/'plan_before_alias_review.json',plan)
    plan['protected']=[p for p in plan['protected'] if not within(Path(p),cache_roots)]
    for item in plan['plan']:
        root=Path(item['root'])
        if root not in cache_roots:continue
        paths=deletions(root,[Path(p) for p in plan['protected']])
        rows=[r for p in paths for r in inventory(p)]
        item.update(delete=list(map(str,paths)),inventory=rows,**totals(rows))
    paths=[p for p in result_files(a.split('/')[0] for a in ALIASES) if str(p) not in plan['retained_results']]
    with ThreadPoolExecutor(max_workers=32) as pool:
        plan['retained_results'].update(zip(map(str,paths),pool.map(file_sha,paths)))
    plan['aliases']=aliases
    save(AUDIT/'plan.json',plan);volume.commit()
    return dict(entries=sum(x['entries'] for x in plan['plan'])+len(aliases),
                bytes=sum(x['bytes'] for x in plan['plan']),aliases=aliases,
                retained_result_files=len(plan['retained_results']))


def apply():
    assert not (AUDIT/'completed.json').exists(), 'Already completed'
    plan=json.loads((AUDIT/'plan.json').read_text())
    for name,digest in plan['documentation'].items():
        assert hashlib.sha256((AUDIT/'documentation'/name).read_bytes()).hexdigest()==digest
    # The pre-deletion SHA snapshot is in the plan; verify it again after deletion.
    for item in plan.get('aliases',[]):
        p=Path(item['path']);assert p.is_symlink() and os.readlink(p)==item['link'];p.unlink()
    volume.commit()
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
                entries=sum(x['entries'] for x in completed)+len(plan.get('aliases',[])),files=sum(x['files'] for x in completed),
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
        assert deletions(keep,[root])==[]
        assert within(keep,[root]) and not within(root,[keep])
        rows=[r for p in selected for r in inventory(p)]
        assert len(rows)==2 and totals(rows)['files']==1
        for p in selected:p.unlink()
        assert (keep/'object').read_text()=='retain'
    return dict(test='passed',checks=['protected subtree','no symlink traversal','inventory counts'])


@app.function(image=image,cpu=2,memory=2048,timeout=1800,volumes={'/runs':volume})
def job(phase):
    if phase=='test':return self_test()
    if phase=='prepare':return prepare()
    if phase=='include-inactive-aliases':return include_inactive_aliases()
    if phase=='apply':return apply()
    if phase=='verify':
        plan=json.loads((AUDIT/'plan.json').read_text())
        report=json.loads((AUDIT/'completed.json').read_text())
        assert len(report['completed'])==len(plan['plan'])
        for item in plan['plan']:
            assert all(not Path(p).exists() and not Path(p).is_symlink() for p in item['delete'])
        assert all(Path(p).exists() for p in plan['protected'])
        for x in plan.get('aliases',[]):assert not Path(x['path']).is_symlink() and not Path(x['path']).exists()
        check_retained(plan)
        result=dict(verified=True,entries=report['entries'],bytes=report['bytes'],
                    retained_result_files=len(plan['retained_results']),
                    free_inodes=os.statvfs('/runs').f_ffree,total_inodes=os.statvfs('/runs').f_files)
        save(AUDIT/'verified.json',result);volume.commit();return result
    raise ValueError(phase)


@app.local_entrypoint()
def main(phase: str='test'):
    print('RESULT',json.dumps(job.remote(phase)),flush=True)
