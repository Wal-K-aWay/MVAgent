"""Flat repair decision for the question's fixed Skill."""


def build_schema():
    return dict(type='object', properties=dict(
        status=dict(type='string', enum=['revise', 'generate']),
        reason=dict(type='string', minLength=1)),
        required=['status', 'reason'], additionalProperties=False)
