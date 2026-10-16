"""Trajectory projection, rollout scoring, comparison, caching, and promotion."""

from .cache import JsonEpisodeCache
from .comparison_cases import (
    attach_paired_regressions,
    build_paired_feedback_cases,
    select_repair_cases,
)
from .evaluator import (
    BatchScorer,
    EvaluationContext,
    EvaluationRequest,
    PairwiseJudge,
    PairwiseJudgment,
    RolloutArtifact,
    RolloutExecutor,
    ScoreAggregator,
    SkillSetEvaluator,
    role_was_invoked,
)
from .gate import (
    GatePolicy,
    GateReport,
    GateStageEvaluation,
    GateStageSpec,
    PromotionEvaluator,
    PromotionGate,
)
from .pairwise import PromptPairwiseJudge
from .planner_replay import (
    PlannerReplayChecker,
    PlannerReplayExecutor,
    PlannerReplayReview,
)
from .splits import DataSplitManifest, SplitSample
from .trace_projector import TrajectoryProjector


__all__ = [
    "BatchScorer",
    "attach_paired_regressions",
    "build_paired_feedback_cases",
    "DataSplitManifest",
    "EvaluationContext",
    "EvaluationRequest",
    "GatePolicy",
    "GateReport",
    "GateStageEvaluation",
    "GateStageSpec",
    "JsonEpisodeCache",
    "PairwiseJudge",
    "PairwiseJudgment",
    "PromotionEvaluator",
    "PromotionGate",
    "PromptPairwiseJudge",
    "PlannerReplayChecker",
    "PlannerReplayExecutor",
    "PlannerReplayReview",
    "RolloutArtifact",
    "RolloutExecutor",
    "ScoreAggregator",
    "role_was_invoked",
    "select_repair_cases",
    "SkillSetEvaluator",
    "SplitSample",
    "TrajectoryProjector",
]
