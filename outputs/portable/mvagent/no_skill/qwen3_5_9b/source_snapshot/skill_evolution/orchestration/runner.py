from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Protocol

from ..strategy.contracts import EvaluationResult, SkillSet, hash_json
from .coordinator import CoordinatorProgress, EvolutionResult, JointSkillCoordinator
from ..evaluation.gate import GateReport, GateStageEvaluation, PromotionGate
from .state import EvolutionCheckpoint, EvolutionStateStore, build_run_identity


@dataclass(frozen=True)
class EvolutionRunResult:
    evolution: EvolutionResult
    gate_report: GateReport
    run_identity_hash: str


class GateStageProvider(Protocol):
    """Run the frozen smoke/public/interaction/private evaluations."""

    @property
    def identity(self) -> Mapping[str, Any]: ...

    def evaluate(
        self,
        *,
        skill_set: SkillSet,
        search_evaluation: EvaluationResult,
    ) -> Mapping[str, GateStageEvaluation]: ...


class EvolutionRunner:
    """Top-level offline orchestration, checkpointing, and promotion boundary."""

    def __init__(
        self,
        *,
        coordinator: JointSkillCoordinator,
        gate: PromotionGate,
        gate_stage_provider: GateStageProvider,
        state_store: EvolutionStateStore,
        identity: Mapping[str, Any] | None = None,
    ) -> None:
        self.coordinator = coordinator
        self.gate = gate
        self.gate_stage_provider = gate_stage_provider
        self.state_store = state_store
        self.extra_identity = dict(identity or {})

    def run(
        self,
        *,
        initial_skill_set: SkillSet,
        resume: bool = False,
    ) -> EvolutionRunResult:
        run_identity_hash = self._run_identity(initial_skill_set)
        checkpoint = (
            self.state_store.load(expected_run_identity_hash=run_identity_hash)
            if resume
            else None
        )
        previous_callback = self.coordinator.on_checkpoint

        def save(progress: CoordinatorProgress) -> None:
            keys = {
                key
                for node in (*progress.global_beam, *progress.video_beam)
                for key in (
                    node.training_evaluation.key.cache_key,
                    node.evaluation.key.cache_key,
                )
            }
            for evaluator in (
                self.coordinator.training_evaluator,
                self.coordinator.selection_evaluator,
            ):
                evaluation_cache = getattr(evaluator, "evaluation_cache", {})
                keys.update(str(item) for item in evaluation_cache)
            episode_cache = getattr(
                self.coordinator.training_evaluator,
                "episode_cache",
                {},
            )
            self.state_store.save(
                EvolutionCheckpoint(
                    run_identity_hash=run_identity_hash,
                    progress=progress,
                    evaluated_keys=tuple(sorted(keys)),
                    rollout_budget_used=len(episode_cache),
                    rng_state={"base_seed": self.coordinator.config.seed},
                )
            )
            if previous_callback is not None:
                previous_callback(progress)

        self.coordinator.on_checkpoint = save
        try:
            evolution = self.coordinator.evolve(
                initial_skill_set,
                resume=checkpoint.progress if checkpoint is not None else None,
            )
        finally:
            self.coordinator.on_checkpoint = previous_callback

        gate_stages = self.gate_stage_provider.evaluate(
            skill_set=evolution.skill_set,
            search_evaluation=evolution.evaluation,
        )
        gate_report = self.gate.evaluate(
            skill_set=evolution.skill_set,
            stages=gate_stages,
        )
        return EvolutionRunResult(
            evolution=evolution,
            gate_report=gate_report,
            run_identity_hash=run_identity_hash,
        )

    def _run_identity(self, initial_skill_set: SkillSet) -> str:
        updater = self.coordinator.updater
        training_evaluator = self.coordinator.training_evaluator
        selection_evaluator = self.coordinator.selection_evaluator
        patcher = self.coordinator.patcher
        reviewer = self.coordinator.reviewer
        payload: dict[str, Any] = {
            "initial_skill_set_hash": initial_skill_set.skill_set_hash(),
            "search": asdict(self.coordinator.config),
            "updater": {
                "max_edits": updater.max_edits,
                "max_chars": updater.max_chars,
                "initial_max_chars": updater.initial_max_chars,
                "max_net_growth": updater.max_net_growth,
                "min_edit_evidence": updater.min_edit_evidence,
                "adaptive_edit_budget": updater.adaptive_edit_budget,
                "adaptive_min_changed_chars": (
                    updater.adaptive_min_changed_chars
                ),
                "adaptive_chars_per_support_group": (
                    updater.adaptive_chars_per_support_group
                ),
                "adaptive_generation_decay": (
                    updater.adaptive_generation_decay
                ),
            },
            "gate": asdict(self.gate.policy),
            "gate_stage_provider": {
                "type": type(self.gate_stage_provider).__qualname__,
                "identity": dict(self.gate_stage_provider.identity),
            },
            "training_context_hash": getattr(
                getattr(training_evaluator, "context", None), "context_hash", None
            ),
            "selection_context_hash": getattr(
                getattr(selection_evaluator, "context", None), "context_hash", None
            ),
            "patcher_hash": hash_json(
                getattr(
                    patcher,
                    "identity",
                    {"type": type(patcher).__qualname__},
                )
            ),
            "reviewer_hash": (
                hash_json(
                    getattr(
                        reviewer,
                        "identity",
                        {"type": type(reviewer).__qualname__},
                    )
                )
                if reviewer is not None
                else None
            ),
            "extra": self.extra_identity,
        }
        return build_run_identity(payload)


__all__ = ["EvolutionRunResult", "EvolutionRunner", "GateStageProvider"]
