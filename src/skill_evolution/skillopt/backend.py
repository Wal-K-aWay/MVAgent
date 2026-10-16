from __future__ import annotations

import json
import math
from collections.abc import Mapping, MutableMapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from ..benchmarks.scoring import ScoreResult
from ..evaluation import (
    BatchScorer,
    EvaluationContext,
    EvaluationRequest,
    RolloutArtifact,
    RolloutExecutor,
    TrajectoryProjector,
    role_was_invoked,
)
from ..strategy import Role, SkillSet
from ..strategy.patcher import render_trace_case, trace_case_event_count
from .adapter import RoleRolloutRequest, RoleRolloutResult


class _ReflectionBatchScorer(BatchScorer, Protocol):
    """Official scores plus the task-specific SkillOpt success label."""

    def score_results(
        self,
        artifacts: Sequence[RolloutArtifact],
    ) -> Mapping[str, ScoreResult]: ...


@dataclass(frozen=True, slots=True)
class RoleSampleMetadata:
    """Frozen task metadata; reference text is exposed only to Global Train."""

    task_description: str
    task_type: str
    reference_text: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "task_description",
            str(self.task_description or "").strip(),
        )
        object.__setattr__(self, "task_type", str(self.task_type or "").strip())
        object.__setattr__(
            self,
            "reference_text",
            str(self.reference_text or "").strip(),
        )


