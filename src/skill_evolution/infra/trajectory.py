from __future__ import annotations
import json
import re
from dataclasses import dataclass
from collections.abc import Mapping, Sequence
from typing import Any, Callable
from mvagent.agents.global_agent.prompts import build_global_action_prompt_blocks
from mvagent.agents.video_agent.prompts import build_planner_action_blocks
from .skills import Role, hash_json


def _episode_data(episode):
    artifact = episode.artifact if hasattr(episode, "artifact") else episode
    return artifact, artifact.get("result", artifact)


def global_view(episode):
    """Public evidence only; references and private Video steps never enter this view."""
    _, result = _episode_data(episode)
    return {"question": result.get("input", {}).get("question", ""),
            "videos": {vid: {"duration_sec": data.get("duration_sec")}
                       for vid, data in result.get("video_metadata", {}).items()},
            "history": result.get("action_history", []), "answer": result.get("answer", {})}


def video_view(episode, video_id, request_id):
    """The pair (video_id, request_id) is unique within a question."""
    _, result = _episode_data(episode)
    memory = []
    for event in result.get("trajectory", []):
        if event.get("agent") != "VideoAgent" or event.get("video_id") != video_id:
            continue
        output = event.get("output", {})
        if output.get("request_id") == request_id:
            return {"video_id": video_id,
                    "duration_sec": result.get("video_metadata", {}).get(video_id, {}).get("duration_sec"),
                    "instruction": event.get("input", {}).get("instruction", ""),
                    "prior_memory": memory, "steps": output.get("steps", []),
                    "report": output.get("report", ""), "status": output.get("status")}
        memory.append({"instruction": event.get("input", {}).get("instruction", ""),
                       "observations": [s for s in output.get("steps", []) if s.get("action") == "observe"]})
    raise KeyError((video_id, request_id))


def decision_view(episode, decision_id):
    artifact, _ = _episode_data(episode)
    events = [e for e in artifact.get("events", []) if e.get("decision_id") == decision_id]
    if not any(e["kind"] == "structured_request" for e in events):
        raise KeyError(f"No recorded decision state: {decision_id}")
    return events


def dependency_links(episode):
    _, result = _episode_data(episode)
    rounds = sorted({e["round"] for e in result.get("trajectory", [])
                     if e.get("agent") == "GlobalAgent" and "round" in e})
    links = []
    for event in result.get("trajectory", []):
        if event.get("agent") != "VideoAgent":
            continue
        parent = event.get("input", {}).get("global_round")
        request = event.get("output", {}).get("request_id")
        if parent is None or not request:
            continue
        node = f"video:{event['video_id']}:{request}"
        links.append({"from": f"global:{parent}", "to": node, "kind": "instruction"})
        following = next((r for r in rounds if r > parent), None)
        if following is not None:
            links.append({"from": node, "to": f"global:{following}", "kind": "public_return"})
    return links

@dataclass(frozen=True)
class TraceCase:
    """A compact, role-visible training example projected from one rollout."""

    case_id: str
    role: Role
    task_type: str
    visible_input: str
    decisions_and_results: str
    output: str
    observed_issue: str
    outcome: str
    official_score: float | None = None
    outcome_feedback: str = ""
    source_group: str = ""
    episode_id: str = ""
    video_id: str = ""
    request_index: int = -1
    instruction: str = ""
    downstream_context: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "case_id", str(self.case_id).strip())
        object.__setattr__(self, "role", Role(self.role))
        for name in (
            "task_type",
            "visible_input",
            "decisions_and_results",
            "output",
            "observed_issue",
            "outcome",
            "outcome_feedback",
            "episode_id",
        ):
            object.__setattr__(self, name, str(getattr(self, name) or "").strip())
        if not self.case_id:
            raise ValueError("TraceCase.case_id must be non-empty.")
        if self.outcome not in {"pass", "fail", "partial", "unscored"}:
            if self.outcome != "unattributed":
                raise ValueError(
                    "TraceCase.outcome must be pass, fail, partial, "
                    "unattributed, or unscored."
                )
        if self.official_score is not None:
            object.__setattr__(self, "official_score", float(self.official_score))
        object.__setattr__(self, "source_group", str(self.source_group or "").strip())

    def to_dict(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "role": self.role.value,
            "task_type": self.task_type,
            "visible_input": self.visible_input,
            "decisions_and_results": self.decisions_and_results,
            "output": self.output,
            "observed_issue": self.observed_issue,
            "outcome": self.outcome,
            "official_score": self.official_score,
            "outcome_feedback": self.outcome_feedback,
            "episode_id": self.episode_id,
            "video_id": self.video_id,
            "request_index": self.request_index,
            "instruction": self.instruction,
            "downstream_context": self.downstream_context,
        }


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


