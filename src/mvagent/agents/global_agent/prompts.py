from __future__ import annotations

from mvagent.skills.prompts import render_skill_text

from mvagent.schema import with_text_limits, ANALYZE_TEXT_BUDGET, TEXT_LIMITS

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from mvagent.utils.tools import format_seconds

from .schema import available_global_action_names


GLOBAL_AGENT_SYSTEM_PROMPT = """You coordinate the task by choosing actions that turn observations into a supported judgment.

- Preserve the task's definitions, constraints, identifiers, and required output. Use available evidence; separate observations, inferences, and unknowns. Missing information is not evidence of absence.
- Check conflicting evidence before concluding. When observations or reports disagree with each other or leave the required judgment unsupported, use an available observation to verify the specific point. A completed analysis may still be incomplete or mistaken; confidence in a report does not resolve a contradiction.
- Each check must address a named uncertainty. If it adds no information, change the focus rather than repeat it. Finish when the judgment is supported or further checks cannot add useful information, retaining material uncertainty.
- Keep each explanation to one or two short sentences: the decisive evidence or unresolved point and the purpose of the next action. State the conflict once, then take the action. Do not rehearse alternatives, guess what the task intended, or invent missing facts.
- Return the complete required response.
""".strip()

GLOBAL_DECISION_PROMPT_TEMPLATE = """# Multi-video evidence decision

## Task
Coordinate the complete question across videos and choose one available action that either obtains missing evidence or returns the answer.

## Inputs

### Question
{question}

### Videos
{videos}

## Available actions
{action_prompt_blocks}

## History
{action_history}

## Rules
- Single-video agents' Observe actions and intermediate visual results are private. Use only facts stated in public summaries and completed joint-watch results.
- Return one decision with a concise evidence-based `reason`, one available `action`, and exactly that action's `parameters`.
- Treat `reason` as a brief decision basis, not an open-ended reasoning transcript.
- Treat the IDs in Videos as an exact allow-list. Copy each `video_id` exactly; do not use an unlisted ID or a positional or semantic alias such as `first`, `middle`, or `reference`.
- Within one `analyze_videos` or `watch_videos` action, each listed video ID may appear at most once.
- Use the durations in Videos when choosing source ranges.

## Decision strategy
{decision_strategy}

## Output contract
Choose the next action and return its JSON object only.
""".strip()


ANSWER_ACTION_PROMPT_BLOCK = """
### Action: answer

Function:
Return the final answer directly from the question and accumulated History.

Fields:
- `reason`: Give a concise evidence-based explanation, including any material uncertainty.
- `parameters.answer`: The requested answer representation, as a non-empty string.

Rules:
- Choose answer when the judgment is supported or further checks cannot add useful information.
- Once answering, submit the best-supported judgment; do not replace the requested result with a discussion of missing evidence.
- Infer the answer representation from the complete question. When options are present, use only the selected option label or explicitly requested option text in `parameters.answer`.

Example:
{{
  "reason": "<brief basis for this answer>",
  "action": "answer",
  "parameters": {{"answer": "<the requested answer representation>"}}
}}
""".strip()


