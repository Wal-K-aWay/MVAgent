from __future__ import annotations

import json
from collections.abc import Callable, Mapping, MutableMapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from models.factory import ModelFactory
from models.llm import LLMClient
from mvagent.configs import MVAgentConfig

from .configs import EvolutionModelConfig, SkillEvolutionConfig
from .evaluation import (
    BatchScorer,
    EvaluationContext,
    JsonEpisodeCache,
    PairwiseJudge,
    PlannerReplayChecker,
    PromotionGate,
    PromptPairwiseJudge,
    RolloutArtifact,
    RolloutExecutor,
    ScoreAggregator,
    SkillSetEvaluator,
    TrajectoryProjector,
)
from .orchestration import (
    EvidencePacketBuilder,
    EvolutionRunResult,
    EvolutionRunner,
    EvolutionStateStore,
    GateStageProvider,
    JointSkillCoordinator,
)
from .strategy import (
    EvaluationResult,
    OptimizerCallCache,
    PromptCandidateReviewer,
    PromptSkillPatcher,
    PromptStagedSkillPatcher,
    SkillSet,
    SkillUpdater,
    build_role_architectures,
    build_system_architecture,
)


ModelBuilder = Callable[[EvolutionModelConfig], LLMClient]


class SkillEvolutionEngine:
    """Compose and own one complete offline Skill-evolution run."""

    def __init__(
        self,
        config: SkillEvolutionConfig,
        *,
        executor: RolloutExecutor,
        scorer: BatchScorer,
        train_context: EvaluationContext,
        eval_context: EvaluationContext,
        gate_stage_provider: GateStageProvider,
        projector: TrajectoryProjector | None = None,
        score_aggregator: ScoreAggregator | None = None,
        episode_cache: MutableMapping[str, RolloutArtifact] | None = None,
        evaluation_cache: MutableMapping[str, EvaluationResult] | None = None,
        state_store: EvolutionStateStore | None = None,
        planner_replay_checker: PlannerReplayChecker | None = None,
        model_builder: ModelBuilder | None = None,
        identity: dict[str, Any] | None = None,
    ) -> None:
        self.config = config
        self.output_dir = Path(config.runtime.output_dir)
        self.cache_dir = Path(config.runtime.cache_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.mvagent_config = MVAgentConfig.from_yaml(
            config.runtime.mvagent_config
        )
        self._models: dict[str, LLMClient] = {}
        self._closed = False
        self._model_builder = model_builder or self._build_shared_model
        overlap = set(train_context.sample_ids) & set(eval_context.sample_ids)
        if overlap:
            raise ValueError(
                "Skill evolution train and eval samples must be disjoint: "
                + ", ".join(sorted(overlap)[:5])
            )

        try:
            patcher_model = self._get_model(config.patcher.model)
            observer_ref = self.mvagent_config.video_agent.observer
            observer_instance = self.mvagent_config.models[observer_ref.model_type]
            observer_runtime = observer_instance.to_runtime_config(
                observer_ref.model_type,
                observer_ref,
            )
            architecture_kwargs = {
                "max_videos_per_watch": (
                    self.mvagent_config.global_agent.max_videos_per_watch
                ),
                "max_video_inputs_per_request": getattr(
                    observer_runtime,
                    "max_videos_per_request",
                    1,
                ),
                "max_video_frames_per_request": getattr(
                    observer_runtime,
                    "max_video_frames_per_request",
                    512,
                ),
                "max_ranges_per_action": (
                    self.mvagent_config.video_agent.max_ranges_per_action
                ),
            }
            system_architecture = build_system_architecture(
                **architecture_kwargs
            )
            self.optimizer_call_cache: OptimizerCallCache | None = None
            if config.patcher.workflow == "diagnose_then_patch":
                self.optimizer_call_cache = OptimizerCallCache(
                    self.output_dir / "state" / "optimizer_calls",
                    audit=self._write_optimizer_call,
                )
                self.patcher = PromptStagedSkillPatcher(
                    model=patcher_model,
                    diagnosis_prompt_path=(
                        config.patcher.diagnosis_prompt_path or None
                    ),
                    patch_prompt_path=config.patcher.patch_prompt_path or None,
                    system_architecture=system_architecture,
                    role_architectures=build_role_architectures(
                        **architecture_kwargs
                    ),
                    call_cache=self.optimizer_call_cache,
                )
            else:
                self.patcher = PromptSkillPatcher(
                    model=patcher_model,
                    prompt_path=config.patcher.prompt_path or None,
                    system_architecture=system_architecture,
                )
            self.reviewer = (
                PromptCandidateReviewer(
                    model=patcher_model,
                    prompt_path=config.reviewer.prompt_path or None,
                )
                if config.reviewer.enabled
                else None
            )
            self.pairwise_judge = self._build_pairwise_judge()
            self.episode_cache = (
                episode_cache
                if episode_cache is not None
                else JsonEpisodeCache(self.cache_dir / "episodes")
            )
            self.train_evaluator = SkillSetEvaluator(
                executor=executor,
                scorer=scorer,
                context=train_context,
                projector=projector,
                pairwise_judge=self.pairwise_judge,
                score_aggregator=score_aggregator,
                episode_cache=self.episode_cache,
                evaluation_cache=evaluation_cache,
            )
            self.eval_evaluator = SkillSetEvaluator(
                executor=executor,
                scorer=scorer,
                context=eval_context,
                projector=projector,
                score_aggregator=score_aggregator,
                episode_cache=self.episode_cache,
                evaluation_cache=evaluation_cache,
            )
            self.updater = SkillUpdater(**config.updater.to_kwargs())
            self.coordinator = JointSkillCoordinator(
                patcher=self.patcher,
                training_evaluator=self.train_evaluator,
                selection_evaluator=self.eval_evaluator,
                updater=self.updater,
                reviewer=self.reviewer,
                planner_replay_checker=planner_replay_checker,
                config=config.search,
                evidence_builder=EvidencePacketBuilder(
                    failure_size=config.minibatch.failure_size,
                    success_size=config.minibatch.success_size,
                    detail_max_chars=config.search.detail_max_chars,
                    seed=config.search.seed,
                ),
                on_attempt=self._write_attempt,
            )
            self.gate = PromotionGate(config.gate)
            self.state_store = state_store or EvolutionStateStore(
                self.output_dir / "state" / "checkpoint.json"
            )
            self.runner = EvolutionRunner(
                coordinator=self.coordinator,
                gate=self.gate,
                gate_stage_provider=gate_stage_provider,
                state_store=self.state_store,
                identity={
                    "skill_evolution_config": config.to_dict(),
                    "planner_replay_checker": (
                        dict(planner_replay_checker.identity)
                        if planner_replay_checker is not None
                        else {"enabled": False}
                    ),
                    **dict(identity or {}),
                },
            )
        except Exception:
            self.close()
            raise

    @classmethod
    def from_yaml(
        cls,
        config_path: str | Path,
        *,
        executor: RolloutExecutor,
        scorer: BatchScorer,
        train_context: EvaluationContext,
        eval_context: EvaluationContext,
        gate_stage_provider: GateStageProvider,
        projector: TrajectoryProjector | None = None,
        score_aggregator: ScoreAggregator | None = None,
        episode_cache: MutableMapping[str, RolloutArtifact] | None = None,
        evaluation_cache: MutableMapping[str, EvaluationResult] | None = None,
        state_store: EvolutionStateStore | None = None,
        planner_replay_checker: PlannerReplayChecker | None = None,
        model_builder: ModelBuilder | None = None,
        identity: dict[str, Any] | None = None,
    ) -> "SkillEvolutionEngine":
        """Load one offline YAML and construct the complete engine."""
        return cls(
            SkillEvolutionConfig.from_yaml(config_path),
            executor=executor,
            scorer=scorer,
            train_context=train_context,
            eval_context=eval_context,
            gate_stage_provider=gate_stage_provider,
            projector=projector,
            score_aggregator=score_aggregator,
            episode_cache=episode_cache,
            evaluation_cache=evaluation_cache,
            state_store=state_store,
            planner_replay_checker=planner_replay_checker,
            model_builder=model_builder,
            identity=identity,
        )

    @property
    def model_identities(self) -> tuple[dict[str, Any], ...]:
        """Return the unique credential-free model identities owned by the engine."""
        return tuple(
            dict(getattr(model, "identity", {}))
            for model in self._models.values()
        )

    def run(
        self,
        *,
        initial_skill_set: SkillSet | None = None,
        resume: bool = False,
    ) -> EvolutionRunResult:
        """Run or resume one evolution search followed by its promotion Gate."""
        if self._closed:
            raise RuntimeError("SkillEvolutionEngine is closed.")
        return self.runner.run(
            initial_skill_set=(
                initial_skill_set
                if initial_skill_set is not None
                else SkillSet.zero()
            ),
            resume=resume,
        )

    def close(self) -> None:
        """Close each engine-owned client once; persistent vLLM services remain alive."""
        if self._closed:
            return
        self._closed = True
        seen: set[int] = set()
        for model in self._models.values():
            if id(model) in seen:
                continue
            seen.add(id(model))
            close = getattr(model, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass
        self._models.clear()

    def __enter__(self) -> "SkillEvolutionEngine":
        if self._closed:
            raise RuntimeError("SkillEvolutionEngine is closed.")
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        del exc_type, exc, traceback
        self.close()

    def _build_shared_model(self, model_ref: EvolutionModelConfig) -> LLMClient:
        return ModelFactory.create_model(
            model_ref=model_ref,
            config=self.mvagent_config,
        )

    def _get_model(self, model_ref: EvolutionModelConfig) -> LLMClient:
        key = json.dumps(model_ref.to_dict(), sort_keys=True)
        if key not in self._models:
            self._models[key] = self._model_builder(model_ref)
        return self._models[key]

    def _build_pairwise_judge(self) -> PairwiseJudge | None:
        config = self.config.pairwise
        if not config.enabled:
            return None
        assert config.model is not None
        return PromptPairwiseJudge(
            model=self._get_model(config.model),
            prompt_path=config.prompt_path or None,
            max_parse_retries=config.max_parse_retries,
            max_cases=config.max_cases,
            seed=config.seed,
        )

    def _write_attempt(self, attempt: dict[str, Any]) -> None:
        """Persist one optimizer attempt without mutating candidate workspaces."""
        audit_dir = self.output_dir / "audit"
        audit_dir.mkdir(parents=True, exist_ok=True)
        attempt_id = str(attempt["attempt_id"])
        temporary = audit_dir / f".{attempt_id}.tmp"
        target = audit_dir / f"{attempt_id}.json"
        temporary.write_text(
            json.dumps(attempt, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(target)

    def _write_optimizer_call(self, event: Mapping[str, Any]) -> None:
        """Persist one compact staged-optimizer call or parse audit event."""

        audit_dir = self.output_dir / "audit" / "optimizer_calls"
        audit_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC)
        event_id = (
            timestamp.strftime("%Y%m%dT%H%M%S.%fZ")
            + "-"
            + uuid4().hex
        )
        payload = {
            "event_id": event_id,
            "timestamp_utc": timestamp.isoformat(),
            **dict(event),
        }
        temporary = audit_dir / f".{event_id}.tmp"
        target = audit_dir / f"{event_id}.json"
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(target)


__all__ = ["ModelBuilder", "SkillEvolutionEngine"]
