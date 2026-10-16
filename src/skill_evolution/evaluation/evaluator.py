from __future__ import annotations

import math
from collections.abc import Mapping, MutableMapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from ..benchmarks.aggregation import MeanScoreAggregator, ScoreAggregation
from ..strategy.contracts import (
    ComparisonResult,
    EvaluationKey,
    EvaluationMetrics,
    EvaluationResult,
    Role,
    SkillSet,
    TraceCase,
    hash_json,
)
from .trace_projector import TrajectoryProjector


def role_was_invoked(episode: RolloutArtifact, role: Role) -> bool:
    """Return whether an immutable episode proves that one Planner ran."""

    if Role(role) is Role.GLOBAL:
        return True
    artifact = episode.artifact
    nested = artifact.get("result")
    result = nested if isinstance(nested, Mapping) else artifact
    trajectory = result.get("trajectory")
    if isinstance(trajectory, Sequence) and not isinstance(
        trajectory, (str, bytes)
    ):
        if any(
            isinstance(item, Mapping) and item.get("agent") == "VideoAgent"
            for item in trajectory
        ):
            return True
        if trajectory:
            return False
    history = result.get("action_history")
    if isinstance(history, Sequence) and not isinstance(history, (str, bytes)):
        return any(
            isinstance(item, Mapping) and item.get("action") == "analyze_videos"
            for item in history
        )
    # Legacy or incomplete artifacts cannot prove inactivity, so rerun.
    return True


EVALUATOR_POLICY = "role-activation-reuse-v2"


@dataclass(frozen=True)
class EvaluationContext:
    """Frozen rollout and scoring identity, excluding Skill text."""

    sample_ids: tuple[str, ...]
    input_hashes: Mapping[str, str]
    rollout_seed: int
    execution_identity: Mapping[str, str]
    evaluation_identity: Mapping[str, str]

    def __post_init__(self) -> None:
        sample_ids = tuple(str(item).strip() for item in self.sample_ids if str(item).strip())
        if not sample_ids or len(sample_ids) != len(set(sample_ids)):
            raise ValueError("EvaluationContext sample IDs must be non-empty and unique.")
        input_hashes = {str(key): str(value) for key, value in self.input_hashes.items()}
        if set(input_hashes) != set(sample_ids):
            raise ValueError("input_hashes must contain exactly the frozen sample IDs.")
        if any(
            len(value) != 64 or any(char not in "0123456789abcdef" for char in value.lower())
            for value in input_hashes.values()
        ):
            raise ValueError("Every input_hashes value must be a SHA256 digest.")
        input_hashes = {key: value.lower() for key, value in input_hashes.items()}
        execution = {str(key): str(value) for key, value in self.execution_identity.items()}
        evaluation = {str(key): str(value) for key, value in self.evaluation_identity.items()}
        required_execution = {
            "benchmark_adapter",
            "effective_config",
            "runtime_snapshot",
            "decoding",
        }
        evaluation.setdefault("aggregator", MeanScoreAggregator.identity)
        required_evaluation = {
            "scorer",
            "aggregator",
            "projector",
            "evaluator_prompt",
        }
        if missing := sorted(required_execution - set(execution)):
            raise ValueError("Execution identity is missing: " + ", ".join(missing))
        if missing := sorted(required_evaluation - set(evaluation)):
            raise ValueError("Evaluation identity is missing: " + ", ".join(missing))
        object.__setattr__(self, "sample_ids", sample_ids)
        object.__setattr__(self, "input_hashes", input_hashes)
        object.__setattr__(self, "rollout_seed", int(self.rollout_seed))
        object.__setattr__(self, "execution_identity", execution)
        object.__setattr__(self, "evaluation_identity", evaluation)

    @property
    def execution_context_hash(self) -> str:
        return hash_json(dict(self.execution_identity))

    @property
    def context_hash(self) -> str:
        return hash_json(
            {
                "ordered_inputs": [
                    [sample_id, self.input_hashes[sample_id]] for sample_id in self.sample_ids
                ],
                "rollout_seed": self.rollout_seed,
                "execution_context_hash": self.execution_context_hash,
                "evaluation_identity": dict(self.evaluation_identity),
                "evaluator_policy": EVALUATOR_POLICY,
            }
        )

    def rollout_cache_key(self, skill_set: SkillSet, sample_id: str) -> str:
        if sample_id not in self.input_hashes:
            raise ValueError(f"Unknown sample ID: {sample_id}")
        return hash_json(
            {
                "sample_id": sample_id,
                "input_hash": self.input_hashes[sample_id],
                "skill_set_hash": skill_set.skill_set_hash(),
                "rollout_seed": self.rollout_seed,
                "execution_context_hash": self.execution_context_hash,
            }
        )