ANALYZE_VIDEOS_ACTION_PROMPT_BLOCK = """
### Action: analyze_videos

Function:
Ask one or more selected single-video agents to analyze their own videos separately. Each analysis is executed only on its selected video and must be independently understandable from its instruction.

Fields:
- `reason`: Give a brief basis for using separate per-video analysis.
- `parameters.videoagent_request`: Return one or more objects containing one existing `video_id` and one non-empty local `instruction`.

Rules:
- Each `video_id` must be copied exactly from the IDs listed under Videos. Never use an unlisted alias or position label, and never request the same video ID more than once in one `analyze_videos` action.
- The selected single-video agents run separately. They never watch multiple videos together and cannot perform joint cross-video visual comparison.
- Each single-video agent sees only its own video and local instruction; it does not receive the complete question, Global History, other videos, or sibling analyses and results.
- Every local instruction must be self-contained and answerable from the selected video alone.
- Every requested output must be visually observable in the selected video. Ask for underlying visible mechanics or attributes, not an external category-to-score table, a standard difficulty value that is not displayed, a cross-video mapping, or a computed answer.
- Across this action, reserve at most {analyze_instruction_budget} characters for all instructions. For N requested videos, each instruction must also stay within floor({analyze_instruction_budget} / N) characters.
- Analyses emitted in one decision are knowledge-independent: no single-video agent can see another analysis or use a sibling result from the same batch.

Example:
{{
  "reason": "<brief basis for using separate video analysis>",
  "action": "analyze_videos",
  "parameters": {{
    "videoagent_request": [
      {{
        "video_id": "<one existing video ID>",
        "instruction": "<one self-contained, visually answerable instruction for that video>"
      }}
    ]
  }}
}}
""".strip()


WATCH_VIDEOS_ACTION_PROMPT_BLOCK = """
### Action: watch_videos

Function:
Select clips from multiple (>1) input videos and observe them jointly when detailed visual information must be compared.

Fields:
- `reason`: State why the required cross-video visual relationship must be watched jointly rather than analyzed separately.
- `parameters.instruction`: Give one self-contained visual-analysis instruction. This exact string is the only text prompt sent to the visual model, so name the selected videos by ID, state exactly which visible relationship, difference, correspondence, phase, motion, appearance, or spatial detail to analyze, and request the desired concise natural-language analysis directly.
- `parameters.videos`: Return at least two video selections. Each selection contains one input-owned `video_id` and exactly one `clip` in `[start_sec, end_sec]` form.

Rules:
- Select more than one distinct input video, but no more than the number listed under Videos or {max_videos_per_watch}, whichever is smaller.
- Every `video_id` must be copied exactly from the IDs listed under Videos; never invent, rename, or infer a video ID.
- Every selected clip is supplied to the same visual-model call. Select each video ID at most once and never return more than one clip for a video.
- Each clip must provide complete start and end seconds inside its source video's duration.
- The number of selected videos must not exceed the visual model's limit of {max_video_inputs_per_request} video inputs.
- Runtime chooses sampling automatically; never include `fps` in this action's parameters. With fixed visual input capacity, longer total selected duration can reveal more of the overall sequence, but makes observation sparser and increases the risk of missing brief or fine-grained details.
- The visual model returns one unstructured natural-language string as evidence for the next multi-video decision. Do not ask it to choose the final answer.

Example:
{{
  "reason": "<brief basis for joint video analysis>",
  "action": "watch_videos",
  "parameters": {{
    "instruction": "<one self-contained visual-analysis instruction naming the selected video IDs and the exact relationship to compare>",
    "videos": [
      {{
        "video_id": "<one selected video ID>",
        "clip": ["<start_sec>", "<end_sec>"]
      }},
      {{
        "video_id": "<another selected video ID>",
        "clip": ["<start_sec>", "<end_sec>"]
      }}
    ]
  }}
}}
""".strip()


GLOBAL_ACTION_PROMPT_BLOCKS = {
    "answer": ANSWER_ACTION_PROMPT_BLOCK,
    "analyze_videos": ANALYZE_VIDEOS_ACTION_PROMPT_BLOCK,
    "watch_videos": WATCH_VIDEOS_ACTION_PROMPT_BLOCK,
}


def _render_videos(
    videos: Sequence[str] | Mapping[str, Mapping[str, Any]],
) -> tuple[list[str], str]:
    """Return normalized identities and their stable prompt view."""
    if isinstance(videos, Mapping):
        video_ids = [str(video_id) for video_id in videos]
        rendered = "\n".join(
            f"- ID: `{video_id}`; "
            f"Duration: {format_seconds(metadata.get('duration_sec') or 0.0)} seconds"
            for video_id, metadata in videos.items()
        )
    else:
        video_ids = [str(video_id) for video_id in videos]
        rendered = "\n".join(
            f"- ID: `{video_id}`; Duration: unavailable"
            for video_id in video_ids
        )
    if not video_ids:
        raise ValueError("GlobalAgent prompt requires at least one video identity")
    return video_ids, rendered


