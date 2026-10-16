from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Collection

from .contracts import (
    CaseAssessment,
    EditOp,
    Role,
    SkillEdit,
    SkillSet,
    SkillUpdateProposal,
    normalize_skill_text,
)


_HEADING_RE = re.compile(r"^#{3,4}\s+\S.+$", re.MULTILINE)
_OUTER_HEADING_RE = re.compile(r"^#{1,2}\s+\S.+$", re.MULTILINE)
_PROTECTED_MARKERS = (
    "<!-- SLOW_UPDATE_START -->",
    "<!-- SLOW_UPDATE_END -->",
    "<!-- APPENDIX_START -->",
    "<!-- APPENDIX_END -->",
)
_PROMPT_OVERRIDE_RE = re.compile(
    r"\bignore\s+(?:the\s+)?(?:previous|system|runtime|schema|rules?)\b",
    re.IGNORECASE,
)
_BENCHMARK_LITERAL_RE = re.compile(
    r"(?i:\b(?:crossvid|cvbench|mvu[-_ ]?eval):[A-Za-z0-9_.:-]+\b|"
    r"\bcorrect\s+(?:answer|option)\s+is\b|"
    r"\b(?:ground[ -]?truth|reference answer)\b)|"
    r"(?i:\b(?:choose|select|answer)(?:\s+with)?\s+"
    r"(?:(?:option|choice)\s+)?)[A-Z]\b"
)
_SCHEMA_REDEFINITION_RE = re.compile(
    r"\b(?:add|emit|return|create|include)\s+(?:a\s+)?(?:new\s+)?"
    r"(?:json\s+)?(?:field|schema)\b|"
    r"\b(?:coverage|uncertainty)\s+field\b",
    re.IGNORECASE,
)
_REMOVED_ACTION_RE = re.compile(
    r"`(?:detect|localize|request_evidence|visual_review)`|"
    r"\baction\s*[:=]\s*(?:detect|localize|request_evidence|visual_review)\b",
    re.IGNORECASE,
)
_GLOBAL_WATCH_FALLBACK_RE = re.compile(
    r"\b(?:if|when)\b.{0,500}\b(?:summar(?:y|ies)|reports?|evidence)\b"
    r".{0,160}\b(?:ambiguous|conflicting|contradictory|incomplete|insufficient|"
    r"uncertain|vague|weak|lack(?:s|ing|ed)?)\b"
    r".{0,260}(?<!not )(?<!never )\b(?:use|choose|issue|call|invoke|perform|try|"
    r"switch\s+to|follow\s+up\s+with)\b"
    r".{0,80}`watch_videos`",
    re.IGNORECASE | re.DOTALL,
)


@dataclass(frozen=True)
class UpdateResult:
    """Result of applying one proposal.

    ``skill_set=None, errors=()`` is a valid no-change proposal. A rejection
    has non-empty errors. This intentionally does not duplicate the updated
    role Skill outside the returned SkillSet.
    """

    skill_set: SkillSet | None
    errors: tuple[str, ...] = ()

    @property
    def accepted(self) -> bool:
        return self.skill_set is not None

    @property
    def no_change(self) -> bool:
        return self.skill_set is None and not self.errors