class MVAgentRoleRolloutBackend:
    """Execute complete MVAgent questions and expose one target-role trajectory.

    This class deliberately knows nothing about Reflect, Merge, Ranking, edits,
    learning rates, or Slow Update.  It is only the environment implementation
    behind SkillOpt's public ``EnvAdapter``.
    """

    def __init__(
        self,
        *,
        executor: RolloutExecutor,
        scorer: _ReflectionBatchScorer,
        train_context: EvaluationContext,
        selection_context: EvaluationContext,
        projector: TrajectoryProjector,
        sample_metadata: Mapping[str, RoleSampleMetadata],
        episode_cache: MutableMapping[str, RolloutArtifact] | None = None,
    ) -> None:
        self.executor = executor
        if not callable(getattr(scorer, "score_results", None)):
            raise TypeError(
                "SkillOpt rollout scoring requires score_results() so task-specific "
                "reflection success cannot be confused with the official score."
            )
        self.scorer = scorer
        overlap = set(train_context.sample_ids) & set(selection_context.sample_ids)
        if overlap:
            raise ValueError("Train and selection contexts must be disjoint.")
        self.train_context = train_context
        self.selection_context = selection_context
        self.projector = projector
        self.sample_metadata = {
            str(sample_id): metadata
            for sample_id, metadata in sample_metadata.items()
        }
        expected_ids = set(train_context.sample_ids) | set(selection_context.sample_ids)
        if set(self.sample_metadata) != expected_ids:
            raise ValueError(
                "Role sample metadata must contain exactly the frozen context IDs."
            )
        self.episode_cache = episode_cache if episode_cache is not None else {}

    def rollout(
        self,
        request: RoleRolloutRequest,
    ) -> Sequence[RoleRolloutResult]:
        context = self._context(request)
        if any(sample_id not in context.input_hashes for sample_id in request.sample_ids):
            raise ValueError("Role rollout requested a sample outside its frozen context.")
        artifacts = self._artifacts(request, context=context)
        score_results = self.scorer.score_results(artifacts)
        if set(score_results) != set(request.sample_ids):
            raise ValueError(
                "Scorer must return exactly one ScoreResult per requested sample."
            )

        results: list[RoleRolloutResult] = []
        for artifact in artifacts:
            assessment = score_results[artifact.sample_id]
            if not isinstance(assessment, ScoreResult):
                raise TypeError("Scorer score_results() values must be ScoreResult.")
            score = assessment.score
            if not math.isfinite(score) or not 0.0 <= score <= 1.0:
                raise ValueError(
                    f"Scorer returned an invalid normalized score for {artifact.sample_id!r}."
                )
            projected = self.projector.project(
                artifact.artifact,
                official_score=score,
            )
            cases = tuple(case for case in projected if case.role is request.role)
            invoked = bool(cases)
            trajectory = self._trajectory_text(request.role, cases)
            metadata = self.sample_metadata[artifact.sample_id]
            result_payload = artifact.artifact.get("result")
            result_payload = (
                result_payload if isinstance(result_payload, Mapping) else artifact.artifact
            )
            answer = result_payload.get("answer")
            answer = answer if isinstance(answer, Mapping) else {}
            prediction = artifact.artifact.get("prediction", answer.get("answer", ""))
            feedback = (
                self._feedback(cases)
                if request.phase == "train" and request.role is Role.GLOBAL
                else ""
            )
            hard = 1.0 if assessment.reflection_success else 0.0
            fail_reason = (
                ""
                if hard
                else self._failure_reason(
                    artifact=artifact,
                    score=score,
                    cases=cases,
                    feedback=feedback,
                    invoked=invoked,
                )
            )
            results.append(
                RoleRolloutResult(
                    sample_id=artifact.sample_id,
                    hard=hard,
                    soft=score,
                    trajectory_text=trajectory,
                    task_description=self._task_description(
                        role=request.role,
                        cases=cases,
                        fallback=metadata.task_description,
                    ),
                    task_type=metadata.task_type or f"mvagent_{request.role.value}",
                    n_turns=self._turn_count(cases),
                    fail_reason=fail_reason,
                    reference_text=(
                        metadata.reference_text or feedback
                        if request.phase == "train" and request.role is Role.GLOBAL
                        else ""
                    ),
                    predicted_answer=str(prediction or ""),
                    invoked=invoked,
                )
            )
        return tuple(results)

    def _artifacts(
        self,
        request: RoleRolloutRequest,
        *,
        context: EvaluationContext,
    ) -> tuple[RolloutArtifact, ...]:
        candidate = request.candidate_skill_set
        anchor = request.anchor_skill_set
        candidate_cached = self._cached(
            skill_set=candidate,
            sample_ids=request.sample_ids,
            context=context,
        )
        missing = tuple(
            sample_id
            for sample_id in request.sample_ids
            if sample_id not in candidate_cached
        )
        if (
            request.role is Role.VIDEO
            and candidate != anchor
            and missing
        ):
            anchor_artifacts = self._cached_or_execute(
                skill_set=anchor,
                sample_ids=missing,
                context=context,
                label=f"{request.label}-anchor-activation",
            )
            still_missing: list[str] = []
            for sample_id in missing:
                reference = anchor_artifacts[sample_id]
                if role_was_invoked(reference, Role.VIDEO):
                    still_missing.append(sample_id)
                    continue
                candidate_cached[sample_id] = reference
                self.episode_cache[
                    context.rollout_cache_key(candidate, sample_id)
                ] = reference
            missing = tuple(still_missing)
        if missing:
            candidate_cached.update(
                self._cached_or_execute(
                    skill_set=candidate,
                    sample_ids=missing,
                    context=context,
                    label=request.label,
                )
            )
        return tuple(candidate_cached[sample_id] for sample_id in request.sample_ids)

    def _cached(
        self,
        *,
        skill_set: SkillSet,
        sample_ids: Sequence[str],
        context: EvaluationContext,
    ) -> dict[str, RolloutArtifact]:
        found: dict[str, RolloutArtifact] = {}
        for sample_id in sample_ids:
            cached = self.episode_cache.get(
                context.rollout_cache_key(skill_set, sample_id)
            )
            if cached is not None:
                found[sample_id] = cached
        return found

    def _cached_or_execute(
        self,
        *,
        skill_set: SkillSet,
        sample_ids: Sequence[str],
        context: EvaluationContext,
        label: str,
    ) -> dict[str, RolloutArtifact]:
        found = self._cached(
            skill_set=skill_set,
            sample_ids=sample_ids,
            context=context,
        )
        missing = tuple(sample_id for sample_id in sample_ids if sample_id not in found)
        if not missing:
            return found
        generated = tuple(
            self.executor.execute(
                EvaluationRequest(
                    skill_set=skill_set,
                    context=context,
                    sample_ids=missing,
                    label=label,
                )
            )
        )
        by_id = {item.sample_id: item for item in generated}
        if len(by_id) != len(generated) or set(by_id) != set(missing):
            raise ValueError(
                "Rollout executor returned duplicate, missing, or unexpected samples."
            )
        for sample_id, artifact in by_id.items():
            self.episode_cache[
                context.rollout_cache_key(skill_set, sample_id)
            ] = artifact
            found[sample_id] = artifact
        return found

    def _context(self, request: RoleRolloutRequest) -> EvaluationContext:
        if request.phase == "train":
            if request.split != "train":
                raise ValueError("Train role rollouts must use the train split.")
            return self.train_context
        if request.split not in {"valid_seen", "selection", "val"}:
            raise ValueError("Selection role rollouts must use the frozen Eval split.")
        return self.selection_context

    @staticmethod
    def _trajectory_text(role: Role, cases: Sequence[Any]) -> str:
        if not cases:
            return ""
        if Role(role) is Role.GLOBAL:
            if len(cases) != 1:
                raise ValueError("One question must project exactly one Global trajectory.")
            return render_trace_case(
                cases[0],
                heading="Global Planner trajectory",
                include_failure_reason=False,
                include_runtime_finalizers=False,
            )
        return "\n\n".join(
            render_trace_case(
                case,
                heading=f"Video Planner trajectory {index}",
                include_failure_reason=False,
                include_runtime_finalizers=False,
            )
            for index, case in enumerate(cases, 1)
        )

    @staticmethod
    def _task_description(
        *,
        role: Role,
        cases: Sequence[Any],
        fallback: str,
    ) -> str:
        if Role(role) is Role.GLOBAL:
            return fallback
        requests: list[str] = []
        for case in cases:
            raw = str(getattr(case, "visible_input", "") or "").strip()
            try:
                value = json.loads(raw)
            except (TypeError, ValueError, json.JSONDecodeError):
                value = {}
            if not isinstance(value, Mapping):
                continue
            video_id = str(value.get("video_id") or "unknown")
            instruction = str(value.get("instruction") or "").strip()
            duration = value.get("duration_sec", "unavailable")
            requests.append(
                f"video={video_id}; instruction={instruction}; "
                f"duration_sec={duration}"
            )
        return " | ".join(requests) or "Single-video Planner request."

    @staticmethod
    def _feedback(cases: Sequence[Any]) -> str:
        for case in cases:
            text = str(getattr(case, "outcome_feedback", "") or "").strip()
            if not text:
                continue
            try:
                parsed = json.loads(text)
            except (TypeError, ValueError, json.JSONDecodeError):
                return text
            if isinstance(parsed, Mapping):
                parts = []
                ground_truth = parsed.get("ground_truth")
                if ground_truth not in (None, ""):
                    parts.append(
                        "Ground truth: "
                        + json.dumps(ground_truth, ensure_ascii=False)
                    )
                outcome = str(parsed.get("outcome") or "").strip()
                if outcome:
                    parts.append(f"Outcome: {outcome}")
                detail = str(parsed.get("feedback") or "").strip()
                if detail:
                    parts.append(f"Scorer feedback: {detail}")
                return "\n".join(parts)
            return text
        return ""

    @staticmethod
    def _failure_reason(
        *,
        artifact: RolloutArtifact,
        score: float,
        cases: Sequence[Any],
        feedback: str,
        invoked: bool,
    ) -> str:
        parts: list[str] = []
        if artifact.status not in {"ok", "answered"}:
            parts.append(f"MVAgent execution status: {artifact.status}")
        if score < 1.0:
            parts.append(f"Official normalized score: {score:.6f}")
        if not invoked:
            parts.append("The target Planner was not invoked in this question.")
        issues = [
            str(getattr(case, "observed_issue", "") or "").strip()
            for case in cases
        ]
        parts.extend(dict.fromkeys(issue for issue in issues if issue))
        if feedback:
            parts.append(feedback.replace("\n", "; "))
        return " | ".join(parts)

    @staticmethod
    def _turn_count(cases: Sequence[Any]) -> int:
        return sum(
            trace_case_event_count(
                case,
                include_runtime_finalizers=False,
            )
            for case in cases
        )


__all__ = [
    "MVAgentRoleRolloutBackend",
    "RoleSampleMetadata",
]
