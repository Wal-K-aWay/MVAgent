from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


GroundTruthValue = str | int | float


class SampleTask(str, Enum):
    """Cross-benchmark output and scoring families, not native task labels."""

    CHOICE = "choice"
    TEMPORAL_LOCALIZATION = "temporal_localization"
    ORDERING = "ordering"
    OPEN_QA = "open_qa"


@dataclass
class EvaluationSample:
    """Minimal benchmark-independent question contract.

    Identity, dataset provenance, native task labels, split membership, source groups,
    and scorer-private annotations deliberately live outside this object. Serialized
    ground truth is always one JSON list; ``task`` gives that list its semantics.
    """

    task: SampleTask | str
    question: str
    videos: Mapping[str, str]
    options: list[str] = field(default_factory=list)
    ground_truth: list[GroundTruthValue] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.task = SampleTask(self.task)
        self.question = str(self.question).strip()
        if not self.question:
            raise ValueError("EvaluationSample.question must be non-empty.")

        videos = {
            str(video_id).strip(): str(path).strip()
            for video_id, path in dict(self.videos).items()
        }
        if not videos or any(not video_id or not path for video_id, path in videos.items()):
            raise ValueError(
                "EvaluationSample.videos must contain non-empty IDs and paths."
            )
        self.videos = videos

        if not isinstance(self.options, list):
            raise TypeError("EvaluationSample.options must be a list.")
        self.options = [str(option).strip() for option in self.options]
        if any(not option for option in self.options):
            raise ValueError("EvaluationSample.options cannot contain empty values.")

        if not isinstance(self.ground_truth, list) or not self.ground_truth:
            raise ValueError("EvaluationSample.ground_truth must be a non-empty list.")
        self.ground_truth = list(self.ground_truth)
        self._validate_ground_truth()

    def _validate_ground_truth(self) -> None:
        if self.task is SampleTask.TEMPORAL_LOCALIZATION:
            if len(self.ground_truth) != 2:
                raise ValueError(
                    "temporal_localization ground_truth must be [start, end]."
                )
            values: list[float] = []
            for value in self.ground_truth:
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise TypeError(
                        "temporal_localization ground_truth values must be numeric."
                    )
                number = float(value)
                if not math.isfinite(number):
                    raise ValueError(
                        "temporal_localization ground_truth values must be finite."
                    )
                values.append(number)
            if values[0] > values[1]:
                raise ValueError(
                    "temporal_localization ground_truth start cannot exceed end."
                )
            self.ground_truth = values
            return

        if any(not isinstance(value, str) or not value.strip() for value in self.ground_truth):
            raise TypeError(f"{self.task.value} ground_truth values must be non-empty strings.")
        self.ground_truth = [str(value).strip() for value in self.ground_truth]
        if self.task is SampleTask.ORDERING:
            if len(self.ground_truth) < 2:
                raise ValueError("ordering ground_truth must contain at least two items.")
            if len(set(self.ground_truth)) != len(self.ground_truth):
                raise ValueError("ordering ground_truth items must be unique.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": self.task.value,
            "question": self.question,
            "videos": dict(self.videos),
            "options": list(self.options),
            "ground_truth": list(self.ground_truth),
        }


__all__ = ["EvaluationSample", "GroundTruthValue", "SampleTask"]
