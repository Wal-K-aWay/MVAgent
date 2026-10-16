from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol, Sequence

from ..strategy.contracts import EvidencePacket, Role, SkillSet, hash_json


class PlannerReplayExecutor(Protocol):
    """Replay bounded saved Planner states without executing visual actions."""

    def replay(
        self,
        *,
        reference_skill_set: SkillSet,
        skill_set: SkillSet,
        role: Role,
        case_ids: Sequence[str],
    ) -> Mapping[str, Sequence[Mapping[str, object]]]: ...


@dataclass(frozen=True)
class PlannerReplayReview:
    passed: bool
    reason: str
    support_changed_ids: tuple[str, ...] = ()
    contrast_action_changed_ids: tuple[str, ...] = ()
    parent_invalid_ids: tuple[str, ...] = ()
    candidate_invalid_ids: tuple[str, ...] = ()
    invalid_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "reason": self.reason,
            "support_changed_ids": list(self.support_changed_ids),
            "contrast_action_changed_ids": list(
                self.contrast_action_changed_ids
            ),
            "parent_invalid_ids": list(self.parent_invalid_ids),
            "candidate_invalid_ids": list(self.candidate_invalid_ids),
            "invalid_ids": list(self.invalid_ids),
        }


class PlannerReplayChecker:
    """Cheap candidate-effect screen over identical saved Planner states.

    This screen can reject a candidate that is inert, invalid, or changes the action
    family on successful contrasts. It cannot establish an official-score gain and
    therefore never accepts or promotes a Skill by itself.
    """

    def __init__(
        self,
        executor: PlannerReplayExecutor,
        *,
        min_support_change_ratio: float = 0.5,
        max_contrast_action_change_ratio: float = 0.0,
    ) -> None:
        ratio = float(min_support_change_ratio)
        if not 0.0 < ratio <= 1.0:
            raise ValueError("min_support_change_ratio must be in (0, 1].")
        self.executor = executor
        self.min_support_change_ratio = ratio
        contrast_ratio = float(max_contrast_action_change_ratio)
        if not 0.0 <= contrast_ratio <= 1.0:
            raise ValueError(
                "max_contrast_action_change_ratio must be in [0, 1]."
            )
        self.max_contrast_action_change_ratio = contrast_ratio

    @property
    def identity(self) -> Mapping[str, object]:
        return {
            "type": "planner-replay-checker-v1",
            "min_support_change_ratio": self.min_support_change_ratio,
            "max_contrast_action_change_ratio": (
                self.max_contrast_action_change_ratio
            ),
            "executor": dict(getattr(self.executor, "identity", {})),
        }

    def check(
        self,
        *,
        role: Role,
        parent_skill_set: SkillSet,
        candidate_skill_set: SkillSet,
        evidence: EvidencePacket,
    ) -> PlannerReplayReview:
        case_ids = (*evidence.support_ids, *evidence.contrast_ids)
        parent = self.executor.replay(
            reference_skill_set=parent_skill_set,
            skill_set=parent_skill_set,
            role=role,
            case_ids=case_ids,
        )
        candidate = self.executor.replay(
            reference_skill_set=parent_skill_set,
            skill_set=candidate_skill_set,
            role=role,
            case_ids=case_ids,
        )
        parent_invalid: list[str] = []
        candidate_invalid: list[str] = []
        candidate_only_invalid: list[str] = []
        pairable_support: list[str] = []
        pairable_contrasts: list[str] = []
        support_changed: list[str] = []
        contrast_action_changed: list[str] = []
        for case_id in case_ids:
            parent_steps = tuple(parent.get(case_id, ()))
            candidate_steps = tuple(candidate.get(case_id, ()))
            parent_valid = self._valid_steps(parent_steps)
            candidate_valid = self._valid_steps(candidate_steps)
            if not parent_valid:
                parent_invalid.append(case_id)
            if not candidate_valid:
                candidate_invalid.append(case_id)
            if not parent_valid:
                # A state that the unchanged parent cannot replay is not causal
                # evidence against the candidate. Exclude it from both ratios.
                continue
            if not candidate_valid:
                candidate_only_invalid.append(case_id)
                continue
            if case_id in evidence.support_ids:
                pairable_support.append(case_id)
                if self._decision_fingerprint(
                    parent_steps
                ) != self._decision_fingerprint(candidate_steps):
                    support_changed.append(case_id)
            if case_id in evidence.contrast_ids:
                pairable_contrasts.append(case_id)
                if self._action_fingerprint(
                    parent_steps
                ) != self._action_fingerprint(candidate_steps):
                    contrast_action_changed.append(case_id)

        required_changed = (
            max(
                1,
                int(
                    len(pairable_support) * self.min_support_change_ratio
                    + 0.999999
                ),
            )
            if pairable_support
            else 0
        )
        contrast_change_ratio = (
            len(contrast_action_changed) / len(pairable_contrasts)
            if pairable_contrasts
            else 0.0
        )
        if candidate_only_invalid:
            passed = False
            reason = (
                "Candidate Planner replay produced an invalid or missing decision "
                "where the parent replay was valid."
            )
        elif pairable_support and len(support_changed) < required_changed:
            passed = False
            reason = (
                "Candidate did not change enough support-case decisions to test its "
                "stated behavior."
            )
        elif contrast_change_ratio > self.max_contrast_action_change_ratio:
            passed = False
            reason = (
                "Candidate changed the selected action family on too many successful "
                "contrasts."
            )
        elif not pairable_support:
            passed = True
            reason = (
                "Parent Planner replay was invalid or missing for every support state; "
                "the cheap screen is inconclusive and full rollout is required."
            )
        else:
            passed = True
            reason = (
                "Candidate changed enough pairable support behavior without exceeding "
                "the configured successful-contrast action-change limit; full rollout "
                "is still required."
            )
        return PlannerReplayReview(
            passed=passed,
            reason=reason,
            support_changed_ids=tuple(support_changed),
            contrast_action_changed_ids=tuple(contrast_action_changed),
            parent_invalid_ids=tuple(parent_invalid),
            candidate_invalid_ids=tuple(candidate_invalid),
            invalid_ids=tuple(candidate_only_invalid),
        )

    @staticmethod
    def _valid_steps(steps: Sequence[Mapping[str, object]]) -> bool:
        return bool(steps) and all(
            step.get("status") == "ok"
            and isinstance(step.get("decision"), Mapping)
            for step in steps
        )

    @staticmethod
    def _decision_fingerprint(
        steps: Sequence[Mapping[str, object]],
    ) -> str:
        return hash_json(
            [
                {
                    "action": step["decision"].get("action"),
                    "parameters": step["decision"].get("parameters"),
                }
                for step in steps
            ]
        )

    @staticmethod
    def _action_fingerprint(
        steps: Sequence[Mapping[str, object]],
    ) -> str:
        return hash_json(
            [step["decision"].get("action") for step in steps]
        )


__all__ = [
    "PlannerReplayChecker",
    "PlannerReplayExecutor",
    "PlannerReplayReview",
]
