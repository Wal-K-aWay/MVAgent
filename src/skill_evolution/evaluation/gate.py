from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol

from ..strategy.contracts import EvaluationResult, GateDecision, SkillSet


@dataclass(frozen=True)
class GatePolicy:
    min_samples: int = 50
    official_delta_min: float = 0.0
    bucket_delta_min: float = -0.02
    fatal_rate_delta_max: float = 0.0
    invalid_action_rate_delta_max: float = 0.0
    observe_call_ratio_max: float = 1.20
    watch_call_ratio_max: float = 1.20
    required_references: Mapping[str, tuple[str, ...]] = field(
        default_factory=lambda: {
            "smoke": ("parent",),
            "public": ("no_skill", "authored", "parent"),
            "interaction": ("global_only", "video_only"),
            "private": ("no_skill", "authored", "parent"),
        }
    )
    stage_min_samples: Mapping[str, int] = field(
        default_factory=lambda: {"smoke": 6}
    )

    def __post_init__(self) -> None:
        if self.min_samples < 1:
            raise ValueError("min_samples must be positive.")
        for name in ("observe_call_ratio_max", "watch_call_ratio_max"):
            if float(getattr(self, name)) < 1.0:
                raise ValueError(f"{name} must be at least 1.0.")
        normalized = {
            str(stage): tuple(str(reference) for reference in references)
            for stage, references in self.required_references.items()
        }
        if not normalized:
            raise ValueError("Gate requires at least one evaluation stage.")
        object.__setattr__(self, "required_references", normalized)
        stage_minimums = {
            str(stage): int(value) for stage, value in self.stage_min_samples.items()
        }
        if any(value < 1 for value in stage_minimums.values()):
            raise ValueError("stage_min_samples values must be positive.")
        object.__setattr__(self, "stage_min_samples", stage_minimums)


@dataclass(frozen=True)
class GateStageEvaluation:
    candidate: EvaluationResult
    references: Mapping[str, EvaluationResult]


class StageEvaluator(Protocol):
    def evaluate(self, *, skill_set: SkillSet, label: str) -> EvaluationResult: ...


@dataclass(frozen=True)
class GateStageSpec:
    evaluator: StageEvaluator
    references: Mapping[str, SkillSet]
    reuse_search_evaluation: bool = False


class PromotionEvaluator:
    """Build all staged candidate/reference results through injected evaluators."""

    def __init__(self, stages: Mapping[str, GateStageSpec]) -> None:
        self.stages = dict(stages)
        if not self.stages:
            raise ValueError("PromotionEvaluator requires at least one stage.")

    @property
    def identity(self) -> Mapping[str, Any]:
        return {
            stage: {
                "context_hash": getattr(
                    getattr(spec.evaluator, "context", None), "context_hash", "unknown"
                ),
                "references": {
                    name: skill_set.skill_set_hash()
                    for name, skill_set in spec.references.items()
                },
                "reuse_search_evaluation": spec.reuse_search_evaluation,
            }
            for stage, spec in self.stages.items()
        }

    def evaluate(
        self,
        *,
        skill_set: SkillSet,
        search_evaluation: EvaluationResult,
    ) -> Mapping[str, GateStageEvaluation]:
        results: dict[str, GateStageEvaluation] = {}
        for stage, spec in self.stages.items():
            context_hash = getattr(
                getattr(spec.evaluator, "context", None), "context_hash", None
            )
            if (
                spec.reuse_search_evaluation
                and search_evaluation.key.skill_set_hash == skill_set.skill_set_hash()
                and search_evaluation.key.context_hash == context_hash
            ):
                candidate = search_evaluation
            else:
                candidate = spec.evaluator.evaluate(
                    skill_set=skill_set,
                    label=f"gate-{stage}-candidate",
                )
            references = {
                name: spec.evaluator.evaluate(
                    skill_set=reference,
                    label=f"gate-{stage}-reference-{name}",
                )
                for name, reference in spec.references.items()
            }
            results[stage] = GateStageEvaluation(candidate, references)
        return results


@dataclass(frozen=True)
class GateReport:
    skill_set_hash: str
    decision: GateDecision
    stage_context_hashes: Mapping[str, str]
    reference_deltas: Mapping[str, Mapping[str, float]]
    passed_checks: tuple[str, ...]
    failed_checks: tuple[str, ...]
    pending_checks: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "skill_set_hash": self.skill_set_hash,
            "decision": self.decision.value,
            "stage_context_hashes": dict(self.stage_context_hashes),
            "reference_deltas": {
                stage: dict(values) for stage, values in self.reference_deltas.items()
            },
            "passed_checks": list(self.passed_checks),
            "failed_checks": list(self.failed_checks),
            "pending_checks": list(self.pending_checks),
        }


