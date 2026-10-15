from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Mapping

from mvagent.utils.tools import (
    clean_text,
    format_number,
    format_time_range,
    json_safe,
)


class GlobalAgentMemory:
    """Question-scoped evidence, action history, and invalid-decision feedback."""

    def __init__(self) -> None:
        self.action_history: list[dict[str, Any]] = []

    def reset(self) -> None:
        self.action_history.clear()

    @property
    def reports(self) -> dict[str, str]:
        """Derive the latest successful report for each video."""
        reports: dict[str, str] = {}
        for event in self.action_history:
            if event.get("action") != "analyze_videos":
                continue
            outcomes = event.get("outcomes")
            for outcome in outcomes if isinstance(outcomes, list) else []:
                if (
                    not isinstance(outcome, Mapping)
                    or outcome.get("status") != "ok"
                ):
                    continue
                video_id = str(outcome.get("video_id") or "").strip()
                report = str(outcome.get("report") or "").strip()
                if video_id and report:
                    reports[video_id] = report
        return reports

    @property
    def watch_results(self) -> list[dict[str, Any]]:
        """Derive successful joint-watch results in execution order."""
        results: list[dict[str, Any]] = []
        for event in self.action_history:
            if (
                event.get("action") != "watch_videos"
                or event.get("status") != "ok"
            ):
                continue
            result = event.get("results")
            if isinstance(result, Mapping):
                results.append(json_safe(dict(result)))
        return results

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
        """Record one executed GlobalAgent evidence action."""
        action_name = str(action or "").strip()
        if action_name not in {"analyze_videos", "watch_videos"}:
            raise ValueError(f"Unsupported GlobalAgent history action: {action_name}")
        normalized_status = str(status or "").strip()
        if normalized_status not in {"ok", "partial", "error"}:
            raise ValueError(
                f"Unsupported GlobalAgent action status: {normalized_status}"
            )
        event = {
            "action": action_name,
            "parameters": json_safe(dict(parameters)),
            "status": normalized_status,
        }
        if action_name == "analyze_videos":
            if results is not None:
                raise ValueError("analyze_videos stores outcomes, not results.")
            if error:
                raise ValueError(
                    "analyze_videos stores errors on individual outcomes."
                )
            normalized_outcomes = self._normalize_analyze_outcomes(outcomes)
            requests = event["parameters"].get("videoagent_request")
            if not isinstance(requests, list):
                raise ValueError(
                    "analyze_videos parameters require videoagent_request."
                )
            requested_pairs = [
                (
                    str(request.get("video_id") or "").strip(),
                    str(request.get("instruction") or "").strip(),
                )
                for request in requests
                if isinstance(request, Mapping)
            ]
            outcome_pairs = [
                (outcome["video_id"], outcome["instruction"])
                for outcome in normalized_outcomes
            ]
            if requested_pairs != outcome_pairs:
                raise ValueError(
                    "analyze_videos outcomes must match requested videos and "
                    "instructions in order."
                )
            expected_status = self._analyze_status(normalized_outcomes)
            if normalized_status != expected_status:
                raise ValueError(
                    "analyze_videos batch status does not match its outcomes: "
                    f"expected {expected_status}, got {normalized_status}."
                )
            event["outcomes"] = normalized_outcomes
            self.action_history.append(json_safe(event))
            return
        if outcomes is not None:
            raise ValueError("watch_videos does not accept per-video outcomes.")
        normalized_error = str(error or "").strip()
        if normalized_status in {"partial", "error"} and not normalized_error:
            raise ValueError(
                "Incomplete GlobalAgent action requires an error message."
            )
        if normalized_error:
            event["error"] = normalized_error
        if results:
            event["results"] = json_safe(dict(results))
        self.action_history.append(json_safe(event))

    @staticmethod
    def _normalize_analyze_outcomes(
        outcomes: Sequence[Mapping[str, Any]] | None,
    ) -> list[dict[str, Any]]:
        """Validate the small public envelope for each VideoAgent run."""
        if not outcomes:
            raise ValueError("analyze_videos requires at least one outcome.")
        normalized: list[dict[str, Any]] = []
        seen_video_ids: set[str] = set()
        for raw_outcome in outcomes:
            if not isinstance(raw_outcome, Mapping):
                raise ValueError("Each analyze_videos outcome must be an object.")
            video_id = str(raw_outcome.get("video_id") or "").strip()
            instruction = str(raw_outcome.get("instruction") or "").strip()
            request_id = str(raw_outcome.get("request_id") or "").strip()
            status = str(raw_outcome.get("status") or "").strip()
            if not video_id or not instruction:
                raise ValueError(
                    "Each analyze_videos outcome requires video_id and instruction."
                )
            if video_id in seen_video_ids:
                raise ValueError(f"Duplicate analyze_videos outcome: {video_id}")
            seen_video_ids.add(video_id)
            outcome: dict[str, Any] = {
                "video_id": video_id,
                "instruction": instruction,
                "request_id": request_id,
                "status": status,
            }
            if status == "ok":
                report = str(raw_outcome.get("report") or "").strip()
                if not request_id or not report:
                    raise ValueError(
                        "Successful analyze_videos outcome requires request_id "
                        "and report."
                    )
                if raw_outcome.get("error"):
                    raise ValueError(
                        "Successful analyze_videos outcome cannot contain an error."
                    )
                outcome["report"] = report
            elif status in {"partial", "error"}:
                error = str(raw_outcome.get("error") or "").strip()
                if not error:
                    raise ValueError(
                        "Incomplete analyze_videos outcome requires a non-empty error."
                    )
                if raw_outcome.get("report"):
                    raise ValueError(
                        "Incomplete analyze_videos outcome cannot contain a report."
                    )
                outcome["error"] = error
            else:
                raise ValueError(
                    f"Unsupported analyze_videos outcome status: {status}"
                )
            normalized.append(outcome)
        return json_safe(normalized)

    @staticmethod
    def _analyze_status(outcomes: Sequence[Mapping[str, Any]]) -> str:
        statuses = [str(outcome.get("status") or "") for outcome in outcomes]
        if statuses and all(status == "ok" for status in statuses):
            return "ok"
        if any(status in {"ok", "partial"} for status in statuses):
            return "partial"
        return "error"

    def add_invalid_decision(
        self,
        *,
        error: str,
        available_video_ids: list[str],
        parsed_decision: Mapping[str, Any] | None = None,
        raw_response: str = "",
    ) -> None:
        """Record one invalid Planner attempt without treating it as evidence."""
        normalized_error = str(error or "").strip()
        if not normalized_error:
            raise ValueError("Invalid GlobalAgent decision requires an error.")
        video_ids = [
            str(video_id).strip()
            for video_id in available_video_ids
            if str(video_id).strip()
        ]
        event: dict[str, Any] = {
            "action": "invalid_decision",
            "status": "invalid",
            "error": normalized_error,
            "available_video_ids": video_ids,
        }
        if isinstance(parsed_decision, Mapping):
            event["parsed_decision"] = json_safe(dict(parsed_decision))
        normalized_raw = str(raw_response or "").strip()
        if normalized_raw:
            event["raw_response"] = normalized_raw
        self.action_history.append(json_safe(event))

    def to_dict(self) -> dict[str, Any]:
        """Return the canonical structured memory used by Runtime and outputs."""
        return json_safe(
            {
                "reports": self.reports,
                "watch_results": self.watch_results,
                "action_history": self.action_history,
            }
        )

    def render_action_history(self) -> str:
        """Render evidence actions and invalid decisions chronologically."""
        if not self.action_history:
            return "(none)"
        return "\n\n".join(
            self._render_action(index, event)
            for index, event in enumerate(self.action_history, start=1)
        )

    @classmethod
    def _render_action(cls, index: int, raw_event: Mapping[str, Any]) -> str:
        event = raw_event if isinstance(raw_event, Mapping) else {}
        action = clean_text(event.get("action")) or "unknown"
        parameters = event.get("parameters")
        parameters = parameters if isinstance(parameters, Mapping) else {}
        lines = [f"Event {index} — {action}"]
        if action == "analyze_videos":
            outcomes = event.get("outcomes")
            for outcome in outcomes if isinstance(outcomes, list) else []:
                if not isinstance(outcome, Mapping):
                    continue
                video_id = clean_text(outcome.get("video_id")) or "unknown video"
                instruction = clean_text(
                    outcome.get("instruction")
                ) or "No instruction recorded"
                instruction = instruction.rstrip(".")
                lines.append(f"Video: {video_id}")
                lines.append(f"Instruction: {instruction}.")
                outcome_status = clean_text(outcome.get("status"))
                lines.append(
                    f"Status: {cls._action_status_text(outcome_status)}."
                )
                if outcome_status == "ok":
                    report = outcome.get("report")
                    parsed = (
                        cls._parse_video_report(report)
                        if isinstance(report, str)
                        else {}
                    )
                    summary = parsed.get("summary")
                    if summary:
                        lines.append(f"Summary: {summary}")
                else:
                    error = cls._concise_error(outcome.get("error"))
                    if error:
                        lines.append(f"Error: {error}")
            lines.append(
                f"Batch status: {cls._action_status_text(event.get('status'))}."
            )
        elif action == "watch_videos":
            instruction = clean_text(parameters.get("instruction"))
            if instruction:
                lines.append(f"Instruction: {instruction}")
            videos = cls._format_selected_clips(parameters.get("videos"))
            lines.append(f"Videos: {videos or 'None recorded.'}")
            results = event.get("results")
            results = results if isinstance(results, Mapping) else {}
            fps = format_number(results.get("fps"))
            if fps:
                lines.append(f"FPS: {fps}")
            text = clean_text(results.get("text"))
            if text:
                lines.append(f"Result: {text}")
        elif action == "invalid_decision":
            parsed_decision = event.get("parsed_decision")
            if isinstance(parsed_decision, Mapping):
                attempted_action = clean_text(parsed_decision.get("action"))
                if attempted_action:
                    lines.append(f"Attempted action: {attempted_action}")
            available_video_ids = event.get("available_video_ids")
            if isinstance(available_video_ids, (list, tuple)):
                rendered_ids = ", ".join(
                    f"`{video_id}`"
                    for video_id in (
                        clean_text(value) for value in available_video_ids
                    )
                    if video_id
                )
                lines.append(
                    f"Available video IDs: {rendered_ids or 'None recorded.'}"
                )
        if action != "analyze_videos":
            lines.append(f"Status: {cls._action_status_text(event.get('status'))}.")
        error = clean_text(event.get("error"))
        if error:
            concise_error = cls._concise_error(error)
            lines.append(f"Error: {concise_error}")
        return "\n".join(lines)

    @staticmethod
    def _concise_error(value: Any) -> str:
        error = clean_text(value)
        return error if len(error) <= 600 else f"{error[:597].rstrip()}..."

    @staticmethod
    def _format_selected_clips(value: Any) -> str:
        if not isinstance(value, (list, tuple)):
            return ""
        videos: list[str] = []
        for raw_video in value:
            if not isinstance(raw_video, Mapping):
                continue
            video_id = clean_text(raw_video.get("video_id"))
            clip = format_time_range(raw_video.get("clip"))
            if video_id:
                videos.append(f"{video_id} ({clip})" if clip else video_id)
        return ", ".join(videos)

    @staticmethod
    def _parse_video_report(report: str) -> dict[str, str]:
        """Extract the deterministic public Summary report line."""
        parsed: dict[str, str] = {}
        for line in str(report or "").splitlines():
            prefix = "Summary: "
            if line.startswith(prefix):
                parsed["summary"] = line[len(prefix):]
        return parsed

    @staticmethod
    def _action_status_text(value: Any) -> str:
        status = str(value or "").strip().casefold()
        return {
            "ok": "Succeeded",
            "partial": "Partially succeeded",
            "error": "Failed",
            "invalid": "Invalid",
        }.get(status, status or "Unknown")

__all__ = ["GlobalAgentMemory"]
