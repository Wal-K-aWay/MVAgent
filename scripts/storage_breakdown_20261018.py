"""Read-only file-size inventory; run from modal-gpu on Modal CPU."""
import collections
import json
import os
from pathlib import Path
import stat
import time
import modal

app=modal.App('wxu-evolve-agent-storage-breakdown-20261018')
runs=modal.Volume.from_name('wxu-evolve-agent-runs-20261006')
assets=modal.Volume.from_name('wxu-evolve-agent-inf-asset-20261006')
weights=modal.Volume.from_name('wxu-sgl-evolve-agent-weight-20261006')


def scan(root):
    groups=collections.defaultdict(lambda:[0,0])
    extensions=collections.defaultdict(lambda:[0,0])
    counts=collections.Counter();files=[];links=[];stack=[root]
    while stack:
        directory=stack.pop()
        with os.scandir(directory) as entries:
            for e in entries:
                rel=os.path.relpath(e.path,root)
                if e.is_symlink():
                    counts['symlinks']+=1;links.append([rel,os.readlink(e.path)]);continue
                if e.is_dir(follow_symlinks=False):
                    counts['dirs']+=1;stack.append(e.path);continue
                try:s=e.stat(follow_symlinks=False)
                except FileNotFoundError:counts['vanished']+=1;continue
                if not stat.S_ISREG(s.st_mode):continue
                counts['files']+=1;counts['bytes']+=s.st_size
                files.append([rel,s.st_size,s.st_mtime_ns])
                parents=rel.split('/')[:-1]
                for depth in range(1,min(len(parents),4)+1):
                    g=groups['/'.join(parents[:depth])];g[0]+=s.st_size;g[1]+=1
                ext=Path(e.name).suffix.lower() or '<none>'
                g=extensions[ext];g[0]+=s.st_size;g[1]+=1
        if (counts['dirs']+1)%20000==0:print('SCANNING',root,dict(counts),flush=True)
    fs=os.statvfs(root)
    result=dict(at=time.time(),root=root,counts=dict(counts),free_entries=fs.f_ffree,
                total_entries=fs.f_files,groups=dict(groups),extensions=dict(extensions),files=files,links=links)
    assert sum(v[0] for v in extensions.values())==counts['bytes']
    top=sorted(groups.items(),key=lambda x:-x[1][0])
    print('SUMMARY',json.dumps({k:v for k,v in result.items() if k not in ['groups','files','links']}),flush=True)
    print('DIRECTORIES',root,json.dumps(top[:65]),flush=True)
    print('LARGEST_FILES',root,json.dumps(sorted(files,key=lambda x:-x[1])[:15]),flush=True)
    return result


@app.function(image=modal.Image.debian_slim(),cpu=2,memory=2048,timeout=1200,
              volumes={'/runs':runs,'/assets':assets,'/weights':weights})
def job():
    output=Path('/runs/devbox/storage_breakdown_20261018');output.mkdir(exist_ok=True)
    for name in ['assets','weights','runs']:
        result=scan('/'+name)
        (output/(name+'.json')).write_text(json.dumps(result))
        runs.commit()
    return dict(completed=True,audit=str(output))


@app.local_entrypoint()
def main():
    print(job.remote())
