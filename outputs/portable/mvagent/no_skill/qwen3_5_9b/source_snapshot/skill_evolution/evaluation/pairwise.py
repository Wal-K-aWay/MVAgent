from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from models.llm import LLMClient

from ..strategy.contracts import Role, TraceCase, hash_json
from .evaluator import PairwiseJudgment
from .comparison_cases import cases_are_pairable
from ..strategy.patcher import (
    PROMPT_ROOT,
    ROLE_CONTRACTS,
    render_case_value,
    render_trace_case,
)


PAIRWISE_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["comparisons", "reason"],
    "properties": {
        "comparisons": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "sample_number",
                    "local_winner",
                    "lookahead_winner",
                ],
                "properties": {
                    "sample_number": {"type": "integer", "minimum": 1},
                    "local_winner": {
                        "type": "string",
                        "enum": [
                            "candidate_a",
                            "candidate_b",
                            "tie",
                            "invalid",
                        ],
                    },
                    "lookahead_winner": {
                        "type": "string",
                        "enum": [
                            "candidate_a",
                            "candidate_b",
                            "tie",
                            "invalid",
                        ],
                    },
                },
            },
        },
        "reason": {"type": "string"},
    },
}


class PromptPairwiseJudge:
    """Optional role-isolated local/lookahead comparison; invalid is never a win."""

    def __init__(
        self,
        *,
        model: LLMClient,
        prompt_path: str | Path | None = None,
        max_parse_retries: int = 2,
        max_cases: int = 10,
        seed: int = 0,
    ) -> None:
        if max_parse_retries < 0:
            raise ValueError("max_parse_retries must be non-negative.")
        if isinstance(max_cases, bool) or not isinstance(max_cases, int) or max_cases < 1:
            raise ValueError("max_cases must be a positive integer.")
        self.model = model
        path = Path(prompt_path) if prompt_path else PROMPT_ROOT / "pairwise_evaluate.md"
        self.template = path.read_text(encoding="utf-8").strip()
        self.max_parse_retries = int(max_parse_retries)
        self.max_cases = max_cases
        self.seed = int(seed)

    @property
    def identity(self) -> Mapping[str, Any]:
        return {
            "template": self.template,
            "max_parse_retries": self.max_parse_retries,
            "max_cases": self.max_cases,
            "seed": self.seed,
            "model": dict(getattr(self.model, "identity", {})),
        }

    def compare(
        self,
        *,
        role: Role,
        reference_cases: Sequence[TraceCase],
        candidate_cases: Sequence[TraceCase],
    ) -> PairwiseJudgment:
        role = Role(role)
        reference = {case.case_id: case for case in reference_cases if case.role is role}
        candidate = {case.case_id: case for case in candidate_cases if case.role is role}
        matched_ids = tuple(
            case_id
            for case_id in sorted(set(reference) & set(candidate))
            if cases_are_pairable(reference[case_id], candidate[case_id])
        )
        if not matched_ids:
            return PairwiseJudgment()
        matched_ids = tuple(
            sorted(
                matched_ids,
                key=lambda case_id: hash_json(
                    {"seed": self.seed, "case_id": case_id}
                ),
            )[: self.max_cases]
        )
        comparison_hash = hash_json(
            {
                "role": role.value,
                "case_ids": matched_ids,
                "reference": [reference[item].to_dict() for item in matched_ids],
                "candidate": [candidate[item].to_dict() for item in matched_ids],
            }
        )
        candidate_is_a = int(comparison_hash[-1], 16) % 2 == 0
        new_cases = [candidate[item] for item in matched_ids]
        old_cases = [reference[item] for item in matched_ids]
        a_cases, b_cases = (new_cases, old_cases) if candidate_is_a else (old_cases, new_cases)
        prompt = self._render(role, a_cases, b_cases)
        expected = {"comparisons", "reason"}
        for attempt in range(self.max_parse_retries + 1):
            result = self.model.json_prompt(
                prompt,
                json_schema=PAIRWISE_OUTPUT_SCHEMA,
                schema_name="skill_pairwise_evaluation",
            )
            if not isinstance(result, Mapping) or result.get("status") != "ok":
                continue
            raw = result.get("value")
            if not isinstance(raw, Mapping) or set(raw) != expected:
                continue
            raw_comparisons = raw["comparisons"]
            if not isinstance(raw_comparisons, list):
                continue
            parsed: dict[int, tuple[float | None, float | None]] = {}
            valid = True
            for item in raw_comparisons:
                if not isinstance(item, Mapping) or set(item) != {
                    "sample_number",
                    "local_winner",
                    "lookahead_winner",
                }:
                    valid = False
                    break
                sample_number = item["sample_number"]
                if (
                    not isinstance(sample_number, int)
                    or isinstance(sample_number, bool)
                    or sample_number < 1
                    or sample_number > len(matched_ids)
                    or sample_number in parsed
                ):
                    valid = False
                    break
                parsed[sample_number] = (
                    self._preference(str(item["local_winner"]), candidate_is_a),
                    self._preference(
                        str(item["lookahead_winner"]), candidate_is_a
                    ),
                )
            if not valid or set(parsed) != set(range(1, len(matched_ids) + 1)):
                continue
            local = self._aggregate_preference(
                tuple(value[0] for _, value in sorted(parsed.items()))
            )
            lookahead = self._aggregate_preference(
                tuple(value[1] for _, value in sorted(parsed.items()))
            )
            ids = tuple(
                matched_ids[sample_number - 1]
                for sample_number, (local_value, lookahead_value) in sorted(
                    parsed.items()
                )
                if local_value == 1.0 and lookahead_value == -1.0
            )
            return PairwiseJudgment(
                local_preference=local,
                lookahead_preference=lookahead,
                misalignment_ids=ids,
            )
        return PairwiseJudgment()

    def _render(
        self,
        role: Role,
        candidate_a: Sequence[TraceCase],
        candidate_b: Sequence[TraceCase],
    ) -> str:
        comparisons = []
        for index, (case_a, case_b) in enumerate(
            zip(candidate_a, candidate_b, strict=True), 1
        ):
            comparisons.append(
                "\n".join(
                    (
                        f"### Comparison {index}",
                        render_trace_case(
                            case_a,
                            heading="#### Candidate A",
                            include_failure_reason=False,
                        ),
                        "##### First downstream effect",
                        render_case_value(case_a.downstream_effect),
                        "",
                        render_trace_case(
                            case_b,
                            heading="#### Candidate B",
                            include_failure_reason=False,
                        ),
                        "##### First downstream effect",
                        render_case_value(case_b.downstream_effect),
                    )
                )
            )
        replacements = {
            "{{role}}": role.value,
            "{{role_contract}}": ROLE_CONTRACTS[role],
            "{{comparisons}}": "\n\n".join(comparisons),
        }
        pattern = re.compile("|".join(re.escape(marker) for marker in replacements))
        return pattern.sub(lambda match: replacements[match.group(0)], self.template)

    @staticmethod
    def _preference(winner: str, candidate_is_a: bool) -> float | None:
        if winner == "tie":
            return 0.0
        if winner == "invalid":
            return None
        if winner not in {"candidate_a", "candidate_b"}:
            return None
        new_won = (winner == "candidate_a") == candidate_is_a
        return 1.0 if new_won else -1.0

    @staticmethod
    def _aggregate_preference(values: Sequence[float | None]) -> float | None:
        valid = tuple(value for value in values if value is not None)
        if not valid:
            return None
        total = sum(valid)
        if total > 0:
            return 1.0
        if total < 0:
            return -1.0
        return 0.0


__all__ = ["PAIRWISE_OUTPUT_SCHEMA", "PromptPairwiseJudge"]
