"""Official answer scoring plus optimizer-facing outcome labels.

Scores follow each benchmark's official protocol. Outcome labels and change margins are
derived from those scores for optimizer evidence and diagnostics only; acceptance always
compares the continuous official aggregate.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Callable, Mapping, Protocol, Sequence

from .contracts import EvaluationSample, SampleTask


# (pass_at, fail_below) per scoring family: pass if score >= pass_at, fail if score <
# fail_below, partial otherwise. Temporal IoU >= 0.5 is the usual R@0.5 hit and IoU < 0.1
# means the step was essentially not found; open QA uses (covered + correct) / (2 * points),
# so 2/3 needs most points covered and right, and < 1/3 means at most one point covered.
OUTCOME_THRESHOLDS = MappingProxyType(
    {
        SampleTask.CHOICE: (1.0, 1.0),
        SampleTask.ORDERING: (1.0, 1.0),
        SampleTask.TEMPORAL_LOCALIZATION: (0.5, 0.1),
        SampleTask.OPEN_QA: (2 / 3, 1 / 3),
    }
)
# Smallest per-question score change counted as an improvement or regression, so boundary
# jitter (a few IoU points) or one judge coverage flip is not read as a Skill effect.
CHANGE_MARGINS = MappingProxyType(
    {
        SampleTask.CHOICE: 1.0,
        SampleTask.ORDERING: 1.0,
        SampleTask.TEMPORAL_LOCALIZATION: 0.2,
        SampleTask.OPEN_QA: 1 / 3,
    }
)
_EPS = 1e-9


def score_outcome(task: SampleTask | str, score: float) -> str:
    pass_at, fail_below = OUTCOME_THRESHOLDS[SampleTask(task)]
    if score >= pass_at - _EPS:
        return "pass"
    if score < fail_below - _EPS:
        return "fail"
    return "partial"


def score_change(task: SampleTask | str, before: float, after: float) -> int:
    """+1 improved, -1 regressed, 0 within the family's change margin."""
    margin = CHANGE_MARGINS[SampleTask(task)]
    if after - before >= margin - _EPS:
        return 1
    if before - after >= margin - _EPS:
        return -1
    return 0


@dataclass(frozen=True)
class ScoreResult:
    score: float
    feedback: str = ""

    def __post_init__(self) -> None:
        score = float(self.score)
        if not math.isfinite(score) or not 0.0 <= score <= 1.0:
            raise ValueError("ScoreResult.score must be finite and in [0, 1].")
        object.__setattr__(self, "score", score)
        object.__setattr__(self, "feedback", str(self.feedback).strip())


class AnswerScorer(Protocol):
    def score(self, *, prediction: str, sample: EvaluationSample) -> ScoreResult: ...


_CVBENCH_PREFIXES = (
    "The best answer is",
    "The correct answer is",
    "The answer is",
    "The answer",
    "The best option is",
    "The correct option is",
    "Best answer:",
    "Best option:",
)


def _cvbench_extract(prediction: str) -> str:
    """CVBench lmms-eval ``extract_characters_regex``: first A-D/YES/NO token."""
    text = str(prediction).strip()
    for prefix in _CVBENCH_PREFIXES:
        text = text.replace(prefix, "")
    if len(text.split()) > 10 and not re.search("[ABCDYESNO]", text):
        return ""
    match = re.search(r"(?i)([ABCD]|YES|NO)", text)
    return match[0].upper() if match else ""


def _option_text(option: str) -> str:
    return re.sub(r"^[A-Z][.)]\s*", "", option).strip().rstrip(".").strip().upper()


