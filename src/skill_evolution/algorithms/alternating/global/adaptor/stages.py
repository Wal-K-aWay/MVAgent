"""Localizer, Linker and candidate stages with recorded, bounded model validation."""
from mvagent.skills.bank import next_skill_id
from pathlib import Path
import json

from models.execution import execution_scope
from models.utils import validate_json_schema
from skill_evolution.infra.bank import BankSnapshot
from skill_evolution.infra.skills import hash_json
from skill_evolution.infra.store import write_json
from .evidence import render_stage_input

from .prompts import build_system_prompt, build_stage_prompt
from .prompts.localizer import schema as localizer
from .prompts.linker import schema as linker
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


def repair_operations(decision, skill):
    """Bind the revision target in code; the Linker only chooses the operation."""
    validate_json_schema(decision, linker.build_schema())
    if decision['status'] == 'revise':
        if skill is None:
            raise ValueError('Revision requires a question Skill')
        return [dict(action='revise', skill_id=skill['meta']['id'], reason=decision['reason'])]
    return [dict(action='create', skill_id='', reason=decision['reason'])]


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

    def localize(self, directory, case, bank):
        if not any(s['editable'] for s in case['steps']):
            return dict(status='skip', reason='No editable Global decisions', fault_chain=[])
        return self.call(directory, 'localizer', dict(case=case,
            global_skills=[c.to_dict() for c in bank.bank.cards if c.role == 'global']),
            localizer.build_schema(case), localizer.validate)

    def link(self, directory, case, context, skill):
        if skill is None:
            value = dict(status='generate', reason='No Skill was used for this question.')
            write_json(Path(directory) / 'result.json', value)
            return value
        return self.call(directory, 'linker', dict(case=case, fault=context,
            used_skill=skill), linker.build_schema())

    def generate(self, directory, case, context, bank, link, history, rejected, max_words):
        target = next((c.to_dict() for c in bank.bank.cards if c.id == link['skill_id']), None)
        name, schema = ('reviser', reviser) if link['action'] == 'revise' else ('generator', generator)
        output_schema = reviser.build_schema(max_words, link['skill_id']) if name == 'reviser' else schema.build_schema(max_words)
        def proposal(value):
            return reviser.proposal(value, target) if name == 'reviser' else generator.proposal(value, next_skill_id(bank.bank.cards))
        payload = dict(case=case, fault=context, decision=link, target_skill=target,
            failure_count=len(history), recent_failures=[record for record in history
                if (record['sample_id'], record['bank_hash']) !=
                   (case.get('sample_id'), case.get('bank_hash'))][-3:],
            rejected_candidates=rejected[-5:], max_card_words=max_words)
        value = self.call(directory, name, payload, output_schema,
            lambda result: candidate_bank(bank, link, proposal(result), max_words))
        return proposal(value)

