#!/usr/bin/env python3
"""Frozen paired 2x2 Global/Video Skill evaluation; no optimizer or API Judge."""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import yaml
ROOT=Path(os.environ.get('MVAGENT_PROJECT_ROOT',Path(__file__).resolve().parents[2]))
LOCAL=Path(__file__).resolve().parent
sys.path.insert(0,str(LOCAL/'src' if (LOCAL/'src').is_dir() else ROOT/'src'))
from mvagent.skills.bank import SkillBank
from mvagent.skills.prompts import render_skill_text
from skill_evolution.infra.data import DataSplitManifest,SplitSample,RolloutArtifact
from skill_evolution.infra.evaluation import episode_health
from skill_evolution.infra.store import write_json,file_fingerprint,tree_hash
SEED=20260926
PRIOR=ROOT/'outputs/analysis/20260925_acquisition_v002_transfer912'
ARMS=('G0V0','G1V0','G0V1','G1V1')

def read(p):return json.loads(Path(p).read_text())
def status(out,phase,**extra):
    write_json(out/'status.json',dict(phase=phase,pid=os.getpid(),updated_at=datetime.now(timezone.utc).isoformat(),**extra))

def collect():
    corpus=[]
    for name in ('20260925_acquisition_v002_1000','20260925_acquisition_v002_transfer912'):
        source=ROOT/'outputs/analysis'/name/'combined_review.json'
        for case in read(source):
            for i,action in enumerate(case['trajectory']):
                if action['action']!='analyze_videos':continue
                for request in action['parameters']['videoagent_request']:
                    corpus.append(dict(sample_id=case['sample_id'],action_index=i,**request,
                        video_metadata=case['videos'].get(request['video_id']),artifact=case['artifact'],
                        source_review=str(source)))
    # Instruction-only authoring selection; no answers, scores or reports used here.
    patterns={'local':r'check|determine if|whether','attribute':r'identify.*color|color of|frame color|shape of',
        'count':r'^Count |total number of|distinct colors used','interval':r'start and end|time interval|precise',
        'boundary':r'initial state|final state|beginning|end of the clip',
        'context':r'consequence|unnecessary|conflict|purpose',
        'followup':r'verify|re.check|precise'}
    ordered=sorted(corpus,key=lambda r:hashlib.sha256(json.dumps(r,sort_keys=True).encode()).hexdigest())
    author=[];seen=set()
    for family,pattern in patterns.items():
        picked=0
        for row in ordered:
            if row['sample_id'] in seen or not re.search(pattern,row['instruction'],re.I):continue
            if family=='followup' and row['action_index']==0:continue
            author.append({**row,'authoring_family':family});seen.add(row['sample_id']);picked+=1
            if picked==4:break
    # Include the concrete instructions that motivated the cards, not their answers.
    for sid in ('cvbench:970','cvbench:420','mvu_eval:OR:443','mvu_eval:Counting:1064','crossvid:FSA:2121'):
        if sid not in seen:
            row=next(r for r in corpus if r['sample_id']==sid)
            author.append({**row,'authoring_family':'previously_inspected'});seen.add(sid)
    return corpus,author

