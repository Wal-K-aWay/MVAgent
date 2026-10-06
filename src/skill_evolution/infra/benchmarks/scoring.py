from __future__ import annotations

import math
import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Callable, Mapping, Protocol, Sequence

from .contracts import EvaluationSample, SampleTask


_NUMBER_RE = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)")
_CHOICE_LABEL_RE = re.compile(r"^[A-Z]$")
TEMPORAL_REFLECTION_SUCCESS_IOU = 0.5
OPEN_QA_REFLECTION_SUCCESS_CORRECT_NUMERATOR = 2
OPEN_QA_REFLECTION_SUCCESS_CORRECT_DENOMINATOR = 3
REFLECTION_SUCCESS_POLICY = MappingProxyType(
    {
        SampleTask.CHOICE.value: "exact",
        SampleTask.ORDERING.value: "exact",
        SampleTask.TEMPORAL_LOCALIZATION.value: "interval-iou-ge-0.5",
        SampleTask.OPEN_QA.value: "fully-correct-points-ratio-ge-2/3",
    }
)


@dataclass(frozen=True)
class ScoreResult:
    score: float
    feedback: str = ""
    reflection_success: bool | None = None

    def __post_init__(self) -> None:
        score = float(self.score)
        if not math.isfinite(score) or not 0.0 <= score <= 1.0:
            raise ValueError("ScoreResult.score must be finite and in [0, 1].")
        reflection_success = self.reflection_success
        if reflection_success is None:
            reflection_success = score >= 1.0
        elif type(reflection_success) is not bool:
            raise TypeError("ScoreResult.reflection_success must be bool or None.")
        object.__setattr__(self, "score", score)
        object.__setattr__(self, "feedback", str(self.feedback).strip())
        object.__setattr__(self, "reflection_success", reflection_success)

    @property
    def outcome(self) -> str:
        if self.score >= 1.0:
            return "pass"
        if self.score <= 0.0:
            return "fail"
        return "partial"


class AnswerScorer(Protocol):
    def score(self, *, prediction: str, sample: EvaluationSample) -> ScoreResult: ...


def _choice_labels(prediction: str) -> list[str]:
    text = str(prediction).strip().upper()
    if re.fullmatch(r"[A-Z]+", text):
        return list(text)
    if re.fullmatch(r"[A-Z](?:\s*[,;/|]\s*[A-Z])+", text):
        return re.findall(r"[A-Z]", text)
    standalone = re.findall(r"\b([A-Z])\b", text)
    return standalone if len(standalone) == 1 else []


class ChoiceScorer:
    def __init__(self, *, strict_format: bool = False, separator: str = "") -> None:
        self.strict_format = bool(strict_format)
        self.separator = str(separator)

    def score(self, *, prediction: str, sample: EvaluationSample) -> ScoreResult:
        if sample.task is not SampleTask.CHOICE:
            raise ValueError("ChoiceScorer requires task=choice.")
        expected = [str(value).strip() for value in sample.ground_truth]
        if all(_CHOICE_LABEL_RE.fullmatch(value.upper()) for value in expected):
            expected = [value.upper() for value in expected]
            parsed = _choice_labels(prediction)
            if not parsed:
                return ScoreResult(0.0, "The answer could not be parsed as option labels.")
            semantic_match = len(parsed) == len(set(parsed)) and set(parsed) == set(expected)
            if not semantic_match:
                return ScoreResult(0.0, "The selected option labels do not match the ground truth.")
            if self.strict_format:
                required = self.separator.join(expected)
                if str(prediction).strip() != required:
                    return ScoreResult(
                        0.0,
                        f"The option set is correct but the required output format is {required!r}.",
                    )
            return ScoreResult(1.0)

        if len(expected) != 1:
            raise ValueError("Non-label choice ground_truth must contain exactly one value.")
        if str(prediction).strip().casefold() == expected[0].casefold():
            return ScoreResult(1.0)
        return ScoreResult(0.0, "The answer does not match the expected choice text.")


