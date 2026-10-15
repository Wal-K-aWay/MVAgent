from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any, Iterable, Sequence

from mvagent.agents.base import BaseAgent
from mvagent.skills import SkillBank
from mvagent.skills.selection import select_skills
from models.vlm.base import VLMClient
from mvagent.utils.media import (
    MIN_TEMPORAL_VIDEO_FRAMES,
    cut_video_segment,
    floor_fps,
    validate_action_video_ranges,
)
from mvagent.utils.tools import json_safe

from .memory import GlobalAgentMemory
from .prompts import (
    GLOBAL_AGENT_SYSTEM_PROMPT,
    GLOBAL_ANSWER_SYSTEM_PROMPT,
    build_global_answer_prompt,
    build_global_decision_prompt,
)
from .schema import (
    GLOBAL_ANSWER_SCHEMA,
    available_global_action_names,
    build_global_decision_schema,
)

class GlobalAgent(BaseAgent):
    """Cross-video coordinator and text-first evidence sufficiency judge."""

    def __init__(
        self,
        *,
        video_ids: Sequence[str],
        question: str,
        model: Any,
        visual_model: Any | None = None,
        video_metadata: Mapping[str, Mapping[str, Any]] | None = None,
        video_paths: Mapping[str, str] | None = None,
        cache_dir: str | None = None,
        max_videos_per_watch: int = 4,
        decision_skill: str | SkillBank = "",
        skill_selector_model: Any | None = None,
        skill_selection_scope: str = "decision",
    ) -> None:
        super().__init__(
            name="global_agent",
            model=model,
            system_prompt=GLOBAL_AGENT_SYSTEM_PROMPT,
        )
        self.question = str(question)
        self.skill_selector_model = skill_selector_model
        if skill_selection_scope not in ('decision', 'task'):
            raise ValueError('Skill selection scope must be decision or task')
        self.skill_selection_scope = skill_selection_scope
        self._skill_selection_cache = {}

        self.decision_skill = decision_skill if isinstance(decision_skill, SkillBank) else str(decision_skill or "").strip()
        self.memory = GlobalAgentMemory()
        self.video_ids = [str(video_id) for video_id in video_ids]
        if not self.video_ids or len(self.video_ids) != len(set(self.video_ids)):
            raise ValueError("GlobalAgent requires unique video identities.")
        raw_metadata = dict(video_metadata or {})
        self.video_metadata: dict[str, dict[str, float]] = {}
        for video_id in self.video_ids:
            metadata = raw_metadata.get(video_id)
            if not isinstance(metadata, Mapping):
                continue
            duration_sec = float(metadata.get("duration_sec") or 0.0)
            source_fps = float(metadata.get("fps") or 0.0)
            if (
                math.isfinite(duration_sec)
                and math.isfinite(source_fps)
                and duration_sec > 0.0
                and source_fps > 0.0
            ):
                self.video_metadata[video_id] = {
                    "duration_sec": duration_sec,
                    "fps": source_fps,
                }
        raw_paths = dict(video_paths or {})
        self.video_paths = {
            video_id: str(raw_paths[video_id])
            for video_id in self.video_ids
            if raw_paths.get(video_id)
        }
        self.cache_dir = str(cache_dir) if cache_dir else None
        self.max_videos_per_watch = max(
            1,
            int(max_videos_per_watch),
        )
        visual_model_candidate = model if visual_model is None else visual_model
        self.visual_model = (
            visual_model_candidate
            if isinstance(visual_model_candidate, VLMClient)
            else None
        )

    def add_action(
        self,
        *,
        action: str,
        parameters: Mapping[str, Any],
        status: str,
        error: str = "",
        results: Mapping[str, Any] | None = None,
        outcomes: Sequence[Mapping[str, Any]] | None = None,
    ) -> None:
        """Expose one executed evidence action to later decisions."""
        self.memory.add_action(
            action=action,
            parameters=parameters,
            status=status,
            error=error,
            results=results,
            outcomes=outcomes,
        )

    def add_invalid_decision(
        self,
        *,
        error: str,
        parsed_decision: Mapping[str, Any] | None = None,
        raw_response: str = "",
    ) -> None:
        """Expose one recoverable Planner failure to later decisions."""
        self.memory.add_invalid_decision(
            error=error,
            available_video_ids=self.video_ids,
            parsed_decision=parsed_decision,
            raw_response=raw_response,
        )

    def decide(self) -> dict[str, Any]:
        """Return one validated decision or recoverable invalid attempt.

        Returns:
            An ``ok`` attempt containing ``decision``, or an ``invalid``
            attempt containing stable failure feedback.
        """
        result = self._request_decision()
        if result.get("status") != "ok":
            attempt: dict[str, Any] = {
                "status": "invalid",
                "error": str(result.get("error") or "Invalid structured output."),
            }
            raw_response = str(result.get("raw_response") or "").strip()
            if raw_response:
                attempt["raw_response"] = raw_response
            return attempt
        decision = result.get("value")
        if not isinstance(decision, dict):
            raise TypeError("Successful GlobalAgent decision must be an object.")

        try:
            validated = self._validate_decision(decision)
        except (KeyError, TypeError, ValueError) as exc:
            return {
                "status": "invalid",
                "error": str(exc).strip() or type(exc).__name__,
                "parsed_decision": json_safe(decision),
            }
        return {"status": "ok", "decision": validated}

    def _request_decision(self) -> dict[str, Any]:
        """Ask the Planner for one structured decision."""
        available_action_names = available_global_action_names(
            watch_videos_available=(
                len(self.video_ids) >= 2
                and len(self.video_metadata) == len(self.video_ids)
                and len(self.video_paths) == len(self.video_ids)
                and self.cache_dir is not None
                and self.visual_model is not None
                and self.max_videos_per_watch >= 2
                and self.visual_model.max_videos_per_request >= 2
                and self.visual_model.max_video_frames_per_request >= 2 * MIN_TEMPORAL_VIDEO_FRAMES
            ),
        )
        watch_videos_available = "watch_videos" in available_action_names
        action_history_view = self.memory.render_action_history()
        skill = self.decision_skill
        if isinstance(skill, SkillBank):
            selection = select_skills(skill,
                selection_cache=self._skill_selection_cache if self.skill_selection_scope == 'task' else None,
                role="global",
                has_evidence=bool(self.memory.reports or self.memory.watch_results), task=self.question,
                state=dict(history=action_history_view,
                           videos={vid: {"duration_sec": meta["duration_sec"]}
                                   for vid, meta in self.video_metadata.items()} or self.video_ids),
                decide=(self.decide_json if self.skill_selector_model is None else
                        lambda *args, **kwargs: self.decide_json(*args, model=self.skill_selector_model, **kwargs)))
            if selection["status"] != "ok":
                return selection
            skill = selection["value"]
        prompt = build_global_decision_prompt(
            question=self.question,
            videos=(
                self.video_metadata
                if self.video_metadata
                else self.video_ids
            ),
            action_history_view=action_history_view,
            available_action_names=available_action_names,
            watch_videos_available=watch_videos_available,
            max_videos_per_watch=self.max_videos_per_watch,
            max_video_inputs_per_request=(
                self.visual_model.max_videos_per_request
                if self.visual_model is not None
                else 1
            ),
            decision_skill=skill,
        )
        return self.decide_json(
            prompt,
            json_schema=build_global_decision_schema(
                available_action_names,
                video_ids=self.video_ids,
                video_durations={key: value["duration_sec"] for key, value in self.video_metadata.items()},
                max_watch_videos=min(
                    self.max_videos_per_watch,
                    self.visual_model.max_videos_per_request,
                    self.visual_model.max_video_frames_per_request // MIN_TEMPORAL_VIDEO_FRAMES,
                ) if self.visual_model is not None else 0,
            ),
            schema_name="global_decision",
        )

    def answer(self) -> dict[str, Any]:
        """Run the standalone best-effort answer block on current memory."""
        prompt = build_global_answer_prompt(
            question=self.question,
            action_history_view=self.memory.render_action_history(),
        )
        result = self.decide_json(
            prompt,
            json_schema=GLOBAL_ANSWER_SCHEMA,
            schema_name="global_answer",
            system_prompt=GLOBAL_ANSWER_SYSTEM_PROMPT,
        )
        if result.get("status") != "ok":
            return result
        value = result.get("value")
        if not isinstance(value, dict):
            raise TypeError("Successful GlobalAgent answer must be an object.")
        value["reason"] = str(value.get("reason") or "").strip()
        value["answer"] = str(value.get("answer") or "").strip()
        return result

    def _validate_decision(
        self,
        decision: dict[str, Any],
    ) -> dict[str, Any]:
        """Normalize one Schema-valid decision and validate its parameters."""
        reason = str(decision.get("reason") or "").strip()
        if not reason:
            raise ValueError(
                "Global decision must include a non-empty reason."
            )
        decision["reason"] = reason
        action = str(decision.get("action") or "")
        parameters = decision.get("parameters")
        if not isinstance(parameters, dict):
            raise ValueError(
                "Global decision must include an action-specific parameters object."
            )
        if action == "answer":
            if parameters:
                raise ValueError("answer takes no input parameters.")
        elif action == "analyze_videos":
            parameters["videoagent_request"] = self.validate_video_analyses(
                parameters.get("videoagent_request") or []
            )
        elif action == "watch_videos":
            instruction = str(parameters.get("instruction") or "").strip()
            if not instruction:
                raise ValueError(
                    "watch_videos requires a non-empty instruction."
                )
            parameters["instruction"] = instruction
            normalized, _, _ = self._build_watch_videos_plan(
                videos=parameters.get("videos") or [],
            )
            parameters["videos"] = normalized

        else:
            raise ValueError(f"Unknown GlobalAgent action: {action}")
        return json_safe(decision)

    def validate_video_analyses(
        self,
        videoagent_request: Iterable[dict[str, Any]],
    ) -> list[dict[str, str]]:
        known_video_ids = set(self.video_ids)

        normalized: list[dict[str, str]] = []
        seen_video_ids: set[str] = set()
        for request in videoagent_request:
            if not isinstance(request, dict):
                raise ValueError("VideoAgent requests must be objects.")
            video_id = str(request.get("video_id") or "").strip()
            instruction = str(request.get("instruction") or "").strip()
            if not video_id or not instruction:
                raise ValueError(
                    "VideoAgent requests require video_id and a non-empty instruction."
                )
            if video_id not in known_video_ids:
                raise ValueError(
                    f"Unknown video in VideoAgent request: {video_id}"
                )
            if video_id in seen_video_ids:
                raise ValueError(
                    f"Duplicate video in one analyze_videos action: {video_id}"
                )
            seen_video_ids.add(video_id)
            normalized.append(
                {"video_id": video_id, "instruction": instruction}
            )
        if not normalized:
            raise ValueError("analyze_videos requires at least one analysis.")
        return normalized

    def watch_videos(
        self,
        *,
        instruction: str,
        videos: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        """Execute and retain one validated watch_videos action."""
        if (
            self.visual_model is None
            or self.cache_dir is None
            or len(self.video_paths) != len(self.video_ids)
        ):
            raise RuntimeError(
                "GlobalAgent has no complete watch_videos runtime."
            )
        _, plan, effective_fps = self._build_watch_videos_plan(
            videos=videos,
        )

        video_paths: dict[str, str] = {}
        for video_index, video in enumerate(plan, start=1):
            video_id = str(video["video_id"])
            time_range = list(video["time_range"])
            clip_path = cut_video_segment(
                self.video_paths[video_id],
                time_range,
                output_dir=self.cache_dir,
                prefix=f"watch_{video_index}_{video_id}",
                sampling_fps=effective_fps,
            )
            video_paths[video_id] = clip_path

        text = str(
            self.visual_model.chat_on_videos(
                video_paths=video_paths,
                text_prompt=str(instruction).strip(),
                fps=effective_fps,
            )
        ).strip()
        if not text:
            raise ValueError("watch_videos model returned empty text.")
        result = {
            "instruction": str(instruction).strip(),
            "fps": effective_fps,
            "videos": plan,
            "text": text,
        }
        return json_safe(result)

    def _build_watch_videos_plan(
        self,
        *,
        videos: Sequence[Mapping[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], float]:
        """Validate selections and allocate model-owned frames by duration."""
        requested = list(videos or [])
        if len(requested) < 2:
            raise ValueError(
                "watch_videos requires at least two selected videos."
            )
        if len(requested) > self.max_videos_per_watch:
            raise ValueError(
                f"watch_videos selects {len(requested)} videos; Agent limit "
                f"is {self.max_videos_per_watch}."
            )
        video_input_limit = (
            self.visual_model.max_videos_per_request
            if self.visual_model is not None
            else 1
        )
        frame_limit = (
            self.visual_model.max_video_frames_per_request
            if self.visual_model is not None
            else 1
        )
        normalized: list[dict[str, Any]] = []
        candidates: list[dict[str, Any]] = []
        selected_durations: dict[str, float] = {}
        seen: set[str] = set()
        for raw_video in requested:
            if not isinstance(raw_video, Mapping):
                raise ValueError("watch_videos selections must be objects.")
            video_id = str(raw_video.get("video_id") or "").strip()
            if video_id in seen:
                raise ValueError(f"Duplicate watch_videos video: {video_id}")
            metadata = self.video_metadata.get(video_id)
            if not video_id or not isinstance(metadata, Mapping):
                raise ValueError(f"Unknown watch_videos video: {video_id}")
            seen.add(video_id)
            duration = float(metadata["duration_sec"])
            source_fps = float(metadata["fps"])
            raw_clip = raw_video.get("clip")
            if (
                not isinstance(raw_clip, Sequence)
                or isinstance(raw_clip, (str, bytes))
                or len(raw_clip) != 2
                or any(
                    isinstance(value, (Mapping, Sequence))
                    and not isinstance(value, (str, bytes))
                    for value in raw_clip
                )
            ):
                raise ValueError(
                    "Each watch_videos selection requires exactly one "
                    "clip: [start_sec, end_sec]."
                )
            clip = validate_action_video_ranges(
                [raw_clip],
                mode="observe",
                duration_sec=duration,
                max_ranges=1,
            )[0]
            normalized.append({"video_id": video_id, "clip": clip})
            selected_durations[video_id] = float(clip[1]) - float(clip[0])
            if source_fps < 0.1:
                raise ValueError(f"Source FPS is below 0.1: {video_id}")
            candidates.append(
                {
                    "video_id": video_id,
                    "time_range": clip,
                    "source_fps": source_fps,
                }
            )

        if len(candidates) > video_input_limit:
            raise ValueError(
                f"watch_videos selects {len(candidates)} video clips; "
                f"model limit is {video_input_limit}."
            )
        minimum_required_frames = (
            MIN_TEMPORAL_VIDEO_FRAMES * len(candidates)
        )
        if frame_limit < minimum_required_frames:
            raise ValueError(
                "watch_videos model frame limit must allow at least "
                f"{MIN_TEMPORAL_VIDEO_FRAMES} temporal frames per selected clip."
            )
        video_frame_limits = self._allocate_video_frame_limits(
            frame_limit=frame_limit,
            selected_durations=selected_durations,
        )
        effective_fps = floor_fps(
            min(
                25.0,
                *(float(candidate["source_fps"]) for candidate in candidates),
                *(
                    video_frame_limits[video_id] / duration
                    for video_id, duration in selected_durations.items()
                ),
            )
        )
        if effective_fps < 0.1:
            raise ValueError(
                "watch_videos model frame limit cannot preserve all clips "
                "at 0.1 FPS."
            )

        plan: list[dict[str, Any]] = []
        for index, candidate in enumerate(candidates):
            start_sec, end_sec = candidate["time_range"]
            duration = float(end_sec) - float(start_sec)
            plan.append(
                {
                    "input_index": index + 1,
                    "video_id": candidate["video_id"],
                    "time_range": candidate["time_range"],
                    "video_frame_limit": video_frame_limits[
                        str(candidate["video_id"])
                    ],
                    "estimated_frames": max(
                        MIN_TEMPORAL_VIDEO_FRAMES,
                        int(math.ceil(duration * effective_fps - 1e-9)),
                    ),
                }
            )
        return json_safe(normalized), json_safe(plan), effective_fps

    @staticmethod
    def _allocate_video_frame_limits(
        *,
        frame_limit: int,
        selected_durations: Mapping[str, float],
    ) -> dict[str, int]:
        """Allocate one model call's frame capacity across logical videos."""
        video_ids = list(selected_durations)
        allocation = {
            video_id: MIN_TEMPORAL_VIDEO_FRAMES
            for video_id in video_ids
        }
        remaining = int(frame_limit) - sum(allocation.values())
        if remaining < 0:
            raise ValueError(
                "watch_videos model frame limit must allow at least "
                f"{MIN_TEMPORAL_VIDEO_FRAMES} temporal frames per selected clip."
            )
        total_duration = sum(
            float(selected_durations[video_id]) for video_id in video_ids
        )
        weighted = [
            remaining * float(selected_durations[video_id]) / total_duration
            for video_id in video_ids
        ]
        whole = [int(value) for value in weighted]
        for video_id, value in zip(video_ids, whole):
            allocation[video_id] += value
        leftovers = remaining - sum(whole)
        order = sorted(
            range(len(video_ids)),
            key=lambda index: (weighted[index] - whole[index], -index),
            reverse=True,
        )
        for index in order[:leftovers]:
            allocation[video_ids[index]] += 1
        return allocation

__all__ = ["GlobalAgent"]
