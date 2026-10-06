#!/usr/bin/env python3
"""Describe paired real trajectories and fixed-input probes without treating routes as GT."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'src'))
from mvagent.skills.bank import SkillBank
from skill_evolution.infra.data import RolloutArtifact
from skill_evolution.infra.evaluation import episode_health
from skill_evolution.infra.store import write_json

def read(p):return json.loads(Path(p).read_text())
def choices(e):return [c['id'] for c in e.get('selected',[])]
def action(v):return dict(action=v.get('action'),parameters=v.get('parameters'))
def decisions(raw,role):return [e for e in raw['artifact']['events'] if e.get('kind')=='structured_parsed' and e.get('skill_phase')!='selection' and e.get('agent')==role+'Agent' and 'action' in e.get('value',{})]
def global_skill(raw):return next((choices(e) for e in raw['artifact']['events'] if e.get('kind')=='skill_selection' and e.get('role')=='global'),[])
def stats(records):
    result={};health=Counter()
    for r in records:health.update(episode_health(RolloutArtifact(r['sample_id'],r['artifact'],bucket=r['bucket'])))
    for role in ('Global','Video'):
        ds=[e['value'] for r in records for e in decisions(r,role)]
        skills=[e for r in records for e in r['artifact']['events'] if e.get('kind')=='skill_selection' and e.get('role')==role.lower()]
        result[role]=dict(actions=dict(Counter(v['action'] for v in ds)),selections=dict(Counter((choices(e) or ['NONE'])[0] for e in skills)),selection_calls=len(skills))
    result['health']=dict(health)
    obs=[v['value']['parameters'] for r in records for v in decisions(r,'Video') if v['value']['action']=='observe']
    result['observe_parameters']=dict(fps=dict(Counter(str(p.get('fps')) for p in obs)),range_counts=dict(Counter(len(p.get('where',[])) for p in obs)))
    guidance={}
    for sid,expected in [('global-direct-detail-watch','watch_videos'),('global-independent-focused-analysis','analyze_videos'),('global-survey-then-focus','analyze_videos')]:
        rows=[r for r in records if global_skill(r)==[sid]]
        guidance[sid]=dict(selected=len(rows),first_action_matches=sum(bool(decisions(r,'Global')) and decisions(r,'Global')[0]['value']['action']==expected for r in rows))
    result['first_action_guidance_proxy']=guidance
    return result

def summarize(out):
    old_paths=read(out/'baseline_paths.json');old={sid:read(p) for sid,p in old_paths.items()}
    new={r['sample_id']:r for p in (out/'cache/rollouts').glob('*.json') if (r:=read(p))['sample_id'] in old}
    assert set(old)==set(new)
    scores=read(out/'evaluation/summary.json')['samples'];old_scores=read(out/'baseline_scores.json')
    bank=SkillBank.from_dict(read(out/'skills.json'));cards={c.id:c for c in bank.cards};errors=[];injections=Counter();cases=[]
    for sid,r in new.items():
        assert r['artifact']['result']['input']==old[sid]['artifact']['result']['input']
        events=r['artifact']['events'];requests={e['decision_id']:e for e in events if e.get('kind')=='structured_request' and e.get('schema') in ('global_decision','video_action')};scopes={};activated=set()
        for e in events:
            if e.get('kind') not in ('skill_selection','skill_reuse'):continue
            did=e['decision_id'];activated.add(did);ids=choices(e);scope='global' if e['role']=='global' else did.rsplit(':',1)[0]
            if e.get('status')!='ok' or len(ids)>1:errors.append([sid,did,'invalid selection'])
            if scope not in scopes and e['kind']!='skill_selection':errors.append([sid,did,'missing initial selection'])
            if scope in scopes and (scopes[scope]!=ids or e['kind']!='skill_reuse'):errors.append([sid,did,'scope changed'])
            scopes[scope]=ids
            req=requests.get(did);text='\n'.join(m['content'] for m in (req or {}).get('messages',[]) if isinstance(m.get('content'),str))
            if req is None:errors.append([sid,did,'missing actor request'])
            if ids:
                body=bank.render(ids)
                if body not in text or cards[ids[0]].role!=e['role']:errors.append([sid,did,'missing/wrong body'])
                region=text.split('\n## Decision strategy\n')[-1].split('\n## Output contract\n')[0]
                if '\n### When-to-Use\n' in region or '\n### Common Pitfalls\n' in region:errors.append([sid,did,'old sections injected'])
                injections[e['role']]+=1
        if activated!=set(requests):errors.append([sid,'activation/request coverage'])
        for req in events:
            if req.get('kind')=='structured_request' and req.get('schema')=='skill_selection':
                payload=json.loads(req['messages'][-1]['content'])
                if any(set(c)!={'id','description','when_to_use'} for c in payload['candidates']):errors.append([sid,req['decision_id'],'selector field leak'])
                if len(payload['candidates'])>8:errors.append([sid,req['decision_id'],'candidate cap'])
        first_old=action(decisions(old[sid],'Global')[0]['value']);first_new=action(decisions(r,'Global')[0]['value'])
        cases.append(dict(sample_id=sid,old_score=old_scores[sid]['score'],new_score=scores[sid]['score'],old_skill=global_skill(old[sid]),new_skill=global_skill(r),old_first=first_old,new_first=first_new,question=r['artifact']['result']['input']['question'],old_artifact=old_paths[sid],new_artifact=next(str(p) for p in (out/'cache/rollouts').glob('*.json') if read(p)['sample_id']==sid)))
    metrics={}
    for group in ('all','cvbench','mvu_eval'):
        rows=[c for c in cases if group=='all' or c['sample_id'].startswith(group+':')]
        metrics[group]=dict(n=len(rows),old_correct=sum(c['old_score'] for c in rows),new_correct=sum(c['new_score'] for c in rows),improved=sum(c['new_score']>c['old_score'] for c in rows),regressed=sum(c['new_score']<c['old_score'] for c in rows),route_changed=sum(c['old_skill']!=c['new_skill'] for c in rows),first_action_changed=sum(c['old_first']['action']!=c['new_first']['action'] for c in rows))
    probe_rows=[]
    for p in sorted((out/'probes').glob('*.json')):
        r=read(p);j=r['job'];row=dict(path=str(p),kind=j['kind'],role=j['role'],sample_id=j['sample_id'],status=r['result']['status'],old_ids=j['old_ids'])
        if j['kind']=='selection' and r['result']['status']=='ok':
            se=next(e for e in reversed(r['events']) if e['kind']=='skill_selection');re=next(e for e in r['events'] if e['kind']=='skill_retrieval');row.update(new_ids=choices(se),changed=j['old_ids']!=choices(se),recalled=[c['id'] for c in re['candidates']],reason=se['reason'],retriever=re['retriever'])
            row['old_selected_recalled']=all(s in row['recalled'] for s in j['old_ids']) if j['old_ids'] else None
        elif j['kind']=='execution' and r['result']['status']=='ok' and (r.get('control') or {}).get('status')=='ok':
            nv,ov=r['result']['value'],r['control']['value'];row.update(old_action=action(ov),new_action=action(nv),action_changed=ov['action']!=nv['action'],parameters_changed=ov['parameters']!=nv['parameters'],control_matches_historical=action(ov)==action(j['old_action']))
        probe_rows.append(row)
    probes={}
    for kind in ('selection','execution'):
        for role in ('global','video'):
            rows=[r for r in probe_rows if r['kind']==kind and r['role']==role];keys=('changed','old_selected_recalled') if kind=='selection' else ('action_changed','parameters_changed','control_matches_historical')
            probes[kind+'/'+role]=dict(n=len(rows),status=dict(Counter(r['status'] for r in rows)),**{k:dict(yes=sum(r.get(k) is True for r in rows),eligible=sum(r.get(k) is not None for r in rows)) for k in keys})
    summary=dict(paired=metrics,old=stats(list(old.values())),new=stats(list(new.values())),injection_errors=errors,checked_selected_injections=dict(injections),probes=probes,limits='Development46, task balanced; no independent Test or significant gain claim. E2E changes jointly affect retrieval, selector and body rendering. Fixed-input execution compares fresh old/new bodies under identical selected skill and evidence; no tool calls are executed in that probe. Exact parameter inequality need not imply semantic change.')
    write_json(out/'comparison.json',summary);write_json(out/'paired_cases.json',cases);write_json(out/'probe_comparison.json',probe_rows)
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();summarize(a.output.resolve())
