from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from models.llm import LLMClient
from mvagent.agents.global_agent.prompts import build_global_action_prompt_blocks
from mvagent.agents.video_agent.prompts import build_planner_action_blocks

from .contracts import (
    EditOp,
    Role,
    SkillDiagnosis,
    SkillEdit,
    SkillUpdateProposal,
    SkillUpdateRequest,
    TraceCase,
)


PROMPT_ROOT = Path(__file__).resolve().parents[1] / "prompts"

ROLE_CONTRACTS = {
    Role.GLOBAL: """The Global Planner is text-only. It sees the complete question,
exact video IDs and durations, and public History. It never sees a VideoAgent's private
Observe calls or intermediate observations. It may choose `analyze_videos`,
`watch_videos` when available, or `answer`. `analyze_videos` sends independent
self-contained instructions to selected single-video agents. `watch_videos` selects at
least two distinct video clips for one joint visual comparison. `answer` returns the
final response. Its strategy can improve action choice, video/clip selection,
single-video instructions, use of returned evidence, and answer timing. Available
actions and their parameter schemas are fixed by Runtime. Decisions repeat across
ordinary rounds and each completed action result enters public History, so a later
decision may refine an earlier call; no remaining-step count is visible.""",
    Role.VIDEO: """The Video Planner is text-only and owns one video. It sees one local
instruction, source duration, and chronological same-video Memory. It does not see the
complete question, sibling videos, Global History, or the visual clip directly. It may
choose `observe` with one focused visual question, ordered source ranges, and one FPS,
then may choose `finish` with a grounded summary after usable evidence exists. Available
actions, parameter validation, Observer execution, and summary publication are fixed by
Runtime. Its strategy can improve WHAT/range/FPS selection, broad-to-focused search,
use of retained Memory, re-observation after weak evidence, and Finish timing. Decisions
repeat across ordinary rounds and each usable Observe enters Memory, so a later decision
may refine an earlier call; no remaining-step count is visible.""",
}


def build_system_architecture(
    *,
    max_videos_per_watch: int = 4,
    max_video_inputs_per_request: int = 8,
    max_video_frames_per_request: int = 512,
    max_ranges_per_action: int = 8,
) -> str:
    """Render the optimizer's immutable view of the online decision system."""

    global_actions = build_global_action_prompt_blocks(
        ("answer", "analyze_videos", "watch_videos"),
        max_videos_per_watch=max_videos_per_watch,
        max_video_inputs_per_request=max_video_inputs_per_request,
    )
    video_actions = build_planner_action_blocks(
        ("observe", "finish"),
        duration_sec=1.0,
        max_video_frames_per_request=max_video_frames_per_request,
        max_ranges_per_action=max_ranges_per_action,
    )
    return f"""MVAgent answers one multi-video question through two nested text-Planner loops.

### Multi-video coordinator
The coordinator sees the complete question, the exact video IDs and durations, and
public History. It cannot directly see videos or a single-video agent's private Observe
calls. Each completed `analyze_videos` result publishes only the corresponding local
instruction and summary; each successful `watch_videos` call publishes its joint visual
result. A later coordinator round may use this History to refine an earlier request or
answer. No remaining-step count is visible to the Planner.

{global_actions}

### Single-video evidence agent
One question-scoped single-video agent exists per input video. Its Planner sees only one
local instruction, that video's duration, and chronological same-video Memory. It does
not see the complete question, sibling videos, coordinator History, or visual pixels.
Each successful `observe` result enters private Memory, so a later local step or later
request for the same video may refine earlier evidence. `finish` publishes one summary
to the coordinator; private Memory is never published. No remaining-step count is
visible to the Planner.

{video_actions}

### Execution and optimization boundary
The coordinator's `analyze_videos` action starts independent single-video runs; their
summaries return to public History before the next coordinator decision.
`watch_videos`, Observer calls inside `observe`, terminal answer generation, and terminal
video summarization are executed by fixed action-internal prompts. If an ordinary loop
reaches its configured limit, Runtime invokes the corresponding standalone finalizer.
The SkillSet may change only the two Planners' Decision strategy text. It cannot add an
action, alter a schema or validator, change action-internal prompts, create new evidence,
    or make a Planner use information absent from its Runtime-visible state.""".strip()


def build_role_architectures(
    *,
    max_videos_per_watch: int = 4,
    max_video_inputs_per_request: int = 8,
    max_video_frames_per_request: int = 512,
    max_ranges_per_action: int = 8,
) -> dict[Role, str]:
    """Render each target Planner's fixed contract for the Patch stage."""

    return {
        Role.GLOBAL: (
            ROLE_CONTRACTS[Role.GLOBAL]
            + "\n\n### Available actions\n"
            + build_global_action_prompt_blocks(
                ("answer", "analyze_videos", "watch_videos"),
                max_videos_per_watch=max_videos_per_watch,
                max_video_inputs_per_request=max_video_inputs_per_request,
            )
        ),
        Role.VIDEO: (
            ROLE_CONTRACTS[Role.VIDEO]
            + "\n\n### Available actions\n"
            + build_planner_action_blocks(
                ("observe", "finish"),
                duration_sec=1.0,
                max_video_frames_per_request=max_video_frames_per_request,
                max_ranges_per_action=max_ranges_per_action,
            )
        ),
    }