def prepare(out,per_task):
    from mvagent.utils.snapshot import ensure_source_snapshot
    from mvagent.configs import MVAgentConfig
    if out.exists():raise ValueError('Use a new output root; existing experiments resume only through frozen controller')
    corpus,author=collect()
    original=read(PRIOR/'panel.json');author_ids={r['sample_id'] for r in author}
    blocked={r['group_id'] for r in original if r['sample_id'] in author_ids}
    buckets=defaultdict(list)
    for r in original:
        if r['sample_id'] not in author_ids:
            buckets[r['bucket']].append({**r,'authoring_scope':'shared_source' if r['group_id'] in blocked else 'known_source_excluded'})
    chosen={}
    for key,rows in sorted(buckets.items()):
        chosen[key]=sorted(rows,key=lambda r:hashlib.sha256(f'{SEED}:{r["sample_id"]}'.encode()).hexdigest())[:per_task]
    if len(chosen)!=23:raise ValueError('An authoring-excluded task has no available cases')
    panel=[chosen[k][i] for i in range(per_task) for k in sorted(chosen) if i<len(chosen[k])]
    if any(len(v)<2 for v in chosen.values()):raise ValueError('Need at least two cases per task')
    out.mkdir(parents=True)
    write_json(out/'instruction_corpus.json',corpus);write_json(out/'authoring_instructions.json',author)
    write_json(out/'panel.json',panel)
    write_json(out/'exclusions.json',dict(authoring_ids=sorted(author_ids),authoring_source_groups=sorted(blocked),
        limits='Exact authoring IDs excluded; shared authoring path-groups retained and flagged to preserve task coverage; historical development exposure remains. Not independent Test.'))
    for phase,members in [('smoke',panel[:23]),('main',panel[23:]),('all',panel)]:
        DataSplitManifest('Paired Global/Video Skill matrix '+phase,SEED,
            tuple(SplitSample(r['sample_id'],'eval',r['group_id']) for r in members)).write(out/(phase+'_split.json'))
    g=read(ROOT/'configs/skill_evolution/skills/global_acquisition_v002.json')['skills']
    v=read(ROOT/'configs/skill_evolution/skills/video_evidence_v001.json')['skills']
    for arm in ARMS:
        d=out/arm;d.mkdir()
        bank=dict(schema_version=3,skills=(g if arm[1]=='1' else [])+(v if arm[3]=='1' else []))
        SkillBank.from_dict(bank);write_json(d/'skills.json',bank)
        config=yaml.safe_load((PRIOR/'runtime.yaml').read_text())
        for role in ('global_agent','video_agent'):
            config['agents'][role]['skill'].update(path=str(d/'skills.json'),sha256=file_fingerprint(d/'skills.json'),
                selection_scope='task',retrieval_top_k=8, embedding=dict(endpoint='http://127.0.0.1:8110/v1',model='qwen3_embedding_8b'))
        MVAgentConfig.from_dict(config)
        (d/'runtime.yaml').write_text(yaml.safe_dump(config,sort_keys=False))
        recipe=dict(algorithm='global-targeted-v1',dataset_root='/home/kww/datasets/Multi-Video',
            runtime=dict(mvagent_config=str(d/'runtime.yaml'),cache_dir=str(d/'cache')),open_qa_judge=dict(enabled=False))
        (d/'recipe.yaml').write_text(yaml.safe_dump(recipe,sort_keys=False))
    shutil.copyfile(PRIOR/'execution.yaml',out/'execution.yaml')
    ensure_source_snapshot(out);shutil.copyfile(__file__,out/'controller.py')
    paths=[out/'controller.py',out/'execution.yaml',out/'panel.json',out/'authoring_instructions.json',out/'exclusions.json']
    paths += [out/(phase+'_split.json') for phase in ('smoke','main','all')]
    paths += [out/arm/name for arm in ARMS for name in ('skills.json','runtime.yaml','recipe.yaml')]
    write_json(out/'control.json',dict(seed=SEED,questions=len(panel),rollouts=4*len(panel),arms=ARMS,
        corpus_instructions=len(corpus),authoring_instructions=len(author),per_task={k:len(v) for k,v in chosen.items()},
        datasets=dict(Counter(r['dataset'] for r in panel)),commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        source_hash=tree_hash(out/'src'),hashes={str(p.relative_to(out)):file_fingerprint(p) for p in paths}))
    status(out,'prepared')

def audit(out,arm,phase):
    base=out/arm;summary=read(base/phase/'summary.json');wanted=set(summary['samples']);cases={};errors=[]
    bank={c.id:c for c in SkillBank.from_dict(read(base/'skills.json')).cards}
    for path in sorted((base/'cache/rollouts').glob('*.json')):
        raw=read(path);sid=raw['sample_id']
        if sid not in wanted:continue
        if sid in cases:raise ValueError('Duplicate rollout cache identity for '+sid)
        a=raw['artifact'];events=a['events'];active={};scopes={};selections=[]
        requests={e['decision_id']:e for e in events if e.get('kind')=='structured_request' and e.get('schema') in ('global_decision','video_action')}
        for e in events:
            if e.get('kind') not in ('skill_selection','skill_reuse'):continue
            did=e.get('decision_id');role=e['role'];ids=[c['id'] for c in e.get('selected',[])]
            scope='global' if role=='global' else did.rsplit(':',1)[0]
            if e.get('status')!='ok' or len(ids)>1:errors.append([sid,did,'invalid selection'])
            if scope not in scopes:
                if e['kind']!='skill_selection':errors.append([sid,did,'missing initial selection'])
                scopes[scope]=ids
            elif ids!=scopes[scope] or e['kind']!='skill_reuse':errors.append([sid,did,'scope changed/reselected'])
            req=requests.get(did);text='\n'.join(m['content'] for m in (req or {}).get('messages',[]) if isinstance(m.get('content'),str))
            if req is None:errors.append([sid,did,'missing actor request'])
            for card in ids:
                if card not in bank or bank[card].role!=role or bank[card].render() not in text:
                    errors.append([sid,did,'wrong role or missing body'])
            active[did]=ids
            if e['kind']=='skill_selection':selections.append(dict(role=role,decision_id=did,selected=ids,reason=e.get('reason','')))
        if set(active)!=set(requests):errors.append([sid,'request/activation coverage'])
        cases[sid]=dict(sample_id=sid,score=summary['samples'][sid]['score'],prediction=summary['samples'][sid]['prediction'],
            selections=selections,health=episode_health(RolloutArtifact(sid,a,bucket=raw['bucket'])),
            question=a['result'].get('input',{}).get('question'),trajectory=a['result'].get('action_history',[]),artifact=str(path))
    if set(cases)!=wanted:raise ValueError('Missing rollout artifacts')
    report=dict(questions=len(cases),injection_errors=errors,health=dict(sum((Counter(c['health']) for c in cases.values()),Counter())),
        selection_counts={role:dict(Counter((s['selected'] or ['NONE'])[0] for c in cases.values() for s in c['selections'] if s['role']==role)) for role in ('global','video')})
    write_json(base/(phase+'_review.json'),list(cases.values()));write_json(base/(phase+'_audit.json'),report)
    return report

