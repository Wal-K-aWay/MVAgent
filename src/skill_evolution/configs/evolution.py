"""Small, explicit search budgets; inference settings belong to MVAgent."""
from dataclasses import dataclass, fields


@dataclass(frozen=True)
class EvolutionConfig:
    rounds: int = 2
    candidates_per_round: int = 2
    max_cards_per_role: int = 8
    examples_per_proposal: int = 8
    max_example_chars: int = 12000
    roles: tuple[str, ...] = ('global', 'video')
    seed: int = 0

    def __post_init__(self):
        for name in ('rounds', 'candidates_per_round', 'max_cards_per_role',
                     'examples_per_proposal', 'max_example_chars'):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ValueError(f'{name} must be a positive integer')
        if self.max_cards_per_role > 8:
            raise ValueError('The initial experiment keeps each role at most 8 cards')
        if not self.roles or len(set(self.roles)) != len(self.roles) or any(r not in ('global', 'video') for r in self.roles):
            raise ValueError('roles must contain distinct global/video entries')
        if type(self.seed) is not int:
            raise ValueError('seed must be an integer')
        object.__setattr__(self, 'roles', tuple(self.roles))

    @classmethod
    def from_dict(cls, value):
        unknown = set(value) - {field.name for field in fields(cls)}
        if unknown:
            raise ValueError(f'Unknown evolution settings: {sorted(unknown)}')
        return cls(**value)
