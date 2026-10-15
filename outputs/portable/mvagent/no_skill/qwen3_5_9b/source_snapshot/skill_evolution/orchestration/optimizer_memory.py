"""Small, typed memory for reusable optimizer lessons.

Child-local parser, lint, and duplicate feedback does not belong here.  This module
retains only compact lessons about candidate behavior that can help a later optimizer
attempt without copying the attempted Skill edit into the model-visible context.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Mapping

from ..strategy.contracts import Role, hash_json


DEFAULT_MAX_LESSONS_PER_ROLE = 4
DEFAULT_MAX_RENDER_CHARS_PER_ROLE = 2_000

_OUTCOME_PRIORITY = {
    "eval_regression": 4,
    "promoted": 4,
    "train_reliability": 3,
    "misalignment": 3,
    "semantic_review": 2,
    "planner_replay": 2,
    "eval_tie": 1,
    "no_change": 1,
}
_TRANSIENT_OUTCOME_FAMILIES = {
    "duplicate",
    "format_static",
    "parser",
    "schema",
    "structured_output",
}
_SUPERVISION_LITERAL_RE = re.compile(
    r"(?i:\b(?:crossvid|cvbench|mvu[-_ ]?eval):[A-Za-z0-9_.:-]+\b|"
    r"\bcorrect\s+(?:answer|option)\s+is\b|"
    r"\b(?:ground[ -]?truth|reference answer)\b)|"
    r"(?i:\b(?:choose|select|answer)(?:\s+with)?\s+"
    r"(?:(?:option|choice)\s+)?)[A-Z]\b"
)


def _compact_text(value: object) -> str:
    return " ".join(str(value or "").split())


def _normalize_outcome(value: object) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower())
    return normalized.strip("_")


def _outcome_family(outcome: str) -> str:
    """Map narrowly qualified outcomes to their stable retention family."""
    normalized = _normalize_outcome(outcome)
    known = (*_OUTCOME_PRIORITY, *_TRANSIENT_OUTCOME_FAMILIES)
    for family in sorted(known, key=len, reverse=True):
        if normalized == family or normalized.startswith(f"{family}_"):
            return family
    return normalized


def sanitize_optimizer_text(
    value: object,
    *,
    fallback: str,
    forbidden_case_ids: Iterable[str] = (),
    forbidden_fragments: Iterable[str] = (),
) -> str:
    """Fail closed on obvious case/supervision/edit leakage in persistent memory."""

    text = _compact_text(value)
    safe_fallback = _compact_text(fallback)
    if not text or _SUPERVISION_LITERAL_RE.search(text):
        return safe_fallback
    lowered = text.casefold()
    for case_id in forbidden_case_ids:
        token = _compact_text(case_id).casefold()
        if len(token) >= 5 and re.search(
            rf"(?<![a-z0-9_]){re.escape(token)}(?![a-z0-9_])",
            lowered,
        ):
            return safe_fallback
    for fragment in forbidden_fragments:
        token = _compact_text(fragment)
        if len(token) < 12:
            continue
        token_lower = token.casefold()
        if token_lower in lowered or lowered in token_lower:
            return safe_fallback
    return text


def optimizer_hypothesis_key(
    *,
    role: Role,
    failure_source: object,
    expected_behavior_change: object,
) -> str:
    """Return the hidden exact-family key used for retention and hard regressions."""

    return hash_json(
        {
            "role": Role(role).value,
            "failure_source": _compact_text(failure_source).casefold(),
            "expected_behavior_change": _compact_text(
                expected_behavior_change
            ).casefold(),
        }
    )


@dataclass(frozen=True)
class OptimizerLesson:
    """One reusable, role-local lesson from a candidate evaluation."""

    role: Role
    outcome: str
    hypothesis: str
    observed_effect: str
    reusable_lesson: str
    hypothesis_key: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "role", Role(self.role))
        object.__setattr__(self, "outcome", _normalize_outcome(self.outcome))
        for name in (
            "hypothesis",
            "observed_effect",
            "reusable_lesson",
            "hypothesis_key",
        ):
            object.__setattr__(self, name, _compact_text(getattr(self, name)))
        if not self.outcome:
            raise ValueError("OptimizerLesson.outcome must be non-empty.")
        if not self.hypothesis:
            raise ValueError("OptimizerLesson.hypothesis must be non-empty.")
        if not self.observed_effect:
            raise ValueError("OptimizerLesson.observed_effect must be non-empty.")
        if not self.reusable_lesson:
            raise ValueError("OptimizerLesson.reusable_lesson must be non-empty.")
        if not self.hypothesis_key:
            raise ValueError("OptimizerLesson.hypothesis_key must be non-empty.")

    @property
    def outcome_family(self) -> str:
        return _outcome_family(self.outcome)

    @property
    def priority(self) -> int:
        return _OUTCOME_PRIORITY.get(self.outcome_family, 0)

    def to_dict(self) -> dict[str, str]:
        return {
            "role": self.role.value,
            "outcome": self.outcome,
            "hypothesis": self.hypothesis,
            "observed_effect": self.observed_effect,
            "reusable_lesson": self.reusable_lesson,
            "hypothesis_key": self.hypothesis_key,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> OptimizerLesson:
        if not isinstance(value, Mapping):
            raise TypeError("OptimizerLesson serialization must be a mapping.")
        required = {
            "role",
            "outcome",
            "hypothesis",
            "observed_effect",
            "reusable_lesson",
            "hypothesis_key",
        }
        missing = required - set(value)
        if missing:
            raise ValueError(
                "OptimizerLesson serialization is missing: "
                + ", ".join(sorted(missing))
            )
        unknown = set(value) - required
        if unknown:
            raise ValueError(
                "OptimizerLesson serialization has unknown fields: "
                + ", ".join(sorted(unknown))
            )
        return cls(**{name: value[name] for name in required})


class OptimizerMemory:
    """Prioritized, bounded optimizer lessons for both Planner roles.

    Lessons are deduplicated by role, hidden hypothesis key, and outcome family.
    Capacity favors higher-value outcomes and then the newest lesson.  The separate
    render budget bounds only model-visible text; checkpoints retain the typed fields.
    """

    def __init__(
        self,
        lessons: Iterable[OptimizerLesson] = (),
        *,
        max_lessons_per_role: int = DEFAULT_MAX_LESSONS_PER_ROLE,
        max_render_chars_per_role: int = DEFAULT_MAX_RENDER_CHARS_PER_ROLE,
    ) -> None:
        for name, value in (
            ("max_lessons_per_role", max_lessons_per_role),
            ("max_render_chars_per_role", max_render_chars_per_role),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer.")
        self.max_lessons_per_role = max_lessons_per_role
        self.max_render_chars_per_role = max_render_chars_per_role
        self._lessons: dict[Role, list[OptimizerLesson]] = {
            role: [] for role in Role
        }
        for lesson in lessons:
            self.add(lesson)

    def add(self, lesson: OptimizerLesson) -> bool:
        """Retain a long-term lesson; return false for child-local outcome types."""
        if not isinstance(lesson, OptimizerLesson):
            raise TypeError("OptimizerMemory.add expects an OptimizerLesson.")
        family = lesson.outcome_family
        if family in _TRANSIENT_OUTCOME_FAMILIES:
            return False
        if family not in _OUTCOME_PRIORITY:
            return False

        role_lessons = self._lessons[lesson.role]
        role_lessons[:] = [
            existing
            for existing in role_lessons
            if not (
                existing.hypothesis_key == lesson.hypothesis_key
                and existing.outcome_family == family
            )
        ]
        role_lessons.append(lesson)
        self._trim(lesson.role)
        return True

    def lessons(self, role: Role) -> tuple[OptimizerLesson, ...]:
        return tuple(self._ranked(Role(role)))

    def snapshot(self) -> dict[Role, tuple[OptimizerLesson, ...]]:
        # Preserve chronological order so checkpoint/resume keeps recency tie-breaks.
        return {role: tuple(self._lessons[role]) for role in Role}

    def blocks(self, role: Role, hypothesis_key: str) -> bool:
        """Whether an exact normalized hypothesis has a retained eval regression."""

        key = _compact_text(hypothesis_key)
        return any(
            lesson.hypothesis_key == key
            and lesson.outcome_family == "eval_regression"
            for lesson in self._lessons[Role(role)]
        )

    def render(self, role: Role | None = None) -> tuple[str, ...]:
        """Render bounded lesson text without the hidden key or attempted edit."""
        roles = tuple(Role) if role is None else (Role(role),)
        include_role = role is None
        rendered: list[str] = []
        for item_role in roles:
            rendered.extend(self._render_role(item_role, include_role=include_role))
        return tuple(rendered)

    def to_dict(self) -> dict[str, list[dict[str, str]]]:
        return {
            role.value: [lesson.to_dict() for lesson in self._lessons[role]]
            for role in Role
        }

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, object],
        *,
        max_lessons_per_role: int = DEFAULT_MAX_LESSONS_PER_ROLE,
        max_render_chars_per_role: int = DEFAULT_MAX_RENDER_CHARS_PER_ROLE,
    ) -> OptimizerMemory:
        if not isinstance(value, Mapping):
            raise TypeError("OptimizerMemory serialization must be a mapping.")
        memory = cls(
            max_lessons_per_role=max_lessons_per_role,
            max_render_chars_per_role=max_render_chars_per_role,
        )
        for role in Role:
            raw_items = value.get(role.value, ())
            if isinstance(raw_items, (str, bytes)) or not isinstance(
                raw_items, (list, tuple)
            ):
                raise ValueError(
                    f"OptimizerMemory.{role.value} must be a list of lessons."
                )
            for raw_item in raw_items:
                # Version-1 checkpoints stored opaque strings.  They are attempt logs,
                # not reusable typed lessons, and intentionally restore as empty.
                if isinstance(raw_item, str):
                    continue
                lesson = OptimizerLesson.from_dict(raw_item)
                if lesson.role is not role:
                    raise ValueError(
                        "OptimizerLesson role does not match its serialized "
                        "role bucket."
                    )
                memory.add(lesson)
        return memory

    def _trim(self, role: Role) -> None:
        items = self._lessons[role]
        if len(items) <= self.max_lessons_per_role:
            return
        keep = {
            index
            for index, _ in sorted(
                enumerate(items),
                key=lambda pair: (pair[1].priority, pair[0]),
                reverse=True,
            )[: self.max_lessons_per_role]
        }
        items[:] = [item for index, item in enumerate(items) if index in keep]

    def _ranked(self, role: Role) -> tuple[OptimizerLesson, ...]:
        return tuple(
            item
            for _, item in sorted(
                enumerate(self._lessons[role]),
                key=lambda pair: (pair[1].priority, pair[0]),
                reverse=True,
            )
        )

    def _render_role(self, role: Role, *, include_role: bool) -> tuple[str, ...]:
        remaining = self.max_render_chars_per_role
        rendered: list[str] = []
        for lesson in self._ranked(role):
            separator_chars = 1 if rendered else 0
            available = remaining - separator_chars
            if available <= 0:
                break
            text = _render_lesson(
                lesson,
                include_role=include_role,
                max_chars=available,
            )
            if not text:
                continue
            rendered.append(text)
            remaining -= len(text) + separator_chars
        return tuple(rendered)


def optimizer_memory_to_dict(
    value: Mapping[Role, Iterable[OptimizerLesson]],
) -> dict[str, list[dict[str, str]]]:
    """Serialize an EvolutionResult memory snapshot for JSON output."""

    serialized: dict[str, list[dict[str, str]]] = {}
    for role in Role:
        items = value.get(role, ())
        serialized[role.value] = []
        for item in items:
            if not isinstance(item, OptimizerLesson):
                raise TypeError(
                    "Optimizer memory snapshots must contain OptimizerLesson values."
                )
            if item.role is not role:
                raise ValueError(
                    "OptimizerLesson role does not match its memory role bucket."
                )
            serialized[role.value].append(item.to_dict())
    return serialized


def _render_lesson(
    lesson: OptimizerLesson,
    *,
    include_role: bool,
    max_chars: int,
) -> str:
    prefix = f"Role: {lesson.role.value}\n" if include_role else ""
    fixed = (
        f"{prefix}Outcome: {lesson.outcome}\n"
        "Hypothesis: \n"
        "Observed effect: \n"
        "Reusable lesson: "
    )
    values = [lesson.hypothesis, lesson.observed_effect, lesson.reusable_lesson]
    fixed_chars = len(fixed)
    if max_chars <= fixed_chars + len(values):
        return ""
    allocations = _fair_allocations(
        tuple(len(value) for value in values),
        max_chars - fixed_chars,
    )
    visible = [
        _truncate(value, allocation)
        for value, allocation in zip(values, allocations, strict=True)
    ]
    return (
        f"{prefix}Outcome: {lesson.outcome}\n"
        f"Hypothesis: {visible[0]}\n"
        f"Observed effect: {visible[1]}\n"
        f"Reusable lesson: {visible[2]}"
    )


def _fair_allocations(lengths: tuple[int, ...], budget: int) -> tuple[int, ...]:
    allocations = [0] * len(lengths)
    unresolved = set(range(len(lengths)))
    remaining = budget
    while unresolved:
        share = max(1, remaining // len(unresolved))
        completed = {
            index for index in unresolved if lengths[index] <= share
        }
        if not completed:
            for index in unresolved:
                allocations[index] = share
            remaining -= share * len(unresolved)
            for index in sorted(unresolved):
                if remaining <= 0:
                    break
                allocations[index] += 1
                remaining -= 1
            break
        for index in completed:
            allocations[index] = lengths[index]
            remaining -= lengths[index]
        unresolved -= completed
    return tuple(allocations)


def _truncate(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    if max_chars <= 1:
        return value[:max_chars]
    return f"{value[: max_chars - 1].rstrip()}…"


__all__ = [
    "DEFAULT_MAX_LESSONS_PER_ROLE",
    "DEFAULT_MAX_RENDER_CHARS_PER_ROLE",
    "OptimizerLesson",
    "OptimizerMemory",
    "optimizer_hypothesis_key",
    "optimizer_memory_to_dict",
    "sanitize_optimizer_text",
]
