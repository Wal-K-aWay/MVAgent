"""Shared text contracts for runtime model outputs (character limits, not tokens)."""

import re


TEXT_LIMITS = {
    "reason": 1200,
    "answer": 2400,
    "instruction": 1600,
    "what": 1600,
    "summary": 3200,
    "text": 2000,
    "uncertainty": 400,
}


# Free-text characters in one analyze action, including its reason.
ANALYZE_TEXT_BUDGET = 4800

def analyze_instruction_limit(request_count: int) -> int:
    return min(TEXT_LIMITS["instruction"],
               (ANALYZE_TEXT_BUDGET - TEXT_LIMITS["reason"]) // request_count)

def text_schema(field: str, *, allow_empty: bool = False) -> dict:
    schema = {"type": "string", "maxLength": TEXT_LIMITS[field]}
    if not allow_empty:
        schema.update(minLength=1, pattern=r"[\s\S]*\S[\s\S]*")
    return schema


def with_text_limits(template: str) -> str:
    """Annotate authored JSON placeholders before inserting question or memory text."""
    def annotate(match: re.Match) -> str:
        field, content = match.group(1), match.group(2)
        nonblank = "; nonblank" if field != "uncertainty" else ""
        return f'"{field}": "<{content}{nonblank}; at most {TEXT_LIMITS[field]} characters>"'

    return re.sub(
        r'"(reason|answer|instruction|what|summary|text|uncertainty)": "<([^>]*)>"',
        annotate,
        template,
    )
