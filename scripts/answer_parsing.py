"""Compatibility answer parsing for historical direct-run artifacts.

Official benchmark evaluation must use the pinned upstream repositories under
``eval/e2e_eval``.  This helper remains only for the older compatibility runner and is
not an official scorer.
"""

from __future__ import annotations

import re
from typing import Any, Iterable


def strip_answer_tags(text: str) -> str:
    value = str(text or "").strip()
    match = re.search(
        r"<answer>\s*(.*?)\s*</answer>",
        value,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if match:
        return match.group(1).strip()
    return value


def option_labels(options: Iterable[str]) -> list[str]:
    labels: list[str] = []
    for index, option in enumerate(options):
        match = re.match(
            r"\s*([A-Z])[\.\)]",
            str(option).strip(),
            flags=re.IGNORECASE,
        )
        labels.append(match.group(1).upper() if match else chr(ord("A") + index))
    return labels


def extract_final_choice_with_method(
    value: Any,
    options: Iterable[str] = (),
) -> tuple[str, str]:
    """Extract a final option for legacy compatibility-run diagnostics."""

    text = strip_answer_tags(str(value or "")).strip()
    labels = option_labels(options) or list("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
    allowed = "".join(re.escape(label) for label in labels)

    direct = re.fullmatch(
        rf"\s*(?:\*\*)?\(?([{allowed}])\)?(?:\*\*)?\s*[.!]?\s*",
        text,
        flags=re.IGNORECASE,
    )
    if direct:
        return direct.group(1).upper(), "direct"

    candidates: list[tuple[int, str, str]] = []
    patterns = (
        (
            "json_answer",
            rf'''(?i)["'](?:final_?)?answer["']\s*:\s*["']?([{allowed}])["']?''',
        ),
        (
            "explicit_answer",
            rf"(?i)(?:final\s+)?(?:answer|option|choice)\s*(?:is\s*)?"
            rf"(?::|=)?\s*(?:option\s*)?(?:\*\*)?\(?([{allowed}])\b"
            rf"\)?(?:\*\*)?",
        ),
    )
    for method, pattern in patterns:
        for match in re.finditer(pattern, text):
            candidates.append((match.start(), match.group(1).upper(), method))

    for match in re.finditer(
        rf"(?im)^\s*(?:\*\*)?\(?([{allowed}])\)?(?:\*\*)?\s*[.!]?\s*$",
        text,
    ):
        candidates.append((match.start(), match.group(1).upper(), "standalone_line"))

    if candidates:
        _, prediction, method = max(candidates, key=lambda item: item[0])
        return prediction, method

    trailing = re.search(
        rf"(?im)^\s*(?:\*\*)?\(?([{allowed}])\)?(?:\*\*)?\s*[.)]\s+[^\n]+\s*\Z",
        text,
    )
    if trailing:
        return trailing.group(1).upper(), "trailing_labeled_line"

    leading = re.match(
        rf"(?i)^\s*(?:\*\*)?\(?([{allowed}])\)?(?:\*\*)?\s*[.)]\s+",
        text,
    )
    if leading:
        return leading.group(1).upper(), "leading_label"
    return "", "unparsed"

