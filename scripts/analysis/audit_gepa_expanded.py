#!/usr/bin/env python3
"""Read-only audit of frozen GEPA rollouts, routing, and proposal support."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
from types import SimpleNamespace
from skill_evolution.infra.bank import BankSnapshot
from skill_evolution.infra.trajectory import routing_audit
from skill_evolution.infra.store import write_json


def audit(root, output):
    train = root/'train'
    banks = {p.parent.name:BankSnapshot.from_dict(json.loads(p.read_text())) for p in (train/'banks').glob('*/bank.json')}
    split = json.loads((train/'split_manifest.json').read_text())
    eval_ids = {s['sample_id'] for s in split['samples'] if s['split'] == 'eval'}
    evals = {}
    for f in (train/'evaluations').glob('*.json'):
        d = json.loads(f.read_text())
        if set(d['scores']) == eval_ids: evals[d['bank_hash']] = d
    groups = json.loads((train/'source_groups.json').read_text())
    compact = defaultdict(dict)
    for f in (root/'cache/rollouts').glob('*.json'):
        d = json.loads(f.read_text()); a=d['artifact']; b=a['execution']['pair_hash']; sid=d['sample_id']
        if b not in evals or sid not in evals[b]['scores']: continue
        report=dict(episodes={sid:SimpleNamespace(artifact=a)},scores={sid:SimpleNamespace(score=evals[b]['scores'][sid])})
        rows=routing_audit(banks[b],report,groups)['rows']
        selection={e['decision_id']:e for e in a['events'] if e['kind']=='skill_selection'}
        for row in rows:
            e=selection[row['decision_id']]
            row.update(stage=e['stage'],reason=e.get('reason'),assessment=e.get('assessment'))
        calls=Counter();seconds=Counter();tokens=Counter()
        for e in a['events']:
            phase='selector' if e.get('skill_phase')=='selection' else 'other'
            if e['kind']=='model_response':
                calls[phase]+=1
                for k in ('prompt_tokens','completion_tokens'):tokens[phase+'_'+k]+=(e.get('usage') or {}).get(k,0)
            if e['kind']=='model_end': seconds[phase]+=e.get('seconds',0)
        sequences=defaultdict(list)
        for row in rows:
            key='global' if row['role']=='global' else row['decision_id'].rsplit(':',1)[0]
            sequences[key].append(row['selected'])
        compact[b][sid]=dict(path=str(f),score=evals[b]['scores'][sid],prediction=a['prediction'],rows=rows,
            sequences=dict(sequences),calls=dict(calls),seconds=dict(seconds),tokens=dict(tokens),
            actions=a['result']['action_history'])
    summary={}
    for b, cases in compact.items():
        assert set(cases)==set(evals[b]['scores']), (b,len(cases))
        tasks={}; switches={}; totals=Counter()
        for task in sorted({s.split(':')[1] for s in cases}):
            subset={s:c for s,c in cases.items() if s.split(':')[1]==task}
            cards={card.id:dict(selected_questions=sum(any(card.id in r['selected'] for r in c['rows']) for c in subset.values()),
                injected_questions=sum(any(card.id in (r['injected'] or []) for r in c['rows']) for c in subset.values()),
                selected_decisions=sum(card.id in r['selected'] for c in subset.values() for r in c['rows'])) for card in banks[b].bank.cards}
            tasks[task]=dict(n=len(subset),cards=cards)
        for role in ('global','video'):
            seqs=[seq for c in cases.values() for key,seq in c['sequences'].items() if (key=='global')==(role=='global')]
            switches[role]=dict(sequences=len(seqs),decisions=sum(map(len,seqs)),multi_step=sum(len(s)>1 for s in seqs),
                changed=sum(any(s[i]!=s[i-1] for i in range(1,len(s))) for s in seqs),
                first_empty_later_selected=sum(not s[0] and any(s[1:]) for s in seqs),
                first_selected_later_empty=sum(bool(s[0]) and any(not x for x in s[1:]) for s in seqs),
                oscillation=sum(any(s[i]==s[i-2] and s[i]!=s[i-1] for i in range(2,len(s))) for s in seqs))
        for c in cases.values():
            totals.update(c['calls']);totals.update(c['tokens'])
        summary[b]=dict(score=evals[b]['score'],bucket_scores=evals[b]['bucket_scores'],tasks=tasks,switches=switches,
            totals=dict(totals),initial_selected=Counter(r['role'] for c in cases.values() for r in c['rows'] if r['stage']=='initial' and r['selected']))
    proposals=[]
    for p in sorted((train/'proposals').glob('*/proposal.json'),key=lambda p:p.stat().st_mtime):
        proposal=json.loads(p.read_text())['value']['candidates'][0]
        payload=json.loads((p.parent/'optimizer_input.json').read_text())['payload'];ev=payload['trajectories'];src=proposal['source_skill_ids']
        support={}
        for label,refs in dict(all=list(ev),cited=proposal['evidence_refs'],**proposal['coverage_refs']).items():
            cases=[ev[r] for r in refs]
            support[label]=dict(cases=len(cases),questions=len({c['sample_id'] for c in cases}),
                groups=len({c['source_group'] for c in cases}),tasks=dict(Counter(c['sample_id'].split(':')[1] for c in cases)),
                source_selected_cases=sum(any(set(src).intersection(v['id'] for v in (x.get('selected') or [])) for x in c['routing']) for c in cases),
                source_injected_cases=sum(any(set(src).intersection(x.get('injected') or []) for x in c['routing']) for c in cases))
        child=json.loads((p.parent/'validation.json').read_text()).get('bank_hash')
        proposals.append(dict(path=str(p),op=proposal['op'],role=proposal['role'],source=src,parent=payload['parent_bank_hash'],child=child,
            parent_score=evals.get(payload['parent_bank_hash'],{}).get('score'),child_score=evals.get(child,{}).get('score'),
            support=support,reason=proposal['reason'],expected_behavior=proposal['expected_behavior']))
    write_json(output/'audit.json',dict(banks=summary,proposals=proposals))
    write_json(output/'cases.json',compact)
    print(json.dumps(dict(banks=len(summary),evaluated_questions=sum(len(v) for v in compact.values()),proposals=len(proposals))))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',default='outputs/analysis/20260923_crossvid_gepa_expanded')
    parser.add_argument('--output',default='outputs/analysis/20260924_gepa_routing_audit')
    args=parser.parse_args();audit(Path(args.root),Path(args.output))
