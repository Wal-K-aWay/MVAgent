"""Batch reflection and candidate stages with recorded, bounded model validation."""
from pathlib import Path
import json

from models.execution import execution_scope
from models.utils import validate_json_schema
from skill_evolution.infra.bank import BankSnapshot
from skill_evolution.infra.skills import hash_json
from skill_evolution.infra.store import write_json
from .evidence import render_stage_input

from mvagent.skills.bank import next_skill_id
from .prompts import build_system_prompt, build_stage_prompt
from .prompts.reflect import schema as reflect
from .prompts.reviser import schema as reviser
from .prompts.generator import schema as generator


def candidate_bank(parent, link, value, max_words):
    """Global-only add/refine, independent of historical two-source/maintenance rules."""
    if value['status'] == 'skip':
        if value['card'] is not None:
            raise ValueError('skip requires card=null')
        return None
    raw = value['card']
    if raw is None:
        raise ValueError('candidate requires a complete card')
    parsed = BankSnapshot.from_dict(dict(schema_version=3, skills=[raw])).bank.cards[0]
    if parsed.role != 'global' or parsed.text_words > max_words:
        raise ValueError(f'Global candidate exceeds max_card_words={max_words} or has wrong role')
    cards = [c.to_dict() for c in parent.bank.cards]
    if link['action'] == 'revise':
        target = next(c for c in cards if c['meta']['id'] == link['skill_id'])
        if raw['meta'] != target['meta']:
            raise ValueError('Revision must preserve target id, role and stages')
        cards = [raw if c['meta']['id'] == link['skill_id'] else c for c in cards]
    elif link['action'] == 'create':
        if any(c['meta']['id'] == parsed.id for c in cards):
            raise ValueError('Creation must use a new id')
        if set(parsed.stages) != {'initial', 'evidence'}:
            raise ValueError('New whole-question Skills need initial and evidence stages')
        cards.append(raw)
    else:
        raise ValueError('Only revise/create can construct a candidate bank')
    result = BankSnapshot.from_dict(dict(schema_version=3, skills=cards))
    if result.skill_set_hash() == parent.skill_set_hash():
        raise ValueError('Candidate makes no substantive change')
    return result


class StageValidationError(ValueError):
    """Invalid structured response; operational errors still abort the run."""


class Stages:
    def __init__(self, optimizer):
        self.optimizer = optimizer

    def call(self, directory, name, payload, schema, validate=lambda value: None):
        """Persist and validate one response; resume reuses it without another call."""
        directory = Path(directory)
        system = build_system_prompt(name)
        user = build_stage_prompt(name, render_stage_input(payload))
        identity = hash_json([self.optimizer.identity, system, user, schema])
        path = directory / 'attempt_0.json'
        if path.exists():
            saved = json.loads(path.read_text())
            if saved['identity'] != identity:
                raise ValueError('Stage resume identity mismatch')
            response = saved['response']
        else:
            write_json(directory / 'input_0.json',
                dict(identity=identity, system=system, user=user, payload=payload, schema=schema))
            events = []
            try:
                with execution_scope(emit=events.append):
                    response = self.optimizer.json_prompt(user,
                        system_prompt=system, json_schema=schema, schema_name='global_' + name)
            finally:
                write_json(directory / 'events_0.json', events)
            response = {k: response.get(k) for k in ('status', 'value', 'raw_response', 'error')}
            write_json(path, dict(identity=identity, response=response))
        errors = []
        value = response.get('value')
        try:
            if response.get('status') != 'ok' or value is None:
                raise ValueError(response.get('error') or 'No valid structured response')
            validate_json_schema(value, schema)
            validate(value)
        except (ValueError, KeyError, TypeError, StopIteration) as exc:
            errors.append(str(exc))
        write_json(directory / 'validation_0.json', dict(response=response, errors=errors))
        if errors:
            raise StageValidationError(f'{name} validation failed; inspect {directory}')
        write_json(directory / 'result.json', value)
        return value

    def reflect(self,directory,payload):
        return self.call(directory,'reflect',payload,reflect.build_schema(payload['cases'],payload['library']),lambda v:reflect.validate(v,payload['cases'],payload['library']))

    def generate(self, directory, payload, bank, link):
        directory = Path(directory)
        target = payload['target_skill']
        max_words = payload['max_card_words']
        mode = payload['reflection']['status']
        fields = generator.FIELDS
        if mode == 'generate':
            result = self.call(directory/'generator', 'generator', payload, generator.build_schema(max_words))
            raw = dict(meta=dict(id=next_skill_id(bank.bank.cards), role='global', stages=['initial','evidence']),
                       **{field: result[field] for field in fields})
        elif mode in ('revise_body', 'revise_metadata'):
            result = self.call(directory/'reviser', 'reviser', payload, reviser.build_schema(max_words, target['meta']['id']))
            if result['status'] == 'skip':
                if any(result[field] is not None for field in fields):
                    raise StageValidationError('Revision skip requires all content fields=null')
                return dict(status='skip', card=None, reason=result['revision_summary'])
            raw = dict(meta=target['meta'], **{field: result[field] for field in fields})
            if mode == 'revise_metadata' and any(raw[k] != target[k] for k in ('strategy',)):
                raise StageValidationError('Metadata revision changed frozen body')
        else:
            raise ValueError('Unsupported reflection mode')
        value = dict(status='candidate', card=raw)
        try:
            candidate_bank(bank, link, value, max_words)
        except (ValueError, KeyError, TypeError) as exc:
            raise StageValidationError(str(exc)) from exc
        write_json(directory/'result.json', value)
        return value
