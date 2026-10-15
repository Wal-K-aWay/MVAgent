from __future__ import annotations

from ..strategy.contracts import EvaluationMetrics, EvaluationResult


def _metrics(value: EvaluationResult | EvaluationMetrics) -> EvaluationMetrics:
    return value.metrics if isinstance(value, EvaluationResult) else value


def has_hard_reliability_regression(
    reference: EvaluationResult | EvaluationMetrics,
    candidate: EvaluationResult | EvaluationMetrics,
    *,
    tolerance: float = 0.0,
) -> bool:
    """Fatal and invalid-action regressions are never repair branches."""

    old = _metrics(reference)
    new = _metrics(candidate)
    return (
        new.fatal_rate > old.fatal_rate + tolerance
        or new.invalid_action_rate > old.invalid_action_rate + tolerance
    )


def has_excessive_call_regression(
    reference: EvaluationResult | EvaluationMetrics,
    candidate: EvaluationResult | EvaluationMetrics,
    *,
    ratio: float = 1.25,
) -> bool:
    old = _metrics(reference)
    new = _metrics(candidate)
    one_sample = 1.0 / max(old.sample_count, 1)
    return any(
        new_value > max(old_value * ratio, one_sample)
        for old_value, new_value in (
            (old.observe_calls_per_sample, new.observe_calls_per_sample),
            (old.watch_calls_per_sample, new.watch_calls_per_sample),
        )
    )


def is_repairable_candidate(
    reference: EvaluationResult | EvaluationMetrics,
    candidate: EvaluationResult | EvaluationMetrics,
) -> bool:
    """Keep a beneficial direction only long enough to repair its regression."""

    old = _metrics(reference)
    new = _metrics(candidate)
    if new.official_score <= old.official_score:
        return False
    if has_hard_reliability_regression(old, new):
        return False
    return has_excessive_call_regression(old, new)


__all__ = [
    "has_excessive_call_regression",
    "has_hard_reliability_regression",
    "is_repairable_candidate",
]
