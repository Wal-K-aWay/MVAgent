from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any

from mvagent.utils.tools import json_safe


class QuestionTrajectory:
    """Append-only question trajectory with stable JSON rendering."""

    def __init__(self, entries: list[dict[str, Any]] | None = None) -> None:
        # A supplied list is intentionally retained so existing callers that
        # pass a list continue to observe appended entries.
        self._entries = entries if entries is not None else []

    @classmethod
    def wrap(
        cls,
        trajectory: QuestionTrajectory | list[dict[str, Any]],
    ) -> QuestionTrajectory:
        if isinstance(trajectory, cls):
            return trajectory
        return cls(trajectory)

    def record(
        self,
        *,
        agent: str,
        action: str,
        input: Mapping[str, Any] | None = None,
        output: Mapping[str, Any] | None = None,
        video_id: str | None = None,
        round_index: int | None = None,
    ) -> None:
        entry: dict[str, Any] = {
            "agent": str(agent),
            "action": str(action),
        }
        if round_index is not None:
            entry["round"] = int(round_index)
        if video_id is not None:
            entry["video_id"] = str(video_id)
        entry["input"] = json_safe(dict(input or {}))
        entry["output"] = json_safe(dict(output or {}))
        self._entries.append(entry)

    def to_list(self) -> list[dict[str, Any]]:
        return json_safe(self._entries)


class VideoRunTrajectory:
    """Append-only steps for the latest VideoAgent request."""

    def __init__(self) -> None:
        self._steps: list[dict[str, Any]] = []

    def __iter__(self) -> Iterator[dict[str, Any]]:
        return iter(self._steps)

    @property
    def last(self) -> dict[str, Any] | None:
        return self._steps[-1] if self._steps else None

    def record(self, action_record: Mapping[str, Any]) -> None:
        self._steps.append(
            {
                "step": len(self._steps) + 1,
                **json_safe(dict(action_record)),
            }
        )

    def to_list(self) -> list[dict[str, Any]]:
        return json_safe(self._steps)


__all__ = ["QuestionTrajectory", "VideoRunTrajectory"]