UPDATE_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["diagnosis", "edits"],
    "properties": {
        "diagnosis": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "failure_source",
                "target_role",
                "pattern",
                "causal_evidence",
                "regression_risk",
                "expected_behavior_change",
            ],
            "properties": {
                "failure_source": {
                    "type": "string",
                    "enum": [
                        "global",
                        "video",
                        "action_internal",
                        "joint",
                        "unattributed",
                    ],
                },
                "target_role": {
                    "type": "string",
                    "enum": ["global", "video", "none"],
                },
                "pattern": {"type": "string"},
                "causal_evidence": {"type": "string"},
                "regression_risk": {"type": "string"},
                "expected_behavior_change": {"type": "string"},
            },
        },
        "edits": {
            "type": "array",
            "maxItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["role", "op", "target", "content"],
                "properties": {
                    "role": {"type": "string", "enum": ["global", "video"]},
                    "op": {"type": "string", "enum": [op.value for op in EditOp]},
                    "target": {"type": "string"},
                    "content": {
                        "type": "string",
                        "description": (
                            "Concise cross-task Markdown policy. An append to an empty "
                            "parent starts with a ### heading. Do not include "
                            "case-specific details."
                        ),
                    },
                },
            },
        },
    },
}


def _decode_case_value(value: str) -> object:
    """Decode projected JSON fields for readable Prompt rendering."""

    text = str(value or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return text


def _field_label(value: object) -> str:
    text = str(value or "").replace("_", " ").strip()
    label = text[:1].upper() + text[1:] if text else "Value"
    return re.sub(
        r"\b(id|fps)\b",
        lambda match: match.group(1).upper(),
        label,
        flags=re.IGNORECASE,
    )


def _scalar_text(value: object) -> str:
    if value is None or value == "":
        return "None"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return str(value)


def _list_item_heading(value: Mapping[str, Any], index: int) -> tuple[str, str | None]:
    for key, label in (
        ("round", "Round"),
        ("step", "Step"),
        ("cluster", "Cluster"),
        ("video_id", "Video"),
    ):
        if key in value:
            return f"{label} {_scalar_text(value[key])}", key
    return f"Item {index}", None


def _render_case_value(value: object, *, depth: int = 0) -> str:
    """Render nested case data as compact Markdown rather than JSON syntax."""

    if isinstance(value, str) and value.strip().startswith(("{", "[")):
        decoded = _decode_case_value(value)
        if not isinstance(decoded, str):
            value = decoded
    indent = "  " * depth
    if isinstance(value, Mapping):
        if not value:
            return f"{indent}- None"
        lines: list[str] = []
        for key, item in value.items():
            label = _field_label(key)
            if isinstance(item, Mapping) or (
                isinstance(item, Sequence) and not isinstance(item, (str, bytes))
            ):
                lines.append(f"{indent}- {label}:")
                lines.append(_render_case_value(item, depth=depth + 1))
                continue
            rendered = _scalar_text(item)
            if "\n" not in rendered:
                lines.append(f"{indent}- {label}: {rendered}")
                continue
            lines.append(f"{indent}- {label}:")
            lines.extend(f"{indent}  {line}" for line in rendered.splitlines())
        return "\n".join(lines)

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        if not value:
            return f"{indent}- None"
        if all(
            not isinstance(item, Mapping)
            and not (
                isinstance(item, Sequence) and not isinstance(item, (str, bytes))
            )
            for item in value
        ):
            return f"{indent}- " + "; ".join(_scalar_text(item) for item in value)
        lines = []
        for index, item in enumerate(value, 1):
            if isinstance(item, Mapping):
                heading, consumed_key = _list_item_heading(item, index)
                lines.append(f"{indent}- {heading}:")
                remaining = {
                    str(key): nested
                    for key, nested in item.items()
                    if key != consumed_key
                }
                lines.append(_render_case_value(remaining, depth=depth + 1))
            elif isinstance(item, Sequence) and not isinstance(item, (str, bytes)) and all(
                not isinstance(nested, Mapping)
                and not (
                    isinstance(nested, Sequence)
                    and not isinstance(nested, (str, bytes))
                )
                for nested in item
            ):
                lines.append(
                    f"{indent}- Item {index}: "
                    + "; ".join(_scalar_text(nested) for nested in item)
                )
            else:
                lines.append(f"{indent}- Item {index}:")
                lines.append(_render_case_value(item, depth=depth + 1))
        return "\n".join(lines)

    rendered = _scalar_text(value)
    if "\n" not in rendered:
        return f"{indent}{rendered}"
    return "\n".join(f"{indent}{line}" for line in rendered.splitlines())


def render_case_value(value: object) -> str:
    """Render one projected value as ordinary Markdown for model-facing Prompts."""

    if isinstance(value, str):
        value = _decode_case_value(value)
    return _render_case_value(value)


def _inline_text(value: object) -> str:
    """Render one trajectory field on a single readable line."""

    return " ".join(str(value or "").split()) or "None"


def _format_ranges(value: object) -> str:
    ranges = _decode_case_value(value) if isinstance(value, str) else value
    if not isinstance(ranges, Sequence) or isinstance(ranges, (str, bytes)):
        return _scalar_text(ranges)
    rendered: list[str] = []
    for item in ranges:
        if (
            isinstance(item, Sequence)
            and not isinstance(item, (str, bytes))
            and len(item) == 2
        ):
            rendered.append(f"{_scalar_text(item[0])}–{_scalar_text(item[1])} seconds")
        else:
            rendered.append(_scalar_text(item))
    return "; ".join(rendered) or "None"


def _compact_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(", ", ": "))


