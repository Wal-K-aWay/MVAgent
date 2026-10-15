from __future__ import annotations

import json
import math
import time
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from models.execution import event_scope, emit_event
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Callable

from mvagent.agents import GlobalAgent, VideoAgent
from mvagent.configs import MVAgentConfig
from models.factory import ModelFactory
from mvagent.runtime import RuntimeResources
from mvagent.skills import load_skill, SkillBank
from mvagent.utils.media import probe_video_info
from mvagent.utils.tools import (
    cleanup_run_cache_dir,
    json_safe,
    normalize_video_map,
    prepare_run_dirs,
)
from mvagent.utils.trace import (
    format_trace_event,
    format_watch_video_results,
    format_watch_video_selections,
)
from mvagent.utils.trajectory import QuestionTrajectory


Trajectory = QuestionTrajectory | list[dict[str, Any]]


class MVAgentEngine:
    """Question-scoped two-level runtime over reusable model clients."""

    def __init__(
        self,
        cfg: MVAgentConfig,
        *,
        logger: Callable[[str], None] | None = None,
    ) -> None:
        """Initialize the engine and reusable model state.

        Args:
            cfg: Parsed MVAgent runtime configuration.
            logger: Optional sink for complete formatted trace events.
        """
        self.cfg = cfg
        self.cache_dir = Path(cfg.runtime.cache_dir).expanduser().resolve()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.run_cache_dir: str | None = None
        self.video_paths: dict[str, str] = {}
        self.global_skill = self._load_configured_skill(cfg.global_agent.skill)
        self.video_skill = self._load_configured_skill(cfg.video_agent.skill)

        self._log: Callable[[str], None] = logger or (
            lambda message: print(message, flush=True)
        )
        self.resources = RuntimeResources(
            cfg,
            model_builder=lambda model_ref: ModelFactory.create_model(
                model_ref=model_ref,
                config=cfg,
            ),
        )

    @staticmethod
    def _load_configured_skill(skill_config: Any) -> str | SkillBank:
        """Load a frozen Skill policy exactly once per Engine."""
        if skill_config is None or not skill_config.enabled:
            return ""
        if skill_config.mode == "dynamic":
            return SkillBank.load(path=skill_config.path, sha256=skill_config.sha256,
                                  retrieval_top_k=skill_config.retrieval_top_k,
                                  embedding=skill_config.embedding)
        return load_skill(
            path=skill_config.path,
            sha256=skill_config.sha256,
        )

    def resolve_models(self) -> dict[str, dict[str, str]]:
        """Eagerly resolve models referenced by both agent layers.

        Returns:
            Runtime status metadata for all resolved model instances.
        """
        return self.resources.resolve_models()

    def _skill_selector_model(self, skill_config: Any) -> Any:
        if (skill_config is not None and skill_config.enabled and skill_config.mode == "dynamic"
                and skill_config.selector is not None):
            return self.resources.get_model(skill_config.selector)
        return None

    def close(self) -> None:
        """Release owned model clients without stopping persistent services.

        Shared local vLLM services intentionally survive Engine shutdown.
        Client close failures are ignored so remaining clients are still
        released.
        """
        self.resources.close()

    def _cleanup_run_cache(self) -> None:
        """Remove the current question cache and clear its stored path."""
        cleanup_run_cache_dir(self.run_cache_dir)
        self.run_cache_dir = None

    def _preprocess(
        self,
        *,
        videos: Mapping[str, str],
        question: str,
        output_dir: str,
    ) -> tuple[GlobalAgent, dict[str, VideoAgent]]:
        """Prepare all question-scoped runtime objects.

        This method validates and resolves video paths, creates the output and
        cache directories, and builds both agent layers. It also replaces any
        previous question state stored by the Engine.

        Args:
            videos: Insertion-ordered stable video IDs mapped to local paths.
            question: Complete model-facing question, including options when
                present.
            output_dir: Directory for persistent outputs of this question.

        Returns:
            The GlobalAgent and ordered VideoAgent mapping.

        Raises:
            ValueError: If the video mapping contains invalid identities or
                paths.
        """
        self._cleanup_run_cache()

        resolved_video_paths = normalize_video_map(videos)
        self._log(
            format_trace_event(
                ["RUN"],
                "Start question",
                fields=[
                    ("video_ids", list(resolved_video_paths)),
                    ("video_count", len(resolved_video_paths)),
                ],
                blocks=[("question", question)],
            )
        )
        self.video_paths = dict(resolved_video_paths)
        cache_path = prepare_run_dirs(
            output_dir=output_dir,
            cache_dir=self.cache_dir,
        )
        self.run_cache_dir = str(cache_path)

        video_cfg = self.cfg.video_agent
        planner_model = self.resources.get_model(video_cfg.planner)
        observer_model = self.resources.get_model(video_cfg.observer)

        video_metadata: dict[str, dict[str, float | int]] = {}
        for video_id, video_path in resolved_video_paths.items():
            info = probe_video_info(video_path)
            duration_sec = float(info.get("duration_sec") or 0.0)
            source_fps = float(info.get("fps") or 0.0)
            frame_count = int(info.get("frame_count") or 0)
            if (
                not math.isfinite(duration_sec)
                or not math.isfinite(source_fps)
                or duration_sec <= 0.0
                or source_fps <= 0.0
                or frame_count <= 0
            ):
                raise ValueError(
                    f"Cannot determine valid video metadata: {video_id}"
                )
            video_metadata[video_id] = {
                "duration_sec": duration_sec,
                "fps": source_fps,
                "frame_count": frame_count,
            }

        self.video_metadata = video_metadata
        global_agent = GlobalAgent(
            video_ids=list(resolved_video_paths),
            question=question,
            model=self.resources.get_model(self.cfg.global_agent.model),
            visual_model=observer_model,
            video_metadata=video_metadata,
            video_paths=resolved_video_paths,
            cache_dir=self.run_cache_dir,
            max_videos_per_watch=(
                self.cfg.global_agent.max_videos_per_watch
            ),
            decision_skill=self.global_skill,
            skill_selector_model=self._skill_selector_model(self.cfg.global_agent.skill),
            skill_selection_scope=self.cfg.global_agent.skill.selection_scope if self.cfg.global_agent.skill else "decision",
        )

        video_agents = {
            video_id: VideoAgent(
                video_id=video_id,
                video_path=video_path,
                duration_sec=video_metadata[video_id]["duration_sec"],
                source_frame_count=int(
                    video_metadata[video_id]["frame_count"]
                ),
                planner_model=planner_model,
                observer_model=observer_model,
                max_steps=video_cfg.max_steps,
                max_ranges_per_action=video_cfg.max_ranges_per_action,
                cache_dir=self.run_cache_dir,
                logger=self._log,
                planning_skill=self.video_skill,
                skill_selector_model=self._skill_selector_model(video_cfg.skill),
                skill_selection_scope=video_cfg.skill.selection_scope if video_cfg.skill else "decision",
            )
            for video_id, video_path in resolved_video_paths.items()
        }

        return global_agent, video_agents

    def _postprocess(
        self,
        *,
        question: str,
        global_agent: GlobalAgent,
        answer: dict[str, Any],
        trajectory: Trajectory,
        stop_reason: str,
        start_time: float,
    ) -> dict[str, Any]:
        """Log completion and assemble the stable Engine result payload.

        Args:
            question: Complete model-facing question.
            global_agent: Question-scoped GlobalAgent containing final memory.
            answer: Final answer, reason, and status fields.
            trajectory: Ordered runtime trajectory accumulated by the Engine.
            stop_reason: Final answer reason for an ordinary answer, or the
                Runtime-owned limit reason for terminal best effort.
            start_time: Monotonic start time captured before preprocessing.

        Returns:
            The JSON-safe result payload returned by :meth:`answer`.
        """
        duration = round(time.perf_counter() - start_time, 2)
        self._log(
            format_trace_event(
                ["RUN"],
                "Completed",
                fields=[
                    ("answer", answer.get("answer") or ""),
                    ("stop_reason", stop_reason),
                    ("runtime", f"{duration}s"),
                ],
            )
        )
        return {
            "input": {
                "question": question,
                "videos": dict(self.video_paths),
            },
            "video_metadata": json_safe(self.video_metadata),
            "video_reports": json_safe(global_agent.memory.reports),
            "watch_results": json_safe(global_agent.memory.watch_results),
            "action_history": json_safe(global_agent.memory.action_history),
            "answer": json_safe(answer),
            "trajectory": QuestionTrajectory.wrap(trajectory).to_list(),
            "stop_reason": stop_reason,
            "time": duration,
        }

    def answer(
        self,
        *,
        videos: Mapping[str, str],
        question: str,
        output_dir: str,
    ) -> dict[str, Any]:
        """Answer one multi-video question through the bounded agent loop.

        The method orchestrates preprocessing, GlobalAgent decisions, targeted
        VideoAgent execution, and postprocessing. Question cache files are
        removed in all success and failure paths.

        Args:
            videos: Insertion-ordered stable video IDs mapped to local paths.
            question: Complete model-facing question, including options when
                present.
            output_dir: Directory for persistent outputs of this question.

        Returns:
            A JSON-safe result containing inputs, evidence, answer, trajectory,
            stop reason, and elapsed time.

        Raises:
            ValueError: If question inputs violate runtime contracts.
            RuntimeError: If a required runtime operation cannot complete.
        """
        start_time = time.perf_counter()
        trajectory = QuestionTrajectory()

        try:
            global_agent, video_agents = self._preprocess(
                videos=videos,
                question=question,
                output_dir=output_dir,
            )
            answer, stop_reason = self._run_global_loop(
                global_agent=global_agent,
                video_agents=video_agents,
                trajectory=trajectory,
            )
            return self._postprocess(
                question=question,
                global_agent=global_agent,
                answer=answer,
                trajectory=trajectory,
                stop_reason=stop_reason,
                start_time=start_time,
            )
        finally:
            self._cleanup_run_cache()

    def _run_global_loop(
        self,
        *,
        global_agent: GlobalAgent,
        video_agents: dict[str, VideoAgent],
        trajectory: Trajectory,
    ) -> tuple[dict[str, Any], str]:
        """Drive the bounded GlobalAgent action loop.

        Args:
            global_agent: Question-scoped cross-video coordinator.
            video_agents: Available VideoAgents keyed by stable video ID.
            trajectory: Mutable trajectory receiving all runtime steps.

        Returns:
            A tuple containing the final answer payload and stop reason.

        Raises:
            RuntimeError: If the Planner or another required infrastructure
                dependency cannot complete. Deterministic model-output and
                action-parameter errors are recorded and retried in-loop.
        """
        max_decisions = max(1, int(self.cfg.global_agent.max_steps))
        question_trajectory = QuestionTrajectory.wrap(trajectory)

        def record_decision(
            decision: dict[str, Any],
            global_round: int,
        ) -> None:
            """Record and print one validated decision from this loop."""
            question_trajectory.record(
                agent="GlobalAgent",
                action="decide",
                round_index=global_round,
                output=decision,
            )
            parameters = decision["parameters"]
            fields: list[tuple[str, Any]] = [
                ("action", decision["action"]),
            ]
            answer = str(parameters.get("answer") or "").strip()
            if answer:
                fields.append(("answer", answer))
            fields.append(("reason", decision["reason"]))

            blocks: list[tuple[str, Any]] = []
            if parameters.get("videoagent_request"):
                blocks.append(
                    (
                        "videoagent_request",
                        json.dumps(
                            parameters["videoagent_request"],
                            ensure_ascii=False,
                            indent=2,
                        ),
                    )
                )
            if decision["action"] == "watch_videos":
                blocks.append(
                    (
                        "instruction",
                        parameters["instruction"],
                    )
                )
                blocks.append(
                    (
                        "videos",
                        format_watch_video_selections(parameters["videos"]),
                    )
                )
            self._log(
                format_trace_event(
                    [f"ROUND {global_round}", "GlobalAgent"],
                    "Decision",
                    fields=fields,
                    blocks=blocks,
                )
            )

        def record_invalid_decision(
            attempt: Mapping[str, Any],
            global_round: int,
        ) -> None:
            """Record one recoverable model decision failure and its feedback."""
            error_text = str(attempt.get("error") or "").strip()
            parsed_value = attempt.get("parsed_decision")
            parsed_decision = (
                dict(parsed_value)
                if isinstance(parsed_value, Mapping)
                else None
            )
            raw_response = str(attempt.get("raw_response") or "").strip()
            global_agent.add_invalid_decision(
                error=error_text,
                parsed_decision=parsed_decision,
                raw_response=raw_response,
            )
            recorded_attempt: dict[str, Any] = {
                "status": "invalid",
                "error": error_text,
                "available_video_ids": list(global_agent.video_ids),
            }
            if parsed_decision is not None:
                recorded_attempt["parsed_decision"] = parsed_decision
            if raw_response:
                recorded_attempt["raw_response"] = raw_response
            question_trajectory.record(
                agent="GlobalAgent",
                action="decide",
                round_index=global_round,
                output=recorded_attempt,
            )
            self._log(
                format_trace_event(
                    [f"ROUND {global_round}", "GlobalAgent"],
                    "Invalid decision",
                    fields=[
                        ("available_video_ids", global_agent.video_ids),
                    ],
                    blocks=[("error", error_text)],
                )
            )

        for global_round in range(1, max_decisions + 1):
            self._log(
                format_trace_event(
                    [f"ROUND {global_round}"],
                    "",
                )
            )
            try:
                with event_scope(agent="GlobalAgent", decision_id=f"global:{global_round}"):
                    attempt = global_agent.decide()
            except Exception as exc:
                error = str(exc).strip() or type(exc).__name__
                question_trajectory.record(
                    agent="GlobalAgent",
                    action="decide",
                    round_index=global_round,
                    output={
                        "status": "error",
                        "error": error,
                    },
                )
                raise
            if attempt.get("status") != "ok":
                record_invalid_decision(attempt, global_round)
                continue
            decision = dict(attempt["decision"])
            record_decision(decision, global_round)

            action = str(decision["action"])
            parameters = decision["parameters"]
            if action == "answer":
                return self._request_terminal_answer(
                    global_agent=global_agent, trajectory=trajectory,
                    round_index=global_round, forced=False,
                )

            if action == "analyze_videos":
                self._execute_analyze_videos_action(
                    global_agent=global_agent,
                    video_agents=video_agents,
                    videoagent_request=list(
                        parameters["videoagent_request"]
                    ),
                    trajectory=trajectory,
                    global_round=global_round,
                )
            elif action == "watch_videos":
                self._execute_watch_videos_action(
                    global_agent=global_agent,
                    instruction=parameters["instruction"],
                    videos=parameters["videos"],
                    trajectory=trajectory,
                    global_round=global_round,
                )
            else:
                raise ValueError(f"Unknown GlobalAgent action: {action}")

        return self._request_terminal_answer(
            global_agent=global_agent,
            trajectory=trajectory,
            round_index=max_decisions + 1,
        )

    def _execute_analyze_videos_action(
        self,
        *,
        global_agent: GlobalAgent,
        video_agents: dict[str, VideoAgent],
        videoagent_request: list[dict[str, str]],
        trajectory: Trajectory,
        global_round: int,
    ) -> None:
        """Execute and record one analyze_videos action."""
        instructions = {
            request["video_id"]: request["instruction"]
            for request in videoagent_request
        }
        outcomes = self._run_video_agents(
            video_agents=video_agents,
            instructions=instructions,
            trajectory=trajectory,
            global_round=global_round,
        )
        statuses = [outcome["status"] for outcome in outcomes]
        status = (
            "ok"
            if all(item == "ok" for item in statuses)
            else (
                "partial"
                if any(item in {"ok", "partial"} for item in statuses)
                else "error"
            )
        )
        global_agent.add_action(
            action="analyze_videos",
            parameters={"videoagent_request": videoagent_request},
            status=status,
            outcomes=outcomes,
        )
        QuestionTrajectory.wrap(trajectory).record(
            agent="GlobalAgent",
            action="analyze_videos",
            input={
                "videoagent_request": videoagent_request,
                "global_round": global_round,
            },
            output={
                "status": status,
                "outcomes": outcomes,
            },
        )

    def _execute_watch_videos_action(
        self,
        *,
        global_agent: GlobalAgent,
        instruction: str,
        videos: list[dict[str, Any]],
        trajectory: Trajectory,
        global_round: int,
    ) -> None:
        """Execute and record one watch_videos action."""
        action_input = {
            "instruction": instruction,
            "videos": videos,
            "global_round": global_round,
        }
        action_parameters = {"instruction": instruction, "videos": videos}
        try:
            result = global_agent.watch_videos(
                instruction=instruction,
                videos=videos,
            )
        except Exception as exc:
            error = str(exc).strip() or type(exc).__name__
            global_agent.add_action(
                action="watch_videos",
                parameters=action_parameters,
                status="error",
                error=error,
            )
            QuestionTrajectory.wrap(trajectory).record(
                agent="GlobalAgent",
                action="watch_videos",
                input=action_input,
                output={
                    "status": "error",
                    "error": error,
                },
            )
            self._log(
                format_trace_event(
                    [f"ROUND {global_round}", "GlobalAgent"],
                    "watch_videos error",
                    blocks=[("error", error)],
                )
            )
            return
        global_agent.add_action(
            action="watch_videos",
            parameters=action_parameters,
            status="ok",
            results=result,
        )
        QuestionTrajectory.wrap(trajectory).record(
            agent="GlobalAgent",
            action="watch_videos",
            input=action_input,
            output=result,
        )
        self._log(
            format_trace_event(
                [f"ROUND {global_round}", "GlobalAgent"],
                "watch_videos result",
                fields=[("fps", result.get("fps"))],
                blocks=[
                    (
                        "videos",
                        format_watch_video_results(result.get("videos") or []),
                    ),
                    ("text", result.get("text") or ""),
                ],
            )
        )

    def _run_video_agents(self, *, video_agents, instructions, trajectory, global_round):
        def run(video_id, instruction):
            with event_scope(agent="VideoAgent", video_id=video_id, global_round=global_round):
                emit_event("video_run_start")
                try:
                    return video_agents[video_id].run(str(instruction))
                finally:
                    emit_event("video_run_end")

        with ThreadPoolExecutor(max_workers=self.cfg.runtime.video_concurrency) as pool:
            runs = {video_id: pool.submit(copy_context().run, run, video_id, instruction)
                    for video_id, instruction in instructions.items()}
            return MVAgentEngine._collect_video_agents(self, video_agents=video_agents, instructions=instructions,
                                              trajectory=trajectory, global_round=global_round, runs=runs)

    def _collect_video_agents(
        self,
        *,
        video_agents: dict[str, VideoAgent],
        instructions: dict[str, str],
        trajectory: Trajectory,
        global_round: int,
        runs,
    ) -> list[dict[str, str]]:
        """Collect independently executed VideoAgents in request order.

        Each VideoAgent failure is isolated so later requested videos still
        run. Every invocation produces one ordered status-bearing outcome.

        Args:
            video_agents: All question-scoped VideoAgents keyed by video ID.
            instructions: Requested video IDs mapped to local instructions.
            trajectory: Mutable trajectory receiving one entry per invocation.
            global_round: One-based GlobalAgent decision round.

        Returns:
            Ordered per-video outcomes. Successful outcomes contain a report;
            partial/error outcomes contain an error message.

        Raises:
            KeyError: If initialized VideoAgents do not contain a requested ID.
        """
        outcomes: list[dict[str, str]] = []
        question_trajectory = QuestionTrajectory.wrap(trajectory)

        for video_id, instruction in instructions.items():
            agent = video_agents[video_id]
            self._log(
                format_trace_event(
                    [
                        f"ROUND {global_round}",
                        f"VideoAgent:{video_id}",
                    ],
                    "Start",
                    blocks=[
                        (
                            "instruction",
                            instruction,
                        )
                    ],
                )
            )
            try:
                run_result = runs[video_id].result()
                if not isinstance(run_result, Mapping):
                    raise TypeError("VideoAgent run result must be an object.")
                run_status = str(run_result.get("status") or "").strip()
                request_id = str(
                    run_result.get("request_id") or ""
                ).strip()
                report = str(run_result.get("report") or "").strip()
                run_error = str(run_result.get("error") or "").strip()
                if not request_id:
                    raise ValueError(
                        "VideoAgent run result requires a request_id."
                    )
                if run_status == "ok":
                    if not report:
                        raise ValueError(
                            "Completed VideoAgent run requires a report."
                        )
                elif run_status in {"partial", "error"}:
                    if not run_error:
                        raise ValueError(
                            "Incomplete VideoAgent run requires an error message."
                        )
                else:
                    raise ValueError(
                        f"Unsupported VideoAgent run status: {run_status}"
                    )
            except Exception as exc:
                run_status = "error"
                request_id = ""
                run_error = str(exc).strip() or type(exc).__name__

            run_steps = getattr(agent, "last_run_steps", None)
            step_delta = run_steps if isinstance(run_steps, list) else []
            outcome = {
                "video_id": video_id,
                "instruction": str(instruction),
                "request_id": request_id,
                "status": run_status,
            }
            if run_status in {"partial", "error"}:
                outcome["error"] = run_error
                outcomes.append(outcome)
                question_trajectory.record(
                    agent="VideoAgent",
                    video_id=video_id,
                    action="run",
                    input={
                        "instruction": instruction,
                        "global_round": global_round,
                    },
                    output={
                        "request_id": request_id,
                        "status": run_status,
                        "error": run_error,
                        "steps": step_delta,
                    },
                )
                self._log(
                    format_trace_event(
                        [
                            f"ROUND {global_round}",
                            f"VideoAgent:{video_id}",
                        ],
                        "Incomplete",
                        fields=[("status", run_status)],
                        blocks=[("error", run_error)],
                    )
                )
                continue

            outcome["report"] = report
            outcomes.append(outcome)
            question_trajectory.record(
                agent="VideoAgent",
                video_id=video_id,
                action="run",
                input={
                    "instruction": instruction,
                    "global_round": global_round,
                },
                output={
                    "request_id": request_id,
                    "status": "ok",
                    "report": report,
                    "steps": step_delta,
                },
            )
        return outcomes

    def _request_terminal_answer(
        self,
        *,
        global_agent: GlobalAgent,
        trajectory: Trajectory,
        round_index: int,
        forced: bool = True,
    ) -> tuple[dict[str, Any], str]:
        """Run the standalone answer block after evidence gathering stops.

        Args:
            global_agent: Question-scoped coordinator with the final memory.
            trajectory: Mutable trajectory receiving the terminal decision.
            round_index: Sequential round assigned to the terminal call.

        Returns:
            The generated answer and stop reason; forced calls retain the gap status.
        """
        stop_reason = "GlobalAgent reached max_steps." if forced else "Agent selected answer."
        event_action = "terminal_answer" if forced else "answer"
        question_trajectory = QuestionTrajectory.wrap(trajectory)
        try:
            attempt = global_agent.answer()
            if attempt.get("status") != "ok":
                error = str(attempt.get("error") or "Terminal decision failed.")
                question_trajectory.record(
                    agent="GlobalAgent",
                    action=event_action,
                    round_index=round_index,
                    input={"stop_reason": stop_reason},
                    output={
                        "status": "error",
                        "error": error,
                    },
                )
                return self._terminal_fallback(stop_reason, error)
            generated = dict(attempt["value"])
            answer = {
                "answer": str(generated.get("answer") or "").strip(),
                "reason": str(generated.get("reason") or "").strip(),
                "status": "forced_with_gaps" if forced else "answered",
            }
            question_trajectory.record(
                agent="GlobalAgent",
                action=event_action,
                round_index=round_index,
                input={"stop_reason": stop_reason},
                output=generated,
            )
            self._log(
                format_trace_event(
                    ["GlobalAgent"],
                    "Terminal answer",
                    fields=[
                        ("answer", answer["answer"]),
                        ("stop_reason", stop_reason),
                    ],
                    blocks=[("reason", answer["reason"])],
                )
            )
            return answer, stop_reason if forced else answer["reason"]
        except Exception as exc:
            error = str(exc).strip() or type(exc).__name__
            question_trajectory.record(
                agent="GlobalAgent",
                action=event_action,
                round_index=round_index,
                input={"stop_reason": stop_reason},
                output={
                    "status": "error",
                    "error": error,
                },
            )
            return self._terminal_fallback(stop_reason, error)

    def _terminal_fallback(
        self,
        stop_reason: str,
        error: str,
    ) -> tuple[dict[str, Any], str]:
        """Return the deterministic answer used when terminal planning fails."""
        self._log(
            format_trace_event(
                ["GlobalAgent"],
                "Terminal answer unavailable",
                fields=[("stop_reason", stop_reason)],
                blocks=[("error", error)],
            )
        )
        return (
            {
                "answer": "",
                "reason": "GlobalAgent reached its decision-loop safety limit.",
                "status": "forced_with_gaps",
            },
            stop_reason,
        )

__all__ = ["MVAgentEngine"]