def build_role_architectures(
    *,
    max_videos_per_watch: int = 4,
    max_video_inputs_per_request: int = 8,
    max_video_frames_per_request: int = 512,
    max_ranges_per_action: int = 8,
    global_max_steps: int = 5,
    video_max_steps: int = 5,
) -> dict[Role, str]:
    """Render each target Planner's fixed contract for the Patch stage."""

    return {
        Role.GLOBAL: (
            ROLE_CONTRACTS[Role.GLOBAL]
            + f"\nConfigured maximum decision steps: {global_max_steps}."
            + "\n\n### Available actions\n"
            + build_global_action_prompt_blocks(
                ("answer", "analyze_videos", "watch_videos"),
                max_videos_per_watch=max_videos_per_watch,
                max_video_inputs_per_request=max_video_inputs_per_request,
            )
        ),
        Role.VIDEO: (
            ROLE_CONTRACTS[Role.VIDEO]
            + f"\nConfigured maximum decision steps: {video_max_steps}; visual frame limit per request: {max_video_frames_per_request}."
            + "\n\n### Available actions\n"
            + build_planner_action_blocks(
                ("observe", "finish"),
                duration_sec=1.0,
                max_video_frames_per_request=max_video_frames_per_request,
                max_ranges_per_action=max_ranges_per_action,
            )
        ),
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
        return f"answer() -> {_compact_json(payload)}"

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
                context = []
                if item.get("time_range") is not None:
                    context.append(f"source range {_inline_text(item['time_range'])}")
                if item.get("fps") is not None:
                    context.append(f"effective FPS {_inline_text(item['fps'])}")
                context.append("actual frame count " + str(item.get("frame_count", "unknown (not recorded)")))
                if context:
                    text = "; ".join(context) + ": " + text
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


def render_global_steps(steps: Sequence[Mapping[str, Any]]) -> str:
    """Compact Global calls; parallel video reports share one decision step."""
    lines = []
    for step in steps:
        decision = step.get('decision', {})
        parameters = json.dumps(decision.get('parameters', {}), ensure_ascii=False)
        marker = ' (runtime finalizer; not editable)' if step.get('editable') is False else ''
        execution = step.get('execution', {})
        action = decision.get('action', 'None')
        call = 'answer' if action == 'answer' else f'{action} {parameters}'
        line = f"Step {step['step']}{marker}: action={call}"
        outcomes = execution.get('outcomes', []) if isinstance(execution, Mapping) else []
        if decision.get('action') == 'analyze_videos' and outcomes:
            reports = [f"  obs[{item.get('video_id', 'unknown')}]: {_render_result(item)}"
                       for item in outcomes if isinstance(item, Mapping)]
            if execution.get('error'):
                reports.append(f"  Error: {_inline_text(execution['error'])}")
            lines.append('\n'.join([line, *reports]))
        elif decision.get('action') == 'answer':
            answer = execution.get('answer') if isinstance(execution, Mapping) else None
            if answer is None:
                # Historical rollouts stored the produced answer in the decision record.
                answer = decision.get('parameters', {}).get('answer')
            lines.append(line + (f' | output={answer}' if answer is not None else ''))
        else:
            lines.append(f"{line} | obs={_render_result(execution)}")
    return '\n'.join(lines) or 'None'


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


def _compact(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: object) -> Sequence[Any]:
    return value if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else ()


_REPORT_SUMMARY_RE = re.compile(r"^Request\s+\d+:\s*(.*?)\nSummary:\s*", re.DOTALL)


def _public_summary(report: object, instruction: object = "") -> str:
    """Remove the Runtime-owned request wrapper when it repeats the instruction."""

    text = str(report or "").strip()
    if not text:
        return ""
    match = _REPORT_SUMMARY_RE.match(text)
    if match is None:
        return text
    rendered_instruction = str(instruction or "").strip()
    if rendered_instruction and match.group(1).strip() != rendered_instruction:
        return text
    return text[match.end() :].strip()


def _normalized_instruction(value: object) -> str:
    return " ".join(str(value or "").casefold().split())












class TrajectoryProjector:
    """Project canonical MVAgent artifacts into compact role-visible cases.

    The projector identifies observable failure symptoms, but deliberately does
    not decide whether they are a Skill gap, an execution lapse, or a model/tool
    capability limit. That assessment belongs to the update model.
    """

    def __init__(
        self,
        *,
        case_salt: str = "mvagent-skill-evolution-v1",
        video_metadata_provider: Callable[
            [Mapping[str, Any]], Mapping[str, Mapping[str, Any]]
        ]
        | None = None,
        outcome_feedback_provider: Callable[[Mapping[str, Any]], Mapping[str, Any]]
        | None = None,
        source_group_provider: Callable[[str], str] | None = None,
    ) -> None:
        self.case_salt = str(case_salt)
        self.video_metadata_provider = video_metadata_provider
        self.outcome_feedback_provider = outcome_feedback_provider
        self.source_group_provider = source_group_provider

    def project(
        self,
        artifact: Mapping[str, Any],
        *,
        official_score: float | None = None,
    ) -> tuple[TraceCase, ...]:
        outer = _mapping(artifact)
        result = _mapping(outer.get("result")) or outer
        sample_token = str(outer.get("sample_id") or result.get("sample_id") or "unknown")
        outcome = self._outcome(official_score)
        outcome_feedback = (
            _compact(self.outcome_feedback_provider(outer))
            if self.outcome_feedback_provider is not None
            else ""
        )
        task_family = str(outer.get("task") or "").strip()
        if not task_family:
            task_family = "multiple_choice" if _sequence(outer.get("options")) else "free_response"
        source_group = self._source_group(sample_token)
        raw_videos = _mapping(_mapping(result.get("input")).get("videos"))
        video_metadata = (
            self.video_metadata_provider(raw_videos)
            if self.video_metadata_provider is not None
            else {
                str(video_id): _mapping(value)
                for video_id, value in raw_videos.items()
                if isinstance(value, Mapping)
            }
        )
        episode_id = self._episode_id(sample_token)
        global_cases = self._project_global(
            result=result,
            sample_token=sample_token,
            outcome=outcome,
            official_score=official_score,
            video_metadata=video_metadata,
            task_family=task_family,
            outcome_feedback=outcome_feedback,
            source_group=source_group,
            episode_id=episode_id,
        )
        video_cases = self._project_video(
            result=result,
            sample_token=sample_token,
            outcome=outcome,
            official_score=official_score,
            video_metadata=video_metadata,
            task_family=task_family,
            source_group=source_group,
            episode_id=episode_id,
        )
        return (*global_cases, *video_cases)


    def _project_global(
        self,
        *,
        result: Mapping[str, Any],
        sample_token: str,
        outcome: str,
        official_score: float | None,
        video_metadata: Mapping[str, Mapping[str, Any]],
        task_family: str,
        outcome_feedback: str,
        source_group: str,
        episode_id: str,
    ) -> tuple[TraceCase, ...]:
        inputs = _mapping(result.get("input"))
        question = str(inputs.get("question") or "").strip()
        raw_videos = _mapping(inputs.get("videos"))
        videos = [
            {
                "video_id": str(video_id),
                "duration_sec": _mapping(video_metadata.get(video_id)).get(
                    "duration_sec", "unavailable"
                ),
            }
            for video_id in raw_videos
        ]
        history = tuple(_mapping(item) for item in _sequence(result.get("action_history")))
        trajectory = tuple(_mapping(item) for item in _sequence(result.get("trajectory")))
        answer = _mapping(result.get("answer"))
        decisions = [
            item
            for item in trajectory
            if item.get("agent") == "GlobalAgent" and item.get("action") in {"decide", "terminal_answer"}
        ]
        rendered_rounds = []
        inferred_order = False
        history_index = 0
        for index, event in enumerate(decisions, 1):
            output = dict(_mapping(event.get("output")))
            event_action = str(event.get("action") or "")
            action = str(output.get("action") or event_action or "unknown")
            if event_action == "terminal_answer" and action == "terminal_answer":
                action = "answer"
            output.setdefault("action", action)
            if event_action == "terminal_answer":
                # Preserve the Runtime-owned finalizer boundary for consumers that
                # optimize only ordinary Planner decisions.  The default renderer
                # still includes this event unless explicitly asked to omit it.
                output["runtime_finalizer"] = True
            inferred_order = inferred_order or "round" not in event
            if action == "answer":
                execution = {"status": answer.get("status", "unknown"), "answer": answer.get("answer", "")}
            elif history_index < len(history):
                execution = self._global_execution(history[history_index])
                history_index += 1
            else:
                execution = {"status": "not_found_in_public_history"}
            rendered_rounds.append(
                {
                    "round": event.get("round", index),
                    "decision": output,
                    "execution": execution,
                }
            )
        unpaired_history = [
            {
                "action": item.get("action", "unknown"),
                "execution": self._global_execution(item),
            }
            for item in history[history_index:]
        ]
        issue = ""
        return (
            TraceCase(
                case_id=self._case_id(sample_token, Role.GLOBAL, 0),
                role=Role.GLOBAL,
                task_type=f"{task_family}:global_episode",
                visible_input=_compact({"question": question, "videos": videos}),
                decisions_and_results=_compact(
                    {
                        "rounds": rendered_rounds,
                        **(
                            {"unpaired_public_executions": unpaired_history}
                            if unpaired_history
                            else {}
                        ),
                    }
                ),
                output=_compact(answer),
                observed_issue=issue,
                outcome=outcome,
                official_score=official_score,
                outcome_feedback=outcome_feedback,
                source_group=source_group,
                episode_id=episode_id,
            ),
        )

    def _project_video(
        self,
        *,
        result: Mapping[str, Any],
        sample_token: str,
        outcome: str,
        official_score: float | None,
        video_metadata: Mapping[str, Mapping[str, Any]],
        task_family: str,
        source_group: str,
        episode_id: str,
    ) -> tuple[TraceCase, ...]:
        trajectory = tuple(_mapping(item) for item in _sequence(result.get("trajectory")))
        history = tuple(_mapping(item) for item in _sequence(result.get("action_history")))
        runs = [
            (trajectory_index, item)
            for trajectory_index, item in enumerate(trajectory)
            if item.get("agent") == "VideoAgent" and item.get("action") == "run"
        ]
        prior_by_video: dict[str, list[dict[str, object]]] = {}
        cases: list[TraceCase] = []
        for index, (trajectory_index, event) in enumerate(runs):
            video_id = str(event.get("video_id") or "unknown")
            event_input = _mapping(event.get("input"))
            event_output = _mapping(event.get("output"))
            steps = tuple(_mapping(item) for item in _sequence(event_output.get("steps")))
            request_id = str(event_output.get("request_id") or "")
            report = str(event_output.get("report") or "")
            local_outcome = outcome
            issue = str(event_output.get("error") or "")
            visible_input = {
                "video_id": video_id,
                "instruction": str(event_input.get("instruction") or ""),
                "duration_sec": _mapping(video_metadata.get(video_id)).get(
                    "duration_sec", "unavailable"
                ),
                "prior_same_video_requests": tuple(prior_by_video.get(video_id, ())),
            }
            duration_sec = _mapping(video_metadata.get(video_id)).get(
                "duration_sec", "unavailable"
            )
            # Only the next public action kind is exposed offline, not sibling reports,
            # full question, answer, or an inferred claim that this report caused it.
            following = next((item for item in trajectory[trajectory_index + 1:]
                if item.get("agent") == "GlobalAgent" and item.get("action") == "decide"), None)
            downstream = {"scope": "Offline public routing context, not local GT or proof of report use",
                "next_global_action": _mapping(following.get("output")).get("action", "unknown") if following else "not recorded"}
            cases.append(
                TraceCase(
                    case_id=self._case_id(sample_token, Role.VIDEO, index),
                    downstream_context=_compact(downstream),
                    video_id=video_id, request_index=len(prior_by_video.get(video_id, ())),
                    instruction=str(event_input.get("instruction") or ""),
                    role=Role.VIDEO,
                    task_type=f"{task_family}:video_request",
                    visible_input=_compact(visible_input),
                    decisions_and_results=_compact({"steps": steps}),
                    output=_compact(
                        {
                            "status": event_output.get("status"),
                            "summary": _public_summary(
                                report,
                                event_input.get("instruction"),
                            ),
                            "error": event_output.get("error", ""),
                        }
                    ),
                    observed_issue=issue,
                    outcome=local_outcome,
                    official_score=official_score,
                    source_group=source_group,
                    episode_id=episode_id,
                )
            )
            prior_by_video.setdefault(video_id, []).append(
                {
                    "instruction": str(event_input.get("instruction") or ""),
                    "observe_actions": tuple(
                        step for step in steps if step.get("action") == "observe"
                    ),
                    "status": event_output.get("status"),
                }
            )
        return tuple(cases)



    @staticmethod
    def _global_execution(event: Mapping[str, Any]) -> dict[str, object]:
        """Render one public execution once, without decision-parameter duplication."""

        execution: dict[str, object] = {
            str(key): value
            for key, value in event.items()
            if key not in {"action", "parameters", "outcomes", "results"}
        }
        outcomes = []
        for raw_outcome in _sequence(event.get("outcomes")):
            outcome = dict(_mapping(raw_outcome))
            instruction = outcome.pop("instruction", "")
            report = outcome.pop("report", "")
            if report:
                outcome["summary"] = _public_summary(report, instruction)
            outcomes.append(outcome)
        if outcomes:
            execution["outcomes"] = outcomes
        raw_results = _mapping(event.get("results"))
        if raw_results:
            results = dict(raw_results)
            results.pop("instruction", None)
            execution["results"] = results
        return execution






    def _case_id(self, sample_token: str, role: Role, index: int) -> str:
        return "case_" + hash_json(
            {
                "salt": self.case_salt,
                "sample": sample_token,
                "role": role.value,
                "index": index,
            }
        )[:16]

    def _episode_id(self, sample_token: str) -> str:
        """Return an opaque join key shared by every case from one question."""

        return "episode_" + hash_json(
            {
                "salt": self.case_salt,
                "sample": sample_token,
            }
        )[:16]

    def _source_group(self, sample_token: str) -> str:
        if self.source_group_provider is not None:
            provided = str(self.source_group_provider(sample_token) or "").strip()
            if provided:
                return provided
        return "source_" + hash_json(
            {"salt": self.case_salt, "sample": sample_token}
        )[:12]

    @staticmethod
    def _outcome(score: float | None) -> str:
        if score is None:
            return "unscored"
        value = float(score)
        if value >= 1.0:
            return "pass"
        if value <= 0.0:
            return "fail"
        return "partial"


__all__ = ["TrajectoryProjector"]


def routing_audit(bank, report, groups):
    """Observed exposure, injection and actions; never infer causal utility."""
    cards = {c.id: c for c in bank.bank.cards}
    rows = []
    for sid, episode in report['episodes'].items():
        events = episode.artifact.get('events', [])
        result = episode.artifact.get('result', {})
        actions = {}
        for event in result.get('trajectory', []):
            if event.get('agent') == 'GlobalAgent' and event.get('action') == 'decide':
                actions[f"global:{event.get('round')}"] = event.get('output', {})
            if event.get('agent') == 'VideoAgent':
                output = event.get('output', {})
                for index, step in enumerate(output.get('steps', []), 1):
                    key = f"video:{event.get('video_id')}:{output.get('request_id')}:{index}"
                    actions[key] = step
        for event in events:
            if event.get('kind') not in ('skill_selection', 'skill_reuse'):
                continue
            did = event.get('decision_id')
            actor_requests = [e for e in events if e.get('kind') == 'structured_request'
                and e.get('decision_id') == did and e.get('schema') in ('global_decision', 'video_action')]
            selected = [c['id'] for c in event.get('selected', [])]
            # Match full bodies inside actual Actor messages, not selector claims.
            injected = [s for s in selected if s in cards and any(
                any(isinstance(m.get('content'), str) and cards[s].render() in
                    m['content'].rsplit('\n## Decision strategy\n', 1)[-1].split('\n## Output contract\n', 1)[0]
                    and '\n## Decision strategy\n' in m['content']
                    for m in request.get('messages', [])) for request in actor_requests)]
            action = actions.get(did, {})
            rows.append(dict(sample_id=sid, source_group=groups[sid], bank_hash=bank.skill_set_hash(),
                role=event.get('role'), decision_id=did, reused=event['kind']=='skill_reuse', eligible=event.get('eligible_ids', []),
                recalled=[c['id'] for c in event.get('candidates', [])], selected=selected,
                injected=injected if actor_requests else None,
                action=action.get('action'), parameters=action.get('parameters'),
                score=report['scores'][sid].score))
    stats = {}
    for sid, card in cards.items():
        stats[sid] = dict(content_hash=hash_json(card.to_dict()), **{
            field: dict(decisions=sum(sid in (r[field] or []) for r in rows),
                        samples=len({r['sample_id'] for r in rows if sid in (r[field] or [])}),
                        source_groups=len({r['source_group'] for r in rows if sid in (r[field] or [])}))
            for field in ('eligible', 'recalled', 'selected', 'injected')})
    return dict(rows=rows, cards=stats, missing_injection_records=sum(r['injected'] is None for r in rows))


def role_routing(episode, role, *, video_id=None, request_id=None):
    """Only actual role-local selection events; no raw model prompts or sibling state."""
    result = []
    for event in episode.artifact.get('events', []):
        if event.get('kind') not in ('skill_retrieval', 'skill_selection', 'skill_reuse') or event.get('role') != role:
            continue
        if role == 'video' and (event.get('video_id') != video_id or event.get('request_id') != request_id):
            continue
        fields = ('kind', 'decision_id', 'request_id', 'video_id', 'stage', 'bank_sha256',
                  'eligible_ids', 'candidates', 'selected', 'status', 'assessment', 'reason',
                  'retriever', 'retrieval_top_k', 'rendered_sha256', 'rendered_chars')
        result.append({k: event[k] for k in fields if k in event})
    return result
