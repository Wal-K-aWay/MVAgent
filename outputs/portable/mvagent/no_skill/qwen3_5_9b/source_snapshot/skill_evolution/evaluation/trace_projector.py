from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any, Callable

from ..strategy.contracts import Role, TraceCase, hash_json


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


def _count_bucket(value: int) -> str:
    if value <= 0:
        return "none"
    if value == 1:
        return "one"
    return "multiple"


def _progression(values: Sequence[object]) -> str:
    normalized = [
        item for item in (_normalized_instruction(value) for value in values) if item
    ]
    if len(normalized) < 2:
        return "none"
    return "repeated" if len(set(normalized)) < len(normalized) else "changed"


def _global_behavior_signature(
    *,
    decisions: Sequence[Mapping[str, Any]],
    available_video_count: int,
) -> str:
    analyze_requests: list[Mapping[str, Any]] = []
    selected_per_action: list[int] = []
    watch_count = 0
    for event in decisions:
        output = _mapping(event.get("output"))
        event_action = str(event.get("action") or "")
        action = str(output.get("action") or event_action or "unknown")
        parameters = _mapping(output.get("parameters"))
        if action == "analyze_videos":
            requests = [
                _mapping(item)
                for item in _sequence(parameters.get("videoagent_request"))
            ]
            analyze_requests.extend(requests)
            selected_per_action.append(len(requests))
        elif action == "watch_videos":
            watch_count += 1
            selected_per_action.append(len(_sequence(parameters.get("videos"))))

    instructions_by_video: dict[str, list[str]] = {}
    for request in analyze_requests:
        video_id = str(request.get("video_id") or "")
        if video_id:
            instructions_by_video.setdefault(video_id, []).append(
                str(request.get("instruction") or "")
            )
    first_instructions = [values[0] for values in instructions_by_video.values() if values]
    if len(first_instructions) < 2:
        assignment = "single_video"
    elif len({_normalized_instruction(item) for item in first_instructions}) == 1:
        assignment = "shared_across_videos"
    else:
        assignment = "different_across_videos"
    per_video_progression = {
        _progression(values) for values in instructions_by_video.values()
    } - {"none"}
    if not per_video_progression:
        request_progression = "none"
    elif len(per_video_progression) == 1:
        request_progression = next(iter(per_video_progression))
    else:
        request_progression = "mixed"

    selected_video_ids = set(instructions_by_video)
    if not selected_per_action:
        selection_scope = "none"
    elif all(count == 1 for count in selected_per_action):
        selection_scope = "one_per_action"
    elif all(count > 1 for count in selected_per_action):
        selection_scope = "multiple_per_action"
    else:
        selection_scope = "mixed"
    if not selected_video_ids:
        analyze_coverage = "none"
    elif available_video_count and len(selected_video_ids) >= available_video_count:
        analyze_coverage = "all_available"
    else:
        analyze_coverage = "subset"

    evidence_rounds = sum(
        1
        for event in decisions
        if str(_mapping(event.get("output")).get("action") or event.get("action"))
        in {"analyze_videos", "watch_videos"}
    )
    return _compact(
        {
            "analyze_coverage": analyze_coverage,
            "answer_timing": "after_evidence" if evidence_rounds else "direct",
            "evidence_rounds": _count_bucket(evidence_rounds),
            "instruction_assignment": assignment,
            "request_progression": request_progression,
            "selection_scope": selection_scope,
            "watch_usage": _count_bucket(watch_count),
        }
    )


def _range_mode(where: Sequence[Any], *, duration_sec: object) -> str:
    ranges = [_sequence(item) for item in where]
    ranges = [item for item in ranges if len(item) == 2]
    if not ranges:
        return "none"
    try:
        duration = float(duration_sec)
    except (TypeError, ValueError):
        return "selected_ranges"
    if duration <= 0:
        return "selected_ranges"
    for item in ranges:
        try:
            start, end = float(item[0]), float(item[1])
        except (TypeError, ValueError):
            continue
        tolerance = max(1e-3, duration * 1e-6)
        if start <= tolerance and end >= duration - tolerance:
            return "full_source"
    return "focused"


