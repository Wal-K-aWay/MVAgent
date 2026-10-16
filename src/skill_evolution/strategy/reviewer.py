from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from models.llm import LLMClient

from .contracts import Role
from .patcher import PROMPT_ROOT, ROLE_CONTRACTS


REVIEW_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["decision", "reasons"],
    "properties": {
        "decision": {"type": "string", "enum": ["pass", "reject"]},
        "reasons": {"type": "array", "items": {"type": "string"}},
    },
}


@dataclass(frozen=True)
class CandidateReview:
    passed: bool
    reasons: tuple[str, ...] = ()


class PromptCandidateReviewer:
    """Cheap semantic guard before a candidate triggers video rollouts."""

    def __init__(
        self,
        *,
        model: LLMClient,
        prompt_path: str | Path | None = None,
        role_contracts: Mapping[Role, str] | None = None,
    ) -> None:
        self.model = model
        path = Path(prompt_path) if prompt_path else PROMPT_ROOT / "review.md"
        self.template = path.read_text(encoding="utf-8").strip()
        self.role_contracts = dict(
            ROLE_CONTRACTS if role_contracts is None else role_contracts
        )
        if set(self.role_contracts) != set(Role):
            raise ValueError("role_contracts must define exactly global and video.")

    @property
    def identity(self) -> Mapping[str, Any]:
        return {
            "template": self.template,
            "role_contracts": {
                role.value: contract for role, contract in self.role_contracts.items()
            },
            "model": dict(getattr(self.model, "identity", {})),
        }

    def review(
        self,
        *,
        role: Role,
        parent_skill: str,
        candidate_skill: str,
    ) -> CandidateReview:
        replacements = {
            "{{role}}": Role(role).value,
            "{{role_contract}}": self.role_contracts[Role(role)].strip(),
            "{{parent_skill}}": parent_skill.strip() or "None",
            "{{candidate_skill}}": candidate_skill.strip(),
        }
        markers = set(re.findall(r"\{\{[a-z_]+\}\}", self.template))
        unknown = markers - set(replacements)
        if unknown:
            raise ValueError(
                "Unknown placeholder in candidate review Prompt: "
                + ", ".join(sorted(unknown))
            )
        pattern = re.compile("|".join(re.escape(item) for item in replacements))
        prompt = pattern.sub(lambda match: replacements[match.group(0)], self.template)
        result = self.model.json_prompt(
            prompt,
            json_schema=REVIEW_OUTPUT_SCHEMA,
            schema_name="skill_candidate_review",
        )
        if not isinstance(result, Mapping) or result.get("status") != "ok":
            error = result.get("error") if isinstance(result, Mapping) else "invalid result"
            return CandidateReview(False, (f"review model failed: {error}",))
        value = result.get("value")
        if not isinstance(value, Mapping) or set(value) != {"decision", "reasons"}:
            return CandidateReview(False, ("review output did not match its contract",))
        reasons = value.get("reasons")
        if not isinstance(reasons, list):
            return CandidateReview(False, ("review reasons must be an array",))
        normalized = tuple(
            str(item).strip() for item in reasons if str(item).strip()
        )
        passed = value.get("decision") == "pass"
        if not passed and not normalized:
            normalized = ("candidate failed semantic generality review",)
        return CandidateReview(passed, normalized)


__all__ = [
    "CandidateReview",
    "PromptCandidateReviewer",
    "REVIEW_OUTPUT_SCHEMA",
]