def _render_action(
    decision: Mapping[str, Any],
    *,
    answer_reason: object = None,
    fallback_answer: object = None,
) -> str:
    """Render an action name followed by one compact parameter object."""

    action = str(decision.get("action") or "unknown")
    parameters = decision.get("parameters")
    parameters = parameters if isinstance(parameters, Mapping) else {}

    if action == "analyze_videos":
        requests = parameters.get("videoagent_request")
        rendered: dict[str, dict[str, str]] = {}
        if isinstance(requests, Sequence) and not isinstance(requests, (str, bytes)):
            for item in requests:
                if isinstance(item, Mapping):
                    rendered[_inline_text(item.get("video_id"))] = {
                        "instruction": _inline_text(item.get("instruction"))
                    }
        return f"analyze_videos {_compact_json(rendered)}"

    if action == "watch_videos":
        clips: dict[str, object] = {}
        videos = parameters.get("videos")
        if isinstance(videos, Sequence) and not isinstance(videos, (str, bytes)):
            for item in videos:
                if isinstance(item, Mapping):
                    clips[_inline_text(item.get("video_id"))] = item.get("clip")
        return "watch_videos " + _compact_json(
            {
                "instruction": _inline_text(parameters.get("instruction")),
                "clips": clips,
            }
        )

    if action == "observe":
        return "observe " + _compact_json(
            {
                "what": _inline_text(parameters.get("what")),
                "where": parameters.get("where"),
                "fps": parameters.get("fps"),
            }
        )

    if action == "answer":
        answer = parameters.get("answer")
        if answer in (None, ""):
            answer = fallback_answer
        payload = {"answer": _inline_text(answer)}
        if answer_reason not in (None, ""):
            payload["reason"] = _inline_text(answer_reason)
        return f"answer {_compact_json(payload)}"

    if action == "finish":
        return "finish"

    return f"{action} {_compact_json(dict(parameters))}" if parameters else action


def _render_observation_result(value: object) -> str:
    """Render Observe evidence without repeating range/FPS action parameters."""

    if isinstance(value, Mapping):
        observations = value.get("observations")
        if isinstance(observations, Sequence) and not isinstance(
            observations, (str, bytes)
        ):
            rendered: list[str] = []
            for item in observations:
                if not isinstance(item, Mapping):
                    if str(item or "").strip():
                        rendered.append(_inline_text(item))
                    continue
                text = _inline_text(item.get("text"))
                uncertainty = _inline_text(item.get("uncertainty"))
                if uncertainty != "None":
                    text += f" Uncertainty: {uncertainty}"
                rendered.append(text)
            errors = value.get("errors")
            if isinstance(errors, Sequence) and not isinstance(errors, (str, bytes)):
                rendered.extend(
                    f"Error: {_inline_text(error)}" for error in errors if error
                )
            if value.get("error"):
                rendered.append(f"Error: {_inline_text(value['error'])}")
            return " | ".join(rendered) or "None"
    return _render_result(value)


