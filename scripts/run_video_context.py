"""Same concise Global: original Video versus boundary-only versus full question."""
import argparse
import ast
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import shutil
import tarfile

import run_system_ablation as trial
from analyze_direct_answer_large import mean_score, interval

ROOT=Path(__file__).resolve().parents[1]
OUT=Path('/runs/devbox/video_context_20261018')
BASE=Path('/runs/devbox/global_short_large_20261017')
PILOT=Path('/runs/devbox/system_ablation_20261017')
ARMS=('boundary_only','with_question')
CHANGED={'src/mvagent/engine.py',trial.VIDEO,trial.AGENT}
read,write,sha,now,MODELS=trial.read,trial.write,trial.sha,trial.now,trial.MODELS


def boundary_source(source):
    before='self.original_question = str(original_question)'
    assert source.count(before)==1
    return source.replace(before,'self.original_question = "(not provided)"')


def prepare():
    assert not OUT.exists(),'Use a new result directory'
    prior=read(BASE/'manifest.json')
    changed={name for name,digest in prior['actor_source_hashes'].items() if sha(ROOT/name)!=digest}
    assert changed==CHANGED,changed
    ids=read(PILOT/'samples.json');assert len(ids)==len(set(ids))==102
    baseline={m:[r for r in read(BASE/'analysis'/f'{m}_paired.json') if r['sample_id'] in ids] for m in MODELS}
    assert all(len(rows)==102 and all(r['reused'] for r in rows) for rows in baseline.values())
    assert Counter(r['dataset'] for r in baseline['9B'])==dict(cvbench=30,mvu_eval=30,crossvid=42)
    def validate(row):assert sha(Path(row['path']))==row['sha256'],row['path']
    with ThreadPoolExecutor(max_workers=8) as pool:list(pool.map(validate,[r for rows in baseline.values() for r in rows]))
    # Keep the visual Observer's wording and callable interface exactly unchanged.
    with tarfile.open(BASE/'source.tar.gz') as archive:
        before=archive.extractfile(trial.VIDEO).read().decode()
    after=(ROOT/trial.VIDEO).read_text()
    assert trial.constant(before,'VISUAL_OBSERVATION_PROMPT_TEMPLATE')==trial.constant(after,'VISUAL_OBSERVATION_PROMPT_TEMPLATE')
    def function(source,name):return ast.dump(next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name==name))
    assert function(before,'build_visual_observation_prompt')==function(after,'build_visual_observation_prompt')
    OUT.mkdir();write(OUT/'samples.json',ids);write(OUT/'baseline.json',baseline)
    with tarfile.open(OUT/'source.tar.gz','w:gz',compresslevel=1) as archive:
        for name in ['src','scripts','configs','eval','.git','requirements.txt','demo.py']:
            archive.add(ROOT/name,arcname=name,filter=lambda t:None if {'__pycache__','.cache'} & set(Path(t.name).parts) else t)
    for arm in ARMS:
        for name in [trial.GLOBAL,trial.VIDEO,trial.AGENT]:
            p=OUT/arm/'code'/name;p.parent.mkdir(parents=True,exist_ok=True)
            text=(ROOT/name).read_text()
            if arm=='boundary_only' and name==trial.AGENT:text=boundary_source(text)
            p.write_text(text)
        write(OUT/arm/'progress.json',dict(phase='prepared',models={},expected=306))
    seconds={m:sum(r['stats']['seconds'] for r in rows) for m,rows in baseline.items()}
    manifest=dict(at=now(),commit=(ROOT/'.git/HEAD').read_text().strip(),profile=prior['profile'],
        archive_sha256=sha(OUT/'source.tar.gz'),samples_sha256=sha(OUT/'samples.json'),
        baseline_sha256=sha(OUT/'baseline.json'),reference_manifest_sha256=sha(BASE/'manifest.json'),
        changed_runtime_files=sorted(changed),runtime_hashes={name:sha(ROOT/name) for name in prior['actor_source_hashes']},
        candidate_hashes={a:{name:sha(OUT/a/'code'/name) for name in [trial.GLOBAL,trial.VIDEO,trial.AGENT]} for a in ARMS},
        expected_hours_per_arm=.5+1.35*sum(seconds.values())/8/3600,
        inference_seed=0,selection_resampled=False,reused_baseline_outputs=306,new_outputs=612,
        baseline='A: existing concise Global plus original Video',
        arms={'boundary_only':'B: shared Video boundary System and identity; question field (not provided)',
              'with_question':'C: exactly B, with the complete original question'},
        visual_observer_unchanged=True,terminal_video_summary_context=True,development_panel=True)
    write(OUT/'manifest.json',manifest)
    print(json.dumps({k:v for k,v in manifest.items() if k not in ('runtime_hashes','candidate_hashes')}),flush=True)


def worker(arm):
    trial.OUT=OUT
    trial.worker(arm)


def analyze():
    trial.OUT=OUT;trial.ARMS=ARMS
    trial.analyze()
    summary=read(OUT/'analysis/summary.json');complete=True
    direct_comparison={}
    for model in MODELS:
        b={r['sample_id']:r for r in read(OUT/'analysis'/f'boundary_only_{model}_paired.json')}
        c=read(OUT/'analysis'/f'with_question_{model}_paired.json')
        complete &= all(summary['arms'][a][model]['valid']==102 and not summary['arms'][a][model]['missing'] and not summary['arms'][a][model]['errors'] for a in ARMS)
        paired=[]
        for r in c:
            if r['sample_id'] not in b:continue
            row={**r,'arms':{**r['arms'],'baseline':b[r['sample_id']]['arms']['direct']}}
            paired.append(row)
        report={}
        for dataset in ('cvbench','mvu_eval','crossvid'):
            group=[r for r in paired if r['dataset']==dataset]
            if not group:continue
            report[dataset]=dict(n=len(group),B=mean_score(group,'baseline'),C=mean_score(group,'direct'),
                delta_ci95=interval(group,'baseline'),wins=sum(r['arms']['direct']['score']>r['arms']['baseline']['score'] for r in group),
                losses=sum(r['arms']['direct']['score']<r['arms']['baseline']['score'] for r in group))
        direct_comparison[model]=report
    summary.update(complete=complete,C_versus_B=direct_comparison)
    write(OUT/'analysis/summary.json',summary)
    write(OUT/'progress.json',dict(phase='completed' if complete else 'incomplete',at=now(),
        valid=sum(summary['arms'][a][m]['valid'] for a in ARMS for m in MODELS),expected=612,reused_baseline=306))
    print(json.dumps(summary),flush=True)
    assert complete,'Missing outputs or scores: report incomplete, never count infrastructure failures as zero'


def self_check():
    text='self.original_question = str(original_question)\nself.video_id = str(video_id)\n'
    modified=boundary_source(text)
    assert modified.replace('"(not provided)"','str(original_question)')==text
    assert 'self.video_id = str(video_id)' in modified
    try:boundary_source(modified)
    except AssertionError:pass
    else:raise AssertionError('Double replacement accepted')
    print('B and C differ only in the supplied background question')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=['prepare','worker','analyze','self-check']);parser.add_argument('--arm',choices=ARMS)
    a=parser.parse_args()
    if a.mode=='worker':assert a.arm;worker(a.arm)
    else:globals()[a.mode.replace('-','_')]()
