"""Deterministic train-case selection for one role-local Skill hypothesis."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Iterable, Sequence

from ..strategy.contracts import EvidencePacket, Role, TraceCase, hash_json


def _shorten_text(value: str, maximum: int) -> str:
    text = str(value or "")
    if len(text) <= maximum:
        return text
    marker_template = " … [omitted {count} characters] … "
    marker = marker_template.format(count=max(0, len(text) - maximum))
    if maximum <= len(marker) + 16:
        return marker[:maximum]
    remaining = maximum - len(marker)
    head_budget = remaining * 2 // 3
    tail_budget = remaining - head_budget
    head = text[:head_budget]
    tail = text[-tail_budget:] if tail_budget else ""
    for separator in ("\n", ". ", "; ", ", ", " "):
        boundary = head.rfind(separator)
        if boundary >= head_budget // 2:
            head = head[: boundary + len(separator)].rstrip()
            break
    for separator in ("\n", ". ", "; ", ", ", " "):
        boundary = tail.find(separator)
        if 0 <= boundary <= max(1, tail_budget // 2):
            tail = tail[boundary + len(separator) :].lstrip()
            break
    omitted = len(text) - len(head) - len(tail)
    marker = marker_template.format(count=max(0, omitted))
    return f"{head}{marker}{tail}"[:maximum]


def _count_strings(value: object) -> int:
    if isinstance(value, str):
        return 1
    if isinstance(value, dict):
        return sum(_count_strings(item) for item in value.values())
    if isinstance(value, list):
        return sum(_count_strings(item) for item in value)
    return 0


def _bound_json_strings(value: object, maximum: int) -> object:
    if isinstance(value, str):
        return _shorten_text(value, maximum)
    if isinstance(value, list):
        return [_bound_json_strings(item, maximum) for item in value]
    if isinstance(value, dict):
        return {
            str(key): _bound_json_strings(item, maximum)
            for key, item in value.items()
        }
    return value


def _compact_json_text(value: str, maximum: int) -> str:
    """Bound projected JSON without ever slicing its serialized representation."""

    try:
        parsed = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return _shorten_text(value, maximum)
    rendered = json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))
    if len(rendered) <= maximum:
        return rendered
    string_count = max(1, _count_strings(parsed))
    string_limit = max(48, maximum // string_count)
    while True:
        bounded = _bound_json_strings(parsed, string_limit)
        rendered = json.dumps(bounded, ensure_ascii=False, separators=(",", ":"))
        if len(rendered) <= maximum or string_limit <= 48:
            return rendered
        string_limit = max(48, string_limit * 3 // 4)


class EvidencePacketBuilder:
    """Build deterministic role-local failure/success trajectory minibatches.

    Action, parameter, task, and behavior similarity are deliberately left to the
    optimizer.  The builder only separates outcomes, reproducibly shuffles each pool,
    enforces independent source groups, and supplies successful preservation examples.
    """

    def __init__(
        self,
        *,
        failure_size: int,
        success_size: int,
        detail_max_chars: int,
        seed: int = 0,
    ) -> None:
        for name, value in (
            ("failure_size", failure_size),
            ("success_size", success_size),
            ("detail_max_chars", detail_max_chars),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer.")
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise ValueError("seed must be an integer.")
        self.failure_size = int(failure_size)
        self.success_size = int(success_size)
        self.detail_max_chars = int(detail_max_chars)
        self.seed = int(seed)

    def build(
        self,
        *,
        role: Role,
        cases: Sequence[TraceCase],
        cycle: int,
        max_batches: int = 1,
        min_support_cases: int = 2,
        min_support_groups: int = 2,
        misalignment_ids: Sequence[str] = (),
        allow_unattributed: bool = False,
    ) -> tuple[EvidencePacket, ...]:
        role = Role(role)
        if max_batches < 1:
            raise ValueError("max_batches must be positive.")
        if min_support_cases < 1 or min_support_groups < 1:
            raise ValueError("Evidence support minima must be positive.")

        role_cases = self._deduplicate(case for case in cases if case.role is role)
        misalignment = {
            str(item).strip() for item in misalignment_ids if str(item).strip()
        }
        failures = [
            (
                replace(
                    case,
                    issue_tags=tuple(
                        dict.fromkeys(
                            (*case.issue_tags, "optimizer_misalignment")
                        )
                    ),
                    observed_issue=(
                        "The role-local behavior was preferred, but its immediate "
                        "downstream effect regressed."
                    ),
                )
                if case.case_id in misalignment
                else case
            )
            for case in role_cases
            if case.case_id in misalignment
            or case.outcome in {"fail", "partial"}
            or (
                allow_unattributed
                and role is Role.VIDEO
                and case.outcome == "unattributed"
            )
        ]
        successes = [
            case
            for case in role_cases
            if case.outcome == "pass" and case.case_id not in misalignment
        ]
        failures = self._shuffle(
            failures,
            role=role,
            cycle=cycle,
            outcome="failure",
        )
        successes = self._shuffle(
            successes,
            role=role,
            cycle=cycle,
            outcome="success",
        )
        if not successes:
            return ()

        packets: list[EvidencePacket] = []
        failure_batches = self._group_distinct_batches(
            failures,
            limit=self.failure_size,
        )
        for batch_index, support in enumerate(failure_batches):
            if len(packets) >= max_batches:
                break
            support_groups = {self._group(case) for case in support}
            if (
                len(support) < min_support_cases
                or len(support_groups) < min_support_groups
            ):
                continue
            contrasts = self._successes_for_batch(
                successes,
                batch_index=batch_index,
                excluded_groups=support_groups,
            )
            if not contrasts:
                continue
            selected = self.fit_detail_budget(support, contrasts)
            support_set = {case.case_id for case in support}
            contrast_set = {case.case_id for case in contrasts}
            support_ids = tuple(
                case.case_id for case in selected if case.case_id in support_set
            )
            contrast_ids = tuple(
                case.case_id for case in selected if case.case_id in contrast_set
            )
            selected_by_id = {case.case_id: case for case in selected}
            selected_groups = {
                self._group(selected_by_id[case_id]) for case_id in support_ids
            }
            if (
                len(support_ids) < min_support_cases
                or len(selected_groups) < min_support_groups
                or not contrast_ids
            ):
                continue
            ordered_ids = (*support_ids, *contrast_ids)
            packets.append(
                EvidencePacket(
                    role=role,
                    cases=selected,
                    support_ids=support_ids,
                    contrast_ids=contrast_ids,
                    signature=hash_json(
                        {
                            "role": role.value,
                            "cycle": cycle,
                            "ids": ordered_ids,
                        }
                    )[:16],
                )
            )
        return tuple(packets)

    def build_repair(
        self,
        *,
        role: Role,
        cases: Sequence[TraceCase],
        cycle: int,
    ) -> EvidencePacket | None:
        """Package already-causal paired regressions for one bounded repair."""
        role = Role(role)
        regressions = [
            case
            for case in cases
            if case.role is role and case.outcome in {"fail", "partial"}
        ][: self.failure_size]
        successes = [
            case for case in cases if case.role is role and case.outcome == "pass"
        ][: self.success_size]
        if not regressions or not successes:
            return None
        selected = self.fit_detail_budget(regressions, successes)
        regression_ids = {case.case_id for case in regressions}
        success_ids = {case.case_id for case in successes}
        support_ids = tuple(
            case.case_id for case in selected if case.case_id in regression_ids
        )
        contrast_ids = tuple(
            case.case_id for case in selected if case.case_id in success_ids
        )
        if not support_ids or not contrast_ids:
            return None
        return EvidencePacket(
            role=role,
            cases=selected,
            support_ids=support_ids,
            contrast_ids=contrast_ids,
            signature=hash_json(
                {
                    "role": role.value,
                    "cycle": cycle,
                    "ids": (*support_ids, *contrast_ids),
                }
            )[:16],
        )

    @staticmethod
    def _deduplicate(cases: Iterable[TraceCase]) -> tuple[TraceCase, ...]:
        """Choose one deterministic representative for each opaque case ID."""

        ordered = sorted(
            cases,
            key=lambda case: (
                case.case_id,
                hash_json(
                    {
                        "case": case.to_dict(),
                        "source_group": case.source_group,
                    }
                ),
            ),
        )
        unique: list[TraceCase] = []
        seen: set[str] = set()
        for case in ordered:
            if case.case_id in seen:
                continue
            seen.add(case.case_id)
            unique.append(case)
        return tuple(unique)

    @staticmethod
    def _group(case: TraceCase) -> str:
        return case.source_group or case.case_id

    def _shuffle(
        self,
        cases: Sequence[TraceCase],
        *,
        role: Role,
        cycle: int,
        outcome: str,
    ) -> list[TraceCase]:
        return sorted(
            cases,
            key=lambda case: (
                hash_json(
                    {
                        "seed": self.seed,
                        "cycle": cycle,
                        "role": role.value,
                        "outcome": outcome,
                        "case_id": case.case_id,
                    }
                ),
                case.case_id,
            ),
        )

    @classmethod
    def _group_distinct_batches(
        cls,
        cases: Sequence[TraceCase],
        *,
        limit: int,
    ) -> tuple[tuple[TraceCase, ...], ...]:
        remaining = list(cases)
        batches: list[tuple[TraceCase, ...]] = []
        while remaining:
            batch: list[TraceCase] = []
            deferred: list[TraceCase] = []
            groups: set[str] = set()
            for case in remaining:
                group = cls._group(case)
                if len(batch) < limit and group not in groups:
                    batch.append(case)
                    groups.add(group)
                else:
                    deferred.append(case)
            batches.append(tuple(batch))
            remaining = deferred
        return tuple(batches)

    def _successes_for_batch(
        self,
        successes: Sequence[TraceCase],
        *,
        batch_index: int,
        excluded_groups: set[str],
    ) -> tuple[TraceCase, ...]:
        """Round-robin over shuffled successes while preserving group independence."""

        if not successes:
            return ()
        start = (batch_index * self.success_size) % len(successes)
        selected: list[TraceCase] = []
        groups = set(excluded_groups)
        for offset in range(len(successes)):
            case = successes[(start + offset) % len(successes)]
            group = self._group(case)
            if group in groups:
                continue
            selected.append(case)
            groups.add(group)
            if len(selected) >= self.success_size:
                break
        return tuple(selected)

    def fit_detail_budget(
        self,
        support: Sequence[TraceCase],
        contrasts: Sequence[TraceCase],
    ) -> tuple[TraceCase, ...]:
        """Bound one already-selected failure/success minibatch without slicing it."""
        priority = [
            *support[:2],
            *contrasts,
            *support[2:],
        ]
        per_case_limit = max(
            2_200,
            min(
                5_000,
                self.detail_max_chars // max(3, min(len(priority), 10)),
            ),
        )
        bounded: list[TraceCase] = []
        used = 0
        for case in priority:
            compact = self._compact(case, per_case_limit)
            size = (
                len(compact.episode_trace)
                if compact.episode_trace
                else len(json.dumps(compact.to_dict(), ensure_ascii=False))
            )
            if bounded and used + size > self.detail_max_chars:
                continue
            bounded.append(compact)
            used += size
        return tuple(bounded)

    @staticmethod
    def _compact(case: TraceCase, limit: int) -> TraceCase:
        if case.episode_trace:
            return replace(
                case,
                episode_trace=_compact_json_text(case.episode_trace, limit),
                observed_issue=_shorten_text(
                    case.observed_issue,
                    max(160, limit // 20),
                ),
                downstream_effect="",
                outcome_feedback="",
            )
        return replace(
            case,
            visible_input=_compact_json_text(
                case.visible_input,
                max(500, limit * 3 // 10),
            ),
            decisions_and_results=_compact_json_text(
                case.decisions_and_results,
                max(900, limit * 5 // 10),
            ),
            output=_compact_json_text(case.output, max(200, limit // 12)),
            observed_issue=_shorten_text(case.observed_issue, max(250, limit // 10)),
            downstream_effect=_compact_json_text(
                case.downstream_effect,
                max(250, limit // 10),
            ),
            outcome_feedback=_compact_json_text(
                case.outcome_feedback,
                max(200, limit // 12),
            ),
        )


__all__ = ["EvidencePacketBuilder"]
