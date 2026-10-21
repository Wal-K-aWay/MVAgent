"""Algorithm-facing evaluation result; benchmark execution stays in eval/."""
from dataclasses import dataclass
from typing import Any
import math


@dataclass(frozen=True)
class Evaluation:
    partition: str
    bank_sha256: str
    score: float
    samples: int
    identity: str
    train_rows: tuple[dict[str, Any], ...] = ()

    def __post_init__(self):
        if self.partition not in ('train', 'cal', 'gate'):
            raise ValueError('Unknown evaluation partition')
        if not math.isfinite(self.score) or not 0 <= self.score <= 1 or self.samples < 1:
            raise ValueError('Evaluation requires a finite official score and nonempty samples')
        if self.partition != 'train' and self.train_rows:
            raise ValueError('Cal/Gate details must not cross the optimizer boundary')
        if self.partition == 'train' and len(self.train_rows) != self.samples:
            raise ValueError('Every Train sample requires a saved, scored rollout')
        if not self.identity or len(self.bank_sha256) != 64:
            raise ValueError('Evaluation identities are required')

    def summary(self):
        return {'partition': self.partition, 'bank_sha256': self.bank_sha256,
                'score': self.score, 'samples': self.samples, 'identity': self.identity}