def _render_result(value: object) -> str:
    """Render semantic evidence or errors, excluding execution bookkeeping."""

    if isinstance(value, str) and value.strip().startswith(("{", "[")):
        decoded = _decode_case_value(value)
        if not isinstance(decoded, str):
            value = decoded
    if isinstance(value, Mapping):
        if "published_summaries" in value:
            count = _inline_text(value.get("published_summaries"))
            errors = value.get("errors")
            rendered = f"{count} single-video summary result(s) entered History."
            if isinstance(errors, Sequence) and not isinstance(errors, (str, bytes)):
                visible_errors = [
                    _inline_text(error) for error in errors if str(error or "").strip()
                ]
                if visible_errors:
                    rendered += " Errors: " + " | ".join(visible_errors)
            return rendered
        observations = value.get("observations")
        if isinstance(observations, Sequence) and not isinstance(
            observations, (str, bytes)
        ):
            rendered = []
            for item in observations:
                if not isinstance(item, Mapping):
                    if str(item or "").strip():
                        rendered.append(_inline_text(item))
                    continue
                context: list[str] = []
                if "time_range" in item:
                    context.append(_format_ranges((item["time_range"],)))
                if item.get("fps") is not None:
                    context.append(f"{_inline_text(item['fps'])} FPS")
                prefix = f"[{', '.join(context)}] " if context else ""
                text = _inline_text(item.get("text"))
                uncertainty = _inline_text(item.get("uncertainty"))
                if uncertainty != "None":
                    text += f" Uncertainty: {uncertainty}"
                rendered.append(prefix + text)
            errors = value.get("errors")
            if isinstance(errors, Sequence) and not isinstance(errors, (str, bytes)):
                rendered.extend(
                    f"Error: {_inline_text(error)}" for error in errors if error
                )
            if value.get("error"):
                rendered.append(f"Error: {_inline_text(value['error'])}")
            return " | ".join(rendered) or "None"

        outcomes = value.get("outcomes")
        if isinstance(outcomes, Sequence) and not isinstance(outcomes, (str, bytes)):
            rendered = []
            for index, item in enumerate(outcomes, 1):
                if not isinstance(item, Mapping):
                    continue
                identity = _inline_text(item.get("video_id") or index)
                content = item.get("summary") or item.get("text") or item.get("report")
                text = f"{identity}: {_inline_text(content)}"
                if item.get("uncertainty"):
                    text += f" Uncertainty: {_inline_text(item['uncertainty'])}"
                if item.get("error"):
                    text += f" Error: {_inline_text(item['error'])}"
                rendered.append(text)
            return " | ".join(rendered) or "None"

        if "results" in value:
            return _render_result(value["results"])

        for key in ("summary", "text", "report"):
            if value.get(key):
                rendered = _inline_text(value[key])
                if value.get("uncertainty"):
                    rendered += f" Uncertainty: {_inline_text(value['uncertainty'])}"
                if value.get("error"):
                    rendered += f" Error: {_inline_text(value['error'])}"
                return rendered
        if value.get("error"):
            return f"Error: {_inline_text(value['error'])}"
        return "None"

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        rendered = [_render_result(item) for item in value]
        return " | ".join(item for item in rendered if item != "None") or "None"
    return _inline_text(value)


def _is_runtime_finalizer(
    decision: Mapping[str, Any],
    result: object,
) -> bool:
    """Return whether an event came from a fixed Runtime finalizer block."""

    return bool(decision.get("runtime_finalizer")) or bool(
        result.get("terminal") if isinstance(result, Mapping) else False
    )


def _process_events(
    value: str,
    *,
    include_runtime_finalizers: bool = True,
) -> tuple[tuple[str, object, Mapping[str, Any], object], ...]:
    process = _decode_case_value(value)
    if isinstance(process, Mapping):
        rounds = process.get("rounds")
        if isinstance(rounds, Sequence) and not isinstance(rounds, (str, bytes)):
            events: list[tuple[str, object, Mapping[str, Any], object]] = []
            for index, item in enumerate(rounds, 1):
                if not isinstance(item, Mapping):
                    continue
                decision = item.get("decision")
                decision = decision if isinstance(decision, Mapping) else {}
                result = item.get("execution")
                if (
                    not include_runtime_finalizers
                    and _is_runtime_finalizer(decision, result)
                ):
                    continue
                events.append(
                    ("round", item.get("round", index), decision, result)
                )
            return tuple(events)

        steps = process.get("steps")
        if isinstance(steps, Sequence) and not isinstance(steps, (str, bytes)):
            events = []
            for index, item in enumerate(steps, 1):
                if not isinstance(item, Mapping):
                    continue
                result = item.get("result")
                if (
                    not include_runtime_finalizers
                    and _is_runtime_finalizer(item, result)
                ):
                    continue
                events.append(
                    ("step", item.get("step", index), item, result)
                )
            return tuple(events)
    return (("step", 1, {}, process),) if process not in (None, "") else ()


def _render_memory(value: object) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or not value:
        return ["Memory: None"]
    lines: list[str] = []
    for request_index, request in enumerate(value, 1):
        if not isinstance(request, Mapping):
            continue
        lines.append(
            f"<VideoAgent memory {request_index} task> "
            f"{_inline_text(request.get('instruction'))}"
        )
        actions = request.get("observe_actions")
        if not isinstance(actions, Sequence) or isinstance(actions, (str, bytes)):
            continue
        for action_index, action in enumerate(actions, 1):
            if not isinstance(action, Mapping):
                continue
            prefix = f"memory {request_index}.{action_index}"
            lines.append(f"<VideoAgent {prefix} action> {_render_action(action)}")
            lines.append(
                f"<VideoAgent {prefix} result> "
                f"{_render_observation_result(action.get('result'))}"
            )
    return lines or ["Memory: None"]


