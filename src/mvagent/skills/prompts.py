"""Skill prompt text and pure rendering; no loading, retrieval or model calls."""

import re

SYSTEM_TEMPLATE = """# Selection task
Select one highly applicable Skill for the supplied Question or Instruction, or select none.
Candidates provide only a reference number and when_to_use. The target Agent executes the selected strategy; you do not answer the task.

# Selection rules
1. Match the requested task, not just related content. Identify the result to establish and the main operation needed. A Skill is applicable only when the ordinary meaning of its when_to_use directly covers that task. Check whether the declared method addresses the specific relation or judgment the question requires. A card that can collect relevant observations is not automatically a method for interpreting, matching, ordering or evaluating those observations. Do not make a card fit by changing the question or inventing the missing main operation. A short task scope may omit execution details without omitting the task itself.
   Example: locating a matching interval from a supplied reference is not covered by a card that only interprets the meaning of events.
2. Check only conditions essential to that method. The supplied inputs must support its required evidence units, relationships, time scope and references or criteria. A contradiction or an unsupported essential relationship makes the card inapplicable. Do not infer relationships from IDs or durations. Unknown facts to be observed are not missing prerequisites, and conditions the method does not require must not be added.
   Examples: ordering events within a clip does not order the supplied clips; reading a state at one moment does not count events over an interval.
3. Allow semantic and domain generalization without expanding the operation. A short when_to_use need not repeat the question, list incidental scene details, explain execution or guarantee the answer. General methods are applicable when they directly establish the requested facts or comparison, even without a task-specific card.
   Example: a card checking specified observable facts in each video can identify which videos show a requested action across different scene topics.
4. Decide applicability before preference. Consider all candidates under the same criteria, then select the most direct supported fit, at most one. If no card clearly fits, return an empty selected_skill_ids array and let the Agent use its baseline workflow. The closest, highest-ranked or only candidate may still be unsuitable. When selection requires an unsupported essential assumption, prefer none; a speculative choice is less acceptable than missing a possible benefit. Candidate order, count and reference numbers are not evidence of applicability.

# Output contract
Return exactly one JSON object with this single field, matching the supplied Schema:
- selected_skill_ids: an array containing the selected reference, or an empty array.
References are sequential numbers represented as strings in JSON. Copy a reference from the supplied candidates; never generate or renumber it.

Example (if candidate 1 is selected):
{"selected_skill_ids": ["1"]}

Example (select none):
{"selected_skill_ids": []}
"""


def build_selector_system_prompt(role: str) -> str:
    if role not in ("global", "video"):
        raise ValueError(f"Unknown Skill role: {role}")
    return SYSTEM_TEMPLATE


def selection_input(task, state, cards, *, role):
    label = "Question" if role == "global" else "Instruction"
    sections = [f"# Input\n\n## {label}\n{task}"]
    videos = state.get("videos")
    if videos:
        lines = []
        for video_id in videos:
            metadata = videos[video_id] if isinstance(videos, dict) else {}
            duration = metadata.get("duration_sec")
            detail = f": duration {duration} seconds" if duration is not None else ""
            lines.append(f"- {video_id}{detail}")
        sections.append("## Videos\n" + "\n".join(lines))
    candidates = [
        f"## Skill ID: {card.id}\nWhen to use: {card.when_to_use}"
        for card in cards
    ]
    sections.append("# Candidate skills\n\n" + "\n\n".join(candidates))
    return "\n\n".join(sections)


def render_skill_text(text: str, *, minimum_level: int = 3) -> str:
    """Preserve prose/code; rebase ATX headings to H3 or deeper, idempotently."""
    lines = str(text or '').strip().splitlines(keepends=True)
    headings = []
    fence = None
    for index, line in enumerate(lines):
        marker = re.match(r'^ {0,3}(`{3,}|~{3,})(.*)$', line.rstrip('\r\n'))
        if fence:
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence) and not marker[2].strip():
                fence = None
            continue
        if marker:
            fence = marker[1]
            continue
        heading = re.match(r'^( {0,3})(#{1,6})(?=[ \t]|\r?$)', line)
        if heading:
            headings.append((index, heading))
    if fence:
        raise ValueError('Skill has an unclosed code fence; it would consume the outer prompt')
    shift = max(0, minimum_level - min((len(h[2]) for _, h in headings), default=minimum_level))
    for index, heading in headings:
        lines[index] = heading[1] + '#' * min(6, len(heading[2]) + shift) + lines[index][heading.end():]
    return ''.join(lines)
