"""Freeze three-benchmark real traces for Localizer evidence-boundary diagnostics."""
from collections import Counter, defaultdict
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace
import argparse
import hashlib
import json

from skill_evolution.infra.bank import BankSnapshot
from skill_evolution.infra.trajectory import TrajectoryProjector
from test_localizer_skill_visibility import ROOT, read, save, sha


def prepare(output):
    if output.exists():raise ValueError('Use a new immutable panel directory')
    regression=read(ROOT/'outputs/analysis/20261002_localizer_task_checks/inputs.json')
    prior_files=sorted({p for pattern in ['*localizer*/inputs.json','*localizer*/selection.json','*localizer*/inputs/*.json']
        for p in (ROOT/'outputs/analysis').glob(pattern) if 'localizer_boundary_panel' not in str(p)})
    excluded=set()
    def collect(value):
        if isinstance(value,dict):
            sid=value.get('sample_id')
            if isinstance(sid,str):excluded.add(sid)
            for item in value.values():collect(item)
        elif isinstance(value,list):
            for item in value:collect(item)
    for p in prior_files:
        collect(read(p))
    jobs=[dict(j,cohort='regression') for j in regression]
    root=ROOT/'outputs/mvagent/no_skill/qwen3_5_35b_a3b'
    bank=BankSnapshot.from_dict(dict(schema_version=3,skills=[]))
    evidence=import_module('skill_evolution.algorithms.alternating.global.adaptor.evidence')
    audit={}
    for benchmark in ['crossvid','cvbench','mvu_eval']:
        buckets=defaultdict(list)
        for p in sorted((root/'records'/benchmark).glob('*/result.json')):
            sid=p.parent.name
            if sid in excluded:continue
            task=sid.split(':')[1] if benchmark!='cvbench' else 'all'
            buckets[task].append(p)
        for paths in buckets.values():paths.sort(key=lambda p:hashlib.sha256(('localizer-boundary-20261002:'+p.parent.name).encode()).hexdigest())
        counts=Counter();task_counts=Counter();discarded=Counter()
        while any(buckets.values()) and (counts['correct']<8 or counts['not_fully_correct']<16):
            tasks=sorted((t for t,paths in buckets.items() if paths),key=lambda t:(task_counts[t],t))
            for task in tasks:
                p=buckets[task].pop(0);record=read(p)
                if record.get('status')!='ok' or record.get('scoring_status')!='ok':discarded['not_scored_ok']+=1;continue
                score=record.get('score')
                if score is None:
                    if type(record.get('correct')) is not bool:discarded['no_score']+=1;continue
                    score=float(record['correct'])
                group='correct' if score==1 else 'not_fully_correct'
                if counts[group]>={'correct':8,'not_fully_correct':16}[group]:continue
                sid=record['sample_id'];result=record['result']
                projector=TrajectoryProjector(video_metadata_provider=lambda raw:result['video_metadata'])
                reference={k:record.get(k) for k in ['ground_truth','reference_answer','judge_question','native_task','task_family']}
                report=dict(episodes={sid:SimpleNamespace(artifact=record)},scores={sid:SimpleNamespace(score=score)})
                case=evidence.training_case(report,sid,bank,projector,reference)
                if not any(s['editable'] for s in case['steps']):discarded['no_editable_step']+=1;continue
                jobs.append(dict(id=sid,case=case,cards=[],score=score,cohort='expansion',
                    benchmark=benchmark,native_task=record['native_task'],outcome_stratum=group,
                    input_source=str(p),source_sha256=sha(p)))
                counts[group]+=1;task_counts[task]+=1
                if counts['correct']==8 and counts['not_fully_correct']==16:break
        assert counts['correct']==8 and counts['not_fully_correct']==16,(benchmark,counts)
        audit[benchmark]=dict(outcomes=dict(counts),native_tasks=dict(task_counts),discarded=dict(discarded))
    assert len(jobs)==88
    assert not ({j['case']['sample_id'] for j in jobs if j['cohort']=='expansion'} & excluded)
    output.mkdir(parents=True)
    save(output/'inputs.json',jobs)
    save(output/'sampling.json',dict(regression_cases=16,expansion_cases=72,unique_expansion_questions=72,
        excluded_prior_question_ids=len(excluded),prior_inputs={str(p):sha(p) for p in prior_files},
        source_run=str(root),benchmarks=audit,
        method='Deterministic hash ordering; round-robin native-task coverage; per benchmark 8 correct and16 not fully correct scored real traces. No localization output used for selection.',
        limits='Outcome-stratified diagnostic, not representative prevalence or independent Test; question-ID exclusion does not establish source-video isolation. CVBench native_task is all, so no fine category coverage guarantee. Added traces use no Skill; no new Actor/Judge.'))
    print(json.dumps(audit,ensure_ascii=False))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    prepare(p.parse_args().output.resolve())