def _render_trajectory_header(
    case: TraceCase,
    *,
    heading: str,
    event_count: int,
    include_failure_reason: bool,
) -> tuple[list[str], list[str]]:
    visible_input = _decode_case_value(case.visible_input)
    visible_input = visible_input if isinstance(visible_input, Mapping) else {}
    if case.role is Role.GLOBAL:
        lines = [
            heading,
            f"Task: {_scalar_text(visible_input.get('question'))}",
        ]
        videos = visible_input.get("videos")
        rendered_videos: list[str] = []
        if isinstance(videos, Sequence) and not isinstance(videos, (str, bytes)):
            for item in videos:
                if isinstance(item, Mapping):
                    rendered_videos.append(
                        f"{_inline_text(item.get('video_id'))} "
                        f"({_inline_text(item.get('duration_sec'))} seconds)"
                    )
        lines.append(f"Videos: {'; '.join(rendered_videos) or 'None'}")
        memory_lines: list[str] = []
        count_label = "Rounds"
    else:
        lines = [
            heading,
            f"Task: {_scalar_text(visible_input.get('instruction'))}",
            "Video: "
            f"{_inline_text(visible_input.get('video_id'))} "
            f"({_inline_text(visible_input.get('duration_sec'))} seconds)",
        ]
        memory_lines = _render_memory(visible_input.get("prior_same_video_requests"))
        count_label = "Steps"
    if (
        include_failure_reason
        and case.outcome in {"fail", "partial", "unattributed"}
        and case.observed_issue
    ):
        lines.append(f"Failure reason: {_inline_text(case.observed_issue)}")
    lines.append(f"{count_label}: {event_count}")
    return lines, memory_lines


def _render_output(case: TraceCase) -> list[str]:
    output = _decode_case_value(case.output)
    if case.role is Role.GLOBAL:
        if isinstance(output, Mapping):
            reason = output.get("reason")
            answer = output.get("answer")
        else:
            reason, answer = None, output
        return [
            f"[output reason] {_inline_text(reason)}",
            f"[output answer] {_inline_text(answer)}",
        ]

    if isinstance(output, Mapping):
        summary = output.get("summary")
    else:
        summary = output
    return [f"[output summary] {_inline_text(summary)}"]


def render_trace_case(
    case: TraceCase,
    *,
    heading: str,
    include_failure_reason: bool = True,
    include_runtime_finalizers: bool = True,
) -> str:
    """Render one role-visible action/result trajectory as flat text."""

    events = _process_events(
        case.decisions_and_results,
        include_runtime_finalizers=include_runtime_finalizers,
    )
    header, memory = _render_trajectory_header(
        case,
        heading=heading,
        event_count=len(events),
        include_failure_reason=include_failure_reason,
    )
    lines = [*header, "", *memory]
    if memory:
        lines.append("")
    output = _decode_case_value(case.output)
    output = output if isinstance(output, Mapping) else {}
    answer_rendered = False
    if case.role is Role.GLOBAL:
        agent, left, right = "GlobalAgent", "[", "]"
    else:
        agent, left, right = "VideoAgent", "<", ">"
    for unit, index, decision, result in events:
        action = str(decision.get("action") or "")
        action_text = _render_action(
            decision,
            answer_reason=output.get("reason") if action == "answer" else None,
            fallback_answer=output.get("answer") if action == "answer" else None,
        )
        lines.append(f"{left}{agent} {unit} {index} action{right} {action_text}")
        if action == "answer":
            answer_rendered = True
        if action not in {"answer", "finish"}:
            result_text = (
                _render_observation_result(result)
                if action == "observe"
                else _render_result(result)
            )
            lines.append(
                f"{left}{agent} {unit} {index} result{right} {result_text}"
            )
    if events:
        lines.append("")
    if not (case.role is Role.GLOBAL and answer_rendered):
        lines.extend(_render_output(case))
    return "\n".join(lines)


def trace_case_event_count(
    case: TraceCase,
    *,
    include_runtime_finalizers: bool = True,
) -> int:
    """Count the same role events that ``render_trace_case`` would expose."""

    return len(
        _process_events(
            case.decisions_and_results,
            include_runtime_finalizers=include_runtime_finalizers,
        )
    )


def _episode_action(
    action: object,
    parameters: object,
    *,
    answer_reason: object = None,
    fallback_answer: object = None,
) -> str:
    return _render_action(
        {
            "action": str(action or "unknown"),
            "parameters": parameters if isinstance(parameters, Mapping) else {},
        },
        answer_reason=answer_reason,
        fallback_answer=fallback_answer,
    )


