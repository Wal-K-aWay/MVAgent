#!/usr/bin/env python3
"""Frozen-candidate generalization diagnostic; historical no-Skill predictions only."""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import yaml

ROOT = Path(os.environ.get('MVAGENT_PROJECT_ROOT', Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(ROOT/'src'))
sys.path.insert(0, str(ROOT/'scripts/analysis'))
from skill_evolution.infra.data import DataSplitManifest, SplitSample, group_by_media
from skill_evolution.infra.benchmarks.catalog import load_multibench_records
from skill_evolution.infra.store import write_json, file_fingerprint
from audit_crossvid_representative_subset import record_header

PRIOR = ROOT/'outputs/analysis/20260923_crossvid_gepa_35b'
BASELINE = ROOT/'outputs/mvagent/no_skill/qwen3_5_35b_a3b'
DATA = Path('/home/kww/datasets/Multi-Video')

def status(out, phase, **kw):
    write_json(out/'status.json', dict(phase=phase, pid=os.getpid(), time=datetime.now(timezone.utc).isoformat(), **kw))

def prepare(out):
    status(out, 'preparing')
    rows = json.loads((ROOT/'outputs/analysis/20260919_crossvid_lite2500/all_features.json').read_text())
    old = json.loads((PRIOR/'data/selected_features.json').read_text())
    prior_ids = {r['sample_id'] for r in old}
    cv = json.loads((DATA/'CVBench/QAs.json').read_text())
    mvu = json.loads((DATA/'MVU-Eval/QAs.json').read_text())
    ids = [r['sample_id'] for r in rows] + [f"cvbench:{r['id']}" for r in cv] + [f"mvu_eval:{r['task']}:{r['id']}" for r in mvu]
    records = load_multibench_records(DATA, ids)
    keys = {sid: [str(Path(p).resolve()) for p in r.sample.videos.values()] +
            ['filename:'+Path(p).name for p in r.sample.videos.values()] for sid,r in records.items()}
    for row in rows:
        keys[row['sample_id']] += row['source_keys']
    # Remove questions touching prior sources BEFORE constructing cross-benchmark
    # components. Unselected bridge questions must not connect disjoint test media
    # to Train through a video that no selected test question actually contains.
    cross_groups = group_by_media({r['sample_id']: r['source_keys'] for r in rows})
    blocked_cross_groups = {cross_groups[s] for s in prior_ids}
    blocked_keys = {k for sid in prior_ids for k in keys[sid]}
    eligible = [s for s in ids if not set(keys[s]) & blocked_keys and
                (s not in cross_groups or cross_groups[s] not in blocked_cross_groups)]
    groups = group_by_media({s:keys[s] for s in set(eligible)|prior_ids})
    blocked = {groups[s] for s in prior_ids}
    rng = random.Random(20260924)
    selected = []
    for dataset in ('crossvid', 'cvbench', 'mvu_eval'):
        strata = defaultdict(list)
        for sid in eligible:
            if records[sid].dataset == dataset:
                strata[records[sid].native_task].append(sid)
        quota, remainder = divmod(200, len(strata))
        for index, task in enumerate(sorted(strata)):
            choices = sorted(strata[task]); rng.shuffle(choices)
            n = quota + (index < remainder)
            if len(choices) < n:
                raise ValueError(f'Insufficient eligible samples: {dataset}/{task}')
            selected.extend(choices[:n])
    assert len(selected)==600 and not set(selected)&prior_ids
    assert not {groups[s] for s in selected}&blocked
    # Byte aliases to any Train/Eval video are excluded; no whole-film claim.
    old_hashes = json.loads((PRIOR/'data/audit.json').read_text())['selected_media_hashes']
    old_sizes = {Path(p).stat().st_size for p in old_hashes}
    selected_paths = {p for sid in selected for p in records[sid].sample.videos.values()}
    aliases = [p for p in sorted(selected_paths) if Path(p).stat().st_size in old_sizes and file_fingerprint(p) in set(old_hashes.values())]
    if aliases:
        raise ValueError('Byte overlap with prior Train/Eval; do not freeze this split')
    manifest = DataSplitManifest('Frozen GEPA candidate transfer diagnostic (historically reused benchmarks)',20260924,
        tuple(SplitSample(s,'test',groups[s]) for s in selected))
    manifest.write(out/'split.json')
    shutil.copyfile(PRIOR/'train/search_bank.json',out/'skill.json')
    # Freeze before loading any baseline outcome. No sample selection uses scores.
    headers = {}
    judge = {int(r['id']):r for r in json.loads((BASELINE/'score/ccqa_scores_official_deepseek_v4_flash.json').read_text())['samples']}
    input_checks = {}
    for sid in selected:
        record = records[sid]
        path = BASELINE/'records'/record.dataset/sid/'result.json'
        h = record_header(path)
        with path.open() as stream:prefix=stream.read(262144)
        start=prefix.index('"input":')+len('"input":')
        inp=json.JSONDecoder().raw_decode(prefix[start:].lstrip())[0]
        same=inp['question']==record.sample.question and list(inp['videos'].values())==list(record.sample.videos.values())
        if not same:raise ValueError('Historical question/video order mismatch: '+sid)
        score=h['score']
        if record.native_task=='CCQA':
            j=judge[int(sid.split(':')[-1])]
            assert j['prediction']==h['prediction'] and j['status']=='ok'
            score=j['score']/(2*len(j['coverage']))
        elif score is None:
            if type(h.get('correct')) is not bool:raise ValueError('Unscored historical sample: '+sid)
            score=float(h['correct'])
        headers[sid]=dict(score=score,prediction=h['prediction'],dataset=record.dataset,task=record.native_task,
            weight=record.sample_weight,group=groups[sid],status=h['status'])
        input_checks[sid]=same
    write_json(out/'baseline.json',headers)
    write_json(out/'audit.json',dict(sample_count=len(selected),questions_per_dataset=200,
        prior_train_eval_overlap=0,known_component_overlap=0,byte_aliases=aliases,
        matching_historical_inputs=sum(input_checks.values()),skill_sha256=file_fingerprint(out/'skill.json'),
        per_task={d:{t:sum(records[s].dataset==d and records[s].native_task==t for s in selected) for t in sorted({records[s].native_task for s in selected if records[s].dataset==d})} for d in ('crossvid','cvbench','mvu_eval')},
        limits='Held out from this GEPA search; reused research benchmarks, not pristine Test. Historical Runtime differs despite identical question/video inputs. No no-Skill rerun.'))
    shutil.copyfile(PRIOR/'runtime.yaml',out/'runtime.yaml')
    shutil.copyfile(PRIOR/'execution.yaml',out/'execution.yaml')
    recipe=yaml.safe_load((PRIOR/'recipe.yaml').read_text())
    recipe['runtime']=dict(mvagent_config=str(out/'runtime.yaml'),cache_dir=str(out/'cache'))
    (out/'recipe.yaml').write_text(yaml.safe_dump(recipe,sort_keys=False))


def report(out):
    baseline=json.loads((out/'baseline.json').read_text())
    result=json.loads((out/'run/summary.json').read_text())['samples']
    assert set(result)==set(baseline)
    rows=[]
    for dataset in ('crossvid','cvbench','mvu_eval'):
        for task in sorted({r['task'] for r in baseline.values() if r['dataset']==dataset}):
            ids=[s for s,r in baseline.items() if r['dataset']==dataset and r['task']==task]
            den=sum(baseline[s]['weight'] for s in ids)
            b=sum(baseline[s]['score']*baseline[s]['weight'] for s in ids)/den
            c=sum(result[s]['score']*baseline[s]['weight'] for s in ids)/den
            rows.append(dict(dataset=dataset,task=task,n=len(ids),baseline=b,candidate=c,delta=c-b,
                gains=sum(result[s]['score']>baseline[s]['score'] for s in ids),losses=sum(result[s]['score']<baseline[s]['score'] for s in ids)))
    datasets={d:{k:sum(r[k] for r in rows if r['dataset']==d)/sum(r['dataset']==d for r in rows) for k in ('baseline','candidate','delta')} for d in ('crossvid','cvbench','mvu_eval')}
    write_json(out/'comparison.json',dict(tasks=rows,dataset_macro=datasets,limits=json.loads((out/'audit.json').read_text())['limits']))
    lines=['# Frozen candidate transfer diagnostic','','Historical no-Skill comparison; not a matched-Runtime causal ablation. No automatic promotion.','','|Dataset/task|n|Historical %|Candidate %|Delta pp|','|---|---:|---:|---:|---:|']
    for r in rows:lines.append(f"|{r['dataset']}/{r['task']}|{r['n']}|{r['baseline']*100:.2f}|{r['candidate']*100:.2f}|{r['delta']*100:+.2f}|")
    (out/'report.md').write_text('\n'.join(lines)+'\n')


def run(out):
    try:
        prepare(out)
        spec=importlib.util.spec_from_file_location('keys',ROOT/'scripts/analysis/credentials.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        env={**os.environ,**module.credentials(ROOT/'.local/skill_evolution_keys.env'),'PYTHONUNBUFFERED':'1'}
        for key in ('NO_PROXY','no_proxy'):env[key]=','.join(filter(None,[env.get(key,''),'127.0.0.1','localhost']))
        command=[sys.executable,str(ROOT/'scripts/run_skill_evolution.py'),'--mode','evaluate','--config',str(out/'recipe.yaml'),
            '--execution-config',str(out/'execution.yaml'),'--split-manifest',str(out/'split.json'),'--split','test',
            '--skills',str(out/'skill.json'),'--output-dir',str(out/'run'),'--repeat-id','gepa-frozen-transfer-20260924']
        with (out/'evaluation.log').open('w') as log:
            child=subprocess.Popen(command,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
            status(out,'evaluating',child_pid=child.pid)
            rc=child.wait()
        if rc:raise RuntimeError(f'Evaluation failed with exit code {rc}')
        report(out);status(out,'completed')
    except Exception as exc:
        status(out,'failed',error=str(exc));raise

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True);args=parser.parse_args()
    out=Path(args.output).resolve();out.mkdir(parents=True,exist_ok=False);run(out)
