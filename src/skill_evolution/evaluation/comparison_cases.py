from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import replace

from ..strategy.contracts import (
    ComparisonResult,
    EvaluationResult,
    Role,
    TraceCase,
    hash_json,
)


_RELIABILITY_ISSUES = frozenset(
    {
        "invalid_decision",
        "request_failure",
        "step_failure",
        "repeated_equivalent_observe",
        "evidence_action_failure",
    }
)


def _compact(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _score_delta(reference: TraceCase, candidate: TraceCase) -> float | None:
    if reference.official_score is None or candidate.official_score is None:
        return None
    return candidate.official_score - reference.official_score


def cases_are_pairable(reference: TraceCase, candidate: TraceCase) -> bool:
    """Return whether two role traces describe the same causal decision input."""

    if reference.role is not candidate.role:
        return False
    if reference.source_group != candidate.source_group:
        return False
    if reference.role is Role.GLOBAL:
        return reference.visible_input == candidate.visible_input
    try:
        old_input = json.loads(reference.visible_input)
        new_input = json.loads(candidate.visible_input)
    except (TypeError, ValueError, json.JSONDecodeError):
        return reference.visible_input == candidate.visible_input
    if not isinstance(old_input, dict) or not isinstance(new_input, dict):
        return reference.visible_input == candidate.visible_input
    return all(
        old_input.get(field) == new_input.get(field)
        for field in ("video_id", "instruction", "duration_sec")
    )


def build_paired_feedback_cases(
    *,
    role: Role,
    reference: EvaluationResult,
    candidate: EvaluationResult,
    comparison: ComparisonResult | None = None,
) -> tuple[TraceCase, ...]:
    """Describe same-input behavioral changes without exposing another split.

    The returned cases are derived only from the two supplied evaluations. A
    reliability regression or judge-identified misalignment becomes a failed
    paired case; an official improvement without a new reliability symptom
    becomes a success contrast. Unchanged and causally ambiguous differences
    remain unattributed.
    """

    role = Role(role)
    reference_cases = {
        case.case_id: case for case in reference.cases if case.role is role
    }
    candidate_cases = {
        case.case_id: case for case in candidate.cases if case.role is role
    }
    misalignment_ids = set(comparison.misalignment_ids if comparison else ())
    paired: list[TraceCase] = []

    for original_id in sorted(set(reference_cases) & set(candidate_cases)):
        old = reference_cases[original_id]
        new = candidate_cases[original_id]
        if not cases_are_pairable(old, new):
            continue
        old_issues = set(old.issue_tags)
        new_issues = set(new.issue_tags)
        added_reliability = tuple(sorted((new_issues - old_issues) & _RELIABILITY_ISSUES))
        delta = _score_delta(old, new)
        misaligned = original_id in misalignment_ids
        changed = any(
            (
                old.action_signature != new.action_signature,
                old.behavior_signature != new.behavior_signature,
                old.decisions_and_results != new.decisions_and_results,
                old.output != new.output,
                old.downstream_effect != new.downstream_effect,
                old.outcome != new.outcome,
            )
        )
        regressed = misaligned or bool(added_reliability) or (
            delta is not None and delta < 0
        )
        improved = delta is not None and delta > 0 and not regressed
        if not changed and not regressed and not improved:
            continue

        if regressed:
            outcome = "fail"
            issue_parts = []
            if misaligned:
                issue_parts.append(
                    "The role-local candidate was preferred, but its immediate downstream "
                    "or complete-system effect regressed."
                )
            if added_reliability:
                issue_parts.append(
                    "The candidate introduced reliability symptoms: "
                    + ", ".join(added_reliability)
                    + "."
                )
            if delta is not None and delta < 0:
                issue_parts.append(f"The paired official score changed by {delta:+.4f}.")
            observed_issue = " ".join(issue_parts)
        elif improved:
            outcome = "pass"
            observed_issue = (
                f"The paired official score improved by {delta:+.4f} without a new "
                "deterministic reliability symptom."
            )
        else:
            outcome = "unattributed"
            observed_issue = (
                "The candidate changed this role's behavior, but this paired trace alone "
                "does not establish that the change was beneficial or harmful."
            )

        case_id = "case_" + hash_json(
            {
                "kind": "paired_feedback",
                "role": role.value,
                "original_case_id": original_id,
                "reference": reference.key.cache_key,
                "candidate": candidate.key.cache_key,
            }
        )[:16]
        tags = ["paired_feedback"]
        if misaligned:
            tags.append("paired_misalignment")
        if regressed:
            tags.append("paired_regression")
        if improved:
            tags.append("paired_improvement")
        issue_tags = tuple(dict.fromkeys((*tags, *added_reliability)))
        paired.append(
            TraceCase(
                case_id=case_id,
                role=role,
                task_type=f"paired:{old.task_type.split(':', 1)[0]}",
                visible_input=new.visible_input or old.visible_input,
                decisions_and_results=_compact(
                    {
                        "parent": {
                            "action_signature": old.action_signature,
                            "behavior_signature": old.behavior_signature,
                            "trace": old.decisions_and_results,
                            "issue_tags": list(old.issue_tags),
                        },
                        "candidate": {
                            "action_signature": new.action_signature,
                            "behavior_signature": new.behavior_signature,
                            "trace": new.decisions_and_results,
                            "issue_tags": list(new.issue_tags),
                        },
                    }
                ),
                output=_compact(
                    {
                        "parent": old.output,
                        "candidate": new.output,
                        "official_score_delta": delta,
                    }
                ),
                observed_issue=observed_issue,
                downstream_effect=_compact(
                    {
                        "parent": old.downstream_effect,
                        "candidate": new.downstream_effect,
                    }
                ),
                outcome=outcome,
                official_score=new.official_score,
                outcome_feedback=new.outcome_feedback,
                source_group=new.source_group or old.source_group,
                action_signature=(
                    f"{old.action_signature}=>{new.action_signature}"
                ),
                behavior_signature=(
                    f"{old.behavior_signature}=>{new.behavior_signature}"
                ),
                issue_tags=issue_tags,
                episode_id=new.episode_id or old.episode_id,
                episode_trace=new.episode_trace or old.episode_trace,
            )
        )
    return tuple(paired)


def attach_paired_regressions(
    *,
    role: Role,
    reference: EvaluationResult,
    candidate: EvaluationResult,
    comparison: ComparisonResult | None = None,
) -> EvaluationResult:
    """Attach per-source regressions for later train-only diagnosis."""

    regressions = tuple(
        case
        for case in build_paired_feedback_cases(
            role=role,
            reference=reference,
            candidate=candidate,
            comparison=comparison,
        )
        if case.outcome in {"fail", "partial"}
    )
    if not regressions:
        return candidate
    return replace(
        candidate,
        evidence_ids=(*candidate.evidence_ids, *(case.case_id for case in regressions)),
        cases=(*candidate.cases, *regressions),
    )


def select_repair_cases(
    *,
    paired_cases: Sequence[TraceCase],
    candidate_cases: Sequence[TraceCase],
    role: Role,
    failure_limit: int = 3,
    success_limit: int = 2,
) -> tuple[TraceCase, ...]:
    """Return compact causal regressions plus ordinary train successes."""

    regressions = [
        case
        for case in paired_cases
        if case.role is role and case.outcome in {"fail", "partial"}
    ][: max(0, failure_limit)]
    successes: list[TraceCase] = []
    seen_groups = {case.source_group or case.case_id for case in regressions}
    for case in candidate_cases:
        if case.role is not role or case.outcome != "pass":
            continue
        group = case.source_group or case.case_id
        if group in seen_groups:
            continue
        successes.append(case)
        seen_groups.add(group)
        if len(successes) >= max(0, success_limit):
            break
    return tuple([*regressions, *successes])


__all__ = [
    "attach_paired_regressions",
    "build_paired_feedback_cases",
    "cases_are_pairable",
    "select_repair_cases",
]