@dataclass(frozen=True)
class EvaluationRequest:
    skill_set: SkillSet
    context: EvaluationContext
    sample_ids: tuple[str, ...]
    label: str


@dataclass(frozen=True)
class RolloutArtifact:
    sample_id: str
    artifact: Mapping[str, Any]
    bucket: str = "default"
    status: str = "ok"

    def __post_init__(self) -> None:
        object.__setattr__(self, "sample_id", str(self.sample_id).strip())
        object.__setattr__(self, "bucket", str(self.bucket or "default"))
        object.__setattr__(self, "status", str(self.status or "unknown"))
        if not self.sample_id:
            raise ValueError("RolloutArtifact.sample_id must be non-empty.")


class RolloutExecutor(Protocol):
    def execute(self, request: EvaluationRequest) -> Sequence[RolloutArtifact]: ...


class BatchScorer(Protocol):
    """Return official per-sample scores; may use a benchmark batch judge."""

    def score(self, artifacts: Sequence[RolloutArtifact]) -> Mapping[str, float]: ...


class ScoreAggregator(Protocol):
    """Combine normalized per-sample scores without depending on an optimizer."""

    identity: str

    def aggregate(
        self,
        *,
        sample_ids: Sequence[str],
        scores: Mapping[str, float],
        buckets: Mapping[str, str],
    ) -> ScoreAggregation: ...


@dataclass(frozen=True)
class PairwiseJudgment:
    local_preference: float | None = None
    lookahead_preference: float | None = None
    misalignment_ids: tuple[str, ...] = ()


class PairwiseJudge(Protocol):
    def compare(
        self,
        *,
        role: Role,
        reference_cases: Sequence[TraceCase],
        candidate_cases: Sequence[TraceCase],
    ) -> PairwiseJudgment: ...


