"""Optimizer-facing views of public trajectories (standard library only).

A case is a plain dict, produced by an adapter from rollout records:
  question        str, benchmark instruction wrapper already removed where it is generic
  options         list[str]
  durations       list[float] | None, one per video in input order
  steps           list of {"action": "analyze_videos", "requests": [{"video_id", "instruction", "report"}]}
                  or {"action": "watch_videos", "instruction", "clips": [{"video_id", "start", "end"}], "result"}
  final_answer    str
  correct_answer  str
  outcome         "pass" | "partial" | "fail"
Reports are VideoAgent public summaries. No task codes, sample IDs or media paths are rendered.
"""
from __future__ import annotations

import re

SUMMARY_QUESTION_CHARS = 400
SUMMARY_OPTION_CHARS = 60
SUMMARY_INSTRUCTION_CHARS = 150
SUMMARY_REPORT_CHARS = 150
FULL_REPORT_CHARS = 600


def clip(text: str, limit: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def first_sentence(text: str) -> str:
    text = " ".join(str(text or "").split())
    match = re.match(r"(.+?[.!?])(\s|$)", text)
    return match.group(1) if match else text


def _videos_line(case: dict) -> str:
    durations = case.get("durations") or []
    count = len(durations) or len({r["video_id"] for s in case["steps"] for r in s.get("requests", [])})
    if durations:
        return f"Videos: {count} (durations " + ", ".join(f"{d:.0f}s" for d in durations) + ")"
    return f"Videos: {count}" if count else "Videos: unknown"


def _header(case: dict, label: str) -> list[str]:
    return [f"### {label} ({case['outcome']})"]


def _analyze_lines(step: dict, n: int, instr_limit: int | None, report: callable) -> list[str]:
    requests = step["requests"]
    ids = ", ".join(r["video_id"] for r in requests)
    instructions = {r["instruction"] for r in requests}
    lines = []
    if len(instructions) == 1:
        text = requests[0]["instruction"]
        text = clip(text, instr_limit) if instr_limit else " ".join(text.split())
        lines.append(f'Step {n} analyze_videos [{ids}], same instruction: "{text}"')
        for r in requests:
            lines.append(f"  {r['video_id']} report: {report(r['report'])}")
    else:
        lines.append(f"Step {n} analyze_videos [{ids}]")
        for r in requests:
            text = clip(r["instruction"], instr_limit) if instr_limit else " ".join(r["instruction"].split())
            lines.append(f'  {r["video_id"]} instruction: "{text}"')
            lines.append(f"  {r['video_id']} report: {report(r['report'])}")
    return lines


def _watch_lines(step: dict, n: int, instr_limit: int | None, report: callable) -> list[str]:
    clips = ", ".join(f"{c['video_id']}[{c['start']:.0f}-{c['end']:.0f}s]" for c in step["clips"])
    text = clip(step["instruction"], instr_limit) if instr_limit else " ".join(step["instruction"].split())
    return [f'Step {n} watch_videos {clips}: "{text}"', f"  result: {report(step['result'])}"]


def _body(case: dict, *, question_limit, option_limit, instr_limit, report) -> list[str]:
    question = clip(case["question"], question_limit) if question_limit else case["question"].strip()
    lines = [f"Question: {question}"]
    if case.get("options"):
        opts = [clip(o, option_limit) if option_limit else o for o in case["options"]]
        lines.append("Options: " + " | ".join(opts))
    lines.append(_videos_line(case))
    for n, step in enumerate(case["steps"], 1):
        if step["action"] == "analyze_videos":
            lines += _analyze_lines(step, n, instr_limit, report)
        elif step["action"] == "watch_videos":
            lines += _watch_lines(step, n, instr_limit, report)
    if not case["steps"]:
        lines.append("No evidence action before answering.")
    lines.append(f"Final answer: {clip(case['final_answer'], 200)} | Correct answer: {clip(case['correct_answer'], 200)}")
    return lines


def render_summary(case: dict, label: str) -> str:
    """Compact view for scanning many cases: truncated question, instructions and first report sentences."""
    report = lambda text: clip(first_sentence(text), SUMMARY_REPORT_CHARS) or "(empty)"
    return "\n".join(_header(case, label) + _body(case, question_limit=SUMMARY_QUESTION_CHARS,
                                                    option_limit=SUMMARY_OPTION_CHARS,
                                                    instr_limit=SUMMARY_INSTRUCTION_CHARS, report=report))


def render_full(case: dict, label: str) -> str:
    """Detailed view: full question and instructions, reports up to FULL_REPORT_CHARS."""
    report = lambda text: clip(text, FULL_REPORT_CHARS) or "(empty)"
    return "\n".join(_header(case, label) + _body(case, question_limit=None, option_limit=None,
                                                    instr_limit=None, report=report))


def render_cases(cases: list[dict], labels: list[str], *, full: bool, max_chars: int) -> tuple[str, list[str]]:
    """Render whole cases in order until max_chars; return text and the labels that were dropped."""
    parts, used, dropped = [], 0, []
    for case, label in zip(cases, labels):
        block = (render_full if full else render_summary)(case, label)
        if used + len(block) + 2 > max_chars:
            dropped.append(label)
            continue
        parts.append(block)
        used += len(block) + 2
    return "\n\n".join(parts), dropped