class SkillUpdater:
    """Apply the same bounded-edit contract to empty and non-empty Skills."""

    def __init__(
        self,
        *,
        max_edits: int = 1,
        max_chars: int = 6_000,
        initial_max_chars: int = 1_200,
        max_net_growth: int = 1_000,
        min_edit_evidence: int = 2,
        adaptive_edit_budget: bool = False,
        adaptive_min_changed_chars: int = 240,
        adaptive_chars_per_support_group: int = 160,
        adaptive_generation_decay: float = 0.5,
    ) -> None:
        if max_edits != 1:
            raise ValueError("Skill evolution supports exactly one edit per candidate.")
        if min(
            max_edits,
            max_chars,
            initial_max_chars,
            max_net_growth,
            min_edit_evidence,
        ) < 1:
            raise ValueError("Skill update limits must be positive.")
        if not isinstance(adaptive_edit_budget, bool):
            raise ValueError("adaptive_edit_budget must be true or false.")
        if min(
            adaptive_min_changed_chars,
            adaptive_chars_per_support_group,
        ) < 1:
            raise ValueError("Adaptive edit-budget character limits must be positive.")
        if float(adaptive_generation_decay) < 0.0:
            raise ValueError("adaptive_generation_decay must be non-negative.")
        self.max_edits = int(max_edits)
        self.max_chars = int(max_chars)
        self.initial_max_chars = int(initial_max_chars)
        self.max_net_growth = int(max_net_growth)
        self.min_edit_evidence = int(min_edit_evidence)
        self.adaptive_edit_budget = adaptive_edit_budget
        self.adaptive_min_changed_chars = int(adaptive_min_changed_chars)
        self.adaptive_chars_per_support_group = int(
            adaptive_chars_per_support_group
        )
        self.adaptive_generation_decay = float(adaptive_generation_decay)

    def changed_char_budget(
        self,
        *,
        parent: str,
        support_group_count: int,
        generation: int,
    ) -> int | None:
        """Return a deterministic evidence-scaled text-change budget when enabled."""

        if not self.adaptive_edit_budget:
            return None
        if support_group_count < 1:
            raise ValueError("support_group_count must be positive.")
        if generation < 0:
            raise ValueError("generation must be non-negative.")
        evidence_budget = max(
            self.adaptive_min_changed_chars,
            self.adaptive_chars_per_support_group * support_group_count,
        )
        decayed = int(
            evidence_budget
            / (1.0 + generation * self.adaptive_generation_decay)
        )
        hard_limit = self.max_net_growth if parent else self.initial_max_chars
        return min(
            hard_limit,
            max(self.adaptive_min_changed_chars, decayed),
        )

    @staticmethod
    def changed_chars(parent: str, candidate: str) -> int:
        """Return the same inserted/deleted/replaced character count used by lint."""

        return SkillUpdater._changed_chars(parent, candidate)

    def apply(
        self,
        parent_skill_set: SkillSet,
        proposal: SkillUpdateProposal,
        *,
        allowed_case_ids: Collection[str] | None = None,
        min_edit_evidence: int | None = None,
        max_changed_chars: int | None = None,
    ) -> UpdateResult:
        parent = parent_skill_set.get(proposal.role)
        errors: list[str] = []
        required_evidence = (
            self.min_edit_evidence
            if min_edit_evidence is None
            else int(min_edit_evidence)
        )
        if required_evidence < 1:
            raise ValueError("min_edit_evidence must be positive.")
        if max_changed_chars is not None and max_changed_chars < 1:
            raise ValueError("max_changed_chars must be positive when provided.")

        if proposal.parent_sha256 != parent_skill_set.skill_sha256(proposal.role):
            errors.append("Proposal parent SHA256 does not match the current Skill.")

        if allowed_case_ids is not None:
            allowed = {str(item) for item in allowed_case_ids}
            unknown = sorted(set(proposal.case_assessments) - allowed)
            unknown.extend(sorted(set(proposal.diagnosis.support_ids) - allowed))
            unknown.extend(sorted(set(proposal.diagnosis.contrast_ids) - allowed))
            if unknown:
                errors.append("Proposal references unknown case IDs: " + ", ".join(sorted(set(unknown))))

        unsupported_evidence = [
            case_id
            for case_id in proposal.diagnosis.support_ids
            if proposal.case_assessments.get(case_id) is not CaseAssessment.STRATEGY_GAP
        ]
        if unsupported_evidence:
            errors.append(
                "Edit support must be assessed as strategy_gap: "
                + ", ".join(unsupported_evidence)
            )

        unsupported_contrasts = [
            case_id
            for case_id in proposal.diagnosis.contrast_ids
            if proposal.case_assessments.get(case_id)
            is not CaseAssessment.PRESERVE_SUCCESS
        ]
        if unsupported_contrasts:
            errors.append(
                "Contrasts must be assessed as preserve_success: "
                + ", ".join(unsupported_contrasts)
            )

        if not proposal.edits:
            return UpdateResult(None, tuple(errors))

        if len(proposal.diagnosis.support_ids) < required_evidence:
            errors.append(
                "A changing proposal must cite at least "
                f"{required_evidence} strategy_gap cases; cross-case independence is checked by the Coordinator."
            )
        if not proposal.diagnosis.contrast_ids:
            errors.append(
                "A changing proposal must cite at least one preserve_success contrast."
            )

        if len(proposal.edits) > 1:
            errors.append("One candidate may contain at most one edit and one behavioral hypothesis.")

        if not parent:
            valid_initial = (
                len(proposal.edits) == 1
                and proposal.edits[0].op is EditOp.APPEND
                and not proposal.edits[0].target
            )
            if not valid_initial:
                errors.append("An empty parent Skill accepts exactly one target-free append edit.")
        elif not 1 <= len(proposal.edits) <= min(self.max_edits, 1):
            errors.append("A non-empty parent Skill accepts exactly one edit per candidate.")

        if errors:
            return UpdateResult(None, tuple(errors))

        try:
            candidate = normalize_skill_text(self._apply_edits(parent, proposal.edits))
        except ValueError as exc:
            return UpdateResult(None, (str(exc),))

        errors.extend(
            self._lint(
                proposal.role,
                parent,
                candidate,
                allowed_case_ids=allowed_case_ids,
                max_changed_chars=max_changed_chars,
            )
        )
        if errors:
            return UpdateResult(None, tuple(errors))
        if candidate == parent:
            return UpdateResult(None)
        return UpdateResult(parent_skill_set.replace(proposal.role, candidate))

    def _lint(
        self,
        role: Role,
        parent: str,
        candidate: str,
        *,
        allowed_case_ids: Collection[str] | None = None,
        max_changed_chars: int | None = None,
    ) -> list[str]:
        errors: list[str] = []
        headings = _HEADING_RE.findall(candidate)
        limit = self.initial_max_chars if not parent else self.max_chars
        checks = (
            (bool(candidate), "Candidate Skill is empty."),
            (bool(headings), "Candidate must contain a Markdown H3 or H4 heading."),
            (
                not _OUTER_HEADING_RE.search(candidate),
                "Candidate must not contain H1 or H2; Runtime owns the Decision strategy H2.",
            ),
            (len(candidate) <= limit, f"Candidate exceeds its {limit}-character limit."),
            (
                not parent or len(candidate) - len(parent) <= self.max_net_growth,
                "Candidate exceeds the allowed net growth relative to its parent.",
            ),
            (
                max_changed_chars is None
                or self._changed_chars(parent, candidate) <= max_changed_chars,
                "Candidate exceeds the adaptive changed-character budget"
                + (
                    f" of {max_changed_chars}."
                    if max_changed_chars is not None
                    else "."
                ),
            ),
            (
                not any(marker in candidate for marker in _PROTECTED_MARKERS),
                "Candidate contains optimizer-owned protected markers.",
            ),
            (not _REMOVED_ACTION_RE.search(candidate), "Candidate names a removed or unknown action."),
            (not _SCHEMA_REDEFINITION_RE.search(candidate), "Candidate attempts to redefine an output Schema."),
            (not _BENCHMARK_LITERAL_RE.search(candidate), "Candidate contains benchmark-specific answer material."),
            (
                not self._contains_case_id(candidate, allowed_case_ids),
                "Candidate copies an optimizer-visible case ID into the Skill.",
            ),
            (not _PROMPT_OVERRIDE_RE.search(candidate), "Candidate contains Prompt-override language."),
            (
                self._respects_role_boundary(role, candidate),
                "Candidate crosses the Global/Video action boundary.",
            ),
            (
                role is not Role.GLOBAL
                or not _GLOBAL_WATCH_FALLBACK_RE.search(candidate),
                "Global candidate uses watch_videos as a generic fallback for weak summaries.",
            ),
        )
        errors.extend(message for valid, message in checks if not valid)
        return errors

    @staticmethod
    def _changed_chars(parent: str, candidate: str) -> int:
        """Count changed text spans rather than only net length growth."""

        matcher = SequenceMatcher(a=parent, b=candidate, autojunk=False)
        return sum(
            max(old_end - old_start, new_end - new_start)
            for tag, old_start, old_end, new_start, new_end in matcher.get_opcodes()
            if tag != "equal"
        )

    @staticmethod
    def _contains_case_id(
        candidate: str,
        allowed_case_ids: Collection[str] | None,
    ) -> bool:
        if not allowed_case_ids:
            return False
        lowered = candidate.casefold()
        for case_id in allowed_case_ids:
            token = str(case_id).strip().casefold()
            if len(token) < 5:
                continue
            if re.search(
                rf"(?<![a-z0-9_]){re.escape(token)}(?![a-z0-9_])",
                lowered,
            ):
                return True
        return False

    @staticmethod
    def _apply_edits(content: str, edits: tuple[SkillEdit, ...]) -> str:
        updated = content
        for index, edit in enumerate(edits, 1):
            if edit.op is EditOp.APPEND:
                if edit.target:
                    raise ValueError(f"Edit {index}: append must not define target.")
                if not edit.content:
                    raise ValueError(f"Edit {index}: append content is empty.")
                prefix = f"{updated.rstrip()}\n\n" if updated.strip() else ""
                updated = f"{prefix}{edit.content.strip()}\n"
                continue

            if not edit.target:
                raise ValueError(f"Edit {index}: {edit.op.value} target is empty.")
            occurrences = updated.count(edit.target)
            if occurrences != 1:
                raise ValueError(
                    f"Edit {index}: target must occur exactly once; found {occurrences}."
                )

            if edit.op is EditOp.INSERT_AFTER:
                if not edit.content:
                    raise ValueError(f"Edit {index}: insert_after content is empty.")
                start = updated.index(edit.target) + len(edit.target)
                line_end = updated.find("\n", start)
                insertion = len(updated) if line_end < 0 else line_end + 1
                updated = updated[:insertion] + f"\n{edit.content.strip()}\n" + updated[insertion:]
            elif edit.op is EditOp.REPLACE:
                if not edit.content:
                    raise ValueError(f"Edit {index}: replace content is empty.")
                updated = updated.replace(edit.target, edit.content.strip(), 1)
            elif edit.op is EditOp.DELETE:
                if edit.content:
                    raise ValueError(f"Edit {index}: delete content must be empty.")
                updated = updated.replace(edit.target, "", 1)
        return updated

    @staticmethod
    def _respects_role_boundary(role: Role, content: str) -> bool:
        lowered = content.lower()
        forbidden = (
            ("`observe`", "`finish`")
            if role is Role.GLOBAL
            else ("`analyze_videos`", "`watch_videos`", "`answer`")
        )
        return not any(name in lowered for name in forbidden)


__all__ = ["SkillUpdater", "UpdateResult"]
