#!/usr/bin/env python3
"""Freeze and sequentially evaluate the four Skill-selection duration arms."""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import yaml
ROOT = Path(os.environ.get('MVAGENT_PROJECT_ROOT', Path(__file__).resolve().parents[2]))
SOURCE = Path(__file__).resolve().parent/'src'
sys.path.insert(0, str(SOURCE if SOURCE.is_dir() else ROOT/'src'))
from mvagent.skills.bank import SkillBank
from skill_evolution.infra.store import write_json, file_fingerprint
from skill_evolution.infra.data import DataSplitManifest, SplitSample

ARMS = {'DD':('decision','decision'), 'DF':('decision','task'),
        'FD':('task','decision'), 'FF':('task','task')}
PRIOR = ROOT/'outputs/analysis/20260923_crossvid_gepa_expanded'


def status(out, phase, **kwargs):
    write_json(out/'status.json',dict(phase=phase,pid=os.getpid(),updated_at=datetime.now(timezone.utc).isoformat(),**kwargs))


def prepare(out):
    from mvagent.utils.snapshot import ensure_source_snapshot
    out.mkdir(parents=True, exist_ok=False)
    old = DataSplitManifest.from_json(PRIOR/'data/split.json')
    samples = [s for s in old.samples if s.split=='eval']
    # Outcome-blind engineering subset; same full manifest makes smoke caches reusable.
    smoke = [next(s for s in samples if s.sample_id.split(':')[1]==task)
             for task in ('BU','CC','FSA','MOC','MSR','NC','PEA','PI')]
    ids = {s.sample_id for s in smoke}
    samples = smoke + [s for s in samples if s.sample_id not in ids]
    DataSplitManifest('Skill duration diagnostic: reused GEPA Eval181',20260924,tuple(samples)).write(out/'split.json')
    shutil.copyfile(PRIOR/'train/search_bank.json',out/'skills.json')
    shutil.copyfile(PRIOR/'execution.yaml',out/'execution.yaml')
    shutil.copyfile(PRIOR/'runtime.yaml',out/'base_runtime.yaml')
    shutil.copyfile(ROOT/'scripts/analysis/credentials.py',out/'credential_reader.py')
    for name, (global_scope, video_scope) in ARMS.items():
        arm = out/name; arm.mkdir()
        runtime = yaml.safe_load((out/'base_runtime.yaml').read_text())
        for role,scope in [('global',global_scope),('video',video_scope)]:
            settings=runtime['agents'][role+'_agent']['skill']
            settings['selection_scope']=scope
            settings.update(path=str(out/'skills.json'),sha256=file_fingerprint(out/'skills.json'))
        (arm/'runtime.yaml').write_text(yaml.safe_dump(runtime,sort_keys=False))
        recipe=yaml.safe_load((PRIOR/'recipe.yaml').read_text())
        recipe['runtime']=dict(mvagent_config=str(arm/'runtime.yaml'),cache_dir=str(arm/'cache'))
        (arm/'recipe.yaml').write_text(yaml.safe_dump(recipe,sort_keys=False))
    ensure_source_snapshot(out)
    shutil.copyfile(__file__,out/'controller.py')
    write_json(out/'control.json',dict(commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        arms=ARMS,questions=len(samples),smoke_questions=[s.sample_id for s in smoke],
        initial_bank='frozen prior search best, not published',keys_file=str(ROOT/'.local/skill_evolution_keys.env'),
        hashes={str(p.relative_to(out)):file_fingerprint(p) for p in [out/'skills.json',out/'split.json',out/'execution.yaml',
            out/'controller.py',out/'credential_reader.py',*[out/name/'runtime.yaml' for name in ARMS],*[out/name/'recipe.yaml' for name in ARMS]]},
        limits='Reused development Eval; no optimizer or new no-Skill baseline; all four arms freshly matched.'))


