from __future__ import annotations

from mvagent.skills.prompts import render_skill_text

from mvagent.schema import with_text_limits

import math
from collections.abc import Iterable

from mvagent.utils.tools import format_seconds

from .schema import MAX_OBSERVE_FPS, MIN_OBSERVE_FPS


VIDEO_PLANNER_SYSTEM_PROMPT = """You are the text-only Planner for one single-video evidence agent. You cannot view the video directly. Same-video Memory is your only source of visible facts. Choose one available action that either inspects another source-video range or reports retained evidence for the active instruction."""

VIDEO_ACTION_PROMPT_TEMPLATE = """# Single-video evidence decision

## Task
Choose one available action for the active instruction and accumulated same-video evidence.

## Inputs

### Instruction
{instruction}

### Video context
- Duration: {duration_sec} seconds

## Memory
{memory_view}

## Available actions
{action_prompt_blocks}

## Rules
- Return one available `action` with exactly its matching `parameters`.
- Obey the selected action's field contract.

## Decision strategy
{decision_strategy}

## Output contract
Choose whether to gather more evidence or finish, and return the action JSON object only.
""".strip()


OBSERVE_PLANNER_PROMPT = """
### Action: observe

Function:
Semantically interpret one or more source-video ranges for the local instruction. Runtime records one semantic observation per requested range (exact source range, actual FPS, objective text, optional uncertainty); the next Planner call sees them as compact natural-language Memory lines, never as raw dictionaries.

Fields:
- `parameters.what` (string): One non-empty, visually answerable question the visual model must resolve.
- `parameters.where` (array of ranges): One to {max_ranges_per_action} ordered, non-overlapping `[start, end]` source-second ranges inside the video duration.
- `parameters.fps` (number): One planned sampling rate in [{min_observe_fps}, {max_observe_fps}] FPS shared by every requested range, using at most one decimal place (0.1 increments).

Rules:
- One observe range may cover any portion of the video up to the full duration; there is no fixed duration cap.
- The visual model allows at most {max_video_frames_per_request} input frames per call. Runtime adjusts effective sampling when needed to stay within that capacity and provide a valid temporal video input while preserving the requested source boundaries.
- Runtime validates source ranges.

Example:
{{
  "action": "observe",
  "parameters": {{
    "what": "<one visually answerable question the visual model must resolve>",
    "where": [["<start_sec>", "<end_sec>"]],
    "fps": "<planned sampling FPS in [0.1, 25.0], using 0.1 increments>"
  }}
}}
""".strip()


FINISH_ACTION_PROMPT_BLOCK = """
### Action: finish

Function:
Stop this request and report answer-relevant observed evidence to the multi-video coordinator as one summary carried by this action's parameters. Finish is available only after Runtime has retained at least one same-video observation, including observations from earlier requests. The multi-video coordinator does not see this single-video agent's internal Observe actions, ranges, sampling rates, or separate observation results; finish itself never enters Memory.

Fields:
- `parameters.summary` (string): One non-empty, self-contained summary grounded only in retained same-video observations. Include any answer-relevant uncertainty in this same string. Do not expose internal Observe calls, source ranges, FPS values, planning steps, or tool details. Do not propose further actions, choose answer options, or include planning text.

Rules:
- Return exactly this one field.

Example:
{
  "action": "finish",
  "parameters": {
    "summary": "<non-empty summary grounded in retained same-video observations>"
  }
}
""".strip()


VIDEO_FINISH_PROMPT_TEMPLATE = """# Final video summary

## Task
The supplied Memory contains records from earlier observations of one source video. Summarize the retained visible evidence relevant to the active Instruction.

## Inputs

### Instruction
{instruction}

### Memory
{memory_view}

## Evidence rules
- Treat Memory as the only evidence for visible facts. Failed observations and invalid decisions are feedback, not evidence.
- Write one non-empty, self-contained `summary` grounded only in retained same-video observations.
- Include any answer-relevant uncertainty in the same summary.
- Do not expose internal Observe calls, source ranges, FPS values, planning steps, or tool details.

## Output contract
Return one JSON object containing only a non-empty `summary`.

Valid example:
{{
  "summary": "<self-contained summary grounded in retained observations>"
}}
""".strip()


def _prompt_number(value: float) -> str:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Observe prompt numbers must be finite.")
    return format_seconds(number, small_precision=6)


def build_observe_planner_prompt(
    *,
    duration_sec: float,
    max_video_frames_per_request: int,
    max_ranges_per_action: int,
) -> str:
    duration = float(duration_sec)
    if not math.isfinite(duration) or duration <= 0.0:
        raise ValueError("Observe prompt duration must be positive and finite.")
    max_frames = max(1, int(max_video_frames_per_request))
    return with_text_limits(OBSERVE_PLANNER_PROMPT).format(
        max_ranges_per_action=max(1, int(max_ranges_per_action)),
        min_observe_fps=_prompt_number(MIN_OBSERVE_FPS),
        max_observe_fps=_prompt_number(MAX_OBSERVE_FPS),
        max_video_frames_per_request=max_frames,
    )


