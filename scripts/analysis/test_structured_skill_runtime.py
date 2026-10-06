#!/usr/bin/env python3
"""Paired real-QA check plus fixed-input selection/execution probes; no optimizer/Judge."""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
import yaml

ROOT=Path(os.environ.get('MVAGENT_PROJECT_ROOT',Path(__file__).resolve().parents[2]))
LOCAL=Path(__file__).resolve().parent
sys.path.insert(0,str(LOCAL/'src' if (LOCAL/'src').is_dir() else ROOT/'src'))
from mvagent.skills.bank import SkillBank
from mvagent.skills.prompts import render_skill_text
from mvagent.skills.selection import select_skills
from skill_evolution.infra.store import write_json,file_fingerprint,tree_hash
from skill_evolution.infra.data import DataSplitManifest,SplitSample
OLD=ROOT/'outputs/analysis/20260926_video_skill_matrix460'

def read(p):return json.loads(Path(p).read_text())
def status(out,phase,**kw):write_json(out/'status.json',dict(phase=phase,updated=datetime.now(timezone.utc).isoformat(),pid=os.getpid(),**kw))

def prepare(out):
    from mvagent.utils.snapshot import ensure_source_snapshot
    from mvagent.configs import MVAgentConfig
    out.mkdir(exist_ok=False,parents=True)
    panel=read(OLD/'panel.json')[:46]
    assert len(panel)==46 and set(Counter(r['bucket'] for r in panel).values())=={2}
    write_json(out/'panel.json',panel)
    DataSplitManifest('Structured Skill paired engineering development panel',20260926,
        tuple(SplitSample(r['sample_id'],'eval',r['group_id']) for r in panel)).write(out/'split.json')
    bank=dict(schema_version=3,skills=sum((read(ROOT/'configs/skill_evolution/skills'/name)['skills'] for name in ('global_acquisition_v002.json','video_evidence_v001.json')),[]))
    SkillBank.from_dict(bank);write_json(out/'skills.json',bank)
    cfg=yaml.safe_load((OLD/'G1V1/runtime.yaml').read_text())
    for role in ('global_agent','video_agent'):
        cfg['agents'][role]['skill'].update(path=str(out/'skills.json'),sha256=file_fingerprint(out/'skills.json'),
            retrieval_top_k=8,embedding=dict(endpoint='http://127.0.0.1:8110/v1',model='qwen3_embedding_8b'))
    MVAgentConfig.from_dict(cfg)
    (out/'runtime.yaml').write_text(yaml.safe_dump(cfg,sort_keys=False))
    shutil.copyfile(OLD/'execution.yaml',out/'execution.yaml')
    recipe=dict(algorithm='global-targeted-v1',dataset_root='/home/kww/datasets/Multi-Video',
        runtime=dict(mvagent_config=str(out/'runtime.yaml'),cache_dir=str(out/'cache')),open_qa_judge=dict(enabled=False))
    (out/'recipe.yaml').write_text(yaml.safe_dump(recipe,sort_keys=False))
    ids={r['sample_id'] for r in panel};base=out/'baseline';base.mkdir();paths={}
    # Preserve exact historical requests, not reconstructed trajectories.
    for p in (OLD/'G1V1/cache/rollouts').glob('*.json'):
        raw=read(p);sid=raw['sample_id']
        if sid in ids:
            if sid in paths:raise ValueError('Duplicate old record: '+sid)
            target=base/p.name;shutil.copyfile(p,target);paths[sid]=str(target)
    assert set(paths)==ids
    write_json(out/'baseline_paths.json',paths)
    old_scores={sid:v for phase in ('smoke','main') for sid,v in read(OLD/'G1V1'/phase/'summary.json')['samples'].items() if sid in ids}
    write_json(out/'baseline_scores.json',old_scores);shutil.copyfile(OLD/'G1V1/skills.json',out/'old_skills.json')
    probe_jobs(out)  # Validate historical event contracts before spending inference.
    ensure_source_snapshot(out);shutil.copyfile(__file__,out/'controller.py')
    files=[p for p in out.rglob('*') if p.is_file() and 'src' not in p.relative_to(out).parts]
    write_json(out/'manifest.json',dict(commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        source_hash=tree_hash(out/'src'),files={str(p.relative_to(out)):file_fingerprint(p) for p in files},
        protocol='First46 historical panel IDs,2 per23 tasks; same Actor/config except structured Skill system. Historical paired comparison, not isolated causal proof. Fixed-input probes isolate visible selector context / body rendering. No optimizer/API Judge.'))
    status(out,'prepared')