def run_child(out, name, phase, env):
    run=out/name/phase
    done=run/'summary.json'
    if done.exists() and json.loads(done.read_text()).get('status')=='completed':return
    resume=(run/'manifest.json').exists()
    args=dict(config=str(out/name/'recipe.yaml'),execution_config=str(out/'execution.yaml'),output_dir=str(run),
        mode='evaluate',split_manifest=str(out/'split.json'),dataset_root=None,skills=str(out/'skills.json'),
        split='eval',limit=8 if phase=='smoke' else None,repeat_id='skill-duration-20260924',resume=resume)
    write_json(out/name/(phase+'_invocation.json'),args)
    code='import json,sys; from argparse import Namespace; from skill_evolution.runner import run; run(Namespace(**json.loads(sys.argv[1])))'
    with (out/name/(phase+'.log')).open('a') as log:
        p=subprocess.Popen([sys.executable,'-u','-c',code,json.dumps(args)],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
        status(out,phase,arm=name,child_pid=p.pid,log=str(out/name/(phase+'.log')))
        rc=p.wait()
    if rc:raise RuntimeError(f'{name}/{phase} failed ({rc}); completed rollouts retained')


def audit_arm(out, name, phase):
    result=json.loads((out/name/phase/'summary.json').read_text())
    cases={}; counts=Counter(); total_seen=0
    for f in (out/name/'cache/rollouts').glob('*.json'):
        d=json.loads(f.read_text());sid=d['sample_id']
        if sid not in result['samples']:continue
        a=d['artifact']; seq=defaultdict(list); requests={}
        for e in a['events']:
            if e['kind']=='structured_request' and e.get('schema') in ('global_decision','video_action'):
                requests[e['decision_id']]=e
            if e['kind'] in ('skill_selection','skill_reuse'):
                key='global' if e['role']=='global' else e['decision_id'].rsplit(':',1)[0]
                seq[key].append(e)
            if e['kind']=='model_response':counts['selector_calls' if e.get('skill_phase')=='selection' else 'other_calls']+=1
        bank={c.id:c.render() for c in SkillBank.from_dict(json.loads((out/'skills.json').read_text())).cards}
        for key,events in seq.items():
            scope=ARMS[name][0 if key=='global' else 1]
            if scope=='task':
                assert events[0]['kind']=='skill_selection', (name,sid,key)
                assert all(e['kind']=='skill_reuse' and e['selected']==events[0]['selected'] for e in events[1:]), (name,sid,key)
            else:assert all(e['kind']=='skill_selection' for e in events), (name,sid,key)
            for e in events:
                actor=requests.get(e['decision_id'])
                assert actor is not None, (name,sid,e['decision_id'])
                text='\n'.join(m['content'] for m in actor['messages'] if isinstance(m.get('content'),str))
                for card in e['selected']:assert bank[card['id']] in text, (name,sid,card)
                total_seen+=1
        cases[sid]=dict(sequences=len(seq),skill_events=sum(map(len,seq.values())))
    assert set(cases)==set(result['samples']), (name,phase,len(cases))
    if phase=='smoke':
        assert not any(s.get('fatal',0) or s.get('invalid',0) for s in result['samples'].values()), name
    write_json(out/name/(phase+'_audit.json'),dict(samples=len(cases),skill_events=total_seen,calls=dict(counts),
        scope_and_injection_verified=True))


def report(out):
    summaries={name:json.loads((out/name/'main/summary.json').read_text()) for name in ARMS}
    base=summaries['DD']; rows=[]
    for name,d in summaries.items():
        assert set(d['samples'])==set(base['samples'])
        rows.append(dict(arm=name,score=d['score'],delta=d['score']-base['score'],buckets=d['bucket_scores'],
            gains=sum(d['samples'][s]['score']>base['samples'][s]['score'] for s in d['samples']),
            losses=sum(d['samples'][s]['score']<base['samples'][s]['score'] for s in d['samples']),
            health={k:sum(v.get(k,0) for v in d['samples'].values()) for k in ('fatal','invalid','model_errors')},
            audit=json.loads((out/name/'main_audit.json').read_text())))
    write_json(out/'comparison.json',dict(arms=rows,limits='Development diagnostic; no automatic promotion.'))
    lines=['# Skill selection duration diagnostic','','|Arm|Macro %|Δ vs DD pp|Improved questions|Regressed questions|','|---|---:|---:|---:|---:|']
    lines += [f"|{r['arm']}|{100*r['score']:.3f}|{100*r['delta']:+.3f}|{r['gains']}|{r['losses']}|" for r in rows]
    (out/'report.md').write_text('\n'.join(lines)+'\n')


def controller(out):
    import fcntl, importlib.util
    with (out/'controller.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        try:
            manifest=json.loads((out/'control.json').read_text())
            assert all(file_fingerprint(out/p)==h for p,h in manifest['hashes'].items()), 'Frozen input changed'
            spec=importlib.util.spec_from_file_location('credential_reader',out/'credential_reader.py')
            m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
            env={**os.environ,**m.credentials(manifest['keys_file']),'PYTHONPATH':str(out/'src'),'MVAGENT_PROJECT_ROOT':str(ROOT)}
            if not env.get('DEEPSEEK_API_KEY'):raise RuntimeError('Missing Judge credential')
            for key in ('NO_PROXY','no_proxy'):env[key]=','.join(filter(None,[env.get(key,''),'localhost','127.0.0.1']))
            for phase in ('smoke','main'):
                for name in ARMS:
                    run_child(out,name,phase,env);audit_arm(out,name,phase)
            report(out);status(out,'completed')
        except Exception as exc:
            status(out,'failed',error=str(exc));raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['launch','controller','status'])
    parser.add_argument('--output',default='outputs/analysis/20260924_skill_duration')
    args=parser.parse_args();out=Path(args.output).resolve()
    if args.command=='launch':
        prepare(out)
        with (out/'controller.log').open('w') as log:
            p=subprocess.Popen([sys.executable,'-u',str(out/'controller.py'),'controller','--output',str(out)],
                cwd=ROOT,env={**os.environ,'MVAGENT_PROJECT_ROOT':str(ROOT)},stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        write_json(out/'launch.json',dict(pid=p.pid));print(json.dumps(dict(pid=p.pid,output=str(out))))
    elif args.command=='controller':controller(out)
    else:print((out/'status.json').read_text())
