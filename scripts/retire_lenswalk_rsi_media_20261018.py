"""Retire only rebuildable MP4s of five paused LensWalk/RSI batches."""
from concurrent.futures import ThreadPoolExecutor
from collections import defaultdict
import hashlib
import json
import os
from pathlib import Path
import stat
import statistics
import time
import modal

NAMES=['lenswalk_full_35b_20261016','lenswalk_full_35b_recovery_20261017',
       'lenswalk_full_35b_audit_recovery_20261017','rsi_full_35b_20261016',
       'rsi_full_35b_recovery_20261017']
ROOT=Path('/runs/devbox')
TARGETS=[ROOT/n/'prepared/media' for n in NAMES]
AUDIT=ROOT/'media_retirement_20261018'
app=modal.App('wxu-evolve-agent-media-retirement-20261018')
runs=modal.Volume.from_name('wxu-evolve-agent-runs-20261006')
assets=modal.Volume.from_name('wxu-evolve-agent-inf-asset-20261006')


def read(p):return json.loads(Path(p).read_text())
def write(p,v):Path(p).write_text(json.dumps(v,indent=2)+'\n')
def in_media(p):return any(p==root or root in p.parents for root in TARGETS)
def selected(p):return in_media(p) and p.suffix=='.mp4'
def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def summary(xs):
    if not xs:return {'n':0}
    xs=sorted(xs)
    return dict(n=len(xs),sum=sum(xs),mean=statistics.mean(xs),median=statistics.median(xs),
                p90=xs[min(len(xs)-1,int(len(xs)*.9))],max=max(xs))


def inspect_json(p):
    v=read(p);refs=[]
    def visit(x):
        if isinstance(x,dict):
            for item in x.values():visit(item)
        elif isinstance(x,list):
            for item in x:visit(item)
        elif isinstance(x,str) and x.startswith('/runs/'):
            target=Path(os.path.normpath(x))
            if in_media(target):refs.append(str(target))
    visit(v)
    return str(p),refs


def prepare():
    assert not (AUDIT/'plan.json').exists()
    inventory=read(ROOT/'storage_breakdown_20261018/runs.json')
    external=[]
    for rel,size,_ in inventory['files']:
        p=Path('/runs')/rel
        if any(ROOT/n in p.parents for n in NAMES):continue
        if p.suffix=='.json' and size<=8*1024**2 and (
            '/media_cache/' in rel or '/prepared/items/' in rel or
            p.name in ('manifest.json','items.json')) and '/frozen_repo/' not in rel:
            if p.is_file():external.append(p)
    protected=set();references=[]
    with ThreadPoolExecutor(max_workers=8) as pool:
        for source,refs in pool.map(inspect_json,external):
            if refs:references.append(dict(source=source,targets=refs));protected.update(refs)
    for rel,dest in inventory['links']:
        p=Path('/runs')/rel
        if any(ROOT/n in p.parents for n in NAMES):continue
        dest=Path(os.path.normpath(str(p.parent/dest)))
        if in_media(dest) or any(dest==ROOT/n or dest==ROOT/n/'prepared' for n in NAMES):
            protected.add(str(dest));references.append(dict(source=str(p),targets=[str(dest)]))
    AUDIT.mkdir(exist_ok=True)
    rows=[];root_stats={};timing=defaultdict(list);metadata={};missing_sources=[]
    for name,target in zip(NAMES,TARGETS):
        current=[]
        for p in target.rglob('*'):
            if p.is_symlink():continue
            if p.is_file() and p.suffix=='.mp4':
                s=p.stat();current.append(dict(path=str(p),bytes=s.st_size,mtime_ns=s.st_mtime_ns,
                                              protected=any(p==Path(v) or Path(v) in p.parents for v in protected)))
        rows.extend(current)
        root_stats[name]=dict(files=sum(not x['protected'] for x in current),
                             bytes=sum(x['bytes'] for x in current if not x['protected']))
        timelines=list(target.glob('*/timeline.json'))
        def timeline_info(p):
            raw=p.read_bytes();v=json.loads(raw)
            missing=[s['source'] for s in v.get('segments',[]) if not Path(s['source']).is_file()]
            return p,hashlib.sha256(raw).hexdigest(),v,missing
        with ThreadPoolExecutor(max_workers=8) as pool:
            for p,h,v,missing in pool.map(timeline_info,timelines):
                metadata[str(p)]=h;missing_sources.extend(missing)
                sec=v.get('preprocessing_seconds');kind='lossless' if 'lossless' in v.get('preprocessing','') else 'stream_copy'
                if isinstance(sec,(int,float)):
                    timing[name+':'+kind].append(sec)
        print('ROOT',name,root_stats[name],{k:summary(v) for k,v in timing.items() if k.startswith(name+':')},flush=True)
    assert not missing_sources,sorted(set(missing_sources))[:10]
    record_timing={}
    for name,method in [(NAMES[2],'lenswalk'),(NAMES[4],'rsi')]:
        paths=list((ROOT/name/method).glob('*/record.json'))
        with ThreadPoolExecutor(max_workers=8) as pool:records=list(pool.map(read,paths))
        valid=[r for r in records if not r.get('infrastructure_error')]
        record_timing[name]=dict(records=len(records),non_infra=len(valid),
            preparation=summary([r['prepared_seconds'] for r in valid if 'prepared_seconds' in r]),
            inference=summary([r['seconds'] for r in valid if 'seconds' in r]))
    for name in NAMES:
        root=ROOT/name
        for p in [root/'manifest.json',root/'samples.json',root/'inherited_records.json',root/'prepared/private_labels.json']:
            if p.is_file():metadata[str(p)]=digest(p)
    # Retained evidence includes all loose result records, archives and metadata under these roots.
    record_paths=[]
    for rel,_,_ in inventory['files']:
        p=Path('/runs')/rel
        if any(ROOT/n in p.parents for n in NAMES) and p.name=='record.json' and p.is_file():
            record_paths.append(p)
    with ThreadPoolExecutor(max_workers=8) as pool:
        for p,h in zip(record_paths,pool.map(digest,record_paths)):metadata[str(p)]=h
    plan=dict(at=time.time(),rows=rows,roots=root_stats,protected=sorted(protected),references=references,
              checked_external_manifests=len(external),retained_metadata_sha256=metadata,
              timing={k:summary(v) for k,v in timing.items()},record_timing=record_timing,
              bytes=sum(x['bytes'] for x in rows if not x['protected']),
              files=sum(not x['protected'] for x in rows))
    write(AUDIT/'plan.json',plan);runs.commit()
    print('PLAN',json.dumps({k:v for k,v in plan.items() if k not in ('rows','retained_metadata_sha256','timing')}),flush=True)


