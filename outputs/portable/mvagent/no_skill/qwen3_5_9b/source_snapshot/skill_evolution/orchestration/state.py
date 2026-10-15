from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from ..strategy.contracts import (
    ComparisonResult,
    EditOp,
    EvaluationKey,
    EvaluationMetrics,
    EvaluationResult,
    Role,
    SkillDiagnosis,
    SkillEdit,
    SkillSet,
    SkillUpdateProposal,
    TraceCase,
    hash_json,
)
from .coordinator import BeamNode, CoordinatorProgress, EvolutionStep
from .optimizer_memory import OptimizerLesson


CHECKPOINT_VERSION = 2


@dataclass(frozen=True)
class EvolutionCheckpoint:
    run_identity_hash: str
    progress: CoordinatorProgress
    evaluated_keys: tuple[str, ...] = ()
    rollout_budget_used: int = 0
    rng_state: Mapping[str, Any] | None = None


class EvolutionStateStore:
    """Atomically persist enough state to resume at a completed role boundary."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser().resolve()

    def save(self, checkpoint: EvolutionCheckpoint) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "checkpoint_version": CHECKPOINT_VERSION,
            "run_identity_hash": checkpoint.run_identity_hash,
            "progress": _progress_to_dict(checkpoint.progress),
            "evaluated_keys": list(checkpoint.evaluated_keys),
            "rollout_budget_used": int(checkpoint.rollout_budget_used),
            "rng_state": dict(checkpoint.rng_state or {}),
        }
        handle, temporary = tempfile.mkstemp(
            prefix=f".{self.path.name}.",
            suffix=".tmp",
            dir=str(self.path.parent),
        )
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        except Exception:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise

    def load(self, *, expected_run_identity_hash: str) -> EvolutionCheckpoint | None:
        if not self.path.is_file():
            return None
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        version = int(payload.get("checkpoint_version", 1))
        if version not in {1, CHECKPOINT_VERSION}:
            raise ValueError(f"Unsupported checkpoint version: {version}.")
        actual = str(payload.get("run_identity_hash") or "")
        if actual != str(expected_run_identity_hash):
            raise ValueError(
                "Checkpoint identity does not match the current initialization, "
                "runtime, evaluation, or Gate configuration."
            )
        return EvolutionCheckpoint(
            run_identity_hash=actual,
            progress=_progress_from_dict(
                payload["progress"],
                checkpoint_version=version,
            ),
            evaluated_keys=tuple(
                str(item) for item in payload.get("evaluated_keys", ())
            ),
            rollout_budget_used=int(payload.get("rollout_budget_used", 0)),
            rng_state=payload.get("rng_state") or {},
        )


def build_run_identity(payload: Mapping[str, Any]) -> str:
    """Hash the full initialization/configuration payload supplied by Runner."""
    return hash_json(dict(payload))


def _case_from_dict(value: Mapping[str, Any]) -> TraceCase:
    return TraceCase(
        case_id=value["case_id"],
        role=value["role"],
        task_type=value["task_type"],
        visible_input=value["visible_input"],
        decisions_and_results=value["decisions_and_results"],
        output=value["output"],
        observed_issue=value["observed_issue"],
        downstream_effect=value["downstream_effect"],
        outcome=value["outcome"],
        official_score=value.get("official_score"),
        outcome_feedback=value.get("outcome_feedback", ""),
        source_group=value.get("source_group", ""),
        action_signature=value.get("action_signature", ""),
        behavior_signature=value.get("behavior_signature", ""),
        issue_tags=tuple(value.get("issue_tags", ())),
        episode_id=value.get("episode_id", ""),
        episode_trace=value.get("episode_trace", ""),
    )


def _evaluation_to_dict(value: EvaluationResult) -> dict[str, Any]:
    return {
        "key": {
            "skill_set_hash": value.key.skill_set_hash,
            "context_hash": value.key.context_hash,
        },
        "metrics": value.metrics.to_dict(),
        "evidence_ids": list(value.evidence_ids),
        "reused_sample_ids": list(value.reused_sample_ids),
        "cases": [
            {**case.to_dict(), "source_group": case.source_group}
            for case in value.cases
        ],
    }


def _evaluation_from_dict(value: Mapping[str, Any]) -> EvaluationResult:
    key = value["key"]
    metrics = value["metrics"]
    return EvaluationResult(
        key=EvaluationKey(
            skill_set_hash=key["skill_set_hash"],
            context_hash=key["context_hash"],
        ),
        metrics=EvaluationMetrics(**metrics),
        evidence_ids=tuple(value.get("evidence_ids", ())),
        cases=tuple(_case_from_dict(item) for item in value.get("cases", ())),
        reused_sample_ids=tuple(value.get("reused_sample_ids", ())),
    )


def _comparison_to_dict(value: ComparisonResult | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        "role": value.role.value,
        "reference_key": {
            "skill_set_hash": value.reference_key.skill_set_hash,
            "context_hash": value.reference_key.context_hash,
        },
        "candidate_key": {
            "skill_set_hash": value.candidate_key.skill_set_hash,
            "context_hash": value.candidate_key.context_hash,
        },
        "official_delta": value.official_delta,
        "local_preference": value.local_preference,
        "lookahead_preference": value.lookahead_preference,
        "misalignment_ids": list(value.misalignment_ids),
    }


def _comparison_from_dict(value: Mapping[str, Any] | None) -> ComparisonResult | None:
    if value is None:
        return None
    reference = value["reference_key"]
    candidate = value["candidate_key"]
    return ComparisonResult(
        role=value["role"],
        reference_key=EvaluationKey(**reference),
        candidate_key=EvaluationKey(**candidate),
        official_delta=value["official_delta"],
        local_preference=value.get("local_preference"),
        lookahead_preference=value.get("lookahead_preference"),
        misalignment_ids=tuple(value.get("misalignment_ids", ())),
    )


def _proposal_to_dict(value: SkillUpdateProposal | None) -> dict[str, Any] | None:
    return value.to_dict() if value is not None else None


def _proposal_from_dict(value: Mapping[str, Any] | None) -> SkillUpdateProposal | None:
    if value is None:
        return None
    diagnosis = dict(value["diagnosis"])
    legacy_controllable = diagnosis.pop("controllable_decision", "")
    diagnosis.setdefault("causal_evidence", legacy_controllable)
    return SkillUpdateProposal(
        role=value["role"],
        parent_sha256=value["parent_sha256"],
        diagnosis=SkillDiagnosis(**diagnosis),
        case_assessments=value.get("case_assessments", {}),
        edits=tuple(
            SkillEdit(
                op=EditOp(item["op"]),
                target=item.get("target", ""),
                content=item.get("content", ""),
            )
            for item in value.get("edits", ())
        ),
    )


def _beam_to_dict(value: BeamNode) -> dict[str, Any]:
    return {
        "role": value.role.value,
        "skill": value.skill,
        "partner_sha256": value.partner_sha256,
        "training_evaluation": _evaluation_to_dict(value.training_evaluation),
        "evaluation": _evaluation_to_dict(value.evaluation),
        "generation": value.generation,
        "search_score": value.search_score,
        "comparison": _comparison_to_dict(value.comparison),
        "proposal": _proposal_to_dict(value.proposal),
        "stale": value.stale,
    }


def _beam_from_dict(value: Mapping[str, Any]) -> BeamNode:
    return BeamNode(
        role=value["role"],
        skill=value["skill"],
        partner_sha256=value["partner_sha256"],
        training_evaluation=_evaluation_from_dict(value["training_evaluation"]),
        evaluation=_evaluation_from_dict(value["evaluation"]),
        generation=int(value["generation"]),
        search_score=float(value["search_score"]),
        comparison=_comparison_from_dict(value.get("comparison")),
        proposal=_proposal_from_dict(value.get("proposal")),
        stale=bool(value.get("stale", False)),
    )


def _progress_to_dict(value: CoordinatorProgress) -> dict[str, Any]:
    return {
        "initial_skill_set": value.initial_skill_set.to_dict(),
        "active_skill_set": value.active_skill_set.to_dict(),
        "next_cycle": value.next_cycle,
        "next_role_index": value.next_role_index,
        "steps": [
            {
                "cycle": step.cycle,
                "role": step.role.value,
                "parent_skill_sha256": step.parent_skill_sha256,
                "selected_skill_sha256": step.selected_skill_sha256,
                "proposed_count": step.proposed_count,
                "valid_count": step.valid_count,
                "changed": step.changed,
            }
            for step in value.steps
        ],
        "beams": {
            Role.GLOBAL.value: [_beam_to_dict(node) for node in value.global_beam],
            Role.VIDEO.value: [_beam_to_dict(node) for node in value.video_beam],
        },
        "optimizer_memory": _optimizer_memory_to_dict(value.optimizer_memory),
        "attempted_skill_sha256": {
            role.value: list(items)
            for role, items in value.attempted_skill_sha256.items()
        },
        "provisional": {
            Role.GLOBAL.value: [
                _beam_to_dict(node) for node in value.provisional_global
            ],
            Role.VIDEO.value: [
                _beam_to_dict(node) for node in value.provisional_video
            ],
        },
    }


def _progress_from_dict(
    value: Mapping[str, Any],
    *,
    checkpoint_version: int,
) -> CoordinatorProgress:
    beams = value["beams"]
    provisional = value.get("provisional", {})
    global_beam = tuple(
        _beam_from_dict(item) for item in beams[Role.GLOBAL.value]
    )
    video_beam = tuple(
        _beam_from_dict(item) for item in beams[Role.VIDEO.value]
    )
    beam_by_role = {
        Role.GLOBAL: global_beam,
        Role.VIDEO: video_beam,
    }
    attempted = value.get("attempted_skill_sha256", {})
    return CoordinatorProgress(
        initial_skill_set=SkillSet(**value["initial_skill_set"]),
        active_skill_set=SkillSet(**value["active_skill_set"]),
        next_cycle=int(value["next_cycle"]),
        next_role_index=int(value["next_role_index"]),
        steps=tuple(
            EvolutionStep(
                cycle=int(item["cycle"]),
                role=Role(item["role"]),
                parent_skill_sha256=item["parent_skill_sha256"],
                selected_skill_sha256=item["selected_skill_sha256"],
                proposed_count=int(item["proposed_count"]),
                valid_count=int(item["valid_count"]),
                changed=bool(item["changed"]),
            )
            for item in value.get("steps", ())
        ),
        global_beam=global_beam,
        video_beam=video_beam,
        optimizer_memory=_optimizer_memory_from_dict(
            value.get("optimizer_memory", {}),
            checkpoint_version=checkpoint_version,
        ),
        attempted_skill_sha256={
            role: tuple(
                attempted.get(
                    role.value,
                    tuple(node.skill_sha256 for node in beam_by_role[role]),
                )
            )
            for role in Role
        },
        provisional_global=tuple(
            _beam_from_dict(item)
            for item in provisional.get(Role.GLOBAL.value, ())
        ),
        provisional_video=tuple(
            _beam_from_dict(item)
            for item in provisional.get(Role.VIDEO.value, ())
        ),
    )


def _optimizer_memory_to_dict(
    value: Mapping[Role, object],
) -> dict[str, list[dict[str, str]]]:
    serialized: dict[str, list[dict[str, str]]] = {
        role.value: [] for role in Role
    }
    for role in Role:
        items = value.get(role, ())
        if isinstance(items, (str, bytes)):
            raise TypeError(
                "Coordinator optimizer_memory role buckets must be lesson sequences."
            )
        for item in items:
            if isinstance(item, str):
                raise TypeError(
                    "Version-2 optimizer_memory cannot contain opaque strings."
                )
            if not isinstance(item, OptimizerLesson):
                raise TypeError(
                    "Coordinator optimizer_memory must contain OptimizerLesson values."
                )
            if item.role is not role:
                raise ValueError(
                    "OptimizerLesson role does not match its checkpoint role bucket."
                )
            serialized[role.value].append(item.to_dict())
    return serialized


def _optimizer_memory_from_dict(
    value: object,
    *,
    checkpoint_version: int,
) -> dict[Role, tuple[OptimizerLesson, ...]]:
    empty = {role: () for role in Role}
    if checkpoint_version < CHECKPOINT_VERSION:
        return empty
    if not isinstance(value, Mapping):
        raise ValueError("Checkpoint optimizer_memory must be a mapping.")

    restored: dict[Role, tuple[OptimizerLesson, ...]] = {}
    for role in Role:
        raw_items = value.get(role.value, ())
        if isinstance(raw_items, (str, bytes)) or not isinstance(
            raw_items, (list, tuple)
        ):
            raise ValueError(
                f"Checkpoint optimizer_memory.{role.value} must be a list."
            )
        lessons: list[OptimizerLesson] = []
        for raw_item in raw_items:
            if isinstance(raw_item, str):
                raise ValueError(
                    "Version-2 optimizer_memory cannot contain opaque strings."
                )
            lesson = OptimizerLesson.from_dict(raw_item)
            if lesson.role is not role:
                raise ValueError(
                    "OptimizerLesson role does not match its checkpoint role bucket."
                )
            lessons.append(lesson)
        restored[role] = tuple(lessons)
    return restored


__all__ = [
    "CHECKPOINT_VERSION",
    "EvolutionCheckpoint",
    "EvolutionStateStore",
    "build_run_identity",
]