class OrderingScorer:
    def __init__(self, *, separator: str = "->", strict_format: bool = True) -> None:
        separator = str(separator)
        if not separator:
            raise ValueError("OrderingScorer.separator must be non-empty.")
        self.separator = separator
        self.strict_format = bool(strict_format)

    def _parse(self, prediction: str) -> list[str]:
        text = str(prediction).strip()
        if self.separator in text:
            return [part.strip() for part in text.split(self.separator) if part.strip()]
        return [part for part in re.split(r"\s*(?:->|>|,|;)\s*", text) if part]

    def score(self, *, prediction: str, sample: EvaluationSample) -> ScoreResult:
        if sample.task is not SampleTask.ORDERING:
            raise ValueError("OrderingScorer requires task=ordering.")
        expected = [str(value) for value in sample.ground_truth]
        parsed = self._parse(prediction)
        if parsed != expected:
            return ScoreResult(0.0, "The parsed item order does not match the ground truth.")
        required = self.separator.join(expected)
        if self.strict_format and str(prediction).strip() != required:
            return ScoreResult(
                0.0,
                f"The order is correct but the required output format is {required!r}.",
            )
        return ScoreResult(1.0)


def _interval_iou(predicted: Sequence[float], expected: Sequence[float]) -> float:
    intersection = max(
        0.0,
        min(predicted[1], expected[1]) - max(predicted[0], expected[0]),
    )
    union = max(predicted[1], expected[1]) - min(predicted[0], expected[0])
    return intersection / union if union > 0.0 else 0.0


class TemporalLocalizationScorer:
    def __init__(self, *, separator: str = ",", strict_format: bool = False) -> None:
        separator = str(separator)
        if not separator:
            raise ValueError("TemporalLocalizationScorer.separator must be non-empty.")
        self.separator = separator
        self.strict_format = bool(strict_format)

    def score(self, *, prediction: str, sample: EvaluationSample) -> ScoreResult:
        if sample.task is not SampleTask.TEMPORAL_LOCALIZATION:
            raise ValueError(
                "TemporalLocalizationScorer requires task=temporal_localization."
            )
        raw = str(prediction).strip()
        numbers = _NUMBER_RE.findall(raw)
        if len(numbers) != 2:
            return ScoreResult(0.0, "The answer must contain exactly one start and end time.")
        predicted = [float(value) for value in numbers]
        if not all(math.isfinite(value) for value in predicted) or predicted[0] > predicted[1]:
            return ScoreResult(0.0, "The predicted time interval is invalid.")
        if self.strict_format:
            exact = re.fullmatch(
                rf"\s*{_NUMBER_RE.pattern}\s*{re.escape(self.separator)}\s*{_NUMBER_RE.pattern}\s*",
                raw,
            )
            if exact is None:
                return ScoreResult(
                    0.0,
                    f"The interval must use {self.separator!r} between start and end.",
                )
        score = _interval_iou(predicted, [float(value) for value in sample.ground_truth])
        return ScoreResult(
            score,
            "" if score >= 1.0 else "The predicted interval only partially overlaps the ground truth.",
            reflection_success=score >= TEMPORAL_REFLECTION_SUCCESS_IOU,
        )


class OpenQAJudge(Protocol):
    def __call__(self, prediction: str, ground_truth: Sequence[str]) -> ScoreResult | float: ...


class OpenQAScorer:
    """Adapter around a fixed, versioned benchmark judge.

    Any scorer-private full reference answer or official annotation remains in the
    judge implementation; the common sample exposes only its list of ground-truth facts.
    """

    def __init__(self, judge: OpenQAJudge) -> None:
        self.judge = judge

    def score(self, *, prediction: str, sample: EvaluationSample) -> ScoreResult:
        if sample.task is not SampleTask.OPEN_QA:
            raise ValueError("OpenQAScorer requires task=open_qa.")
        result = self.judge(str(prediction), [str(value) for value in sample.ground_truth])
        return result if isinstance(result, ScoreResult) else ScoreResult(float(result))


