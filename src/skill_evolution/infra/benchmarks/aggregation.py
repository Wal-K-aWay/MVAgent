from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from dataclasses import dataclass
from typing import Mapping, Sequence


@dataclass(frozen=True)
class ScoreAggregation:
    official_score: float
    bucket_scores: Mapping[str, float]

    def __post_init__(self) -> None:
        score = float(self.official_score)
        if not math.isfinite(score) or not 0.0 <= score <= 1.0:
            raise ValueError("Aggregated official_score must be finite and in [0, 1].")
        bucket_scores = {
            str(key): float(value) for key, value in self.bucket_scores.items()
        }
        if any(
            not math.isfinite(value) or not 0.0 <= value <= 1.0
            for value in bucket_scores.values()
        ):
            raise ValueError("Aggregated bucket scores must be finite and in [0, 1].")
        object.__setattr__(self, "official_score", score)
        object.__setattr__(self, "bucket_scores", bucket_scores)


class MeanScoreAggregator:
    """Backward-compatible sample mean with one score per artifact bucket."""

    identity = "sample-mean-v1"

    def aggregate(
        self,
        *,
        sample_ids: Sequence[str],
        scores: Mapping[str, float],
        buckets: Mapping[str, str],
    ) -> ScoreAggregation:
        if not sample_ids:
            raise ValueError("Score aggregation requires at least one sample.")
        grouped: dict[str, list[float]] = defaultdict(list)
        ordered_scores: list[float] = []
        for sample_id in sample_ids:
            score = float(scores[sample_id])
            ordered_scores.append(score)
            grouped[str(buckets.get(sample_id) or "default")].append(score)
        return ScoreAggregation(
            official_score=sum(ordered_scores) / len(ordered_scores),
            bucket_scores={
                name: sum(values) / len(values) for name, values in grouped.items()
            },
        )


class HierarchicalScoreAggregator:
    """Macro-average samples within native tasks, then tasks within datasets.

    Dataset and native-task provenance remain external to ``EvaluationSample``. This
    prevents uneven benchmark sizes from silently dominating a mixed evolution run.
    """

    def __init__(
        self,
        *,
        dataset_of: Mapping[str, str],
        category_of: Mapping[str, str],
        sample_weights: Mapping[str, float] | None = None,
    ) -> None:
        self.dataset_of = {
            str(sample_id): str(dataset).strip()
            for sample_id, dataset in dataset_of.items()
        }
        self.category_of = {
            str(sample_id): str(category).strip()
            for sample_id, category in category_of.items()
        }
        if set(self.dataset_of) != set(self.category_of):
            raise ValueError("dataset_of and category_of must have identical sample IDs.")
        if any(not value for value in (*self.dataset_of.values(), *self.category_of.values())):
            raise ValueError("Dataset and category names must be non-empty.")
        self.sample_weights = {
            sample_id: float((sample_weights or {}).get(sample_id, 1.0))
            for sample_id in self.dataset_of
        }
        if set(sample_weights or {}) - set(self.dataset_of):
            raise ValueError("sample_weights contains unknown sample IDs.")
        if any(
            not math.isfinite(value) or value <= 0.0
            for value in self.sample_weights.values()
        ):
            raise ValueError("Sample weights must be finite and positive.")
        identity_payload = {
            "type": "dataset-task-macro-v2",
            "dataset_of": sorted(self.dataset_of.items()),
            "category_of": sorted(self.category_of.items()),
            "sample_weights": sorted(self.sample_weights.items()),
        }
        self.identity = "dataset-task-macro-v2:" + hashlib.sha256(
            json.dumps(
                identity_payload,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

    def aggregate(
        self,
        *,
        sample_ids: Sequence[str],
        scores: Mapping[str, float],
        buckets: Mapping[str, str],
    ) -> ScoreAggregation:
        del buckets
        if not sample_ids:
            raise ValueError("Score aggregation requires at least one sample.")
        missing = [
            sample_id
            for sample_id in sample_ids
            if sample_id not in self.dataset_of or sample_id not in self.category_of
        ]
        if missing:
            raise ValueError(
                "Hierarchical aggregation metadata is missing: "
                + ", ".join(missing[:5])
            )

        task_values: dict[tuple[str, str], list[tuple[float, float]]] = defaultdict(list)
        for sample_id in sample_ids:
            task_values[(self.dataset_of[sample_id], self.category_of[sample_id])].append(
                (float(scores[sample_id]), self.sample_weights[sample_id])
            )
        task_scores = {
            key: (
                sum(score * weight for score, weight in values)
                / sum(weight for _score, weight in values)
            )
            for key, values in task_values.items()
        }
        dataset_values: dict[str, list[float]] = defaultdict(list)
        for (dataset, _category), score in task_scores.items():
            dataset_values[dataset].append(score)
        dataset_scores = {
            dataset: sum(values) / len(values)
            for dataset, values in dataset_values.items()
        }
        bucket_scores = {
            f"dataset:{dataset}": score
            for dataset, score in sorted(dataset_scores.items())
        }
        bucket_scores.update(
            {
                f"task:{dataset}/{category}": score
                for (dataset, category), score in sorted(task_scores.items())
            }
        )
        return ScoreAggregation(
            official_score=sum(dataset_scores.values()) / len(dataset_scores),
            bucket_scores=bucket_scores,
        )


__all__ = [
    "HierarchicalScoreAggregator",
    "MeanScoreAggregator",
    "ScoreAggregation",
]