def render_episode_trace(
    case: TraceCase,
    *,
    heading: str,
    evaluation_outcome: str | None = None,
    evaluation_feedback_override: str | None = None,
) -> str:
    """Render one complete cross-role train episode as compact ordinary text."""

    episode = _decode_case_value(case.episode_trace)
    if not isinstance(episode, Mapping):
        # Legacy projected cases remain inspectable, but new Runtime projections always
        # take the complete-episode path above.
        feedback = _decode_case_value(case.outcome_feedback)
        if isinstance(feedback, Mapping):
            ground_truth = feedback.get(
                "ground_truth",
                feedback.get("reference_answer", feedback.get("reference")),
            )
            stored_feedback = _inline_text(feedback.get("feedback"))
        else:
            ground_truth = feedback
            stored_feedback = ""
        lines = [render_trace_case(case, heading=heading)]
        evaluation = (
            f"[Evaluation] ground_truth={_inline_text(ground_truth)}; "
            f"outcome={evaluation_outcome or case.outcome}"
        )
        visible_feedback = (
            evaluation_feedback_override
            if evaluation_feedback_override is not None
            else stored_feedback
        )
        if visible_feedback:
            evaluation += f"; feedback={visible_feedback}"
        lines.append(evaluation)
        return "\n".join(lines)

    episode_input = episode.get("input")
    episode_input = episode_input if isinstance(episode_input, Mapping) else {}
    lines = [heading, "", "Input:"]
    lines.append(f"Question: {_inline_text(episode_input.get('question'))}")
    videos = episode_input.get("videos")
    rendered_videos: list[str] = []
    if isinstance(videos, Sequence) and not isinstance(videos, (str, bytes)):
        for item in videos:
            if isinstance(item, Mapping):
                rendered_videos.append(
                    f"{_inline_text(item.get('video_id'))} "
                    f"({_inline_text(item.get('duration_sec'))} seconds)"
                )
    lines.append(f"Videos: {'; '.join(rendered_videos) or 'None'}")
    lines.append("")

    events = episode.get("events")
    events = (
        events
        if isinstance(events, Sequence) and not isinstance(events, (str, bytes))
        else ()
    )
    output = episode.get("output")
    output = output if isinstance(output, Mapping) else {}
    answer_rendered = False
    for item in events:
        if not isinstance(item, Mapping):
            continue
        kind = str(item.get("kind") or "")
        if kind == "global_decision":
            round_number = _inline_text(item.get("round"))
            action = str(item.get("action") or "unknown")
            lines.append(
                f"[GlobalAgent round {round_number} action] "
                + _episode_action(
                    action,
                    item.get("parameters"),
                    answer_reason=(
                        output.get("reason") if action == "answer" else None
                    ),
                    fallback_answer=(
                        output.get("answer") if action == "answer" else None
                    ),
                )
            )
            if action == "answer":
                answer_rendered = True
            continue
        if kind == "video_run":
            video_id = _inline_text(item.get("video_id"))
            request_number = _inline_text(item.get("request"))
            prefix = f"VideoAgent {video_id} request {request_number}"
            steps = item.get("steps")
            steps = (
                steps
                if isinstance(steps, Sequence) and not isinstance(steps, (str, bytes))
                else ()
            )
            for step_index, step in enumerate(steps, 1):
                if not isinstance(step, Mapping):
                    continue
                number = _inline_text(step.get("step", step_index))
                action = str(step.get("action") or "unknown")
                lines.append(
                    f"<{prefix} step {number} action> "
                    + _episode_action(action, step.get("parameters"))
                )
                if action != "finish":
                    step_result = (
                        _render_observation_result(step.get("result"))
                        if action == "observe"
                        else _render_result(step.get("result"))
                    )
                    lines.append(
                        f"<{prefix} step {number} result> {step_result}"
                    )
            public_result = item.get("summary")
            if not public_result and item.get("error"):
                public_result = f"Error: {_inline_text(item.get('error'))}"
            lines.append(
                f"<{prefix} result> output -> GlobalAgent: "
                f"{_inline_text(public_result)}"
            )
            continue
        if kind == "global_execution":
            round_number = _inline_text(item.get("global_round"))
            lines.append(
                f"[GlobalAgent round {round_number} result] "
                f"{_render_result(item.get('result'))}"
            )
            continue
        lines.append(
            f"[Execution result] {_render_result(item.get('result'))}"
        )

    if not answer_rendered and (
        output.get("answer") not in (None, "")
        or output.get("reason") not in (None, "")
    ):
        lines.append(
            "[GlobalAgent final action] "
            + _episode_action(
                "answer",
                {"answer": output.get("answer")},
                answer_reason=output.get("reason"),
                fallback_answer=output.get("answer"),
            )
        )
    outcome = str(evaluation_outcome or episode.get("outcome") or "").strip()
    if not outcome:
        correct = episode.get("correct")
        outcome = (
            "pass" if correct is True else "fail" if correct is False else "unscored"
        )
    evaluation = (
        f"[Evaluation] ground_truth={_inline_text(episode.get('ground_truth'))}; "
        f"outcome={outcome}"
    )
    visible_feedback = _inline_text(
        evaluation_feedback_override
        if evaluation_feedback_override is not None
        else episode.get("evaluation_feedback")
    )
    if visible_feedback:
        evaluation += f"; feedback={visible_feedback}"
    lines.append(evaluation)
    return "\n".join(lines)


