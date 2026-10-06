"""Generator returns a flat Skill; the program supplies fixed metadata."""


def build_schema(max_words):
    return {'type': 'object',
     'properties': {
                    'when_to_use': {'type': 'string', 'minLength': 1, 'description': 'Task, core method, prerequisites and applicability boundaries'},
                    'strategy': {'type': 'string', 'minLength': 1, 'description': f'Two text fields combined: at most {max_words} words'}},
     'required': ['when_to_use', 'strategy'],
     'additionalProperties': False}


def proposal(value, reference):
    card = dict(value)
    card['meta'] = dict(id=reference, role='global', stages=['initial', 'evidence'])
    return dict(status='candidate', card=card)
