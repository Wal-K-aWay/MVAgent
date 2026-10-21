"""Validated one-card edits and immutable whole-bank artifacts."""
from dataclasses import dataclass
from pathlib import Path
from copy import deepcopy
import hashlib,json
from mvagent.skills.bank import SkillBank, next_skill_id, STAGES
from mvagent.utils.io import write_json


@dataclass(frozen=True)
class BankSnapshot:
    path: Path
    sha256: str

    def load(self):
        return SkillBank.load(path=str(self.path), sha256=self.sha256)


def freeze_bank(bank, directory):
    raw = json.dumps(bank.to_dict(), ensure_ascii=False, indent=2).encode()
    sha = hashlib.sha256(raw).hexdigest()
    path = Path(directory) / f'{sha}.json'
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError('Immutable bank content changed')
    else:
        write_json(path, bank.to_dict())
    snapshot = BankSnapshot(path.absolute(), sha)
    snapshot.load()
    return snapshot


def apply_edit(bank, role, edit, max_cards):
    if role not in ('global', 'video'):
        raise ValueError('Unknown target role')
    if set(edit) != {'operation', 'target_id', 'when_to_use', 'strategy', 'hypothesis'}:
        raise ValueError('Unexpected edit fields')
    if any(not isinstance(v, str) for v in edit.values()) or not edit['hypothesis'].strip():
        raise ValueError('Edit fields must be strings and hypothesis nonempty')
    cards = {card.id: card.to_dict() for card in bank.cards}
    operation, target = edit['operation'], edit['target_id']
    if operation in ('noop', 'remove') and (edit['when_to_use'] or edit['strategy']):
        raise ValueError('Noop/remove must not carry replacement text')
    if operation == 'noop':
        if target:
            raise ValueError('Noop has no target')
        return bank
    if operation == 'add':
        if target:
            raise ValueError('New IDs are allocated by the program')
        target = next_skill_id(bank.cards)
        meta = {'id': target, 'role': role, 'stages': list(STAGES)}
    elif operation in ('revise', 'remove'):
        if target not in cards or cards[target]['meta']['role'] != role:
            raise ValueError('Edit must target an existing card in the current role')
        meta = cards[target]['meta']
    else:
        raise ValueError('Unknown edit operation')
    if operation == 'remove':
        del cards[target]
    else:
        cards[target] = {'meta': meta, 'when_to_use': edit['when_to_use'], 'strategy': edit['strategy']}
    result = SkillBank.from_dict({'schema_version': 3, 'skills': list(cards.values())})
    if sum(card.role == role for card in result.cards) > max_cards:
        raise ValueError('Role card budget exceeded')
    signatures = [(c.role, c.when_to_use, c.strategy) for c in result.cards]
    if len(signatures) != len(set(signatures)):
        raise ValueError('Duplicate cards')
    return result


def runtime_with_bank(runtime, snapshot):
    result = deepcopy(runtime)
    bank = snapshot.load()
    for role in ('global', 'video'):
        enabled = any(card.role == role for card in bank.cards)
        result['agents'][f'{role}_agent']['skill'] = (
            {'enabled': True, 'mode': 'dynamic', 'selection_scope': 'task',
             'path': str(snapshot.path), 'sha256': snapshot.sha256} if enabled else {'enabled': False})
    return result
