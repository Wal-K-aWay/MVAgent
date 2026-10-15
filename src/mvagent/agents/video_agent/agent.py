from __future__ import annotations
from models.execution import event_scope

import math
from typing import Any, Callable, Mapping

from mvagent.agents.base import BaseAgent
from mvagent.skills import SkillBank
from mvagent.skills.selection import select_skills
from models.vlm.base import VLMClient
from mvagent.utils.media import (
    cut_video_segment,
    fit_video_sampling_fps,
    normalize_fps,
    validate_action_video_ranges,
)
from mvagent.utils.tools import extract_json, json_safe
from mvagent.utils.trace import format_trace_event
from mvagent.utils.trajectory import VideoRunTrajectory

from .memory import VideoAgentMemory
from .prompts import (
    VIDEO_PLANNER_SYSTEM_PROMPT,
    build_video_finish_prompt,
    build_visual_observation_prompt,
    build_video_action_prompt,
)
from .schema import (
    MAX_OBSERVE_FPS,
    MIN_OBSERVE_FPS,
    VISUAL_OBSERVATION_SCHEMA,
    VIDEO_FINISH_SCHEMA,
    build_video_action_schema,
)


class VideoAgent(BaseAgent):
    """Adaptive Observe/Finish loop bound to one question-scoped video."""

    def __init__(
        self,
        *,
        video_id: str,
        video_path: str,
        duration_sec: float,
        planner_model: Any,
        observer_model: Any,
        source_frame_count: int | None = None,
        max_steps: int = 6,
        max_ranges_per_action: int = 8,
        cache_dir: str | None = None,
        logger: Callable[[str], None] | None = None,
        planning_skill: str | SkillBank = "",
        skill_selector_model: Any | None = None,
        skill_selection_scope: str = "decision",
    ) -> None:
        self.video_id = str(video_id)
        self.video_path = str(video_path)
        self.duration_sec = float(duration_sec)
        if not math.isfinite(self.duration_sec) or self.duration_sec <= 0.0:
            raise ValueError("VideoAgent duration_sec must be finite and positive.")
        self.source_frame_count = (
            None if source_frame_count is None else int(source_frame_count)
        )
        if self.source_frame_count is not None and self.source_frame_count <= 0:
            raise ValueError("VideoAgent source_frame_count must be positive.")
        missing_roles = [
            role
            for role, model in (
                ("planner_model", planner_model),
                ("observer_model", observer_model),
            )
            if model is None
        ]
        if missing_roles:
            raise ValueError(
                "VideoAgent requires model clients for: "
                + ", ".join(missing_roles)
            )
        if not isinstance(observer_model, VLMClient):
            raise TypeError(
                "VideoAgent observer_model must be a VLMClient with video "
                "input support."
            )
        super().__init__(
            name=f"VideoAgent[{self.video_id}].Planner",
            model=planner_model,
            system_prompt=VIDEO_PLANNER_SYSTEM_PROMPT,
            logger=logger,
        )
        self._visual_model = observer_model
        self.skill_selector_model = skill_selector_model
        if skill_selection_scope not in ('decision', 'task'):
            raise ValueError('Skill selection scope must be decision or task')
        self.skill_selection_scope = skill_selection_scope
        self._skill_selection_cache = {}
        self._skill_selection_request = None

        self.cache_dir = str(cache_dir) if cache_dir else None
        self.max_steps = max(1, int(max_steps))
        self.max_video_frames_per_request = (
            observer_model.max_video_frames_per_request
        )
        self.max_ranges_per_action = max(1, int(max_ranges_per_action))
        self.planning_skill = planning_skill if isinstance(planning_skill, SkillBank) else str(planning_skill or "").strip()
        self.memory = VideoAgentMemory()
        self._run_trajectory = VideoRunTrajectory()

    @property
    def last_run_steps(self) -> list[dict[str, Any]]:
        """Return trajectory steps from the latest ``run(...)`` call."""
        return self._run_trajectory.to_list()

    def _trace_action(
        self,
        *,
        step_index: int,
        action: str,
        parameters: Mapping[str, Any],
        effective_fps: list[float] | None = None,
        terminal: bool = False,
    ) -> None:
        """Print one validated VideoAgent action."""
        trace_parameters = dict(parameters)
        fields: list[tuple[str, Any]] = [("action", action)]
        if terminal:
            fields.append(("terminal", True))
        if action == "observe":
            trace_parameters.pop("fps", None)
        if trace_parameters:
            fields.append(("parameters", trace_parameters))
        if action == "observe" and effective_fps:
            actual_fps: float | list[float]
            actual_fps = (
                effective_fps[0]
                if len(effective_fps) == 1
                else list(effective_fps)
            )
            fields.append(("fps", actual_fps))
        self._log(
            format_trace_event(
                [f"VideoAgent:{self.video_id}", f"STEP {step_index}"],
                "Action",
                fields=fields,
            )
        )

    def _trace_observations(
        self,
        observations: list[dict[str, Any]],
    ) -> None:
        """Print Runtime-owned observation ranges and visual results."""
        for observation in observations:
            fields: list[tuple[str, Any]] = [
                ("time_range", observation.get("time_range") or []),
            ]
            if observation.get("fps") is not None:
                fields.append(("fps", observation.get("fps")))
            self._log(
                format_trace_event(
                    [f"VideoAgent:{self.video_id}"],
                    "Observation",
                    fields=fields,
                    blocks=[("text", observation.get("text") or "")],
                )
            )

    def _trace_report(self, report: str) -> None:
        """Print one completed public report."""
        self._log(
            format_trace_event(
                [f"VideoAgent:{self.video_id}"],
                "Report",
                blocks=[("report", report)],
            )
        )

    def run(self, instruction: str) -> dict[str, str]:
        """Plan and observe, then return one small status-bearing result."""
        self._run_trajectory = VideoRunTrajectory()
        request_id = self.memory.begin_request(instruction)
        try:
            with event_scope(request_id=request_id):
                return self._run_request(instruction=instruction, request_id=request_id)
        except Exception as exc:
            error = str(exc).strip() or type(exc).__name__
            last_step = self._run_trajectory.last or {}
            if (last_step.get("result") or {}).get("status") not in {
                "error",
                "invalid",
                "partial",
            }:
                self._record_step(
                    action="runtime",
                    parameters={},
                    status="error",
                    error=error,
                )
            return {
                "request_id": request_id,
                "status": "error",
                "report": "",
                "error": error,
            }

    def _run_request(
        self,
        *,
        instruction: str,
        request_id: str,
    ) -> dict[str, str]:
        """Execute one already-created request within the bounded loop."""
        for round_index in range(self.max_steps):
            step_index = round_index + 1
            try:
                result = self._call_planner(
                    instruction=instruction,
                    request_id=request_id,
                )
            except Exception as exc:
                self._record_step(
                    action="decide",
                    parameters={},
                    status="error",
                    error=str(exc).strip() or type(exc).__name__,
                )
                raise
            if result.get("status") != "ok":
                attempted_action, attempted_parameters = (
                    self._structured_decision_attempt(result)
                )
                self._record_step(
                    action=attempted_action,
                    parameters=attempted_parameters,
                    status="invalid",
                    error=str(result.get("error") or "Invalid structured output."),
                    record_in_memory=False,
                )
                continue
            decision = result.get("value")
            if not isinstance(decision, Mapping):
                raise TypeError("Successful VideoAgent decision must be an object.")
            action_name = str(decision.get("action") or "")
            raw_parameters = decision.get("parameters")
            parameters = (
                dict(raw_parameters)
                if isinstance(raw_parameters, Mapping)
                else {"raw_parameters": json_safe(raw_parameters)}
            )

            if action_name == "finish":
                try:
                    return self._finish_result(
                        parameters=parameters,
                        request_id=request_id,
                        step_index=step_index,
                    )
                except (KeyError, TypeError, ValueError) as exc:
                    self._record_step(
                        action="finish",
                        parameters=parameters,
                        status="invalid",
                        error=str(exc),
                    )
                    continue

            try:
                if action_name != "observe":
                    raise ValueError(
                        f"Unsupported VideoAgent action: {action_name}"
                    )
                prepared = self._prepare_observe(parameters)
            except (KeyError, TypeError, ValueError) as exc:
                self._record_step(
                    action=action_name or "invalid_decision",
                    parameters=parameters,
                    request_id=(
                        request_id if action_name == "observe" else None
                    ),
                    status=("error" if action_name == "observe" else "invalid"),
                    error=str(exc),
                )
                continue

            self._trace_action(
                step_index=step_index,
                action="observe",
                parameters=prepared["parameters"],
                effective_fps=prepared["effective_fps"],
            )
            observations, raw_execution_errors = self._execute_observe(prepared)
            execution_errors = self._normalize_execution_errors(
                raw_execution_errors
            )
            self._trace_observations(observations)
            status = (
                "ok"
                if observations and not execution_errors
                else ("partial" if observations else "error")
            )
            self._record_step(
                action="observe",
                parameters=prepared["parameters"],
                request_id=request_id,
                status=status,
                error="; ".join(
                    execution_errors
                ),
                errors=execution_errors,
                observations=observations,
            )

        return self._request_terminal_finish(
            instruction=instruction,
            request_id=request_id,
        )

    def _finish_result(
        self,
        *,
        parameters: Mapping[str, Any],
        request_id: str,
        step_index: int,
        terminal: bool = False,
    ) -> dict[str, str]:
        """Validate Finish and produce the active request's public report."""
        summary = str(parameters.get("summary") or "").strip()
        if not summary:
            raise ValueError("finish requires a non-empty summary.")
        self.memory.add_summary(
            request_id=request_id,
            summary=summary,
        )
        report = self.memory.render_report()
        self._trace_action(
            step_index=step_index,
            action="finish",
            parameters={},
            terminal=terminal,
        )
        self._record_step(
            action="finish",
            parameters=parameters,
            status="ok",
            report=report,
            terminal=terminal,
        )
        self._trace_report(report)
        return {
            "request_id": request_id,
            "status": "ok",
            "report": report,
            "error": "",
        }

    def _prepare_observe(
        self,
        parameters: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Validate one Observe decision into a small execution dictionary."""
        ranges = validate_action_video_ranges(
            parameters["where"],
            mode="observe",
            duration_sec=self.duration_sec,
            max_ranges=self.max_ranges_per_action,
        )
        what = str(parameters["what"]).strip()
        if not what:
            raise ValueError("observe requires a non-empty what.")
        planned_fps = normalize_fps(
            parameters["fps"],
            minimum=MIN_OBSERVE_FPS,
            maximum=MAX_OBSERVE_FPS,
        )
        effective_fps = [
            self._effective_fps(planned_fps, end - start)
            for start, end in ranges
        ]
        normalized = {"what": what, "where": ranges, "fps": planned_fps}
        return {
            "parameters": normalized,
            "ranges": ranges,
            "effective_fps": effective_fps,
        }

    def _execute_observe(
        self,
        prepared: Mapping[str, Any],
    ) -> tuple[list[dict[str, Any]], list[str]]:
        observations: list[dict[str, Any]] = []
        errors: list[str] = []
        parameters = prepared["parameters"]
        for time_range, fps in zip(
            prepared["ranges"], prepared["effective_fps"]
        ):
            try:
                observations.append(
                    self._observe_range(
                        what=str(parameters["what"]),
                        time_range=list(time_range),
                        fps=float(fps),
                    )
                )
            except Exception as exc:
                errors.append(str(exc).strip() or type(exc).__name__)
        return observations, errors

    def _observe_range(
        self,
        *,
        what: str,
        time_range: list[float],
        fps: float,
    ) -> dict[str, Any]:
        video_input = self._video_input_path(time_range, fps)
        result = self._visual_model.json_on_video(
            video_path=video_input,
            video_id=self.video_id,
            text_prompt=build_visual_observation_prompt(
                what=what,
                duration_sec=self.duration_sec,
                time_range=time_range,
                fps=fps,
            ),
            fps=fps,
            json_schema=VISUAL_OBSERVATION_SCHEMA,
            schema_name="visual_observation",
        )
        if result.get("status") != "ok":
            raise ValueError(
                str(result.get("error") or "Invalid visual observation output.")
            )
        visual = result.get("value")
        if not isinstance(visual, Mapping):
            raise TypeError("Successful visual observation must be an object.")
        text = str(visual.get("text") or "").strip()
        if not text:
            raise ValueError("Observer returned empty observation text.")
        return {
            "time_range": list(time_range),
            "fps": fps,
            "text": text,
            "uncertainty": str(visual.get("uncertainty") or "").strip(),
        }

    def _video_input_path(
        self,
        time_range: list[float],
        fps: float,
    ) -> str:
        requires_temporal_padding = (
            (float(time_range[1]) - float(time_range[0])) * float(fps)
            < 2.0 - 1e-9
            or (
                self.source_frame_count is not None
                and self.source_frame_count < 2
            )
        )
        if (
            not requires_temporal_padding
            and float(time_range[0]) <= 1e-6
            and float(time_range[1]) >= self.duration_sec - 1e-6
        ):
            return self.video_path
        return cut_video_segment(
            self.video_path,
            time_range,
            output_dir=self.cache_dir,
            prefix=f"{self.video_id}_observe",
            sampling_fps=fps,
        )

    def _effective_fps(self, planned_fps: float, duration_sec: float) -> float:
        if not math.isfinite(duration_sec) or duration_sec <= 0.0:
            raise ValueError("Observe range duration must be positive.")
        return fit_video_sampling_fps(
            planned_fps,
            duration_sec=duration_sec,
            max_frames=self.max_video_frames_per_request,
            maximum_fps=MAX_OBSERVE_FPS,
        )

    def _call_planner(self, *, instruction, request_id):
        decision_id = f"video:{self.video_id}:{request_id}:{len(self._run_trajectory.to_list()) + 1}"
        with event_scope(decision_id=decision_id):
            return self._call_planner_impl(instruction=instruction, request_id=request_id)

    def _call_planner_impl(
        self,
        *,
        instruction: str,
        request_id: str,
    ) -> dict[str, Any]:
        """Run the VideoAgent's integrated Planner once."""
        action_names = ["observe"]
        if self.memory.has_observations:
            action_names.append("finish")
        memory_view = self.memory.render_planner_view(request_id=request_id)
        decision_feedback = self._render_decision_feedback()
        if decision_feedback:
            memory_view = (
                f"{memory_view}\n\n{decision_feedback}"
                if memory_view != "(none)"
                else decision_feedback
            )
        if self._skill_selection_request != request_id:
            self._skill_selection_cache.clear()
            self._skill_selection_request = request_id
        skill = self.planning_skill
        if isinstance(skill, SkillBank):
            selection = select_skills(skill,
                selection_cache=self._skill_selection_cache if self.skill_selection_scope == 'task' else None,
                role="video", has_evidence=self.memory.has_observations,
                task=instruction, state=dict(history=memory_view),
                decide=(self.decide_json if self.skill_selector_model is None else
                        lambda *args, **kwargs: self.decide_json(*args, model=self.skill_selector_model, **kwargs)))
            if selection["status"] != "ok":
                return selection
            skill = selection["value"]
        prompt = build_video_action_prompt(
            instruction=instruction,
            duration_sec=self.duration_sec,
            max_video_frames_per_request=(
                self.max_video_frames_per_request
            ),
            available_action_names=action_names,
            memory_view=memory_view,
            max_ranges_per_action=self.max_ranges_per_action,
            planning_skill=skill,
        )
        return self.decide_json(
            prompt,
            json_schema=build_video_action_schema(
                action_names,
                duration_sec=self.duration_sec, max_ranges=self.max_ranges_per_action,
            ),
            schema_name="video_action",
        )

    def _request_terminal_finish(
        self,
        *,
        instruction: str,
        request_id: str,
    ) -> dict[str, str]:
        """Request one text-only Finish after the ordinary loop is exhausted."""
        stop_reason = "Reached VideoAgent max_steps."
        if not self.memory.has_observations:
            return self._stop_without_finish(
                request_id=request_id,
                stop_reason=stop_reason,
            )
        try:
            result = self.decide_json(
                build_video_finish_prompt(
                    instruction=instruction,
                    memory_view=self.memory.render_planner_view(
                        request_id=request_id
                    ),
                ),
                json_schema=VIDEO_FINISH_SCHEMA,
                schema_name="video_finish",
                system_prompt="",
            )
        except Exception as exc:
            terminal_error = str(exc).strip() or type(exc).__name__
            self._record_step(
                action="finish",
                parameters={},
                status="error",
                error=terminal_error,
                terminal=True,
            )
            return self._stop_without_finish(
                request_id=request_id,
                stop_reason=stop_reason,
                terminal_error=terminal_error,
            )
        if result.get("status") != "ok":
            terminal_error = str(
                result.get("error") or "Invalid structured output."
            )
            self._record_step(
                action="finish",
                parameters={},
                status="invalid",
                error=terminal_error,
                terminal=True,
                record_in_memory=False,
            )
            return self._stop_without_finish(
                request_id=request_id,
                stop_reason=stop_reason,
                terminal_error=terminal_error,
            )
        parameters = result.get("value")
        if not isinstance(parameters, Mapping):
            raise TypeError("Successful terminal Finish must be an object.")
        try:
            return self._finish_result(
                parameters=parameters,
                request_id=request_id,
                step_index=self.max_steps + 1,
                terminal=True,
            )
        except (KeyError, TypeError, ValueError) as exc:
            terminal_error = str(exc).strip() or type(exc).__name__
            self._record_step(
                action="finish",
                parameters=parameters,
                status="invalid",
                error=terminal_error,
                terminal=True,
            )
            return self._stop_without_finish(
                request_id=request_id,
                stop_reason=stop_reason,
                terminal_error=terminal_error,
            )

    def _stop_without_finish(
        self,
        *,
        request_id: str,
        stop_reason: str,
        terminal_error: str = "",
    ) -> dict[str, str]:
        """Return execution feedback without exposing private observations."""
        has_observations = self.memory.has_observations
        status = "partial" if has_observations else "error"
        if terminal_error:
            error = f"{stop_reason} Terminal Finish failed: {terminal_error}"
        elif has_observations:
            error = (
                f"{stop_reason} An observation exists, but no Finish "
                "summary was produced."
            )
        else:
            error = f"{stop_reason} No observation was produced."
        self._log(
            format_trace_event(
                [f"VideoAgent:{self.video_id}"],
                "Incomplete",
                fields=[("status", status)],
                blocks=[("error", error)],
            )
        )
        return {
            "request_id": request_id,
            "status": status,
            "report": "",
            "error": error,
        }

    def _record_step(
        self,
        *,
        action: str,
        parameters: Mapping[str, Any],
        status: str,
        request_id: str | None = None,
        error: str = "",
        errors: list[str] | None = None,
        observations: list[dict[str, Any]] | None = None,
        report: str | None = None,
        terminal: bool = False,
        record_in_memory: bool | None = None,
    ) -> None:
        """Record Observe in Memory and every action in run trajectory."""
        normalized_status = str(status)
        if normalized_status in {"error", "invalid", "partial"}:
            if not str(error or "").strip():
                raise ValueError(
                    "Failed VideoAgent step requires an error message."
                )
        result: dict[str, Any] = {"status": normalized_status}
        if terminal:
            result["terminal"] = True
        if observations:
            result["observations"] = json_safe(observations)
        if error:
            result["error"] = str(error)
        if errors:
            result["errors"] = json_safe(errors)
        if report is not None:
            result["report"] = str(report)
        action_record = {
            "action": str(action),
            "parameters": json_safe(dict(parameters)),
            "result": result,
        }
        should_record_in_memory = (
            action == "observe"
            if record_in_memory is None
            else bool(record_in_memory)
        )
        if should_record_in_memory:
            if action != "observe":
                raise ValueError("Only Observe can enter VideoAgent memory.")
            if request_id is None:
                raise ValueError("Observe recording requires request_id.")
            self.memory.add_action(action_record, request_id=request_id)
            action_record = self.memory.actions[-1]
        self._run_trajectory.record(action_record)

    @staticmethod
    def _structured_decision_attempt(
        result: Mapping[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        """Recover a truthful attempted action from one safe model response."""
        raw_response = str(result.get("raw_response") or "").strip()
        if not raw_response:
            return "invalid_decision", {}
        try:
            parsed = extract_json(raw_response)
        except ValueError:
            return "invalid_decision", {"raw_response": raw_response}
        if not isinstance(parsed, Mapping):
            return "invalid_decision", {"raw_response": raw_response}
        action = str(parsed.get("action") or "").strip()
        raw_parameters = parsed.get("parameters")
        parameters = (
            dict(raw_parameters)
            if isinstance(raw_parameters, Mapping)
            else {"raw_parameters": json_safe(raw_parameters)}
        )
        return action or "invalid_decision", json_safe(parameters)

    @staticmethod
    def _normalize_execution_errors(
        errors: list[Any],
    ) -> list[str]:
        """Normalize overridden/test Observe executors to the current contract."""
        normalized: list[str] = []
        for item in errors:
            if isinstance(item, Mapping):
                error = str(item.get("error") or "").strip()
            else:
                error = str(item or "").strip()
            normalized.append(error or "Observe execution failed.")
        return normalized

    def _render_decision_feedback(self) -> str:
        """Render current-run invalid attempts without treating them as evidence."""
        lines: list[str] = []
        memory_actions = self.memory.actions
        for step in self._run_trajectory:
            action_record = {
                key: value
                for key, value in step.items()
                if key != "step"
            }
            if action_record in memory_actions:
                continue
            result = step.get("result") or {}
            if result.get("status") != "invalid":
                continue
            action = str(step.get("action") or "invalid_decision")
            error = str(result.get("error") or "").strip()
            if len(error) > 600:
                error = f"{error[:597].rstrip()}..."
            lines.append(
                f"- Attempted action `{action}` was rejected "
                f": {error or 'No error detail was recorded.'}"
            )
        if not lines:
            return ""
        return "### Current Request Decision Feedback\n" + "\n".join(lines)


__all__ = ["VideoAgent"]