def apply():
    assert not (AUDIT/'completed.json').exists()
    p=read(AUDIT/'plan.json')
    for name in NAMES:
        write(ROOT/name/'USER_PAUSED.json',dict(at=time.time(),reason='User requested pause and on-demand media',
            resume='Do not resume old frozen cache consumers; create a new run with per-question local scratch media.'))
    runs.commit()
    for row in p['rows']:
        if row['protected']:continue
        file=Path(row['path']);assert selected(file) and not file.is_symlink()
        s=file.stat();assert (s.st_size,s.st_mtime_ns)==(row['bytes'],row['mtime_ns']),file
    deleted=[]
    for name in NAMES:
        part=[r for r in p['rows'] if not r['protected'] and ROOT/name in Path(r['path']).parents]
        for r in part:Path(r['path']).unlink()
        write(ROOT/name/'MEDIA_RETIRED.json',dict(at=time.time(),audit=str(AUDIT),
            files=len(part),bytes=sum(r['bytes'] for r in part),
            retained='Results, frozen code, items, cache indices, timelines and source checksums; original assets unchanged',
            warning='Historical video paths may no longer exist. Generate media per question before future inference.'))
        deleted+=part;write(AUDIT/'progress.json',dict(deleted_files=len(deleted)));runs.commit()
        print('DELETED',name,len(part),sum(r['bytes'] for r in part),flush=True)
    result=dict(at=time.time(),files=len(deleted),bytes=sum(r['bytes'] for r in deleted),compression=False)
    write(AUDIT/'completed.json',result);runs.commit();return result


def verify():
    p=read(AUDIT/'plan.json')
    for r in p['rows']:
        f=Path(r['path']);assert f.exists() if r['protected'] else not f.exists()
    with ThreadPoolExecutor(max_workers=8) as pool:
        hashes=pool.map(digest,p['retained_metadata_sha256'])
        for (path,h),actual in zip(p['retained_metadata_sha256'].items(),hashes):assert h==actual,path
    result=dict(verified=True,**read(AUDIT/'completed.json'),retained_hashes=len(p['retained_metadata_sha256']),
                free_entries=os.statvfs('/runs').f_ffree,total_entries=os.statvfs('/runs').f_files)
    write(AUDIT/'verified.json',result);runs.commit();return result


@app.function(image=modal.Image.debian_slim(),cpu=2,memory=2048,timeout=1800,volumes={'/runs':runs,'/assets':assets})
def job(phase):
    assert selected(TARGETS[0]/'example/0.mp4')
    assert not selected(ROOT/NAMES[0]/'results/0.mp4')
    assert not selected(TARGETS[0]/'example/timeline.json')
    if phase=='prepare':return prepare()
    if phase=='apply':return apply()
    if phase=='verify':return verify()
    raise ValueError(phase)


@app.local_entrypoint()
def main(phase: str='prepare'):print('RESULT',json.dumps(job.remote(phase)),flush=True)
