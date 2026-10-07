"""Format-robust reading of final answers, reported next to (never instead of) the official scores.

The official scorers only accept an answer written in the requested format, so a model that explains
first and then commits to an answer is scored wrong even when that answer is right. These readers
recover the committed answer under fixed, conservative rules that do not depend on the system being
evaluated (E2E here; the same rules are meant for MVAgent). Nothing is guessed: if an output states
no final answer clearly, nothing is read and the question counts as wrong.
"""

from __future__ import annotations

import re

_TAGS = re.compile(r"<answer>\s*(.*?)\s*</answer>", re.I | re.S)
_DECOR = re.compile(r"[*_`]")


def _clean(text: str) -> str:
    text = str(text or "")
    tagged = _TAGS.findall(text)
    return _DECOR.sub("", tagged[-1] if tagged else text).strip()


def _last(pattern: str, text: str, flags: int = 0) -> re.Match | None:
    matches = list(re.finditer(pattern, text, flags))
    return matches[-1] if matches else None


_STATED = r"(?i:(?:final\s+)?(?:answer|option|choice)s?(?:\s+(?:is|are|would\s+be|should\s+be))?\s*[:=]?\s*(?:option\s+)?)"


def option_labels(options: list[str]) -> str:
    """Option letters as written ("A. ...", "(B) ..."); falls back to A, B, C... by position."""
    labels = []
    for index, option in enumerate(options):
        match = re.match(r"\s*\(?([A-Z])[.):]", str(option))
        labels.append(match.group(1) if match else chr(ord("A") + index))
    return "".join(labels)


def leads_with_choice(text: str, labels: str) -> bool:
    """The output starts with its answer: "C", "C.", "(C)", "C. Video 3" (not "Based on ...")."""
    return bool(re.fullmatch(rf"\s*[\(\[]?[{re.escape(labels)}][\)\]]?(?:[.):]\s*.*)?", str(text), re.S))


def read_choice(text: str, labels: str) -> str | None:
    """One option letter out of `labels` (e.g. "ABCD"); letters must be upper case."""
    text = _clean(text)
    letter = f"[{re.escape(labels)}]"
    # The whole output is the letter, possibly with its option text: "C", "(C)", "C.", "C. Video 3".
    whole = re.fullmatch(rf"[\(\[]?({letter})[\)\]]?(?:[.):]\s*.*)?", text, re.S)
    if whole:
        return whole.group(1)
    stated = _last(rf"{_STATED}[\(\[]?({letter})\b", text)
    if stated:
        return stated.group(1)
    alone = _last(rf"(?m)^\s*[\(\[]?({letter})[\)\]]?\.?\s*$", text)
    return alone.group(1) if alone else None


def read_yes_no(text: str) -> str | None:
    """YES or NO."""
    text = _clean(text)
    whole = re.match(r"(?i)(yes|no)\b", text)
    if whole:
        return whole.group(1).upper()
    stated = _last(rf"{_STATED}(?i:(yes|no))\b", text)
    if stated:
        return stated.group(1).upper()
    alone = _last(r"(?im)^\s*(yes|no)\.?\s*$", text)
    return alone.group(1).upper() if alone else None


def read_letters(text: str, labels: str) -> str | None:
    """A set of option letters (multi-select), returned sorted and joined, e.g. "BCD"."""
    text = _clean(text)
    letter = f"[{re.escape(labels)}]"
    group = rf"[\(\[]?{letter}[\)\]]?(?:\s*(?:,|and|&)?\s*[\(\[]?{letter}[\)\]]?)*"
    whole = re.fullmatch(rf"({group})\.?", text)
    stated = whole or _last(rf"{_STATED}({group})(?![A-Za-z])", text)
    if not stated:
        return None
    return "".join(sorted(set(re.findall(letter, stated.group(1)))))


def read_order(text: str) -> str | None:
    """A segment order such as "2->4->1->3" (the last one stated)."""
    text = _clean(text)
    number = r"(?:segment\s*)?\d+"
    found = _last(rf"(?i){number}(?:\s*(?:->|→)\s*{number})+", text)
    return "->".join(re.findall(r"\d+", found.group(0))) if found else None


def read_interval(text: str) -> str | None:
    """A time interval "start,end" in seconds (the last one stated)."""
    text = _clean(text)
    value = r"(\d+(?:\.\d+)?)"
    whole = re.fullmatch(rf"{value}\s*,\s*{value}", text)
    found = whole or _last(rf"{value}\s*(?:s|sec|seconds)?\s*(?:,|-|–|to)\s*{value}\s*(?:s|sec|seconds)?", text)
    return f"{found.group(1)},{found.group(2)}" if found else None