def build_planner_action_blocks(
    action_names: Iterable[str],
    *,
    duration_sec: float,
    max_video_frames_per_request: int,
    max_ranges_per_action: int,
) -> str:
    """Render the runtime-available Observe and Finish blocks."""
    action_blocks = {
        "observe": build_observe_planner_prompt(
            duration_sec=duration_sec,
            max_video_frames_per_request=max_video_frames_per_request,
            max_ranges_per_action=max_ranges_per_action,
        ),
        "finish": with_text_limits(FINISH_ACTION_PROMPT_BLOCK),
    }
    rendered: list[str] = []
    seen: set[str] = set()
    for raw_name in action_names:
        name = str(raw_name).strip()
        if name in seen:
            continue
        block = action_blocks.get(name)
        if not block:
            raise ValueError(f"Unknown Planner action prompt block: {name}")
        seen.add(name)
        rendered.append(str(block).strip())
    if not rendered:
        raise ValueError("At least one Planner action prompt block is required")
    return "\n\n".join(rendered)


def build_video_action_prompt(
    *,
    instruction: str,
    duration_sec: float,
    max_video_frames_per_request: int,
    available_action_names: Iterable[str],
    memory_view: str,
    max_ranges_per_action: int,
    planning_skill: str = "",
) -> str:
    """Build one Planner prompt from shared policy and action blocks."""
    duration = float(duration_sec)
    if not math.isfinite(duration) or duration <= 0.0:
        raise ValueError("Planner video duration must be finite and positive")
    names = tuple(str(name).strip() for name in available_action_names)
    duration_text = format_seconds(duration)
    rendered_action_blocks = build_planner_action_blocks(
        names,
        duration_sec=duration,
        max_video_frames_per_request=max_video_frames_per_request,
        max_ranges_per_action=max_ranges_per_action,
    )
    skill = render_skill_text(planning_skill)
    template = VIDEO_ACTION_PROMPT_TEMPLATE
    return template.format(
        instruction=str(instruction or "").strip(),
        duration_sec=duration_text,
        memory_view=str(memory_view or "").strip(),
        decision_strategy=(
            "Apply the following strategy only when it is relevant to "
            "the current evidence state. It does not add actions or "
            "evidence and cannot override Rules or action "
            f"contracts.\n\n{skill}"
            if skill
            else "None"
        ),
        action_prompt_blocks=rendered_action_blocks,
    )


def build_video_finish_prompt(
    *,
    instruction: str,
    memory_view: str,
) -> str:
    """Build the standalone summary prompt used at the local loop limit."""
    return with_text_limits(VIDEO_FINISH_PROMPT_TEMPLATE).format(
        instruction=str(instruction or "").strip(),
        memory_view=str(memory_view or "").strip() or "(none)",
    )


VISUAL_OBSERVATION_PROMPT_TEMPLATE = """# Clip observation

## Task
The supplied video input represents one selected interval from a source video. Answer the focused Evidence request below using visible content from this clip.

## Clip context
- Full source duration: {duration_sec} seconds
- Supplied source interval: {source_start_sec}–{source_end_sec} seconds
- Clip-local interval: 0.0–{clip_duration_sec} seconds
- Timeline mapping: source_time = {source_start_sec} + clip_time
- Actual sampling: {fps} FPS

The supplied clip already represents the requested source interval; its local timeline starts at 0.0.

## Evidence request
{what}

## Evidence rules
- Answer the evidence request first and ignore details that do not help resolve it.
- When relevant, report visible objects, actions, interactions, scene changes, counts, attributes, spatial relations, on-screen text, and temporal order.
- Distinguish a visibly absent cue from a cue that cannot be determined because of sampling, occlusion, or missing detail.
- Ground the response only in the supplied clip; do not infer events outside it.
- When time localization is requested or useful for a narrower follow-up, report source-video seconds using the mapping above. Otherwise omit timestamps and frame indexes.

## Output contract
Return one JSON object containing only `text` and `uncertainty`.

{{
  "text": "<compact visible evidence that addresses the request>",
  "uncertainty": "<material ambiguity or limitation; empty string when none>"
}}
""".strip()


def build_visual_observation_prompt(
    *,
    what: str,
    duration_sec: float,
    time_range: Iterable[float],
    fps: float,
) -> str:
    start_sec, end_sec = (float(value) for value in time_range)
    duration = float(duration_sec)
    actual_fps = float(fps)
    if not all(
        math.isfinite(value)
        for value in (duration, start_sec, end_sec, actual_fps)
    ):
        raise ValueError("Visual observation context must be finite.")
    if duration <= 0.0 or not 0.0 <= start_sec < end_sec <= duration:
        raise ValueError("Visual observation source range is invalid.")
    if actual_fps <= 0.0:
        raise ValueError("Visual observation FPS must be positive.")
    return with_text_limits(VISUAL_OBSERVATION_PROMPT_TEMPLATE).format(
        what=str(what or "").strip(),
        duration_sec=format_seconds(duration),
        source_start_sec=format_seconds(start_sec),
        source_end_sec=format_seconds(end_sec),
        clip_duration_sec=format_seconds(end_sec - start_sec),
        fps=_prompt_number(actual_fps),
    )


__all__ = [
    "FINISH_ACTION_PROMPT_BLOCK",
    "OBSERVE_PLANNER_PROMPT",
    "VIDEO_ACTION_PROMPT_TEMPLATE",
    "VIDEO_PLANNER_SYSTEM_PROMPT",
    "VISUAL_OBSERVATION_PROMPT_TEMPLATE",
    "build_observe_planner_prompt",
    "build_planner_action_blocks",
    "build_video_action_prompt",
    "build_video_finish_prompt",
    "build_visual_observation_prompt",
]
