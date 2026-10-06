"""Full-profile revision contract; metadata belongs to the existing target."""
from ..generator.schema import build_schema as build_generator_schema


def build_schema(max_words, target_skill_id=None):
    card = build_generator_schema(max_words)
    fields = {key: value for key, value in card['properties'].items() if key != 'id'}
    profile = dict(type='object', properties=fields, required=list(fields), additionalProperties=False)
    target = dict(type='string', minLength=1)
    if target_skill_id is not None:
        target['const'] = target_skill_id
    return dict(type='object', properties=dict(
        update_mode=dict(type='string', enum=['revise_existing', 'skip']),
        target_skill_id=target,
        revision_summary=dict(type='string', minLength=1),
        skill_profile=dict(anyOf=[profile, dict(type='null')])),
        required=['update_mode', 'target_skill_id', 'revision_summary', 'skill_profile'],
        additionalProperties=False,
        allOf=[{'if': {'properties': {'update_mode': {'const': 'revise_existing'}}},
                'then': {'properties': {'skill_profile': {'type': 'object'}}},
                'else': {'properties': {'skill_profile': {'type': 'null'}}}}])


def proposal(value, target):
    """Convert the stage result to the shared internal candidate representation."""
    if value['target_skill_id'] != target['meta']['id']:
        raise ValueError('Revision target does not match the selected Skill')
    if value['update_mode'] == 'skip':
        return dict(status='skip', card=None, reason=value['revision_summary'])
    return dict(status='candidate', card=dict(meta=target['meta'], **value['skill_profile']),
                reason=value['revision_summary'])
