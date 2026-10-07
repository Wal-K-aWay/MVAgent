"""Method writer: turn one problem pattern and its selected Train cases into a card strategy.

Chinese mirror: ../chinese_prompts/method_writer.md
"""
from __future__ import annotations

from .pattern_finder import BACKGROUND, DECISION_POINTS, METHOD_TEXT, count_words

SYSTEM_PROMPT = """You write one strategy card for the coordinator of a multi-video question-answering agent. The card targets one recurring evidence-gathering problem. Its effect will be measured on new questions of the same kind, so it must give concrete, executable decisions that generalize, not advice tailored to the example cases."""

TASK = """# Task
Below are a problem pattern, the when_to_use text that routes questions to the card, and cases that the selector routed to it: failures (outcome fail or partial) and successes, with the coordinator's steps and the reports it received.

Write the strategy the coordinator should follow on these questions so that the failures' evidence-gathering problem is fixed while the successes' working behavior is kept.

Requirements for the strategy:
1. Address the decision point named in the pattern. Say exactly what to do differently: which action, how to word each instruction (what each report must contain), which clips, when to follow up and with what request, when to stop. Prefer one clear default procedure with at most two conditional branches.
2. Stay within the existing actions and their contracts. analyze_videos instructions are sent to agents that do not see the question, so the strategy must tell the coordinator to put the needed criteria into each instruction. watch_videos must ask for visible evidence, never for the final answer.
3. Write for any question that matches when_to_use. Do not mention the example cases, their topics, objects, scenes or answers. Do not introduce fixed numbers (seconds, frame rates, counts) unless they follow from the question itself.
4. Do not include answer-format rules: the final answer is written by a separate answerer that never sees this card.
5. Keep successful behavior that the successes show; do not add steps the evidence does not motivate.
6. Plain English, short numbered steps, usually 150 to 350 words; never more than 600 words. No headings above the steps.

Also return when_to_use: keep the given text unless the cases show it routes clearly different questions; if you change it, it must still only describe which questions the card is for (requested result, main operation, one exclusion), at most 80 words, never the method."""

OUTPUT = """# Output
Return one JSON object with exactly strategy, when_to_use and expected_change (at most 60 words: which behavior should change and why it should help on such questions)."""

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["strategy", "when_to_use", "expected_change"],
    "properties": {
        "strategy": {"type": "string", "minLength": 1},
        "when_to_use": {"type": "string", "minLength": 1},
        "expected_change": {"type": "string", "minLength": 1},
    },
}

MAX_STRATEGY_WORDS = 600


def build_user_prompt(pattern: str, decision_point: str, when_to_use: str, cases_text: str) -> str:
    return "\n\n".join([BACKGROUND, DECISION_POINTS, TASK,
                        f"# Pattern\n{pattern}\nDecision point: {decision_point}",
                        f"# when_to_use\n{when_to_use}",
                        "# Cases routed to this card\n" + cases_text, OUTPUT])


def validate(value: dict) -> list[str]:
    errors = []
    words = count_words(value["strategy"])
    if words > MAX_STRATEGY_WORDS:
        errors.append(f"strategy has {words} words (> {MAX_STRATEGY_WORDS})")
    if count_words(value["when_to_use"]) > 80:
        errors.append("when_to_use over 80 words")
    if METHOD_TEXT.search(value["when_to_use"]):
        errors.append("when_to_use describes the method")
    if "```" in value["strategy"]:
        errors.append("strategy contains a code fence")
    return errors
