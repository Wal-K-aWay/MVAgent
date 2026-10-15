from __future__ import annotations

import json
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mvagent.configs import MVAgentConfig

from ..benchmarks.aggregation import MeanScoreAggregator
from ..benchmarks.scoring import REFLECTION_SUCCESS_POLICY
from ..evaluation import (
    BatchScorer,
    EvaluationContext,
    GateReport,
    GateStageEvaluation,
    JsonEpisodeCache,
    PromotionGate,
    RolloutArtifact,
    RolloutExecutor,
    ScoreAggregator,
    SkillSetEvaluator,
    TrajectoryProjector,
)
from ..strategy import EvaluationResult, GateDecision, Role, SkillSet
from ..strategy.contracts import hash_json
from ..strategy.patcher import build_role_architectures
from .adapter import SkillOptCoordinateRunner
from .backend import MVAgentRoleRolloutBackend, RoleSampleMetadata
from .config import SkillOptEvolutionConfig
from .coordinator import (
    RoleSessionCandidate,
    RoleSessionCoordinator,
    RoleSessionEvolutionResult,
    RoleSessionRecord,
)


@dataclass(frozen=True, slots=True)
class SkillOptEvolutionOutcome:
    skill_set: SkillSet
    sessions: tuple[RoleSessionRecord, ...]
    training_evaluation: EvaluationResult
    evaluation: EvaluationResult


@dataclass(frozen=True, slots=True)
class SkillOptEvolutionRunResult:
    evolution: SkillOptEvolutionOutcome
    gate_report: GateReport
    run_identity_hash: str


class _EvalGateAcceptor:
    """Apply MVAgent's complete-system reliability Gate after one role session."""

    def __init__(
        self,
        *,
        evaluator: SkillSetEvaluator,
        gate: PromotionGate,
        audit_dir: Path,
    ) -> None:
        self.evaluator = evaluator
        self.gate = gate
        self.audit_dir = audit_dir
        self.reports: dict[int, GateReport] = {}

    @property
    def identity(self) -> Mapping[str, object]:
        return {
            "type": "mvagent-role-session-eval-gate-v1",
            "context_hash": self.evaluator.context.context_hash,
            "policy": self.gate.policy.__dict__,
            "strict_official_improvement": True,
        }

    def __call__(self, candidate: RoleSessionCandidate) -> bool:
        parent = self.evaluator.evaluate(
            skill_set=candidate.parent_skill_set,
            label=f"role-session-{candidate.session_index}-parent",
        )
        evaluated = self.evaluator.evaluate_role_candidate(
            skill_set=candidate.candidate_skill_set,
            reference_skill_set=candidate.parent_skill_set,
            changed_role=candidate.role,
            label=f"role-session-{candidate.session_index}-candidate",
        )
        report = self.gate.evaluate(
            skill_set=candidate.candidate_skill_set,
            stages={
                "eval": GateStageEvaluation(
                    candidate=evaluated,
                    references={"parent": parent},
                )
            },
        )
        self.reports[candidate.session_index] = report
        strictly_better = (
            evaluated.metrics.official_score > parent.metrics.official_score
        )
        accepted = report.decision is GateDecision.READY and strictly_better
        self.audit_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "session_index": candidate.session_index,
            "role": candidate.role.value,
            "parent_skill_set_hash": candidate.parent_skill_set.skill_set_hash(),
            "candidate_skill_set_hash": candidate.candidate_skill_set.skill_set_hash(),
            "parent_official_score": parent.metrics.official_score,
            "candidate_official_score": evaluated.metrics.official_score,
            "strictly_better": strictly_better,
            "accepted": accepted,
            "gate_report": report.to_dict(),
        }
        path = self.audit_dir / f"session_{candidate.session_index:04d}.json"
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
        return accepted


