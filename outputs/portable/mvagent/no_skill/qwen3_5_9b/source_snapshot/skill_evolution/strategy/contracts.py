"""Stable data contracts shared by the offline evolution layers."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Mapping


class Role(StrEnum):
    GLOBAL = "global"
    VIDEO = "video"


class EditOp(StrEnum):
    APPEND = "append"
    INSERT_AFTER = "insert_after"
    REPLACE = "replace"
    DELETE = "delete"


class CaseAssessment(StrEnum):
    STRATEGY_GAP = "strategy_gap"
    NOT_ATTRIBUTABLE = "not_attributable"
    PRESERVE_SUCCESS = "preserve_success"


class GateDecision(StrEnum):
    REJECT = "reject"
    HOLD = "hold_for_more_evidence"
    READY = "ready_for_human_approval"


def normalize_skill_text(content: str) -> str:
    """Return the canonical in-memory and on-disk representation of a Skill."""
    if not isinstance(content, str):
        raise TypeError("Skill content must be text.")
    normalized = content.replace("\r\n", "\n").replace("\r", "\n").strip()
    return f"{normalized}\n" if normalized else ""


def sha256_text(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def hash_json(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class SkillSet:
    """The complete pair of role-local planning Skills used by one rollout."""

    global_skill: str = ""
    video_skill: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "global_skill", normalize_skill_text(self.global_skill))
        object.__setattr__(self, "video_skill", normalize_skill_text(self.video_skill))

    @classmethod
    def zero(cls) -> SkillSet:
        return cls()

    @classmethod
    def from_text(cls, *, global_skill: str, video_skill: str) -> SkillSet:
        return cls(global_skill=global_skill, video_skill=video_skill)

    def get(self, role: Role) -> str:
        return self.global_skill if Role(role) is Role.GLOBAL else self.video_skill

    def replace(self, role: Role, content: str) -> SkillSet:
        role = Role(role)
        if role is Role.GLOBAL:
            return SkillSet(global_skill=content, video_skill=self.video_skill)
        return SkillSet(global_skill=self.global_skill, video_skill=content)

    def skill_sha256(self, role: Role) -> str:
        return sha256_text(self.get(role))

    @property
    def is_promotable(self) -> bool:
        return bool(self.global_skill or self.video_skill)

    def skill_set_hash(self) -> str:
        """Hash only Skill content; rollout context has a separate identity."""
        return hash_json(
            {
                "global_sha256": self.skill_sha256(Role.GLOBAL),
                "video_sha256": self.skill_sha256(Role.VIDEO),
            }
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "global_skill": self.global_skill,
            "video_skill": self.video_skill,
        }


@dataclass(frozen=True)
class SkillEdit:
    op: EditOp
    target: str = ""
    content: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "op", EditOp(self.op))
        object.__setattr__(self, "target", str(self.target or ""))
        object.__setattr__(self, "content", str(self.content or "").strip())

    def to_dict(self) -> dict[str, str]:
        return {
            "op": self.op.value,
            "target": self.target,
            "content": self.content,
        }


@dataclass(frozen=True)
class TraceCase:
    """A compact, role-visible training example projected from one rollout."""

    case_id: str
    role: Role
    task_type: str
    visible_input: str
    decisions_and_results: str
    output: str
    observed_issue: str
    downstream_effect: str
    outcome: str
    official_score: float | None = None
    outcome_feedback: str = ""
    source_group: str = ""
    action_signature: str = ""
    behavior_signature: str = ""
    issue_tags: tuple[str, ...] = ()
    episode_id: str = ""
    episode_trace: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "case_id", str(self.case_id).strip())
        object.__setattr__(self, "role", Role(self.role))
        for name in (
            "task_type",
            "visible_input",
            "decisions_and_results",
            "output",
            "observed_issue",
            "downstream_effect",
            "outcome",
            "outcome_feedback",
            "episode_id",
            "episode_trace",
        ):
            object.__setattr__(self, name, str(getattr(self, name) or "").strip())
        if not self.case_id:
            raise ValueError("TraceCase.case_id must be non-empty.")
        if self.outcome not in {"pass", "fail", "partial", "unscored"}:
            if self.outcome != "unattributed":
                raise ValueError(
                    "TraceCase.outcome must be pass, fail, partial, "
                    "unattributed, or unscored."
                )
        if self.official_score is not None:
            object.__setattr__(self, "official_score", float(self.official_score))
        object.__setattr__(self, "source_group", str(self.source_group or "").strip())
        object.__setattr__(
            self,
            "action_signature",
            str(self.action_signature or "none").strip(),
        )
        object.__setattr__(
            self,
            "behavior_signature",
            str(self.behavior_signature or "none").strip(),
        )
        object.__setattr__(
            self,
            "issue_tags",
            tuple(
                dict.fromkeys(
                    str(item).strip()
                    for item in self.issue_tags
                    if str(item).strip()
                )
            ),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "role": self.role.value,
            "task_type": self.task_type,
            "visible_input": self.visible_input,
            "decisions_and_results": self.decisions_and_results,
            "output": self.output,
            "observed_issue": self.observed_issue,
            "downstream_effect": self.downstream_effect,
            "outcome": self.outcome,
            "official_score": self.official_score,
            "outcome_feedback": self.outcome_feedback,
            "action_signature": self.action_signature,
            "behavior_signature": self.behavior_signature,
            "issue_tags": list(self.issue_tags),
            "episode_id": self.episode_id,
            "episode_trace": self.episode_trace,
        }


@dataclass(frozen=True)
class EvidencePacket:
    """One system-selected recurring behavior and its successful contrasts.

    Source-group identity is intentionally consumed while constructing the packet but
    never rendered to the optimizer.  The optimizer therefore judges the behavioral
    hypothesis and writes an edit; it does not need to solve the experiment's sampling
    and independence constraints.
    """

    role: Role
    cases: tuple[TraceCase, ...]
    support_ids: tuple[str, ...]
    contrast_ids: tuple[str, ...]
    signature: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "role", Role(self.role))
        cases = tuple(self.cases)
        object.__setattr__(self, "cases", cases)
        support_ids = tuple(
            dict.fromkeys(str(item).strip() for item in self.support_ids if str(item).strip())
        )
        contrast_ids = tuple(
            dict.fromkeys(str(item).strip() for item in self.contrast_ids if str(item).strip())
        )
        object.__setattr__(self, "support_ids", support_ids)
        object.__setattr__(self, "contrast_ids", contrast_ids)
        object.__setattr__(self, "signature", str(self.signature or "").strip())
        if not cases:
            raise ValueError("EvidencePacket.cases must be non-empty.")
        if any(case.role is not self.role for case in cases):
            raise ValueError("EvidencePacket cases must all match its role.")
        if not support_ids or not contrast_ids:
            raise ValueError("EvidencePacket requires support and contrast cases.")
        if set(support_ids) & set(contrast_ids):
            raise ValueError("EvidencePacket support and contrast IDs must be disjoint.")
        case_ids = {case.case_id for case in cases}
        referenced = set(support_ids) | set(contrast_ids)
        if len(case_ids) != len(cases):
            raise ValueError("EvidencePacket case IDs must be unique.")
        if referenced != case_ids:
            raise ValueError(
                "EvidencePacket cases must be exactly its support and contrast cases."
            )
        if not self.signature:
            raise ValueError("EvidencePacket.signature must be non-empty.")

    @property
    def case_assessments(self) -> dict[str, CaseAssessment]:
        return {
            **{
                case_id: CaseAssessment.STRATEGY_GAP
                for case_id in self.support_ids
            },
            **{
                case_id: CaseAssessment.PRESERVE_SUCCESS
                for case_id in self.contrast_ids
            },
        }


@dataclass(frozen=True)
class SkillUpdateRequest:
    role: Role
    parent_skill: str
    evidence: EvidencePacket
    cycle: int
    candidate_number: int
    candidate_count: int
    seed: int
    max_chars: int = 3_000
    max_changed_chars: int | None = None
    changed_char_budgets: Mapping[Role, int | None] = field(default_factory=dict)
    generation: int = 0
    target_role_lock: Role | None = None
    optimizer_memory: tuple[str, ...] = ()
    parent_skill_set: SkillSet | None = None
    mode: str = "discover"
    min_support_cases: int = 2
    min_support_groups: int = 2

    def __post_init__(self) -> None:
        object.__setattr__(self, "role", Role(self.role))
        object.__setattr__(self, "parent_skill", normalize_skill_text(self.parent_skill))
        if not isinstance(self.evidence, EvidencePacket):
            raise TypeError("SkillUpdateRequest.evidence must be an EvidencePacket.")
        if self.evidence.role is not self.role:
            raise ValueError("SkillUpdateRequest evidence role does not match request role.")
        object.__setattr__(
            self,
            "optimizer_memory",
            tuple(str(item).strip() for item in self.optimizer_memory if str(item).strip()),
        )
        parent_skill_set = self.parent_skill_set
        if parent_skill_set is None:
            parent_skill_set = SkillSet.zero().replace(self.role, self.parent_skill)
        elif not isinstance(parent_skill_set, SkillSet):
            raise TypeError("parent_skill_set must be a SkillSet.")
        if parent_skill_set.get(self.role) != self.parent_skill:
            raise ValueError(
                "parent_skill must match parent_skill_set for the evidence role."
            )
        object.__setattr__(self, "parent_skill_set", parent_skill_set)
        mode = str(self.mode or "").strip().lower()
        if mode not in {"discover", "repair"}:
            raise ValueError("SkillUpdateRequest.mode must be discover or repair.")
        object.__setattr__(self, "mode", mode)
        target_role_lock = self.target_role_lock
        if target_role_lock is not None:
            target_role_lock = Role(target_role_lock)
        object.__setattr__(self, "target_role_lock", target_role_lock)
        for name in ("min_support_cases", "min_support_groups"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer.")
        if len(self.evidence.support_ids) < self.min_support_cases:
            raise ValueError("EvidencePacket has fewer support cases than requested.")
        by_id = {case.case_id: case for case in self.evidence.cases}
        support_groups = {
            by_id[case_id].source_group or case_id
            for case_id in self.evidence.support_ids
        }
        if len(support_groups) < self.min_support_groups:
            raise ValueError("EvidencePacket has fewer independent groups than requested.")
        if min(
            self.cycle,
            self.candidate_number,
            self.candidate_count,
            self.max_chars,
        ) < 1:
            raise ValueError(
                "cycle, candidate numbers, and max_chars must be positive."
            )
        if self.candidate_number > self.candidate_count:
            raise ValueError("candidate_number cannot exceed candidate_count.")
        if isinstance(self.generation, bool) or not isinstance(
            self.generation,
            int,
        ):
            raise ValueError("generation must be a non-negative integer.")
        if self.generation < 0:
            raise ValueError("generation must be a non-negative integer.")
        if self.max_changed_chars is not None and (
            isinstance(self.max_changed_chars, bool)
            or not isinstance(self.max_changed_chars, int)
            or self.max_changed_chars < 1
        ):
            raise ValueError(
                "max_changed_chars must be a positive integer when provided."
            )
        budgets: dict[Role, int | None] = {}
        for raw_role, raw_budget in self.changed_char_budgets.items():
            budget_role = Role(raw_role)
            if raw_budget is not None and (
                isinstance(raw_budget, bool)
                or not isinstance(raw_budget, int)
                or raw_budget < 1
            ):
                raise ValueError(
                    "changed_char_budgets values must be positive integers or None."
                )
            budgets[budget_role] = raw_budget
        object.__setattr__(self, "changed_char_budgets", budgets)

    @property
    def parent_sha256(self) -> str:
        return sha256_text(self.parent_skill)

    def parent_sha256_for(self, role: Role) -> str:
        assert self.parent_skill_set is not None
        return self.parent_skill_set.skill_sha256(Role(role))

    @property
    def cases(self) -> tuple[TraceCase, ...]:
        return self.evidence.cases


@dataclass(frozen=True)
class SkillDiagnosis:
    """One auditable, cross-case behavioral hypothesis for a candidate."""

    pattern: str
    support_ids: tuple[str, ...] = ()
    contrast_ids: tuple[str, ...] = ()
    regression_risk: str = ""
    expected_behavior_change: str = ""
    failure_source: str = "unattributed"
    target_role: Role | None = None
    causal_evidence: str = ""

    def __post_init__(self) -> None:
        for name in (
            "pattern",
            "regression_risk",
            "expected_behavior_change",
            "failure_source",
            "causal_evidence",
        ):
            object.__setattr__(self, name, str(getattr(self, name) or "").strip())
        if not self.pattern:
            raise ValueError("SkillDiagnosis.pattern must be non-empty.")
        failure_source = str(self.failure_source or "").strip().lower()
        if failure_source not in {
            "global",
            "video",
            "action_internal",
            "joint",
            "unattributed",
        }:
            raise ValueError("SkillDiagnosis.failure_source is invalid.")
        object.__setattr__(self, "failure_source", failure_source)
        target_role = self.target_role
        if target_role in (None, "", "none"):
            target_role = None
        else:
            target_role = Role(target_role)
        object.__setattr__(self, "target_role", target_role)
        for name in ("support_ids", "contrast_ids"):
            object.__setattr__(
                self,
                name,
                tuple(
                    dict.fromkeys(
                        str(item).strip()
                        for item in getattr(self, name)
                        if str(item).strip()
                    )
                ),
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "pattern": self.pattern,
            "support_ids": list(self.support_ids),
            "contrast_ids": list(self.contrast_ids),
            "regression_risk": self.regression_risk,
            "expected_behavior_change": self.expected_behavior_change,
            "failure_source": self.failure_source,
            "target_role": (
                self.target_role.value if self.target_role is not None else "none"
            ),
            "causal_evidence": self.causal_evidence,
        }


@dataclass(frozen=True)
class SkillUpdateProposal:
    """One role-local hypothesis and edit; empty edits keep the parent."""

    role: Role
    parent_sha256: str
    diagnosis: SkillDiagnosis
    case_assessments: Mapping[str, CaseAssessment | str] = field(default_factory=dict)
    edits: tuple[SkillEdit, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "role", Role(self.role))
        object.__setattr__(self, "parent_sha256", str(self.parent_sha256).strip().lower())
        if not isinstance(self.diagnosis, SkillDiagnosis):
            object.__setattr__(self, "diagnosis", SkillDiagnosis(**dict(self.diagnosis)))
        if len(self.parent_sha256) != 64 or any(
            char not in "0123456789abcdef" for char in self.parent_sha256
        ):
            raise ValueError("SkillUpdateProposal.parent_sha256 must be a SHA256 digest.")
        assessments = {
            str(case_id).strip(): CaseAssessment(value)
            for case_id, value in dict(self.case_assessments).items()
            if str(case_id).strip()
        }
        object.__setattr__(self, "case_assessments", assessments)
        object.__setattr__(self, "edits", tuple(self.edits))

    def to_dict(self) -> dict[str, object]:
        return {
            "role": self.role.value,
            "parent_sha256": self.parent_sha256,
            "diagnosis": self.diagnosis.to_dict(),
            "case_assessments": {
                key: value.value for key, value in self.case_assessments.items()
            },
            "edits": [edit.to_dict() for edit in self.edits],
        }


@dataclass(frozen=True)
class EvaluationKey:
    skill_set_hash: str
    context_hash: str

    def __post_init__(self) -> None:
        for name in ("skill_set_hash", "context_hash"):
            value = str(getattr(self, name)).strip().lower()
            if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
                raise ValueError(f"{name} must be a 64-character SHA256 digest.")
            object.__setattr__(self, name, value)

    @property
    def cache_key(self) -> str:
        return hash_json(
            {
                "skill_set_hash": self.skill_set_hash,
                "context_hash": self.context_hash,
            }
        )


@dataclass(frozen=True)
class EvaluationMetrics:
    sample_count: int
    official_score: float
    fatal_rate: float = 0.0
    invalid_action_rate: float = 0.0
    observe_calls_per_sample: float = 0.0
    watch_calls_per_sample: float = 0.0
    bucket_scores: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if int(self.sample_count) < 0:
            raise ValueError("sample_count must be non-negative.")
        object.__setattr__(self, "sample_count", int(self.sample_count))
        object.__setattr__(self, "official_score", float(self.official_score))
        for name in ("fatal_rate", "invalid_action_rate"):
            value = float(getattr(self, name))
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be in [0, 1].")
            object.__setattr__(self, name, value)
        for name in ("observe_calls_per_sample", "watch_calls_per_sample"):
            object.__setattr__(self, name, float(getattr(self, name)))
        object.__setattr__(
            self,
            "bucket_scores",
            {str(key): float(value) for key, value in dict(self.bucket_scores).items()},
        )

    def rank_key(self) -> tuple[float, ...]:
        return (
            self.official_score,
            -self.fatal_rate,
            -self.invalid_action_rate,
            -self.observe_calls_per_sample,
            -self.watch_calls_per_sample,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "sample_count": self.sample_count,
            "official_score": self.official_score,
            "fatal_rate": self.fatal_rate,
            "invalid_action_rate": self.invalid_action_rate,
            "observe_calls_per_sample": self.observe_calls_per_sample,
            "watch_calls_per_sample": self.watch_calls_per_sample,
            "bucket_scores": dict(self.bucket_scores),
        }


@dataclass(frozen=True)
class EvaluationResult:
    key: EvaluationKey
    metrics: EvaluationMetrics
    evidence_ids: tuple[str, ...] = ()
    cases: tuple[TraceCase, ...] = ()
    reused_sample_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_ids", tuple(self.evidence_ids))
        object.__setattr__(self, "cases", tuple(self.cases))
        reused = tuple(
            dict.fromkeys(
                str(item).strip()
                for item in self.reused_sample_ids
                if str(item).strip()
            )
        )
        object.__setattr__(self, "reused_sample_ids", reused)
        if self.cases:
            unknown = set(self.evidence_ids) - {case.case_id for case in self.cases}
            if unknown:
                raise ValueError("Evaluation evidence IDs must reference its TraceCases.")


@dataclass(frozen=True)
class ComparisonResult:
    role: Role
    reference_key: EvaluationKey
    candidate_key: EvaluationKey
    official_delta: float
    local_preference: float | None = None
    lookahead_preference: float | None = None
    misalignment_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "role", Role(self.role))
        object.__setattr__(self, "official_delta", float(self.official_delta))
        for name in ("local_preference", "lookahead_preference"):
            value = getattr(self, name)
            if value is not None:
                value = float(value)
                if not -1.0 <= value <= 1.0:
                    raise ValueError(f"{name} must be in [-1, 1].")
                object.__setattr__(self, name, value)
        object.__setattr__(self, "misalignment_ids", tuple(self.misalignment_ids))


__all__ = [
    "CaseAssessment",
    "ComparisonResult",
    "EditOp",
    "EvidencePacket",
    "EvaluationKey",
    "EvaluationMetrics",
    "EvaluationResult",
    "GateDecision",
    "Role",
    "SkillEdit",
    "SkillDiagnosis",
    "SkillSet",
    "SkillUpdateProposal",
    "SkillUpdateRequest",
    "TraceCase",
    "hash_json",
    "normalize_skill_text",
    "sha256_text",
]
