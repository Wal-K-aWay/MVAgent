"""Train-only public batch evidence and verified Skill exposure."""
import json
from skill_evolution.infra.skills import Role
from skill_evolution.infra.trajectory import routing_audit, render_global_steps

def _render_input(input_value):
    videos = '; '.join(f"{v['video_id']} ({v['duration_sec']} seconds)" for v in input_value.get('videos', []))
    question = input_value.get('question', '')
    options = input_value.get('options', [])
    if options and '\nOptions:\n' not in question:
        question += '\n\nOptions:\n' + '\n'.join(options)
    return f"Videos: {videos}\n\n{question}"


def _render_case(case, level=2, *, show_usage=True, skill=None):
    """One public case, without storage identities or duplicated execution metadata."""
    heading = '#' * level
    input_value = case.get('input', {})
    steps = case.get('steps', [])
    used = list(dict.fromkeys(sid for step in steps for sid in (step.get('injected') or [])))
    unknown = any(step.get('injected') is None for step in steps)
    skill_text = ', '.join(used) if used else ('Unknown' if unknown else 'None')
    if used and unknown:
        skill_text += '; usage verification is incomplete.'
    reference = case.get('offline_feedback', {}).get('reference', {})
    truth = reference.get('reference_answer') or reference.get('ground_truth', [])
    parts = [
        f"{heading} Input\n\n{_render_input(input_value)}",
        f"{heading} Steps\n\n{render_global_steps(steps)}",
        f"{heading} Final answer\n\n{case.get('final_answer', {}).get('answer', '')}",
        f"{heading} Ground truth\n\n" + ('; '.join(map(str, truth)) if isinstance(truth, list) else str(truth)),
    ]
    if skill is not None:
        parts.insert(1, f"{heading} Skill Used for This Question\n\n" + _render_card(skill))
    elif show_usage:
        parts.insert(1, f"{heading} Used skills\n\n{skill_text}")
    return '\n\n'.join(parts)



def _render_card(card):
    return '\n'.join(f"**{label}:** {card[field].strip()}" for field, label in (
        ('when_to_use', 'When to use'),
        ('strategy', 'Strategy')))


def training_case(report, sample_id, bank, projector, reference):
    """Project public evidence; never forward raw requests or private Video traces."""
    episode = report['episodes'][sample_id]
    case = next(c for c in projector.project(episode.artifact,
        official_score=report['scores'][sample_id].score) if c.role == Role.GLOBAL)
    audit = routing_audit(bank, {'episodes': {sample_id: episode},
        'scores': {sample_id: report['scores'][sample_id]}}, {sample_id: case.source_group})
    exposure = {r['decision_id']: r for r in audit['rows'] if r['role'] == 'global'}
    trajectory = json.loads(case.decisions_and_results)
    steps = []
    for index, row in enumerate(trajectory['rounds'], 1):
        row['decision'].pop('reason', None)
        route = exposure.get(f"global:{row['round']}", {})
        steps.append(dict(step=index, **row,
            editable=not row['decision'].get('runtime_finalizer', False),
            selected=route.get('selected'), injected=route.get('injected')))
    final_answer = json.loads(case.output)
    final_answer.pop('reason', None)
    result = dict(sample_id=sample_id, bank_hash=bank.skill_set_hash(),
        input=json.loads(case.visible_input), steps=steps,
        final_answer=final_answer,
        offline_feedback=dict(reference=reference, score=case.official_score,
                              feedback=case.outcome_feedback))
    result['used_skill'] = used_skill(result, bank)
    return result


def used_skill(case, bank):
    """Resolve one question-wide Skill from verified decision requests."""
    cards = {c.id: c for c in bank.bank.cards if c.role == 'global'}
    if not cards:
        return None
    decisions = [s for s in case['steps'] if s.get('editable', True)]
    if not decisions:
        raise ValueError('Missing question-level Skill usage records')
    selections = []
    for step in decisions:
        selected, injected = step.get('selected'), step.get('injected')
        if selected is None or injected is None:
            raise ValueError('Missing question-level Skill usage records')
        if len(selected) > 1 or selected != injected:
            raise ValueError('Question Skill selection and injection must agree')
        selections.append(tuple(selected))
    if len(set(selections)) != 1:
        raise ValueError('Question Skill changed between decisions')
    ids = selections[0]
    if not ids:
        return None
    if ids[0] not in cards:
        raise ValueError('Question Skill is absent from the current bank')
    return cards[ids[0]].to_dict()


def card_content(card):
    return {k: card[k] for k in ('when_to_use', 'strategy')}



def render_stage_input(payload):
    parts=['## Full-library Train batch','Clusters organize examples, never bind cards. Each case used the full current library; verified usage is listed.']
    target=payload.get('target_skill')
    parts+=['## Fixed target',('**ID:** '+target['meta']['id']+'\n'+_render_card(target)) if target else 'None']
    parts+=['## Library selection metadata',json.dumps([dict(id=c['meta']['id'],when_to_use=c['when_to_use']) for c in payload.get('library',[])],ensure_ascii=False)]
    used={c['used_skill']['meta']['id']:c['used_skill'] for c in payload['cases'] if c.get('used_skill')}
    for sid,c in used.items():
        if not target or sid!=target['meta']['id']:parts+=['## Related actually used card '+sid,_render_card(c)]
    for case in payload['cases']:
        score=case['offline_feedback']['score'];outcome='correct' if score==1 else ('partially correct' if score>0 else 'incorrect')
        parts+=['## Case '+case['sample_id'],'Offline outcome: '+outcome,_render_case(case,3,skill=case.get('used_skill'))]
    if 'reflection' in payload:parts+=['## Supported edit',json.dumps(payload['reflection'],ensure_ascii=False)]
    if payload.get('routing_feedback'):parts+=['## Previous Train routing replay (not gold applicability)',json.dumps(payload['routing_feedback'],ensure_ascii=False)]
    parts+=['## Related rejected candidates',json.dumps(payload.get('rejected',[]),ensure_ascii=False),'Rejection status alone does not reveal its cause. No Gate details are supplied.','## Word limit',str(payload['max_card_words'])+' words across the assembled four fields.']
    return '\n\n'.join(parts)
