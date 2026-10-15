"""Global-only Train evidence rendering; no optimizer policy or Gate data."""
import json

from skill_evolution.infra.skills import Role, hash_json
from skill_evolution.infra.trajectory import routing_audit, render_case_value, render_global_steps


def _render_input(input_value):
    videos = '; '.join(f"{v['video_id']} ({v['duration_sec']} seconds)" for v in input_value.get('videos', []))
    return f"Videos: {videos}\n\n{input_value.get('question', '')}"


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



def _render_material(member, *, show_usage=True):
    case = member['case']
    outcome = 'successful' if case['offline_feedback']['score'] == 1 else 'not fully successful'
    status = member['localization']['status']
    return ('Outcome: ' + outcome + '; localization: ' + status + '. '
        'Success does not prove Skill causality; missing localization does not prove an error-free trace.\n\n'
        + _render_case(case, 4, show_usage=show_usage))

def _render_fault(fault):
    return (f"Step: {fault['step']}\nFault type: {fault['fault_type']}\n"
            f"Evidence reason: {fault['evidence_reason']}\n"
            f"Improvement principle: {fault['improvement_principle']}")


def _render_cases(payload):
    case, fault = payload['case'], payload['fault']
    parts = ['## Current case', _render_case(case, 3), '### Localization', _render_fault(fault)]
    related = [member for member in fault.get('group_cases', [])
               if (member['case'].get('sample_id'), member['case'].get('bank_hash')) !=
                  (case.get('sample_id'), case.get('bank_hash'))]
    if related:
        parts.append('## Related cases')
    for index, member in enumerate(related, 1):
        prior = member['case'].get('bank_hash') != case.get('bank_hash')
        parts.append(f"### Related case {index}" + (' (earlier library version)' if prior else ''))
        parts.append(_render_material(member))
        for entry in member['faults']:
            parts.extend(['#### Localization', _render_fault(entry)])
    return parts


def _render_card(card):
    return '\n'.join(f"**{label}:** {card[field].strip()}" for field, label in (
        ('when_to_use', 'When to use'),
        ('strategy', 'Strategy')))


def skill_relationship(case, current):
    """Compare frozen question cards, not whole-bank versions."""
    if 'used_skill' not in case:
        return 'Skill usage unknown; context only, not evidence of a defect in this card.'
    other = case['used_skill']
    if other is None:
        return 'No Skill used; context only, not evidence of a defect in this card.'
    if other['meta']['id'] != current['meta']['id']:
        return 'Different Skill used; context only, not evidence of a defect in this card.'
    if hash_json(card_content(other)) != hash_json(card_content(current)):
        return 'Different version of this Skill used; context only, not evidence of a defect in the current version.'
    return 'Same Skill version used; may support analysis of this card, subject to the case evidence.'


def render_linker_input(payload):
    case, fault, skill = payload['case'], payload['fault'], payload['used_skill']
    parts = [_render_case(case, show_usage=False, skill=skill).replace('## Steps\n', '## Trajectory\n'),
             '## Localization', _render_fault(fault)]
    related = [m for m in fault.get('group_cases', [])
               if (m['case'].get('sample_id'), m['case'].get('bank_hash')) !=
                  (case.get('sample_id'), case.get('bank_hash'))]
    if related:
        parts.append('## Related Cases')
    for index, member in enumerate(related, 1):
        prior = member['case'].get('bank_hash') != case.get('bank_hash')
        parts.extend([f'### Related Case {index}' + (' (earlier library version)' if prior else ''),
                      skill_relationship(member['case'], skill),
                      _render_material(member, show_usage=False)])
        for entry in member['faults']:
            parts.extend(['#### Localization', _render_fault(entry)])
    return '\n\n'.join(parts)


def render_reviser_input(payload):
    """Render editing evidence as explicit sections, not nested storage records."""
    parts = _render_cases(payload)
    parts.extend(['## Revision reason', payload['decision'].get('reason', 'No routing reason supplied.')])
    target = payload['target_skill']
    parts.extend(['## Skill to revise', '**ID:** ' + target['meta']['id'] + '\n' + _render_card(target)])
    parts.extend(['## Recent failure history',
        f"Recorded revision attempts, including the current attempt: {payload['failure_count']}. "
        'These records do not establish confirmed Skill defects.'])
    for index, record in enumerate(payload['recent_failures'], 1):
        fault = record['fault']
        parts.extend([f'### Previous failure {index}', _render_input(record['input']), _render_fault(fault)])
        action = fault['action']
        text = 'Action: ' + action['action']
        if action['action'] != 'answer':
            text += ' ' + json.dumps(action.get('parameters', {}), ensure_ascii=False)
        parts.append(text)
    if not payload['recent_failures']:
        parts.append('None.')
    return '\n\n'.join(parts + _render_proposal_library(payload))


