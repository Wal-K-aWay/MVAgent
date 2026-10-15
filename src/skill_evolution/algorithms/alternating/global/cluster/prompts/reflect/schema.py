"""Dynamic reflection Schema and evidence-dependent validation."""

def build_schema(cases, library=()):
    nullable=lambda x: dict(anyOf=[x,dict(type='null')])
    return dict(type='object', additionalProperties=False, required=['status','reason','target_skill_id','sample_id','step','evidence_ids'],properties=dict(
        status=dict(type='string',enum=['generate','revise_metadata','revise_body','skip']),reason=dict(type='string',minLength=1),
        target_skill_id=nullable(dict(type='string',enum=[c['meta']['id'] for c in library])) if library else dict(type='null'),
        sample_id=nullable(dict(type='string',enum=[c['sample_id'] for c in cases])),
        step=nullable(dict(type='integer',minimum=1)),evidence_ids=dict(type='array',uniqueItems=True,items=dict(type='string',enum=[c['sample_id'] for c in cases]))))

def validate(value,cases,library=()):
    if value['status']=='skip':
        if any(value[k] is not None for k in ('sample_id','step','target_skill_id')) or value['evidence_ids']:raise ValueError('skip requires null anchors and no evidence')
        return
    by_id={c['sample_id']:c for c in cases}
    case=by_id[value['sample_id']]
    if case['offline_feedback']['score']>=1 or value['sample_id'] not in value['evidence_ids']:raise ValueError('Edit requires a non-perfect evidence anchor')
    target=next((c for c in library if c['meta']['id']==value['target_skill_id']),None)
    if value['status']=='generate':
        if value['target_skill_id'] is not None:raise ValueError('generate has no target')
    elif target is None:raise ValueError('Revision requires an existing Global target')
    if value['status']!='revise_metadata' or value['step'] is not None:
        if not any(s['step']==value['step'] and s['editable'] for s in case['steps']):raise ValueError('Anchor must reference an editable Global decision')
    if value['status']=='revise_body' and case.get('used_skill')!=target:raise ValueError('Body revision requires anchor using exact target version')