def build_global_action_prompt_blocks(
    action_names: Iterable[str],
    *,
    max_videos_per_watch: int,
    max_video_inputs_per_request: int,
) -> str:
    """Render GlobalAgent action blocks in stable caller order."""
    rendered_blocks: list[str] = []
    seen: set[str] = set()
    for raw_name in action_names:
        name = str(raw_name).strip()
        if name in seen:
            continue
        try:
            template = GLOBAL_ACTION_PROMPT_BLOCKS[name]
        except KeyError as exc:
            raise ValueError(
                f"Unknown GlobalAgent action prompt block: {name}"
            ) from exc
        seen.add(name)
        rendered_blocks.append(
            with_text_limits(template, unbounded_fields=("reason",) if name == "answer" else ()).format(
                analyze_instruction_budget=ANALYZE_TEXT_BUDGET - TEXT_LIMITS["reason"],
                max_videos_per_watch=max(
                    1,
                    int(max_videos_per_watch),
                ),
                max_video_inputs_per_request=max(
                    1,
                    int(max_video_inputs_per_request),
                ),
            )
        )
    if not rendered_blocks:
        raise ValueError("At least one GlobalAgent action prompt block is required")
    return "\n\n".join(rendered_blocks)


def build_global_decision_prompt(
    *,
    question: str,
    videos: Sequence[str] | Mapping[str, Mapping[str, Any]],
    action_history_view: str,
    available_action_names: Iterable[str] | None = None,
    watch_videos_available: bool = False,
    max_videos_per_watch: int = 4,
    max_video_inputs_per_request: int = 1,
    decision_skill: str = "",
) -> str:
    """Build one decision prompt containing only available action blocks."""
    normalized_video_ids, rendered_videos = _render_videos(videos)
    rendered_action_history = (
        str(action_history_view or "").strip() or "(none)"
    )
    if available_action_names is None:
        action_names = available_global_action_names(
            watch_videos_available=watch_videos_available,
        )
    else:
        action_names = tuple(
            dict.fromkeys(
                str(action_name).strip()
                for action_name in available_action_names
                if str(action_name).strip()
            )
        )
    if "watch_videos" in action_names and len(normalized_video_ids) < 2:
        raise ValueError(
            "watch_videos requires at least two video identities"
        )

    action_prompt_blocks = build_global_action_prompt_blocks(
        action_names,
        max_videos_per_watch=max_videos_per_watch,
        max_video_inputs_per_request=max_video_inputs_per_request,
    )

    skill = render_skill_text(decision_skill)
    return GLOBAL_DECISION_PROMPT_TEMPLATE.format(
        question=question,
        videos=rendered_videos,
        action_history=rendered_action_history,
        decision_strategy=(
            "No further evidence collection is available. Submit the best-supported final answer now.\n\n"
            if action_names == ("answer",) else ""
        ) + (
            "Apply the following strategy only when it is relevant to "
            "the current evidence state. It does not add actions or "
            "evidence and cannot override Rules or action "
            f"contracts.\n\n{skill}"
            if skill
            else "None"
        ),
        action_prompt_blocks=action_prompt_blocks,
    )


__all__ = [
    "ANSWER_ACTION_PROMPT_BLOCK",
    "GLOBAL_ACTION_PROMPT_BLOCKS",
    "GLOBAL_AGENT_SYSTEM_PROMPT",
    "GLOBAL_DECISION_PROMPT_TEMPLATE",
    "ANALYZE_VIDEOS_ACTION_PROMPT_BLOCK",
    "WATCH_VIDEOS_ACTION_PROMPT_BLOCK",
    "build_global_action_prompt_blocks",
    "build_global_decision_prompt",
]