def _render_proposal_library(payload):
    parts = []
    parts.append('## Previously rejected candidates')
    for index, record in enumerate(payload['rejected_candidates'], 1):
        parts.extend([f'### Rejected candidate {index}', '**ID:** ' + record['card']['meta']['id'] + '\n' + _render_card(record['card']), 'Result: ' + record['status']])
        if record.get('reason'):
            parts.append('Reason: ' + record['reason'])
    if not payload['rejected_candidates']:
        parts.append('None.')
    parts.extend(['## Card word limit', str(payload['max_card_words']) + ' words across the two text fields.'])
    return parts


def render_generator_input(payload):
    """Use the same public cases and compact localization as Linker."""
    parts = _render_cases(payload)
    parts.extend(['## Generation task',
                  'Assess whether the localized failure supports a distinct reusable Skill. '
                  'Compare the supplied successful and unsuccessful cases to derive a complete candidate; cluster membership does not establish one shared method.'])
    return '\n\n'.join(parts + _render_proposal_library(payload))


def render_stage_input(payload):
    """Use the infra Global trace renderer, including nested stage inputs."""
    if 'used_skill' in payload and 'case' in payload:
        return render_linker_input(payload)

    if 'target_skill' in payload:
        if payload['decision']['action'] == 'revise':
            return render_reviser_input(payload)
        return render_generator_input(payload)

    def prepare(value):
        if isinstance(value, list):
            return [prepare(item) for item in value]
        if not isinstance(value, dict):
            return value
        if 'case' in value:
            case = value['case']
            steps = case.get('steps', [])
            selected_ids = list(dict.fromkeys(sid for step in steps for sid in (step.get('selected') or [])))
            cards = {c['meta']['id']: c for c in value.get('global_skills', [])}
            selected = [_render_card(cards[sid]) if sid in cards else 'Skill content unavailable.'
                        for sid in selected_ids]
            unknown = any(step.get('selected') is None for step in steps)
            selected_text = '\n\n'.join(selected) if selected else 'None'
            if unknown:
                selected_text += '\nSelection records are unavailable for some steps.'
            reference = case.get('offline_feedback', {}).get('reference', {})
            truth = reference.get('reference_answer') or reference.get('ground_truth', [])
            output = case.get('final_answer', {}).get('answer', '')
            sections = [
                '## Input\n\n' + _render_input(case.get('input', {})),
                '## selected skill\n' + selected_text,
                '## steps\n' + render_global_steps(steps),
                '## output\n' + (str(output) or 'None'),
                '## ground truth\n' + ('; '.join(map(str, truth)) if isinstance(truth, list) else str(truth)),
            ]
            # Later stages still need the candidate catalog and editing context.
            extra = {k: v for k, v in value.items() if k not in ('case', 'global_skills')}
            if extra:
                if 'global_skills' in value:
                    extra['global_skills'] = value['global_skills']
                sections.append(render_case_value(prepare(extra)))
            return '\n\n'.join(sections)
        result = {}
        for key, item in value.items():
            if key in ('sample_id', 'bank_hash', 'final_answer', 'source_bank', 'fault_ref'):
                continue
            if key == 'offline_feedback':
                reference = item.get('reference', {})
                truth = reference.get('reference_answer') or reference.get('ground_truth', [])
                result['ground_truth'] = '; '.join(map(str, truth)) if isinstance(truth, list) else truth
            elif key == 'videos' and isinstance(item, list) and all(
                    isinstance(video, dict) and 'duration_sec' in video for video in item):
                result[key] = '; '.join(f"{video['video_id']} ({video['duration_sec']} seconds)" for video in item)
            elif key == 'steps' and isinstance(item, list):
                result[key] = render_global_steps(item)
            else:
                result[key] = prepare(item)
        return result
    return render_case_value(prepare(payload))


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


def fault_context(case, entry):
    step = next(s for s in case['steps'] if s['step'] == entry['step'])
    return dict(**entry, action=step['decision'],
        available_evidence=[s['execution'] for s in case['steps'] if s['step'] < entry['step']],
        selected=step['selected'], injected=step['injected'])



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

