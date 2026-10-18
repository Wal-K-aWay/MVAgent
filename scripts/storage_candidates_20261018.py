"""Inspect the saved inventory, without deleting or changing media."""
import collections
import hashlib
import json
from pathlib import Path
import modal
app=modal.App('wxu-evolve-agent-storage-candidates-20261018')
runs=modal.Volume.from_name('wxu-evolve-agent-runs-20261006')
assets=modal.Volume.from_name('wxu-evolve-agent-inf-asset-20261006')

BASE=Path('/runs/devbox/storage_breakdown_20261018')


def grouped(items):
    groups=collections.defaultdict(list)
    for key,path,size in items:groups[key].append([path,size])
    repeated=[g for g in groups.values() if len(g)>1]
    return dict(groups=len(repeated),extra_files=sum(len(g)-1 for g in repeated),
                candidate_bytes=sum(sum(x[1] for x in g)-max(x[1] for x in g) for g in repeated),
                examples=sorted(repeated,key=lambda g:-sum(x[1] for x in g))[:5]),repeated


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
    return h.hexdigest()


@app.function(image=modal.Image.debian_slim(),cpu=2,memory=2048,timeout=900,
              volumes={'/runs':runs,'/assets':assets})
def detail():
    check,_=grouped([('same','a',10),('same','b',10),('different','c',3)])
    assert check['candidate_bytes']==10 and check['extra_files']==1
    a=json.loads((BASE/'assets.json').read_text());r=json.loads((BASE/'runs.json').read_text())
    sizes={p:s for p,s,_ in a['files']};specs=[]
    for task in ['PEA','PI','PSS']:
        for row in json.loads((Path('/assets/crossvid/QA')/(task+'.json')).read_text()):
            if task=='PEA':
                clips=[(f'video_{i}',source,[[begin,end]]) for i,(source,begin,end) in
                       enumerate(zip(row['videos'],row['begin'],row['end']),1)]
            elif task=='PI':clips=[(role,row['video'],[row[role]]) for role in ['beginning','ending']]
            else:clips=[('segment_'+role,row['video'],ranges) for role,ranges in row['segments'].items()]
            for role,source,ranges in clips:
                p=f"crossvid/.mvagent_media/{task}/{row['id']}/{role}.mp4"
                if p not in sizes:continue
                key=json.dumps([source,ranges,sizes[p]],sort_keys=True)
                specs.append((key,p,sizes[p]))
    aset,ag=grouped(specs)
    media=[(Path(p).parent.name+':'+str(s),p,s) for p,s,_ in r['files'] if p.endswith('/concatenated.mp4')]
    rset,rg=grouped(media)
    parts=[(p,s) for p,s,_ in r['files'] if '/prepared/media/' in p and Path(p).suffix=='.mp4'
           and Path(p).stem.isdigit()]
    largest=sorted(media,key=lambda x:-x[2])[:5];examples=[]
    for _,p,s in largest:
        timeline=Path('/runs')/Path(p).parent/'timeline.json'
        if not timeline.exists():continue
        t=json.loads(timeline.read_text())
        sources=[seg['source'] for seg in t['segments']]
        examples.append(dict(path=p,bytes=s,source_bytes=sum(Path(x).stat().st_size for x in sources),
                             preprocessing=t.get('preprocessing'),segments=len(sources)))
    samples=[]
    for name,groups,prefix in [('assets',ag,'/assets'),('runs',rg,'/runs')]:
        if not groups:continue
        pair=min(groups,key=lambda g:abs(g[0][1]-64*1024**2))[:2]
        digests=[sha(Path(prefix)/p) for p,_ in pair]
        samples.append(dict(volume=name,paths=pair,sha256=digests,equal=len(set(digests))==1))
    record=dict(asset_same_spec_candidates=aset,runs_same_key_size_candidates=rset,
                numbered_parts=dict(files=len(parts),bytes=sum(s for _,s in parts),
                                    examples=sorted(parts,key=lambda x:-x[1])[:10]),
                large_media_examples=examples,hash_samples=samples,
                note='Candidate totals are not all-file hash verified; no media mutation.')
    (BASE/'candidates.json').write_text(json.dumps(record,indent=2));runs.commit()
    print(json.dumps(record),flush=True)


@app.local_entrypoint()
def inspect():
    detail.remote()