def factorial(rows):
    means={arm:sum(r[arm] for r in rows)/len(rows) for arm in ARMS}
    return dict(n=len(rows),accuracy=means,video_without_global=means['G0V1']-means['G0V0'],
        video_with_global=means['G1V1']-means['G1V0'],global_without_video=means['G1V0']-means['G0V0'],
        joint_vs_none=means['G1V1']-means['G0V0'],interaction=means['G1V1']-means['G1V0']-means['G0V1']+means['G0V0'],
        paired={label:dict(improved=sum(r[b]>r[a] for r in rows),regressed=sum(r[b]<r[a] for r in rows))
            for label,a,b in [('video_without_global','G0V0','G0V1'),('video_with_global','G1V0','G1V1'),('joint_vs_none','G0V0','G1V1')]})

def report(out):
    results={arm:{r['sample_id']:r for phase in ('smoke','main') for r in read(out/arm/(phase+'_review.json'))} for arm in ARMS}
    panel=read(out/'panel.json');ids={r['sample_id'] for r in panel}
    if any(set(v)!=ids for v in results.values()):raise ValueError('Matrix is not complete')
    rows=[dict(sample_id=r['sample_id'],dataset=r['dataset'],task=r['bucket'],group_id=r['group_id'],authoring_scope=r['authoring_scope'],
        **{arm:results[arm][r['sample_id']]['score'] for arm in ARMS}) for r in panel]
    metrics={key:{value:factorial([r for r in rows if r[key]==value]) for value in sorted({r[key] for r in rows})} for key in ('dataset','task','authoring_scope')}
    write_json(out/'matrix_scores.json',rows);write_json(out/'matrix_summary.json',metrics)
    lines=['# Global / Video Skill 2×2 results','', 'All four arms use the same frozen Runtime, models, split and budgets. Development evidence; no universal-gain claim.', '',json.dumps(metrics,ensure_ascii=False,indent=2)]
    (out/'report.md').write_text('\n'.join(lines)+'\n')

def controller(out):
    lock=(out/'controller.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    control=read(out/'control.json')
    for name,h in control['hashes'].items():
        if file_fingerprint(out/name)!=h:raise ValueError('Frozen input changed: '+name)
    if tree_hash(out/'src')!=control['source_hash']:raise ValueError('Frozen source changed')
    env={**os.environ,'PYTHONPATH':str(out/'src'),'MVAGENT_PROJECT_ROOT':str(ROOT),'PYTHONUNBUFFERED':'1'}
    for k in ('NO_PROXY','no_proxy'):env[k]=','.join(filter(None,[env.get(k,''),'localhost','127.0.0.1']))
    try:
        for phase in ('smoke','main'):
            for arm in ARMS:
                d=out/arm;run=d/phase;run.mkdir(exist_ok=True)
                if not (run/'summary.json').exists() or read(run/'summary.json').get('status')!='completed':
                    args=dict(config=str(d/'recipe.yaml'),execution_config=str(out/'execution.yaml'),output_dir=str(run),mode='evaluate',
                        split_manifest=str(out/(phase+'_split.json')),dataset_root=None,skills=str(d/'skills.json'),split='eval',limit=None,
                        repeat_id=out.name+'-'+arm,resume=(run/'manifest.json').exists())
                    code='import json,sys;from argparse import Namespace;from skill_evolution.runner import run;run(Namespace(**json.loads(sys.argv[1])))'
                    with (d/(phase+'.log')).open('a') as log:
                        child=subprocess.Popen([sys.executable,'-u','-c',code,json.dumps(args)],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
                        status(out,phase,arm=arm,child_pid=child.pid);rc=child.wait()
                    if rc:raise RuntimeError(f'{arm}/{phase} exited {rc}')
                check=audit(out,arm,phase)
                if phase=='smoke' and (check['injection_errors'] or check['health'].get('fatal',0)):raise RuntimeError('Smoke audit failed: '+arm)
        report(out);status(out,'completed',report=str(out/'report.md'))
    except Exception as exc:status(out,'failed',error=str(exc));raise

def main():
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['launch','run','report']);p.add_argument('--output',type=Path,required=True);p.add_argument('--per-task',type=int,default=20)
    a=p.parse_args();out=a.output.resolve()
    if a.mode=='launch':
        if a.per_task<2:raise ValueError('per-task must be at least two')
        prepare(out,a.per_task)
        with (out/'controller.log').open('a') as log:
            child=subprocess.Popen([sys.executable,'-u',str(out/'controller.py'),'run','--output',str(out)],cwd=ROOT,
                env={**os.environ,'MVAGENT_PROJECT_ROOT':str(ROOT)},stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        write_json(out/'launch.json',dict(pid=child.pid));print(json.dumps(dict(output=str(out),pid=child.pid)))
    elif a.mode=='run':controller(out)
    else:report(out)
if __name__=='__main__':main()
