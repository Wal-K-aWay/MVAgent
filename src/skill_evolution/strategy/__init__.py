"""Skill text contracts, model-proposed edits, and deterministic application."""

from .contracts import (
    CaseAssessment,
    ComparisonResult,
    EditOp,
    EvidencePacket,
    EvaluationKey,
    EvaluationMetrics,
    EvaluationResult,
    GateDecision,
    Role,
    SkillDiagnosis,
    SkillEdit,
    SkillSet,
    SkillUpdateProposal,
    SkillUpdateRequest,
    TraceCase,
)
from .optimizer_calls import (
    OptimizerCallCache,
    OptimizerCallCacheCorruptionError,
    optimizer_call_hash,
)
from .patcher import (
    PromptSkillPatcher,
    build_role_architectures,
    build_system_architecture,
)
from .reviewer import CandidateReview, PromptCandidateReviewer
from .staged_patcher import (
    DIAGNOSIS_OUTPUT_SCHEMA,
    PATCH_OUTPUT_SCHEMA,
    PromptStagedSkillPatcher,
)
from .updater import SkillUpdater, UpdateResult


__all__ = [
    "CaseAssessment",
    "ComparisonResult",
    "EditOp",
    "EvidencePacket",
    "EvaluationKey",
    "EvaluationMetrics",
    "EvaluationResult",
    "GateDecision",
    "PromptSkillPatcher",
    "PromptStagedSkillPatcher",
    "DIAGNOSIS_OUTPUT_SCHEMA",
    "PATCH_OUTPUT_SCHEMA",
    "OptimizerCallCache",
    "OptimizerCallCacheCorruptionError",
    "optimizer_call_hash",
    "build_role_architectures",
    "build_system_architecture",
    "PromptCandidateReviewer",
    "Role",
    "SkillDiagnosis",
    "SkillEdit",
    "SkillSet",
    "SkillUpdateProposal",
    "SkillUpdateRequest",
    "SkillUpdater",
    "TraceCase",
    "UpdateResult",
    "CandidateReview",
]