class SkillSetEvaluator:
    """Complete-rollout evaluator with exact episode and result cache keys."""

    def __init__(
        self,
        *,
        executor: RolloutExecutor,
        scorer: BatchScorer,
        context: EvaluationContext,
        projector: TrajectoryProjector | None = None,
        pairwise_judge: PairwiseJudge | None = None,
        score_aggregator: ScoreAggregator | None = None,
        episode_cache: MutableMapping[str, RolloutArtifact] | None = None,
        evaluation_cache: MutableMapping[str, EvaluationResult] | None = None,
    ) -> None:
        self.executor = executor
        self.scorer = scorer
        self.context = context
        self.projector = projector or TrajectoryProjector()
        self.pairwise_judge = pairwise_judge
        self.score_aggregator = score_aggregator or MeanScoreAggregator()
        if self.context.evaluation_identity["aggregator"] != self.score_aggregator.identity:
            raise ValueError(
                "EvaluationContext aggregator identity does not match the configured "
                "score aggregator."
            )
        self.episode_cache = episode_cache if episode_cache is not None else {}
        self.evaluation_cache = evaluation_cache if evaluation_cache is not None else {}

    def evaluate(self, *, skill_set: SkillSet, label: str) -> EvaluationResult:
        return self._evaluate(skill_set=skill_set, label=label)

    def evaluate_role_candidate(
        self,
        *,
        skill_set: SkillSet,
        reference_skill_set: SkillSet,
        changed_role: Role,
        label: str,
    ) -> EvaluationResult:
        """Evaluate one role-local edit without rerunning provably inactive samples.

        A Video Skill cannot affect an episode in which no Video Planner was invoked.
        Reusing the reference artifact for those samples removes unrelated visual-model
        variation from the paired comparison and avoids an unnecessary full rollout.
        Global planning is always on the answer path, so Global edits still rerun every
        sample.
        """

        role = Role(changed_role)
        other = Role.VIDEO if role is Role.GLOBAL else Role.GLOBAL
        if skill_set.get(other) != reference_skill_set.get(other):
            raise ValueError(
                "A role-local candidate evaluation may change exactly one role Skill."
            )
        if skill_set.get(role) == reference_skill_set.get(role):
            return self.evaluate(skill_set=skill_set, label=label)
        if role is Role.GLOBAL:
            return self.evaluate(skill_set=skill_set, label=label)

        # The reference is normally already evaluated by the coordinator. Calling the
        # cached path here also makes this public method safe to use independently.
        self.evaluate(
            skill_set=reference_skill_set,
            label=f"{label}-reference",
        )
        reusable: dict[str, RolloutArtifact] = {}
        for sample_id in self.context.sample_ids:
            reference = self.episode_cache[
                self.context.rollout_cache_key(reference_skill_set, sample_id)
            ]
            if not role_was_invoked(reference, role):
                reusable[sample_id] = reference
        return self._evaluate(
            skill_set=skill_set,
            label=label,
            reusable=reusable,
        )

    def _evaluate(
        self,
        *,
        skill_set: SkillSet,
        label: str,
        reusable: Mapping[str, RolloutArtifact] | None = None,
    ) -> EvaluationResult:
        key = EvaluationKey(
            skill_set_hash=skill_set.skill_set_hash(),
            context_hash=self.context.context_hash,
        )
        if cached := self.evaluation_cache.get(key.cache_key):
            return cached

        episodes: dict[str, RolloutArtifact] = {}
        missing: list[str] = []
        reusable = reusable or {}
        for sample_id in self.context.sample_ids:
            cache_key = self.context.rollout_cache_key(skill_set, sample_id)
            if sample_id in reusable:
                episodes[sample_id] = reusable[sample_id]
                # Alias the immutable raw artifact under the candidate cache key. This
                # keeps later absolute reads and checkpoint resumes causally consistent.
                self.episode_cache[cache_key] = reusable[sample_id]
            elif cached := self.episode_cache.get(cache_key):
                episodes[sample_id] = cached
            else:
                missing.append(sample_id)
        if missing:
            request = EvaluationRequest(
                skill_set=skill_set,
                context=self.context,
                sample_ids=tuple(missing),
                label=str(label),
            )
            generated = tuple(self.executor.execute(request))
            if len(generated) != len(missing):
                raise ValueError(
                    f"Rollout executor returned {len(generated)} episodes for {len(missing)} requested samples."
                )
            by_id = {item.sample_id: item for item in generated}
            if set(by_id) != set(missing):
                raise ValueError("Rollout executor returned duplicate, missing, or unexpected sample IDs.")
            for sample_id, artifact in by_id.items():
                episodes[sample_id] = artifact
                self.episode_cache[
                    self.context.rollout_cache_key(skill_set, sample_id)
                ] = artifact

        ordered = tuple(episodes[sample_id] for sample_id in self.context.sample_ids)
        scored = self.scorer.score(ordered)
        if set(scored) != set(self.context.sample_ids):
            raise ValueError("Scorer must return exactly one score for every frozen sample ID.")
        score_map: dict[str, float] = {}
        for sample_id in self.context.sample_ids:
            score = float(scored[sample_id])
            if not math.isfinite(score) or not 0.0 <= score <= 1.0:
                raise ValueError(
                    f"Scorer returned an invalid normalized score for {sample_id!r}."
                )
            score_map[sample_id] = score
        scores = tuple(score_map[sample_id] for sample_id in self.context.sample_ids)
        metrics = self._aggregate(ordered, score_map)
        cases = tuple(
            case
            for episode, score in zip(ordered, scores, strict=True)
            for case in self.projector.project(episode.artifact, official_score=score)
        )
        result = EvaluationResult(
            key=key,
            metrics=metrics,
            evidence_ids=tuple(
                case.case_id for case in cases if case.outcome in {"fail", "partial"}
            ),
            cases=cases,
            reused_sample_ids=tuple(
                sample_id
                for sample_id in self.context.sample_ids
                if sample_id in reusable
            ),
        )
        self.evaluation_cache[key.cache_key] = result
        return result

    def compare(
        self,
        *,
        role: Role,
        reference: EvaluationResult,
        candidate: EvaluationResult,
    ) -> ComparisonResult:
        if reference.key.context_hash != candidate.key.context_hash:
            raise ValueError("Paired evaluations must share exactly one context_hash.")
        judgment = PairwiseJudgment()
        if self.pairwise_judge is not None:
            judgment = self.pairwise_judge.compare(
                role=Role(role),
                reference_cases=tuple(case for case in reference.cases if case.role == Role(role)),
                candidate_cases=tuple(case for case in candidate.cases if case.role == Role(role)),
            )
        return ComparisonResult(
            role=Role(role),
            reference_key=reference.key,
            candidate_key=candidate.key,
            official_delta=candidate.metrics.official_score - reference.metrics.official_score,
            local_preference=judgment.local_preference,
            lookahead_preference=judgment.lookahead_preference,
            misalignment_ids=judgment.misalignment_ids,
        )

    def _aggregate(
        self,
        episodes: Sequence[RolloutArtifact],
        scores: Mapping[str, float],
    ) -> EvaluationMetrics:
        sample_count = len(episodes)
        if not sample_count:
            raise ValueError("Evaluation requires at least one rollout artifact.")
        fatal = invalid = observe = watch = 0
        aggregation = self.score_aggregator.aggregate(
            sample_ids=tuple(episode.sample_id for episode in episodes),
            scores=scores,
            buckets={episode.sample_id: episode.bucket for episode in episodes},
        )
        for episode in episodes:
            artifact = episode.artifact
            nested = artifact.get("result")
            result = nested if isinstance(nested, Mapping) else artifact
            history = result.get("action_history")
            history = history if isinstance(history, Sequence) and not isinstance(history, (str, bytes)) else ()
            trajectory = result.get("trajectory")
            trajectory = (
                trajectory
                if isinstance(trajectory, Sequence)
                and not isinstance(trajectory, (str, bytes))
                else ()
            )
            fatal += int(episode.status not in {"ok", "answered"})
            invalid += int(
                any(
                    isinstance(item, Mapping)
                    and (item.get("action") == "invalid_decision" or item.get("status") == "invalid")
                    for item in history
                )
            )
            watch += sum(
                1
                for item in history
                if isinstance(item, Mapping) and item.get("action") == "watch_videos"
            )
            for item in trajectory:
                if not isinstance(item, Mapping) or item.get("agent") != "VideoAgent":
                    continue
                output = item.get("output")
                steps = output.get("steps") if isinstance(output, Mapping) else ()
                if not isinstance(steps, Sequence) or isinstance(steps, (str, bytes)):
                    continue
                observe += sum(
                    1
                    for step in steps
                    if isinstance(step, Mapping) and step.get("action") == "observe"
                )
        return EvaluationMetrics(
            sample_count=sample_count,
            official_score=aggregation.official_score,
            fatal_rate=fatal / sample_count,
            invalid_action_rate=invalid / sample_count,
            observe_calls_per_sample=observe / sample_count,
            watch_calls_per_sample=watch / sample_count,
            bucket_scores=aggregation.bucket_scores,
        )


__all__ = [
    "BatchScorer",
    "EVALUATOR_POLICY",
    "EvaluationContext",
    "EvaluationRequest",
    "PairwiseJudge",
    "PairwiseJudgment",
    "RolloutArtifact",
    "RolloutExecutor",
    "ScoreAggregator",
    "SkillSetEvaluator",
]
