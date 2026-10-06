from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from mvagent.utils.tools import (
    clean_text,
    format_fps,
    format_time_range,
    json_safe,
)


class VideoAgentMemory:
    """Request-grouped Observe history for one question-scoped video."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self._current_request: dict[str, Any] | None = None
        self._next_request_index = 1

    @property
    def actions(self) -> list[dict[str, Any]]:
        """Return all request-owned Observe records chronologically."""
        return json_safe(
            [action for request in self.requests for action in request["actions"]]
        )

    @property
    def observations(self) -> list[dict[str, Any]]:
        return json_safe(
            [
                observation
                for action in self.actions
                if (action.get("result") or {}).get("status")
                in {"ok", "partial"}
                for observation in action.get("result", {}).get("observations", [])
                if self._is_usable_observation(observation)
            ]
        )

    def begin_request(self, instruction: str) -> str:
        instruction = str(instruction or "").strip()
        if not instruction:
            raise ValueError("VideoAgent request instruction must not be empty.")
        request = {
            "request_id": f"req_{self._next_request_index}",
            "instruction": instruction,
            "actions": [],
        }
        self._next_request_index += 1
        self.requests.append(request)
        self._current_request = request
        return str(request["request_id"])

    def add_action(self, entry: dict[str, Any], *, request_id: str) -> None:
        request = self._require_request(request_id)
        entry = json_safe(entry or {})
        if set(entry) != {"action", "parameters", "result"}:
            raise ValueError(
                "Action memory entries require action, parameters, and result."
            )
        if entry.get("action") != "observe":
            raise ValueError("Only Observe actions enter VideoAgent memory.")
        if not isinstance(entry.get("parameters"), Mapping) or not isinstance(
            entry.get("result"), Mapping
        ):
            raise ValueError("Action parameters and result must be objects.")
        observations = entry["result"].get("observations") or []
        if observations and entry["result"].get("status") not in {
            "ok",
            "partial",
        }:
            raise ValueError(
                "Observe memory accepts observations only from successful "
                "or partial execution."
            )
        if any(
            not self._is_usable_observation(observation)
            for observation in observations
        ):
            raise ValueError(
                "Observe memory accepts only observations with non-empty text."
            )
        request["actions"].append(
            {
                "action": "observe",
                "parameters": json_safe(dict(entry["parameters"])),
                "result": json_safe(dict(entry["result"])),
            }
        )

    def add_summary(
        self,
        request_id: str,
        *,
        summary: str,
    ) -> None:
        """Attach the Planner-written public summary to a request."""
        request = self._require_request(request_id)
        request["summary"] = clean_text(summary)

    def has_request_observations(self, request_id: str) -> bool:
        request = self._require_request(request_id)
        return any(
            self._is_usable_observation(observation)
            for action in request.get("actions") or []
            if (action.get("result") or {}).get("status")
            in {"ok", "partial"}
            for observation in (action.get("result") or {}).get(
                "observations", []
            )
        )

    @property
    def has_observations(self) -> bool:
        return bool(self.observations)

    @staticmethod
    def _is_usable_observation(value: Any) -> bool:
        return isinstance(value, Mapping) and bool(
            clean_text(value.get("text"))
        )

    def render_report(self) -> str:
        """Render only the active request for the public GlobalAgent report."""
        if self._current_request is None:
            return "(none)"
        request = self._current_request
        index = self.requests.index(request) + 1
        lines = [f"Request {index}: {clean_text(request['instruction'])}"]
        summary = request.get("summary")
        if summary:
            lines.append(f"Summary: {summary}")
            return "\n".join(lines)
        actions = request["actions"]
        lines.append(
            "\n\n".join(self._render_action(action) for action in actions)
            if actions
            else "Result: No Observe action was completed."
        )
        return "\n".join(lines)

    def render_planner_view(self, *, request_id: str) -> str:
        self._require_request(request_id)
        blocks: list[str] = []
        for index, request in enumerate(self.requests, start=1):
            actions = request["actions"]
            current = request is self._current_request
            if current and not actions:
                continue
            lines = ["Current request" if current else f"Request {index}"]
            if not current:
                lines.append(f"Instruction: {clean_text(request['instruction'])}")
            if actions:
                lines.append("")
                lines.append(
                    "\n\n".join(
                        self._render_action(action) for action in actions
                    )
                )
            elif not current:
                lines.append("Actions: (none)")
            blocks.append("\n".join(lines))
        return "\n\n".join(blocks) if blocks else "(none)"

    @classmethod
    def _render_action(cls, entry: Mapping[str, Any]) -> str:
        parameters = entry.get("parameters") or {}
        result = entry.get("result") or {}
        what = clean_text(parameters.get("what"))
        observations = [
            observation
            for observation in result.get("observations") or []
            if isinstance(observation, Mapping)
        ]
        lines = [cls._render_observation(what, item) for item in observations]
        error = clean_text(result.get("error"))
        if not observations:
            request = cls._render_request_line(
                what=what,
                ranges=parameters.get("where") or [],
                fps=parameters.get("fps"),
            )
            outcome = (
                f"Observation failed. {error}"
                if error
                else "No visual evidence was returned."
            )
            lines.append(f"{request}\nResult: {outcome}")
        elif error:
            lines.append(f"Error: {error}")
        return "\n".join(lines)

    @classmethod
    def _render_observation(
        cls,
        what: str,
        observation: Mapping[str, Any],
    ) -> str:
        request = cls._render_request_line(
            what=what,
            ranges=[observation.get("time_range")],
            fps=observation.get("fps"),
        )
        text = clean_text(observation.get("text"))
        text = text or "No visual description was returned."
        lines = [request, f"Result: {text}"]
        uncertainty = clean_text(observation.get("uncertainty"))
        if uncertainty:
            lines.append(f"Limitation: {uncertainty}")
        return "\n".join(lines)

    @staticmethod
    def _render_request_line(
        *,
        what: str,
        ranges: Iterable[Any],
        fps: Any,
    ) -> str:
        details = [f"Evidence request: {what or 'Not recorded.'}"]
        rendered_ranges = [format_time_range(item) for item in ranges]
        rendered_ranges = [item for item in rendered_ranges if item]
        if rendered_ranges:
            details.append(f"Source range: {', '.join(rendered_ranges)}")
        rendered_fps = format_fps(fps)
        if rendered_fps:
            details.append(f"Sampling: {rendered_fps}")
        return "; ".join(details)

    def to_dict(self) -> dict[str, Any]:
        return json_safe({"requests": self.requests})

    def _require_request(self, request_id: str) -> dict[str, Any]:
        if self._current_request is None:
            raise RuntimeError("VideoAgent request has not been started.")
        if str(request_id or "").strip() != self._current_request["request_id"]:
            raise ValueError(f"Request {request_id!r} is not active.")
        return self._current_request


__all__ = ["VideoAgentMemory"]
