"""Per-step fault classification and editable-step constraints."""

FAULT_TYPES = ('action_selection_error', 'action_parameter_error', 'action_execution_error')


def build_schema(case):
    steps = [s for s in case['steps'] if s['editable']]
    parameter_steps = [s['step'] for s in steps
                       if s.get('decision', {}).get('action') in ('analyze_videos', 'watch_videos')]
    item = dict(type='object', properties=dict(
        step=dict(type='integer', enum=[s['step'] for s in steps]),
        fault_type=dict(type='string', enum=list(FAULT_TYPES)),
        evidence_reason=dict(type='string', minLength=1),
        improvement_principle=dict(type='string', minLength=1)),
        required=['step', 'fault_type', 'evidence_reason', 'improvement_principle'],
        additionalProperties=False,
        allOf=[{'if': {'properties': {'fault_type': {'const': 'action_parameter_error'}}},
                'then': {'properties': {'step': {'enum': parameter_steps}}} if parameter_steps else False}])
    return dict(type='object', properties=dict(
        status=dict(type='string', enum=['located', 'skip']),
        reason=dict(type='string', minLength=1),
        fault_chain=dict(type='array', maxItems=3, uniqueItems=True, items=item)),
        required=['status', 'reason', 'fault_chain'], additionalProperties=False,
        allOf=[{'if': {'properties': {'status': {'const': 'located'}}},
                'then': {'properties': {'fault_chain': {'minItems': 1}}},
                'else': {'properties': {'fault_chain': {'maxItems': 0}}}}])


def validate(value):
    chain = value['fault_chain']
    if (value['status'] == 'located') != bool(chain):
        raise ValueError('located requires a chain; skip requires an empty chain')
    ids = [c['step'] for c in chain]
    if len(ids) != len(set(ids)):
        raise ValueError('fault_chain steps must be distinct')