class ChoiceScorer:
    """Option-label answers scored with one benchmark's official parsing.

    - ``exact`` (CrossVid): the answer string equals the concatenated answer labels.
    - ``first_char`` (MVU-Eval): the first character of the answer is the answer label.
    - ``cvbench``: lmms-eval regex extraction; a YES/NO token maps to its option label.
    """

    PROTOCOLS = ("exact", "first_char", "cvbench")

    def __init__(self, *, protocol: str = "exact") -> None:
        if protocol not in self.PROTOCOLS:
            raise ValueError(f"Unknown choice protocol: {protocol!r}")
        self.protocol = protocol

    def _parse(self, prediction: str, sample: EvaluationSample) -> str:
        text = str(prediction).strip()
        if self.protocol == "exact":
            return text
        if self.protocol == "first_char":
            return text.upper()[:1]
        token = _cvbench_extract(text)
        if token in {"YES", "NO"}:
            labels = [
                chr(ord("A") + index)
                for index, option in enumerate(sample.options)
                if _option_text(option) == token
            ]
            return labels[0] if len(labels) == 1 else token
        return token

    def score(self, *, prediction: str, sample: EvaluationSample) -> ScoreResult:
        if sample.task is not SampleTask.CHOICE:
            raise ValueError("ChoiceScorer requires task=choice.")
        expected = "".join(str(value).strip().upper() for value in sample.ground_truth)
        parsed = self._parse(prediction, sample)
        if parsed == expected:
            return ScoreResult(1.0)
        if not parsed:
            return ScoreResult(0.0, "The answer could not be parsed as option labels.")
        return ScoreResult(
            0.0,
            f"The answer {parsed!r} does not match the required option labels {expected!r}.",
        )


class OrderingScorer:
    """CrossVid PSS: the answer string equals the reference order, e.g. ``2->4->1->3``."""

    def score(self, *, prediction: str, sample: EvaluationSample) -> ScoreResult:
        if sample.task is not SampleTask.ORDERING:
            raise ValueError("OrderingScorer requires task=ordering.")
        required = "->".join(str(value) for value in sample.ground_truth)
        if str(prediction).strip() == required:
            return ScoreResult(1.0)
        return ScoreResult(0.0, "The answer is not the reference order written as 'a->b->c'.")


def _interval_iou(predicted: Sequence[float], expected: Sequence[float]) -> float:
    intersection = max(
        0.0,
        min(predicted[1], expected[1]) - max(predicted[0], expected[0]),
    )
    union = max(predicted[1], expected[1]) - min(predicted[0], expected[0])
    return intersection / union if union > 0.0 else 0.0


class TemporalLocalizationScorer:
    """CrossVid FSA: ``start,end`` in seconds split on one comma; score is IoU with the reference."""

    def score(self, *, prediction: str, sample: EvaluationSample) -> ScoreResult:
        if sample.task is not SampleTask.TEMPORAL_LOCALIZATION:
            raise ValueError(
                "TemporalLocalizationScorer requires task=temporal_localization."
            )
        parts = str(prediction).split(",")
        try:
            if len(parts) != 2:
                raise ValueError
            predicted = [float(part) for part in parts]
        except ValueError:
            return ScoreResult(0.0, "The answer must be 'start,end' in seconds.")
        if not all(math.isfinite(value) for value in predicted):
            return ScoreResult(0.0, "The predicted interval is not finite.")
        score = min(1.0, _interval_iou(predicted, [float(value) for value in sample.ground_truth]))
        return ScoreResult(
            score,
            "" if score >= 1.0 else f"The predicted interval has IoU {score:.2f} with the reference interval.",
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
            "outcome": score_outcome(self.samples[sample_id].task, result.score),
        }
        if result.feedback:
            payload["feedback"] = result.feedback
        return payload


__all__ = [
    "AnswerScorer",
    "CHANGE_MARGINS",
    "ChoiceScorer",
    "DatasetScorer",
    "OUTCOME_THRESHOLDS",
    "OpenQAJudge",
    "OpenQAScorer",
    "OrderingScorer",
    "ScoreResult",
    "ScorerRegistry",
    "TemporalLocalizationScorer",
    "score_change",
    "score_outcome",
]