def render_evidence_episodes(request: SkillUpdateRequest) -> str:
    """Render selected complete episodes under explicit failure/success labels."""

    by_id = {case.case_id: case for case in request.cases}
    seen_episodes: set[str] = set()
    sections: list[str] = []
    trajectory_number = 0
    for section, case_ids in (
        ("Failed trajectories", request.evidence.support_ids),
        ("Successful trajectories", request.evidence.contrast_ids),
    ):
        rendered: list[str] = []
        for case_id in case_ids:
            case = by_id[case_id]
            identity = case.episode_id or case.case_id
            if identity in seen_episodes:
                continue
            seen_episodes.add(identity)
            trajectory_number += 1
            misaligned = "optimizer_misalignment" in case.issue_tags
            rendered.append(
                render_episode_trace(
                    case,
                    heading=f"#### Trajectory {trajectory_number}",
                    evaluation_outcome="fail" if misaligned else None,
                    evaluation_feedback_override=(
                        case.observed_issue if misaligned else None
                    ),
                )
            )
        sections.append(f"### {section}\n\n" + ("\n\n".join(rendered) or "None"))
    return "\n\n".join(sections)


class PromptSkillPatcher:
    """Diagnose complete episodes and propose at most one role-local Skill edit."""

    def __init__(
        self,
        *,
        model: LLMClient,
        prompt_path: str | Path | None = None,
        system_architecture: str | None = None,
    ) -> None:
        self.model = model
        path = Path(prompt_path) if prompt_path else PROMPT_ROOT / "update.md"
        self.template = path.read_text(encoding="utf-8").strip()
        self.system_architecture = str(
            system_architecture or build_system_architecture()
        ).strip()
        if not self.system_architecture:
            raise ValueError("system_architecture must be non-empty.")

    @property
    def identity(self) -> Mapping[str, Any]:
        return {
            "workflow": "single_stage",
            "template": self.template,
            "output_schema": UPDATE_OUTPUT_SCHEMA,
            "system_architecture": self.system_architecture,
            "model": dict(getattr(self.model, "identity", {})),
        }

    def propose(self, request: SkillUpdateRequest) -> Sequence[SkillUpdateProposal]:
        prompt = self.render_prompt(request)
        result = self.model.json_prompt(
            prompt,
            json_schema=UPDATE_OUTPUT_SCHEMA,
            schema_name="skill_update",
        )
        if not isinstance(result, Mapping) or result.get("status") != "ok":
            return ()
        try:
            return (self._parse(result.get("value"), request),)
        except (TypeError, ValueError):
            return ()

    def render_prompt(
        self,
        request: SkillUpdateRequest,
    ) -> str:
        rendered_cases = render_evidence_episodes(request)
        assert request.parent_skill_set is not None
        global_skill = request.parent_skill_set.global_skill or "None"
        video_skill = request.parent_skill_set.video_skill or "None"
        visible_budgets = [
            (role, budget)
            for role, budget in request.changed_char_budgets.items()
            if budget is not None
        ]
        if len(visible_budgets) > 1:
            rendered_budget = "; ".join(
                f"`{role.value}` <= {budget}"
                for role, budget in sorted(
                    visible_budgets,
                    key=lambda item: item[0].value,
                )
            )
            changed_chars_rule = (
                "- After selecting the target role, keep that role's textual "
                "difference within its exact evidence- and generation-scaled budget: "
                f"{rendered_budget} changed characters. The budget counts insertions, "
                "deletions, and replacements, not only net length growth."
            )
        elif visible_budgets:
            budget_role, budget = visible_budgets[0]
            changed_chars_rule = (
                f"- Keep the `{budget_role.value}` strategy's textual difference within "
                f"{budget} changed characters. This evidence-scaled budget limits "
                "insertions, deletions, and replacements, not only net length growth."
            )
        elif request.max_changed_chars is not None:
            changed_chars_rule = (
                "- Keep the textual difference from the current target strategy "
                f"within {request.max_changed_chars} changed characters. This "
                "evidence-scaled budget limits insertions, deletions, and replacements, "
                "not only net length growth."
            )
        else:
            changed_chars_rule = ""
        replacements = {
            "{{system_architecture}}": self.system_architecture,
            "{{global_skill}}": global_skill,
            "{{video_skill}}": video_skill,
            "{{mode_instructions}}": (
                (
                    "Discover one missing, recurring decision rule from the current "
                    "train trajectories. This candidate slot is locked to the "
                    f"`{request.target_role_lock.value}` Planner: select that role only "
                    "when its Runtime-visible state establishes the defect; otherwise "
                    "set `target_role` to `none`. Do not select the other Planner role."
                    if request.target_role_lock is not None
                    else "Discover one missing, recurring decision rule from the current "
                    "train trajectories. Diagnose the responsible layer before selecting "
                    "a role."
                )
                if request.mode == "discover"
                else f"Repair only the `{request.role.value}` strategy. It produced a "
                "useful direction but also a paired train regression. Preserve its gain, "
                "change only the recorded cause, and return one integrated replacement."
            ),
            "{{optimizer_memory}}": "\n".join(f"- {item}" for item in request.optimizer_memory) or "None",
            "{{cases}}": rendered_cases,
            "{{candidate_number}}": str(request.candidate_number),
            "{{candidate_count}}": str(request.candidate_count),
            "{{seed}}": str(request.seed),
            "{{max_chars}}": str(request.max_chars),
            "{{changed_chars_rule}}": changed_chars_rule,
            "{{min_support_cases}}": str(request.min_support_cases),
            "{{min_support_groups}}": str(request.min_support_groups),
        }
        template_markers = set(re.findall(r"\{\{[a-z_]+\}\}", self.template))
        unknown = template_markers - set(replacements)
        if unknown:
            raise ValueError("Unknown placeholder in Skill update Prompt: " + ", ".join(sorted(unknown)))
        pattern = re.compile("|".join(re.escape(marker) for marker in replacements))
        return pattern.sub(lambda match: replacements[match.group(0)], self.template)

    @staticmethod
    def _parse(
        raw: Mapping[str, Any],
        request: SkillUpdateRequest,
    ) -> SkillUpdateProposal:
        if not isinstance(raw, Mapping):
            raise ValueError("Skill update model must return a JSON object.")
        required = {"diagnosis", "edits"}
        if set(raw) != required:
            raise ValueError(
                "Skill update output fields must be exactly: " + ", ".join(sorted(required))
            )
        diagnosis = raw["diagnosis"]
        raw_edits = raw["edits"]
        if not isinstance(diagnosis, Mapping):
            raise ValueError("diagnosis must be an object.")
        if not isinstance(raw_edits, list):
            raise ValueError("edits must be an array.")
        diagnosis_fields = {
            "failure_source",
            "target_role",
            "pattern",
            "causal_evidence",
            "regression_risk",
            "expected_behavior_change",
        }
        if set(diagnosis) != diagnosis_fields:
            raise ValueError(
                "diagnosis fields must be exactly: "
                + ", ".join(sorted(diagnosis_fields))
            )
        if len(raw_edits) > 1:
            raise ValueError("Skill update may contain at most one edit.")
        target_text = str(diagnosis["target_role"]).strip().lower()
        target_role = None if target_text == "none" else Role(target_text)
        if (
            request.target_role_lock is not None
            and target_role is not None
            and target_role is not request.target_role_lock
        ):
            raise ValueError("The diagnosis violates the candidate slot's role lock.")
        edits: list[SkillEdit] = []
        for item in raw_edits:
            if not isinstance(item, Mapping) or set(item) != {
                "role",
                "op",
                "target",
                "content",
            }:
                raise ValueError(
                    "Each edit must contain exactly role, op, target, and content."
                )
            edit_role = Role(str(item["role"]))
            if target_role is None or edit_role is not target_role:
                raise ValueError("The edit role must equal diagnosis.target_role.")
            edits.append(
                SkillEdit(
                    op=EditOp(str(item["op"])),
                    target=str(item["target"]),
                    content=str(item["content"]),
                )
            )
        if edits and target_role is None:
            raise ValueError("An edit requires one target_role.")
        if not edits and target_role is not None:
            raise ValueError("A no-edit diagnosis must use target_role none.")
        if request.mode == "repair" and target_role is not request.role:
            raise ValueError("A repair cannot switch roles.")
        proposal_role = target_role or request.role
        causal_evidence = str(diagnosis["causal_evidence"])
        return SkillUpdateProposal(
            role=proposal_role,
            parent_sha256=request.parent_sha256_for(proposal_role),
            diagnosis=SkillDiagnosis(
                pattern=str(diagnosis["pattern"]),
                support_ids=request.evidence.support_ids,
                contrast_ids=request.evidence.contrast_ids,
                regression_risk=str(diagnosis["regression_risk"]),
                expected_behavior_change=str(
                    diagnosis["expected_behavior_change"]
                ),
                failure_source=str(diagnosis["failure_source"]),
                target_role=target_role,
                causal_evidence=causal_evidence,
            ),
            case_assessments=request.evidence.case_assessments,
            edits=tuple(edits),
        )


__all__ = [
    "PromptSkillPatcher",
    "ROLE_CONTRACTS",
    "UPDATE_OUTPUT_SCHEMA",
    "build_role_architectures",
    "build_system_architecture",
    "render_case_value",
    "render_evidence_episodes",
    "render_episode_trace",
    "render_trace_case",
    "trace_case_event_count",
]
