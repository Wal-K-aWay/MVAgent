"""Summarize completed visibility A/B calls and prepare arm-blinded evidence review."""
from collections import Counter,defaultdict
from importlib import import_module
from pathlib import Path
import argparse
import json
import random
import sys


def read(p):return json.loads(p.read_text())
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def signature(row):
    if row['status']!='ok':return None
    v=row['value'];return (v['status'],tuple((x['step'],x['fault_type']) for x in v['fault_chain']))


def run(root):
    status=read(root/'status.json')
    if status['status']!='completed':raise ValueError('Wait for completed status before summarizing')
    cases=read(root/'inputs.json');results=read(root/'results.json')
    arm_names=read(root/'protocol.json')['arms']
    assert len(arm_names)==2
    first_arm,second_arm=arm_names
    index={(x['case_id'],x['arm'],x['repeat']):x for x in results}
    expected_calls=len(cases)*len(arm_names)*2
    assert len(index)==len(results)==expected_calls
    expected={(c['experiment_case_id'],a,r) for c in cases for a in arm_names for r in range(2)}
    assert set(index)==expected
    groups={}
    subsets={'all':cases,'actual_skill':[c for c in cases if c['used_skill_present']],
        'no_actual_skill':[c for c in cases if not c['used_skill_present']],
        'correct_controls':[c for c in cases if c['score']==1]}
    for cohort in sorted({c['cohort'] for c in cases if 'cohort' in c}):
        subsets[cohort]=[c for c in cases if c.get('cohort')==cohort]
        for benchmark in sorted({c['case']['sample_id'].split(':')[0] for c in subsets[cohort]}):
            subsets[cohort+':'+benchmark]=[c for c in subsets[cohort] if c['case']['sample_id'].split(':')[0]==benchmark]
    for label,selected in subsets.items():
        ids={c['experiment_case_id'] for c in selected}
        pairs=[(index[sid,first_arm,r],index[sid,second_arm,r]) for sid in sorted(ids) for r in range(2)]
        valid=[(a,b) for a,b in pairs if a['status']==b['status']=='ok']
        agreement=Counter()
        for a,b in valid:
            sa,sb=signature(a),signature(b)
            agreement['localization_status_same']+=sa[0]==sb[0]
            agreement['ordered_step_types_same']+=sa==sb
            if sa[1] and sb[1]:
                agreement['both_located']+=1
                agreement['first_step_same']+=sa[1][0][0]==sb[1][0][0]
                agreement['first_type_same']+=sa[1][0][1]==sb[1][0][1]
        arms={}
        for arm in arm_names:
            armrows=[x for x in results if x['case_id'] in ids and x['arm']==arm]
            repeats=[(index[sid,arm,0],index[sid,arm,1]) for sid in sorted(ids)]
            validrep=[(a,b) for a,b in repeats if a['status']==b['status']=='ok']
            arms[arm]=dict(calls=len(armrows),statuses=dict(Counter(x['value']['status'] if x['status']=='ok' else 'error' for x in armrows)),
                repeat_valid_pairs=len(validrep),repeat_ordered_step_types_same=sum(signature(a)==signature(b) for a,b in validrep))
        groups[label]=dict(cases=len(selected),valid_ab_pairs=len(valid),agreement=dict(agreement),arms=arms)
    usage=Counter();event_counts=Counter()
    for p in (root/'calls').rglob('events.json'):
        for e in read(p):
            event_counts[e['kind']]+=1
            if e['kind']=='model_response':usage.update({k:v for k,v in (e.get('usage') or {}).items() if type(v) in [int,float]})
    changed=[dict(case_id=c['experiment_case_id'],sample_id=c['case']['sample_id'],used_skill_present=c['used_skill_present'],score=c['score'],
        outputs=[dict(arm=a,repeat=r,status=index[c['experiment_case_id'],a,r]['status'],value=index[c['experiment_case_id'],a,r].get('value')) for a in arm_names for r in range(2)]) for c in cases]
    save(root/'comparison.json',dict(groups=groups,event_counts=dict(event_counts),model_response_usage=dict(usage),cases=changed,
        limits='Structural agreement and repeat variance do not measure correctness. Manual grounding/actionability review is required; cohorts and shared question identities must be reported separately.'))
    sys.path.insert(0,str(root/'src'))
    evidence=import_module('skill_evolution.algorithms.alternating.global.adaptor.evidence')
    trajectory=import_module('skill_evolution.infra.trajectory')
    review=['# Localizer evidence review (arm-blinded)\n','Assess each output for actual step/action alignment, decision-time evidence, public support for result defects, feasible correction, GT-only leakage, and unjustified fault assertions. Correct final answers alone do not establish an error-free trajectory.\n']
    keys=[];rng=random.Random(20261002)
    for c in cases:
        case=c['case'];truth=case['offline_feedback']['reference'];truth=truth.get('reference_answer') or truth.get('ground_truth',[])
        review.extend([f"## {c['experiment_case_id']}",evidence._render_input(case['input']),trajectory.render_global_steps(case['steps']),
            'Final answer: '+str(case['final_answer'].get('answer','')),'Ground truth: '+str(truth)])
        outputs=[index[c['experiment_case_id'],a,r] for a in arm_names for r in range(2)];rng.shuffle(outputs)
        for k,x in enumerate(outputs):
            review.extend([f'### Output {chr(65+k)}','```json',json.dumps(x.get('value') or dict(error=x.get('error')),ensure_ascii=False,indent=2),'```'])
            keys.append(dict(case_id=c['experiment_case_id'],output=chr(65+k),arm=x['arm'],repeat=x['repeat']))
    (root/'blind_review.md').write_text('\n\n'.join(review)+'\n');save(root/'review_key.json',keys)
    save(root/'analysis_validation.json',dict(status='passed',calls=expected_calls,cases=len(cases),unique_questions=len({c['case']['sample_id'] for c in cases}),ab_pairs=len(cases)*2,quality_review_pending=True))
    print(json.dumps(groups,ensure_ascii=False,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);a=p.parse_args();run(a.output.resolve())