class ScorerRegistry:
    def __init__(self, scorers: Mapping[SampleTask | str, AnswerScorer]) -> None:
        self.scorers = {SampleTask(task): scorer for task, scorer in scorers.items()}

    def score(self, *, prediction: str, sample: EvaluationSample) -> ScoreResult:
        try:
            scorer = self.scorers[sample.task]
        except KeyError as exc:
            raise ValueError(f"No scorer registered for task {sample.task.value!r}.") from exc
        return scorer.score(prediction=str(prediction), sample=sample)


class DatasetScorer:
    """Bridge external sample identities to the existing batch-scorer boundary."""

    def __init__(
        self,
        *,
        samples: Mapping[str, EvaluationSample],
        registry: ScorerRegistry,
        prediction_getter: Callable[[Mapping[str, Any]], str],
        scorer_by_sample: Mapping[str, AnswerScorer] | None = None,
    ) -> None:
        self.samples = {str(sample_id): sample for sample_id, sample in samples.items()}
        if not self.samples:
            raise ValueError("DatasetScorer requires at least one sample.")
        self.registry = registry
        self.prediction_getter = prediction_getter
        self.scorer_by_sample = {
            str(sample_id): scorer
            for sample_id, scorer in (scorer_by_sample or {}).items()
        }
        if unknown := sorted(set(self.scorer_by_sample) - set(self.samples)):
            raise ValueError(
                "Per-sample scorers contain unknown sample IDs: "
                + ", ".join(unknown[:5])
            )
        self._score_cache: dict[tuple[str, str], ScoreResult] = {}

    def score_prediction(self, sample_id: str, prediction: str) -> ScoreResult:
        sample_id = str(sample_id)
        prediction = str(prediction)
        cache_key = (sample_id, prediction)
        if cache_key in self._score_cache:
            return self._score_cache[cache_key]
        try:
            sample = self.samples[sample_id]
        except KeyError as exc:
            raise ValueError(f"Unknown sample ID: {sample_id!r}") from exc
        scorer = self.scorer_by_sample.get(sample_id)
        result = (
            scorer.score(prediction=prediction, sample=sample)
            if scorer is not None
            else self.registry.score(prediction=prediction, sample=sample)
        )
        self._score_cache[cache_key] = result
        return result

    def score_results(self, artifacts: Sequence[Any]) -> Mapping[str, ScoreResult]:
        results: dict[str, ScoreResult] = {}
        for artifact in artifacts:
            sample_id = str(artifact.sample_id)
            prediction = self.prediction_getter(artifact.artifact)
            results[sample_id] = self.score_prediction(sample_id, prediction)
        return results

    def score(self, artifacts: Sequence[Any]) -> Mapping[str, float]:
        return {
            sample_id: result.score
            for sample_id, result in self.score_results(artifacts).items()
        }

    def feedback(self, artifact: Mapping[str, Any]) -> Mapping[str, Any]:
        sample_id = str(artifact.get("sample_id") or "").strip()
        if not sample_id:
            raise ValueError("Scoring feedback requires artifact.sample_id.")
        prediction = self.prediction_getter(artifact)
        result = self.score_prediction(sample_id, prediction)
        payload: dict[str, Any] = {
            "ground_truth": list(self.samples[sample_id].ground_truth),
            "outcome": result.outcome,
        }
        if result.feedback:
            payload["feedback"] = result.feedback
        return payload


__all__ = [
    "AnswerScorer",
    "ChoiceScorer",
    "DatasetScorer",
    "OPEN_QA_REFLECTION_SUCCESS_CORRECT_DENOMINATOR",
    "OPEN_QA_REFLECTION_SUCCESS_CORRECT_NUMERATOR",
    "OpenQAJudge",
    "OpenQAScorer",
    "OrderingScorer",
    "REFLECTION_SUCCESS_POLICY",
    "ScoreResult",
    "ScorerRegistry",
    "TEMPORAL_REFLECTION_SUCCESS_IOU",
    "TemporalLocalizationScorer",
]