def probe_jobs(out):
    jobs=[]
    old_cards={c['id']:c for c in read(out/'old_skills.json')['skills']}
    bank=SkillBank.from_dict(read(out/'skills.json'))
    for sid,path in read(out/'baseline_paths.json').items():
        ev=read(path)['artifact']['events'];used=set()
        for e in ev:
            if e.get('kind')!='skill_selection' or e.get('status')!='ok' or e['role'] in used:continue
            role=e['role'];did=e['decision_id'];used.add(role)
            req=next(x for x in ev if x.get('kind')=='structured_request' and x.get('schema')=='skill_selection' and x.get('decision_id')==did)
            payload=json.loads(req['messages'][-1]['content']);task=payload['query'];state={}
            if role=='global' and '\nVideos: ' in task:
                task,videos=task.rsplit('\nVideos: ',1);state['videos']=json.loads(videos)
            history=payload['history'];state['history']=history.removeprefix('Assistant: ')
            # Source records use the historical JSON input; current rollouts render text.
            regenerated = task + ('\nVideos: ' + json.dumps(state['videos'], ensure_ascii=False) if state.get('videos') else '')
            assert regenerated == payload['query']
            old_ids=[x['id'] for x in e['selected']]
            jobs.append(dict(kind='selection',sample_id=sid,role=role,decision_id=did,stage=e['stage'],task=task,state=state,old_ids=old_ids))
            if old_ids:
                request=next(x for x in ev if x.get('kind')=='structured_request' and x.get('schema') in ('global_decision','video_action') and x.get('decision_id')==did)
                parsed=next(x for x in ev if x.get('kind')=='structured_parsed' and x.get('skill_phase')!='selection' and 'action' in x.get('value',{}) and x.get('decision_id')==did)
                old_body=render_skill_text(old_cards[old_ids[0]]['content']);messages=deepcopy(request['messages']);replaced=0
                for m in messages:
                    if isinstance(m['content'],str) and old_body in m['content']:
                        replaced+=m['content'].count(old_body);m['content']=m['content'].replace(old_body,bank.render(old_ids))
                assert replaced==1
                jobs.append(dict(kind='execution',sample_id=sid,role=role,decision_id=did,old_ids=old_ids,
                    messages=messages,control_messages=request['messages'],json_schema=request['json_schema'],schema=request['schema'],old_action=parsed['value']))
    return jobs

