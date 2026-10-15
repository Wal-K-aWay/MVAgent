"""Offline immutable bank candidates and atomic lifecycle commits."""
from dataclasses import dataclass
from copy import deepcopy
import fcntl
import json
from pathlib import Path

from mvagent.skills.bank import MAX_SKILL_WORDS, SkillBank, digest
from mvagent.utils import mask_sensitive_data
from .skills import hash_json
from .store import write_json
from .rollout import FrozenMVAgentExecutor


@dataclass(frozen=True)
class BankSnapshot:
    bank: SkillBank

    @classmethod
    def from_dict(cls, value):
        return cls(SkillBank.from_dict(value))

    @classmethod
    def empty(cls):
        return cls.from_dict({'schema_version': 3, 'skills': []})

    def to_dict(self):
        return self.bank.to_dict()

    def skill_set_hash(self):
        # Shared rollout protocol: identity includes every card, including unselected ones.
        return hash_json(self.to_dict())


class BankExecutor(FrozenMVAgentExecutor):
    def _config(self, snapshot):
        directory = self.output_dir / 'banks' / snapshot.skill_set_hash()
        directory.mkdir(parents=True, exist_ok=True)
        bank_path = directory / 'bank.json'
        if bank_path.exists() and json.loads(bank_path.read_text()) != snapshot.to_dict():
            raise ValueError('Immutable bank snapshot was modified')
        write_json(bank_path, snapshot.to_dict())
        sha = digest(bank_path.read_text())
        config = deepcopy(self.base_config)
        for role in ('global', 'video'):
            settings = config['agents'][role + '_agent']['skill']
            if settings.get('mode') != 'dynamic':
                raise ValueError('Bank evolution requires dynamic Skill configuration for both roles')
            settings.update(enabled=True, path=str(bank_path.resolve()), sha256=sha)
        # Empty banks remain dynamic; Runtime abstains without a selector call.
        write_json(directory / 'config.json', mask_sensitive_data(config))
        return str((directory / 'config.json').resolve()), config


def build_candidate(parent, proposal, *, role, evidence, max_card_words=MAX_SKILL_WORDS):
    """One exact operation; evidence is a Train-only ref -> provenance map."""
    if proposal['parent_bank_hash'] != parent.skill_set_hash() or proposal['role'] != role:
        raise ValueError('Stale parent or wrong role')
    op, sources, raw = proposal['op'], proposal['source_skill_ids'], proposal['proposed_cards']
    counts = {'add': (0, 1), 'refine': (1, 1), 'merge': (2, 1), 'retire': (1, 0), 'keep': (0, 0)}
    if op not in counts or (len(sources), len(raw)) != counts[op] or len(set(sources)) != len(sources):
        raise ValueError('Operation cardinality violation')
    cards = {c.id: c for c in parent.bank.cards}
    if any(s not in cards or cards[s].role != role for s in sources):
        raise ValueError('Sources must exist and belong to the active role')
    if op == 'keep':
        return parent
    refs = proposal['evidence_refs']
    if not refs or not set(refs) <= evidence.keys():
        raise ValueError('Unknown or empty Train evidence references')
    if len({evidence[r]['source_group'] for r in refs}) < 2:
        raise ValueError('An edit requires evidence from at least two source groups')
    coverage = proposal['coverage_refs']
    required = {'target', 'protection', 'negative'}
    if op == 'merge':
        required |= {'a_only', 'b_only', 'shared', 'excluded'}
    if op == 'retire':
        required |= {'historical_success', 'low_frequency', 'harm_or_replacement'}
    if not required <= coverage.keys() or any(not coverage[k] or not set(coverage[k]) <= set(refs) for k in required):
        raise ValueError('Missing or ungrounded operation coverage')
    if op in ('merge', 'retire') and not proposal['maintenance_evidence'].strip():
        raise ValueError('Maintenance requires explicit redundancy/replacement/outdated evidence')
    new_cards = SkillBank.from_dict({'schema_version': 3, 'skills': raw}).cards
    for card in new_cards:
        if card.role != role or card.text_words > max_card_words:
            raise ValueError('Candidate role or length violation')
        if card.id in cards and card.id not in sources:
            raise ValueError('Candidate overwrites an unrelated card')
    if op == 'refine' and new_cards[0].id != sources[0]:
        raise ValueError('Refine must preserve the card ID')
    if op == 'merge':
        stages = [set(cards[s].stages) for s in sources]
        if stages[0] != stages[1] or set(new_cards[0].stages) != stages[0]:
            raise ValueError('Merge requires identical role/stage scope')
    result = BankSnapshot.from_dict({'schema_version': 3, 'skills':
        [c.to_dict() for sid, c in cards.items() if sid not in sources] + raw})
    if result.skill_set_hash() == parent.skill_set_hash():
        raise ValueError('Non-keep operation must change the bank')
    return result


class BankStore:
    """One atomic state file is the commit point; snapshots never change."""
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def read(self):
        return json.loads((self.root / 'state.json').read_text())

    def snapshot(self, bank):
        path = self.root / 'versions' / (bank.skill_set_hash() + '.json')
        if path.exists() and json.loads(path.read_text()) != bank.to_dict():
            raise ValueError('Immutable version corrupted')
        write_json(path, bank.to_dict())

    def load(self, sha):
        bank = BankSnapshot.from_dict(json.loads((self.root / 'versions' / (sha + '.json')).read_text()))
        if bank.skill_set_hash() != sha:
            raise ValueError('Bank version hash mismatch')
        return bank

    def initialize(self, seed, identity, *, resume):
        with (self.root / '.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            path = self.root / 'state.json'
            if path.exists():
                state = self.read()
                if not resume or state['identity'] != identity:
                    raise ValueError('Existing state or changed experiment identity')
                self.load(state['bank_hash'])
                return state
            if resume:
                raise ValueError('Resume requires a committed initial state')
            self.snapshot(seed)
            state = dict(identity=identity, bank_hash=seed.skill_set_hash(), next_round=0, decisions=[])
            write_json(path, state)
            return state

    def commit(self, expected, bank, decision):
        with (self.root / '.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            state = self.read()
            if state != expected:
                raise ValueError('Stale bank transaction')
            self.snapshot(bank)
            updated = {**state, 'bank_hash': bank.skill_set_hash(),
                       'next_round': state['next_round'] + 1,
                       'decisions': state['decisions'] + [decision]}
            write_json(self.root / 'state.json', updated)
            return updated