class PromotionGate:
    """Static, smoke, paired, interaction, and private promotion guardrail."""

    def __init__(self, policy: GatePolicy | None = None) -> None:
        self.policy = policy or GatePolicy()

    def evaluate(
        self,
        *,
        skill_set: SkillSet,
        stages: Mapping[str, GateStageEvaluation],
    ) -> GateReport:
        passed: list[str] = []
        failed: list[str] = []
        pending: list[str] = []
        deltas: dict[str, dict[str, float]] = {}
        context_hashes: dict[str, str] = {}

        if not skill_set.is_promotable:
            failed.append("static: at least one role Skill must be non-empty")

        for stage_name, required_references in self.policy.required_references.items():
            stage = stages.get(stage_name)
            if stage is None:
                pending.append(f"{stage_name}: evaluation is missing")
                continue
            missing = sorted(set(required_references) - set(stage.references))
            if missing:
                pending.append(
                    f"{stage_name}: missing references " + ", ".join(missing)
                )
                continue
            candidate = stage.candidate
            if candidate.key.skill_set_hash != skill_set.skill_set_hash():
                failed.append(f"{stage_name}: candidate SkillSet hash mismatch")
                continue
            context_hashes[stage_name] = candidate.key.context_hash
            selected_references = {
                name: stage.references[name] for name in required_references
            }
            if any(
                reference.key.context_hash != candidate.key.context_hash
                for reference in selected_references.values()
            ):
                failed.append(f"{stage_name}: candidate/reference context mismatch")
                continue
            stage_deltas = {
                name: candidate.metrics.official_score - reference.metrics.official_score
                for name, reference in selected_references.items()
            }
            deltas[stage_name] = stage_deltas
            stage_min_samples = self.policy.stage_min_samples.get(
                stage_name, self.policy.min_samples
            )
            insufficient = [
                name
                for name, result in {"candidate": candidate, **selected_references}.items()
                if result.metrics.sample_count < stage_min_samples
            ]
            if insufficient:
                pending.append(
                    f"{stage_name}: insufficient sample_count for "
                    + ", ".join(insufficient)
                )
                continue
            for reference_name, reference in selected_references.items():
                self._compare_metrics(
                    prefix=f"{stage_name}.{reference_name}",
                    candidate=candidate,
                    reference=reference,
                    official_delta=stage_deltas[reference_name],
                    passed=passed,
                    failed=failed,
                )

        if failed:
            decision = GateDecision.REJECT
        elif pending:
            decision = GateDecision.HOLD
        else:
            decision = GateDecision.READY
        return GateReport(
            skill_set_hash=skill_set.skill_set_hash(),
            decision=decision,
            stage_context_hashes=context_hashes,
            reference_deltas=deltas,
            passed_checks=tuple(passed),
            failed_checks=tuple(failed),
            pending_checks=tuple(pending),
        )

    def _compare_metrics(
        self,
        *,
        prefix: str,
        candidate: EvaluationResult,
        reference: EvaluationResult,
        official_delta: float,
        passed: list[str],
        failed: list[str],
    ) -> None:
        candidate_metrics = candidate.metrics
        reference_metrics = reference.metrics
        self._check_minimum(
            f"{prefix}.official_score",
            official_delta,
            self.policy.official_delta_min,
            passed,
            failed,
        )
        for name, limit in (
            ("fatal_rate", self.policy.fatal_rate_delta_max),
            ("invalid_action_rate", self.policy.invalid_action_rate_delta_max),
        ):
            self._check_maximum(
                f"{prefix}.{name}",
                getattr(candidate_metrics, name) - getattr(reference_metrics, name),
                limit,
                passed,
                failed,
            )
        for name, limit in (
            ("observe_calls_per_sample", self.policy.observe_call_ratio_max),
            ("watch_calls_per_sample", self.policy.watch_call_ratio_max),
        ):
            self._check_ratio(
                f"{prefix}.{name}",
                getattr(candidate_metrics, name),
                getattr(reference_metrics, name),
                limit,
                passed,
                failed,
            )
        for bucket, reference_score in reference_metrics.bucket_scores.items():
            if bucket not in candidate_metrics.bucket_scores:
                failed.append(f"{prefix}.bucket_{bucket}: missing candidate score")
                continue
            self._check_minimum(
                f"{prefix}.bucket_{bucket}",
                candidate_metrics.bucket_scores[bucket] - reference_score,
                self.policy.bucket_delta_min,
                passed,
                failed,
            )

    @staticmethod
    def _check_minimum(
        label: str,
        value: float,
        minimum: float,
        passed: list[str],
        failed: list[str],
    ) -> None:
        if value >= minimum:
            passed.append(label)
        else:
            failed.append(f"{label}: {value:.6f} < {minimum:.6f}")

    @staticmethod
    def _check_maximum(
        label: str,
        value: float,
        maximum: float,
        passed: list[str],
        failed: list[str],
    ) -> None:
        if value <= maximum:
            passed.append(label)
        else:
            failed.append(f"{label}: {value:.6f} > {maximum:.6f}")

    @staticmethod
    def _check_ratio(
        label: str,
        candidate: float,
        reference: float,
        maximum: float,
        passed: list[str],
        failed: list[str],
    ) -> None:
        ratio = (1.0 if candidate <= 0.0 else float("inf")) if reference <= 0.0 else candidate / reference
        if ratio <= maximum:
            passed.append(label)
        else:
            failed.append(f"{label}: ratio {ratio:.6f} > {maximum:.6f}")


__all__ = [
    "GatePolicy",
    "GateReport",
    "GateStageEvaluation",
    "GateStageSpec",
    "PromotionEvaluator",
    "PromotionGate",
    "StageEvaluator",
]