class SkillOptEvolutionEngine:
    """Canonical offline engine: stock SkillOpt inside MVAgent role sessions."""

    def __init__(
        self,
        config: SkillOptEvolutionConfig,
        *,
        executor: RolloutExecutor,
        scorer: BatchScorer,
        train_context: EvaluationContext,
        eval_context: EvaluationContext,
        sample_metadata: Mapping[str, RoleSampleMetadata],
        projector: TrajectoryProjector | None = None,
        score_aggregator: ScoreAggregator | None = None,
        episode_cache: MutableMapping[str, RolloutArtifact] | None = None,
        evaluation_cache: MutableMapping[str, EvaluationResult] | None = None,
        identity: Mapping[str, Any] | None = None,
    ) -> None:
        self.config = config
        self.output_dir = Path(config.runtime.output_dir)
        self.cache_dir = Path(config.runtime.cache_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        overlap = set(train_context.sample_ids) & set(eval_context.sample_ids)
        if overlap:
            raise ValueError("Skill evolution Train and Eval IDs must be disjoint.")
        self.projector = projector or TrajectoryProjector()
        self.score_aggregator = score_aggregator or MeanScoreAggregator()
        self.episode_cache = (
            episode_cache
            if episode_cache is not None
            else JsonEpisodeCache(self.cache_dir / "episodes")
        )
        self.eval_evaluator = SkillSetEvaluator(
            executor=executor,
            scorer=scorer,
            context=eval_context,
            projector=self.projector,
            score_aggregator=self.score_aggregator,
            episode_cache=self.episode_cache,
            evaluation_cache=evaluation_cache,
        )
        self.train_evaluator = SkillSetEvaluator(
            executor=executor,
            scorer=scorer,
            context=train_context,
            projector=self.projector,
            score_aggregator=self.score_aggregator,
            episode_cache=self.episode_cache,
            evaluation_cache=evaluation_cache,
        )
        self.backend = MVAgentRoleRolloutBackend(
            executor=executor,
            scorer=scorer,
            train_context=train_context,
            selection_context=eval_context,
            projector=self.projector,
            sample_metadata=sample_metadata,
            episode_cache=self.episode_cache,
        )
        self.gate = PromotionGate(config.gate)
        self.acceptor = _EvalGateAcceptor(
            evaluator=self.eval_evaluator,
            gate=self.gate,
            audit_dir=self.output_dir / "audit" / "role_sessions",
        )
        role_architectures = self._role_architectures(
            config.runtime.mvagent_config
        )
        self.coordinate_runner = SkillOptCoordinateRunner(
            backend=self.backend,
            artifact_root=self.output_dir / "skillopt_sessions",
            target_system_prompt=role_architectures,
        )
        update_items = self._items(
            train_context,
            sample_metadata,
            include_reference=True,
        )
        selection_items = self._items(
            eval_context,
            sample_metadata,
            include_reference=False,
        )
        self.coordinator = RoleSessionCoordinator(
            runner=self.coordinate_runner,
            structured_config=config.skillopt.to_dict(),
            update_items=update_items,
            selection_items=selection_items,
            output_root=self.output_dir,
            role_rounds=config.coordination.rounds,
            role_order=config.coordination.role_order,
            accept_candidate=self.acceptor,
            identity={
                "train_context_hash": train_context.context_hash,
                "eval_context_hash": eval_context.context_hash,
                "upstream": {
                    "package": "skillopt",
                    "version": "0.2.0",
                    "commit": "e7014cd18a18e11e6f6c10b897f7a009960d2e1b",
                },
                **dict(identity or {}),
                "reflection_success_policy": dict(REFLECTION_SUCCESS_POLICY),
            },
        )
        self._closed = False

    @staticmethod
    def _items(
        context: EvaluationContext,
        metadata: Mapping[str, RoleSampleMetadata],
        *,
        include_reference: bool,
    ) -> tuple[dict[str, str], ...]:
        return tuple(
            {
                "id": sample_id,
                "task_description": metadata[sample_id].task_description,
                "task_type": metadata[sample_id].task_type,
                "reference_text": (
                    metadata[sample_id].reference_text
                    if include_reference
                    else ""
                ),
            }
            for sample_id in context.sample_ids
        )

    @staticmethod
    def _role_architectures(config_path: str) -> Mapping[Role, str]:
        mvagent = MVAgentConfig.from_yaml(config_path)
        observer_ref = mvagent.video_agent.observer
        observer_instance = mvagent.models[observer_ref.model_type]
        observer_runtime = observer_instance.to_runtime_config(
            observer_ref.model_type,
            observer_ref,
        )
        return build_role_architectures(
            max_videos_per_watch=mvagent.global_agent.max_videos_per_watch,
            max_video_inputs_per_request=getattr(
                observer_runtime,
                "max_videos_per_request",
                1,
            ),
            max_video_frames_per_request=getattr(
                observer_runtime,
                "max_video_frames_per_request",
                512,
            ),
            max_ranges_per_action=mvagent.video_agent.max_ranges_per_action,
        )

    @property
    def model_identities(self) -> tuple[dict[str, object], ...]:
        model = dict(self.config.skillopt.sections["model"])
        safe = {
            key: value
            for key, value in model.items()
            if "key" not in key.casefold() and "token" not in key.casefold()
        }
        return (safe,)

    def run(
        self,
        *,
        initial_skill_set: SkillSet | None = None,
        resume: bool = False,
    ) -> SkillOptEvolutionRunResult:
        if self._closed:
            raise RuntimeError("SkillOptEvolutionEngine is closed.")
        initial = initial_skill_set or SkillSet.zero()
        coordinated: RoleSessionEvolutionResult = self.coordinator.run(
            initial_skill_set=initial,
            resume=resume,
        )
        train_result = self.train_evaluator.evaluate(
            skill_set=coordinated.skill_set,
            label="final-train",
        )
        eval_result = self.eval_evaluator.evaluate(
            skill_set=coordinated.skill_set,
            label="final-eval",
        )
        initial_eval = self.eval_evaluator.evaluate(
            skill_set=initial,
            label="final-eval-initial",
        )
        gate_report = self.gate.evaluate(
            skill_set=coordinated.skill_set,
            stages={
                "eval": GateStageEvaluation(
                    candidate=eval_result,
                    references={"parent": initial_eval},
                )
            },
        )
        outcome = SkillOptEvolutionOutcome(
            skill_set=coordinated.skill_set,
            sessions=coordinated.sessions,
            training_evaluation=train_result,
            evaluation=eval_result,
        )
        return SkillOptEvolutionRunResult(
            evolution=outcome,
            gate_report=gate_report,
            run_identity_hash=coordinated.coordinator_identity,
        )

    def close(self) -> None:
        self._closed = True

    def __enter__(self) -> "SkillOptEvolutionEngine":
        if self._closed:
            raise RuntimeError("SkillOptEvolutionEngine is closed.")
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        del exc_type, exc, traceback
        self.close()


__all__ = [
    "SkillOptEvolutionEngine",
    "SkillOptEvolutionOutcome",
    "SkillOptEvolutionRunResult",
]
