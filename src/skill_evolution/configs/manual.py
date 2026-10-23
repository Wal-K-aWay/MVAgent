"""Validated, explicitly authored factors for controlled skill experiments."""
import json
from pathlib import Path

from mvagent.skills.bank import SkillBank, STAGES


BODY_STYLES = ('concise', 'procedural')
ENTRY_STYLES = ('broad', 'relation', 'contrastive')


def load_manual(path):
    value = json.loads(Path(path).read_text())
    if set(value) != {'role', 'methods'} or value['role'] not in ('global', 'video'):
        raise ValueError('Manual definitions require role and methods')
    if not isinstance(value['methods'], list) or not value['methods']:
        raise ValueError('At least one authored method is required')
    keys = []
    for method in value['methods']:
        if set(method) != {'key', 'strategies', 'applicability'}:
            raise ValueError('Unexpected manual method fields')
        if not isinstance(method['key'], str) or not method['key'].strip():
            raise ValueError('Method keys must be nonempty strings')
        keys.append(method['key'])
        if set(method['strategies']) != set(BODY_STYLES) or set(method['applicability']) != set(ENTRY_STYLES):
            raise ValueError('Each method must cover the declared body and entry styles')
    if len(keys) != len(set(keys)):
        raise ValueError('Duplicate method keys')
    for body in BODY_STYLES:
        for entry in ENTRY_STYLES:
            manual_bank(value, body=body, entry=entry)
    return value


def manual_bank(definition, *, body, entry, order=None):
    if body not in BODY_STYLES or entry not in ENTRY_STYLES:
        raise ValueError('Unknown style')
    methods = {m['key']: m for m in definition['methods']}
    order = list(methods) if order is None else list(order)
    if len(order) != len(methods) or set(order) != set(methods):
        raise ValueError('Order must be a permutation of all methods')
    cards = [{'meta': {'id': str(i + 1), 'role': definition['role'], 'stages': list(STAGES)},
              'when_to_use': methods[key]['applicability'][entry],
              'strategy': methods[key]['strategies'][body]} for i, key in enumerate(order)]
    return SkillBank.from_dict({'schema_version': 3, 'skills': cards})