def probes(out):
    from mvagent.configs import MVAgentConfig
    from mvagent.batch import BatchExecutor,ExecutionConfig
    from models.factory import ModelFactory
    from models.pool import install_pools
    from models.execution import execution_scope
    cfg=MVAgentConfig.from_yaml(out/'runtime.yaml');events=[];clients=[];local=threading.local()
    batch=BatchExecutor(ExecutionConfig.from_yaml(out/'execution.yaml'),on_event=events.append)
    bank=SkillBank.load(path=str(out/'skills.json'),sha256=file_fingerprint(out/'skills.json'),embedding=cfg.global_agent.skill.embedding)
    jobs=probe_jobs(out);write_json(out/'probe_jobs.json',jobs);(out/'probes').mkdir(exist_ok=True)
    try:
        batch.prepare(cfg.to_dict());write_json(out/'probe_pool.json',events);install_pools(batch.pools)
        def work(pair):
            i,j=pair;p=out/'probes'/f'{i:03d}.json'
            if p.exists():return read(p)['result']['status']
            if not hasattr(local,'model'):
                local.model=ModelFactory.create_model(cfg.global_agent.model,cfg);clients.append(local.model)
            recorded=[];control=None
            def decide(prompt,**kw):return local.model.json_chat(messages=[dict(role='system',content=kw['system_prompt']),dict(role='user',content=prompt)],json_schema=kw['json_schema'],schema_name=kw['schema_name'],temperature=0.,top_p=1,max_tokens=2048)
            try:
                with execution_scope(emit=recorded.append,deadline=time.monotonic()+240):
                    if j['kind']=='selection':
                        result=select_skills(bank,role=j['role'],has_evidence=j['stage']=='evidence',task=j['task'],state=j['state'],decide=decide,selection_cache={})
                    else:
                        values={}
                        for arm in (('control_messages','messages') if i%2 else ('messages','control_messages')):
                            values[arm]=local.model.json_chat(messages=j[arm],json_schema=j['json_schema'],schema_name=j['schema'],temperature=0.,top_p=1,max_tokens=2048)
                        result,control=values['messages'],values['control_messages']
            except Exception as exc:result=dict(status='error',error=str(exc))
            write_json(p,dict(job=j,result=result,control=control,events=recorded));return result['status']
        counts=Counter()
        with ThreadPoolExecutor(max_workers=6) as pool:
            for f in as_completed([pool.submit(work,x) for x in enumerate(jobs)]):
                counts[f.result()]+=1;status(out,'probes',completed=sum(counts.values()),total=len(jobs),counts=counts)
    finally:
        for c in clients:c.close()
        batch.close()

def controller(out):
    lock=(out/'controller.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    manifest=read(out/'manifest.json')
    assert tree_hash(out/'src')==manifest['source_hash']
    assert all(file_fingerprint(out/p)==h for p,h in manifest['files'].items())
    try:
        dest=out/'evaluation';dest.mkdir(exist_ok=True)
        if not (dest/'summary.json').exists():
            args=dict(config=str(out/'recipe.yaml'),execution_config=str(out/'execution.yaml'),output_dir=str(dest),mode='evaluate',split_manifest=str(out/'split.json'),dataset_root=None,skills=str(out/'skills.json'),split='eval',limit=None,repeat_id=out.name,resume=(dest/'manifest.json').exists())
            code='import json,sys;from argparse import Namespace;from skill_evolution.runner import run;run(Namespace(**json.loads(sys.argv[1])))'
            env={**os.environ,'PYTHONPATH':str(out/'src'),'MVAGENT_PROJECT_ROOT':str(ROOT),'PYTHONUNBUFFERED':'1'}
            with (out/'evaluation.log').open('a') as log:
                child=subprocess.Popen([sys.executable,'-u','-c',code,json.dumps(args)],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
                status(out,'evaluation',child_pid=child.pid,questions=46);rc=child.wait()
            if rc:raise RuntimeError('Evaluation failed: '+str(rc))
        probes(out);status(out,'completed')
    except Exception as exc:status(out,'failed',error=str(exc));raise

def main():
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['launch','run']);p.add_argument('--output',type=Path,required=True);a=p.parse_args();out=a.output.resolve()
    if a.mode=='launch':
        prepare(out)
        with (out/'controller.log').open('a') as log:child=subprocess.Popen([sys.executable,'-u',str(out/'controller.py'),'run','--output',str(out)],cwd=ROOT,env={**os.environ,'MVAGENT_PROJECT_ROOT':str(ROOT)},stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        write_json(out/'launch.json',dict(pid=child.pid));print(json.dumps(dict(output=str(out),pid=child.pid)))
    else:controller(out)
if __name__=='__main__':main()