def _video_behavior_signature(
    *,
    steps: Sequence[Mapping[str, Any]],
    duration_sec: object,
    has_prior_memory: bool,
) -> str:
    observes = [step for step in steps if step.get("action") == "observe"]
    parameters = [_mapping(step.get("parameters")) for step in observes]
    range_modes = {
        _range_mode(_sequence(item.get("where")), duration_sec=duration_sec)
        for item in parameters
    } - {"none"}
    if not range_modes:
        range_mode = "none"
    elif len(range_modes) == 1:
        range_mode = next(iter(range_modes))
    else:
        range_mode = "mixed"
    range_requests = [_compact(_sequence(item.get("where"))) for item in parameters]
    fps_values = [item.get("fps") for item in parameters if item.get("fps") is not None]
    finish_steps = [step for step in steps if step.get("action") == "finish"]
    finish_mode = "present" if finish_steps else "none"
    return _compact(
        {
            "finish_mode": finish_mode,
            "memory_available": bool(has_prior_memory),
            "observe_count": _count_bucket(len(observes)),
            "range_mode": range_mode,
            "range_progression": _progression(range_requests),
            "sampling_progression": _progression(fps_values),
            "what_progression": _progression([item.get("what") for item in parameters]),
        }
    )


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
        episode_trace = self._project_episode_trace(
            outer=outer,
            result=result,
            outcome=outcome,
            outcome_feedback=outcome_feedback,
            video_metadata=video_metadata,
        )
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
            episode_trace=episode_trace,
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
            episode_trace=episode_trace,
        )
        return (*global_cases, *video_cases)

    def _project_episode_trace(
        self,
        *,
        outer: Mapping[str, Any],
        result: Mapping[str, Any],
        outcome: str,
        outcome_feedback: str,
        video_metadata: Mapping[str, Mapping[str, Any]],
    ) -> str:
        """Project one complete question as a path-free cross-role episode."""

        inputs = _mapping(result.get("input"))
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
        events: list[dict[str, object]] = []
        prior_requests: dict[str, int] = {}
        for raw_event in _sequence(result.get("trajectory")):
            event = _mapping(raw_event)
            agent = str(event.get("agent") or "")
            action = str(event.get("action") or "")
            event_input = _mapping(event.get("input"))
            event_output = _mapping(event.get("output"))
            if agent == "GlobalAgent" and action in {"decide", "terminal_answer"}:
                selected_action = str(event_output.get("action") or action or "unknown")
                if selected_action == "terminal_answer":
                    selected_action = "answer"
                events.append(
                    {
                        "kind": "global_decision",
                        "round": event.get("round", len(events) + 1),
                        "action": selected_action,
                        "parameters": _mapping(event_output.get("parameters")),
                    }
                )
                continue
            if agent == "VideoAgent" and action == "run":
                video_id = str(event.get("video_id") or "unknown")
                request_number = prior_requests.get(video_id, 0) + 1
                prior_requests[video_id] = request_number
                steps = []
                for step_index, raw_step in enumerate(
                    _sequence(event_output.get("steps")), 1
                ):
                    step = _mapping(raw_step)
                    steps.append(
                        {
                            "step": step.get("step", step_index),
                            "action": step.get("action", "unknown"),
                            "parameters": _mapping(step.get("parameters")),
                            "result": step.get("result"),
                        }
                    )
                events.append(
                    {
                        "kind": "video_run",
                        "global_round": event_input.get("global_round"),
                        "video_id": video_id,
                        "request": request_number,
                        "instruction": str(event_input.get("instruction") or ""),
                        "duration_sec": _mapping(video_metadata.get(video_id)).get(
                            "duration_sec", "unavailable"
                        ),
                        "prior_request_count": request_number - 1,
                        "steps": steps,
                        "summary": _public_summary(
                            event_output.get("report"),
                            event_input.get("instruction"),
                        ),
                        "error": event_output.get("error", ""),
                    }
                )
                continue
            if agent == "GlobalAgent" and action == "analyze_videos":
                errors = [
                    str(item.get("error") or "").strip()
                    for item in (
                        _mapping(value)
                        for value in _sequence(event_output.get("outcomes"))
                    )
                    if str(item.get("error") or "").strip()
                ]
                events.append(
                    {
                        "kind": "global_execution",
                        "global_round": event_input.get("global_round"),
                        "action": action,
                        "result": {
                            "published_summaries": sum(
                                bool(_mapping(value).get("report"))
                                for value in _sequence(event_output.get("outcomes"))
                            ),
                            "errors": errors,
                        },
                    }
                )
                continue
            if agent == "GlobalAgent" and action == "watch_videos":
                events.append(
                    {
                        "kind": "global_execution",
                        "global_round": event_input.get("global_round"),
                        "action": action,
                        "result": {
                            "text": event_output.get("text", ""),
                            "error": event_output.get("error", ""),
                        },
                    }
                )
                continue
            if agent or action:
                events.append(
                    {
                        "kind": "execution_feedback",
                        "agent": agent or "unknown",
                        "action": action or "unknown",
                        "result": event_output,
                    }
                )

        answer = _mapping(result.get("answer"))
        feedback = {}
        if outcome_feedback:
            try:
                parsed_feedback = json.loads(outcome_feedback)
            except (TypeError, ValueError, json.JSONDecodeError):
                parsed_feedback = {}
            feedback = _mapping(parsed_feedback)
        ground_truth = outer.get("ground_truth")
        if ground_truth in (None, ""):
            ground_truth = feedback.get(
                "ground_truth",
                feedback.get("reference_answer", feedback.get("reference")),
            )
        prediction = answer.get("answer", outer.get("prediction", ""))
        return _compact(
            {
                "input": {
                    "question": str(inputs.get("question") or "").strip(),
                    "videos": videos,
                },
                "events": events,
                "output": {
                    "reason": answer.get("reason", ""),
                    "answer": prediction,
                },
                "ground_truth": ground_truth,
                "outcome": outcome,
                "evaluation_feedback": str(feedback.get("feedback") or "").strip(),
            }
        )

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
        episode_trace: str,
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
        action_names: list[str] = []
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
            action_names.append(action)
            inferred_order = inferred_order or "round" not in event
            if action == "answer":
                execution = {"status": answer.get("status", "unknown")}
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
        issue_tags = self._global_issue_tags(
            decisions=decisions,
            history=history,
            outcome=outcome,
            inferred_order=inferred_order,
        )
        issue = self._global_episode_issue(outcome=outcome, issue_tags=issue_tags)
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
                downstream_effect=(
                    "Final public answer status: "
                    f"{answer.get('status', 'unknown')}; answer: {answer.get('answer', '')}."
                ),
                outcome=outcome,
                official_score=official_score,
                outcome_feedback=outcome_feedback,
                source_group=source_group,
                action_signature=">".join(action_names) or "none",
                behavior_signature=_global_behavior_signature(
                    decisions=decisions,
                    available_video_count=len(videos),
                ),
                issue_tags=issue_tags,
                episode_id=episode_id,
                episode_trace=episode_trace,
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
        episode_trace: str,
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
            public_effect = self._find_public_video_effect(
                history=history,
                video_id=video_id,
                request_id=request_id,
                local_report=report,
            )
            downstream_effect = self._video_downstream_effect(
                trajectory=trajectory,
                trajectory_index=trajectory_index,
                global_round=event_input.get("global_round"),
                video_id=video_id,
                request_id=request_id,
                public_effect=public_effect,
            )
            issue_tags = self._video_issue_tags(
                status=str(event_output.get("status") or "unknown"),
                steps=steps,
                outcome=outcome,
                inferred_order=any("step" not in step for step in steps),
            )
            local_outcome = self._video_outcome(outcome, issue_tags)
            issue = self._video_issue(
                status=str(event_output.get("status") or "unknown"),
                steps=steps,
                outcome=local_outcome,
                inferred_order=any("step" not in step for step in steps),
            )
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
            cases.append(
                TraceCase(
                    case_id=self._case_id(sample_token, Role.VIDEO, index),
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
                    downstream_effect=_compact(downstream_effect),
                    outcome=local_outcome,
                    official_score=official_score,
                    source_group=source_group,
                    action_signature=">".join(
                        str(step.get("action") or "unknown") for step in steps
                    )
                    or "none",
                    behavior_signature=_video_behavior_signature(
                        steps=steps,
                        duration_sec=duration_sec,
                        has_prior_memory=bool(prior_by_video.get(video_id)),
                    ),
                    issue_tags=issue_tags,
                    episode_id=episode_id,
                    episode_trace=episode_trace,
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
    def _find_public_video_effect(
        *,
        history: Sequence[Mapping[str, Any]],
        video_id: str,
        request_id: str,
        local_report: str,
    ) -> Mapping[str, object]:
        for action in history:
            for outcome in _sequence(action.get("outcomes")):
                item = _mapping(outcome)
                if str(item.get("video_id")) != video_id:
                    continue
                if request_id and str(item.get("request_id")) != request_id:
                    continue
                return {
                    "global_action": action.get("action"),
                    "status": item.get("status"),
                    "report_forwarded": bool(item.get("report")),
                    "report_matches_local": str(item.get("report") or "") == local_report,
                    "error": item.get("error", ""),
                }
        return {"status": "not_found_in_public_history"}

    @staticmethod
    def _video_downstream_effect(
        *,
        trajectory: Sequence[Mapping[str, Any]],
        trajectory_index: int,
        global_round: object,
        video_id: str,
        request_id: str,
        public_effect: Mapping[str, object],
    ) -> Mapping[str, object]:
        """Keep the first public result and subsequent Global decision for lookahead."""

        public_execution_seen = False
        next_decision: Mapping[str, object] | str = "not_observed"
        for event in trajectory[trajectory_index + 1 :]:
            if event.get("agent") != "GlobalAgent":
                continue
            action = str(event.get("action") or "")
            event_input = _mapping(event.get("input"))
            event_output = _mapping(event.get("output"))
            if action == "analyze_videos":
                same_round = (
                    global_round is not None
                    and event_input.get("global_round") == global_round
                )
                matching_outcome = any(
                    str(item.get("video_id") or "") == video_id
                    and (
                        not request_id
                        or str(item.get("request_id") or "") == request_id
                    )
                    for item in (
                        _mapping(raw)
                        for raw in _sequence(event_output.get("outcomes"))
                    )
                )
                if same_round or matching_outcome:
                    public_execution_seen = True
                continue
            if public_execution_seen and action in {"decide", "terminal_answer"}:
                selected_action = str(event_output.get("action") or action)
                if selected_action == "terminal_answer":
                    selected_action = "answer"
                next_decision = {
                    "action": selected_action,
                    "parameters": _mapping(event_output.get("parameters")),
                }
                break
        return {
            "public_result": dict(public_effect),
            "next_global_decision": next_decision,
        }

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

    @staticmethod
    def _global_issue_tags(
        *,
        decisions: Sequence[Mapping[str, Any]],
        history: Sequence[Mapping[str, Any]],
        outcome: str,
        inferred_order: bool,
    ) -> tuple[str, ...]:
        tags: list[str] = []
        if inferred_order:
            tags.append("legacy_order_inferred")
        if outcome in {"fail", "partial"}:
            tags.append(f"official_{outcome}")
        actions = [
            str(_mapping(event.get("output")).get("action") or event.get("action") or "")
            for event in decisions
        ]
        if any(
            action == "invalid_decision"
            or str(event.get("status") or "") == "invalid"
            for action, event in zip(actions, decisions, strict=True)
        ) or any(
            item.get("action") == "invalid_decision"
            or str(item.get("status") or "") == "invalid"
            for item in history
        ):
            tags.append("invalid_decision")
        if any(str(item.get("status") or "") in {"error", "partial"} for item in history):
            tags.append("evidence_action_failure")
        if any(first == second for first, second in zip(actions, actions[1:])):
            tags.append("consecutive_same_action")
        return tuple(tags) or ("no_deterministic_issue",)

    @staticmethod
    def _global_episode_issue(*, outcome: str, issue_tags: Sequence[str]) -> str:
        notes: list[str] = []
        if "legacy_order_inferred" in issue_tags:
            notes.append("One or more legacy decisions had no explicit round.")
        if "invalid_decision" in issue_tags:
            notes.append("At least one Global decision was invalid.")
        if "evidence_action_failure" in issue_tags:
            notes.append("At least one public evidence action ended partial or error.")
        if "consecutive_same_action" in issue_tags:
            notes.append("The same action type occurred in consecutive Global rounds.")
        if outcome == "fail":
            notes.append(
                "The final official outcome failed; the complete episode is shown, "
                "but the projection does not pre-assign the cause."
            )
        elif outcome == "partial":
            notes.append("The final official outcome was partial.")
        elif outcome == "pass":
            notes.append("The final official outcome passed; preserve useful behavior.")
        return " ".join(notes) or "No deterministic issue was identified in this episode."

    @staticmethod
    def _video_issue_tags(
        *,
        status: str,
        steps: Sequence[Mapping[str, Any]],
        outcome: str,
        inferred_order: bool,
    ) -> tuple[str, ...]:
        tags: list[str] = []
        if inferred_order:
            tags.append("legacy_order_inferred")
        if status != "ok":
            tags.append("request_failure")
        if any(
            str(_mapping(step.get("result")).get("status") or "")
            not in {"", "ok"}
            for step in steps
        ):
            tags.append("step_failure")
        observe_parameters = [
            _compact(_mapping(step.get("parameters")))
            for step in steps
            if step.get("action") == "observe"
        ]
        if len(observe_parameters) != len(set(observe_parameters)):
            tags.append("repeated_equivalent_observe")
        if outcome in {"fail", "partial"}:
            tags.append(f"downstream_official_{outcome}")
        return tuple(tags) or ("no_deterministic_issue",)

    @staticmethod
    def _video_outcome(outcome: str, issue_tags: Sequence[str]) -> str:
        if outcome not in {"fail", "partial"}:
            return outcome
        attributable = {
            "request_failure",
            "step_failure",
            "repeated_equivalent_observe",
        }
        return outcome if attributable.intersection(issue_tags) else "unattributed"

    @staticmethod
    def _video_issue(
        *,
        status: str,
        steps: Sequence[Mapping[str, Any]],
        outcome: str,
        inferred_order: bool,
    ) -> str:
        notes: list[str] = []
        if inferred_order:
            notes.append("One or more legacy steps had no explicit step number; order was inferred.")
        if status != "ok":
            notes.append(f"The video request ended with status {status}.")
        failed_steps = sum(
            1 for step in steps if str(_mapping(step.get("result")).get("status")) not in {"", "ok"}
        )
        if failed_steps:
            notes.append(f"{failed_steps} local step(s) did not complete successfully.")
        if outcome == "fail":
            notes.append(
                "The downstream official outcome failed and the local request has at "
                "least one deterministic execution or planning symptom."
            )
        elif outcome == "partial":
            notes.append(
                "The downstream official outcome was partial and the local request has "
                "at least one deterministic execution or planning symptom."
            )
        elif outcome == "unattributed":
            notes.append(
                "The downstream official outcome failed, but this local trace has no "
                "deterministic symptom that attributes the failure to this request."
            )
        elif outcome == "pass":
            notes.append("The final official outcome passed; retain useful evidence-planning behavior.")
        return " ".join(notes) or "No deterministic issue was identified from this request alone."

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
