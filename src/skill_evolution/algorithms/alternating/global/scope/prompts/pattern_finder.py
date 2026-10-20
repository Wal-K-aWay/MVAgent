"""Pattern finder: propose recurring, fixable evidence-gathering problems from Train failures.

Chinese mirror: ../chinese_prompts/pattern_finder.md
"""
from __future__ import annotations

import re

METHOD_TEXT = re.compile(r"\bthe card\b|\bcard should\b|\bshould (?:make|require|replace|trigger|ask|request)\b", re.I)

SYSTEM_PROMPT = """You review trajectories of a multi-video question-answering agent and identify recurring problems in how it gathers evidence that a written strategy could fix. You propose hypotheses; they will be tested by measurement, so report only patterns that several cases clearly share, and report none when the cases do not support one."""

BACKGROUND = """# How the agent works
- A coordinator receives the question, its options, and the list of videos with durations. It cannot view videos. Each step it chooses one action:
  - analyze_videos: sends one self-contained instruction to a separate single-video agent per selected video. That agent sees only its own video and the instruction (not the question, not other videos) and returns a text report.
  - watch_videos: sends one instruction plus one clip from each of two to four videos to a visual model that views them together and returns text. The visual model has a fixed frame budget shared by all selected clips.
  - answer: the coordinator directly submits the final answer in parameters.answer using the question and collected reports.
- A strategy card can be injected into the coordinator's prompt. It can change which action is chosen, how instructions are written, which clips are selected, when to follow up, and when to stop. It cannot change model weights, the single-video agents' abilities, or runtime output contracts.
- A selector decides from the question alone whether to inject a card. Each card has a short when_to_use description that the selector reads; questions that match no card get no card and behave exactly as now."""

DECISION_POINTS = """# Decision points a card can change
1. Per-video instruction wording: neutral, comparable descriptions instead of leading yes/no questions; which visible details each report must contain; keeping the question's qualifiers.
2. Action choice: analyze_videos versus watch_videos; for joint viewing, which videos and what instruction (the visual model must report visible evidence, not pick an answer).
3. Clips and coverage: localize first and then inspect closely; fewer videos per joint view leave more frames for each.
4. Follow-up trigger: when reports do not single out an answer or contradict each other, which candidates to re-check and with what question.
5. When to answer: stop once the evidence separates the candidates.
You may name another decision point if the cases require it; explain it in the description."""

TASK = """# Task
The cases below are a random sample of questions where the coordinator received no card. Most are failures (outcome fail or partial); a few are successes for contrast. Find at most 3 recurring problem patterns.

A pattern must satisfy all of the following:
1. At least 4 failure cases share it.
2. The shared feature is visible in the question and options themselves (what result is requested, what must be compared, counted, ordered or located, how the answer is formed). Describe it without dataset names, topic words or scene content, so that it would apply to new questions of the same kind.
3. The failure can be traced to the coordinator's evidence-gathering decisions (what it asked, which action it chose, a missing follow-up, answering too early), as shown by the steps and reports. Do not use patterns whose failures come mainly from the visual models misperceiving, from missing knowledge, or from the answer format.
4. If successes share the same question feature, use them to check what worked; a pattern contradicted by those successes is weak.

Single cases are noisy: the same agent can fail or succeed on a rerun of an identical question. Do not build a pattern on one striking case. If no pattern meets all conditions, return an empty list and explain why in not_found_reason.

For each pattern give:
- description: the question feature and the faulty evidence-gathering behavior, at most 60 words.
- failure_cases and success_cases: labels from the input.
- decision_point: the number of the decision point (or a short name if it is another one).
- draft_when_to_use: at most 80 words describing only which questions the card is for, using features a reader can see in a new question: the requested result, the main operation, and one short exclusion of a similar-looking question that should not get the card. Do not describe the method, what the card does, or how evidence should be gathered; the strategy is written separately. No dataset names, topic words, task codes or example content.
  Good: 'Questions that give several shuffled clips cut from one continuous recording and ask for their original order as a sequence of clip numbers. Not for questions that order separate, independent videos.'
  Bad (describes the method): 'Use for ordering questions. The card should make each report capture the start and end state.'"""

OUTPUT = """# Output
Return one JSON object with exactly the fields patterns and not_found_reason. not_found_reason is an empty string when at least one pattern is returned."""

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["patterns", "not_found_reason"],
    "properties": {
        "patterns": {
            "type": "array",
            "maxItems": 3,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["description", "failure_cases", "success_cases", "decision_point", "draft_when_to_use"],
                "properties": {
                    "description": {"type": "string", "minLength": 1},
                    "failure_cases": {"type": "array", "items": {"type": "string"}, "minItems": 4},
                    "success_cases": {"type": "array", "items": {"type": "string"}},
                    "decision_point": {"type": "string", "minLength": 1},
                    "draft_when_to_use": {"type": "string", "minLength": 1},
                },
            },
        },
        "not_found_reason": {"type": "string"},
    },
}


def build_user_prompt(cases_text: str, existing_cards: list[str]) -> str:
    catalog = "\n".join(f"- {text}" for text in existing_cards) if existing_cards else "(none)"
    return "\n\n".join([BACKGROUND, DECISION_POINTS, TASK,
                        "# Existing cards (when_to_use); do not duplicate them\n" + catalog,
                        "# Cases\n" + cases_text, OUTPUT])


def count_words(text: str) -> int:
    return len(text.split())


def validate(value: dict, failure_labels: set[str], success_labels: set[str]) -> list[str]:
    """Program checks beyond the Schema; returns a list of problems (empty when valid)."""
    errors = []
    patterns = value["patterns"]
    if not patterns and not value["not_found_reason"].strip():
        errors.append("empty patterns require not_found_reason")
    for i, p in enumerate(patterns, 1):
        bad = [c for c in p["failure_cases"] if c not in failure_labels]
        if bad:
            errors.append(f"pattern {i}: failure_cases not failures in input: {bad}")
        if len(set(p["failure_cases"])) < 4:
            errors.append(f"pattern {i}: fewer than 4 distinct failure cases")
        bad = [c for c in p["success_cases"] if c not in success_labels]
        if bad:
            errors.append(f"pattern {i}: success_cases not successes in input: {bad}")
        if count_words(p["description"]) > 60:
            errors.append(f"pattern {i}: description over 60 words")
        if count_words(p["draft_when_to_use"]) > 80:
            errors.append(f"pattern {i}: draft_when_to_use over 80 words")
        if METHOD_TEXT.search(p["draft_when_to_use"]):
            errors.append(f"pattern {i}: draft_when_to_use describes the method")
    return errors
