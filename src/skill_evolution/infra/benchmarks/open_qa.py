from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence
from uuid import uuid4

from models.llm import LLMClient

from .contracts import EvaluationSample, SampleTask
from .scoring import (
    OPEN_QA_REFLECTION_SUCCESS_CORRECT_DENOMINATOR,
    OPEN_QA_REFLECTION_SUCCESS_CORRECT_NUMERATOR,
    ScoreResult,
)


PROTOCOL_VERSION = "crossvid.ccqa_m3_coverage_correctness.v2"
SYSTEM_PROMPT = "You are a helpful assistant."
DEFAULT_PROMPT_PATH = (
    Path(__file__).resolve().parent / "prompts" / "open_qa_judge.md"
)
_PLACEHOLDERS = (
    "{question}",
    "{reference_answer}",
    "{scoring_points}",
    "{prediction}",
)
_PLACEHOLDER_PATTERN = re.compile(
    "|".join(re.escape(value) for value in _PLACEHOLDERS)
)


def _hash_json(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


class FixedOpenQAJudge:
    """Frozen coverage/correctness judge with a content-addressed disk cache."""

    def __init__(
        self,
        *,
        model: LLMClient,
        cache_dir: str | Path,
        prompt_path: str | Path | None = None,
    ) -> None:
        self.model = model
        self.cache_dir = Path(cache_dir).expanduser().resolve()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.prompt_path = Path(prompt_path or DEFAULT_PROMPT_PATH).resolve()
        self.prompt_template = self.prompt_path.read_text(encoding="utf-8").strip()
        missing = [
            placeholder
            for placeholder in _PLACEHOLDERS
            if self.prompt_template.count(placeholder) != 1
        ]
        if missing:
            raise ValueError(
                "OpenQA judge prompt must contain each input placeholder exactly once: "
                + ", ".join(missing)
            )
        self.prompt_sha256 = hashlib.sha256(
            self.prompt_template.encode("utf-8")
        ).hexdigest()
        self._identity = {
            "type": "fixed-open-qa-judge",
            "protocol": PROTOCOL_VERSION,
            "model": dict(getattr(model, "identity", {})),
            "system_prompt_sha256": hashlib.sha256(
                SYSTEM_PROMPT.encode("utf-8")
            ).hexdigest(),
            "prompt_sha256": self.prompt_sha256,
            "scoring": "sum(coverage + correctness) / (2 * point_count)",
        }

    @property
    def identity(self) -> Mapping[str, Any]:
        return dict(self._identity)

    def bind(
        self,
        *,
        sample_id: str,
        question: str,
        reference_answer: str,
        scoring_points: Sequence[str],
    ) -> "BoundOpenQAScorer":
        return BoundOpenQAScorer(
            judge=self,
            sample_id=sample_id,
            question=question,
            reference_answer=reference_answer,
            scoring_points=scoring_points,
        )

    def score(
        self,
        *,
        sample_id: str,
        question: str,
        reference_answer: str,
        scoring_points: Sequence[str],
        prediction: str,
    ) -> ScoreResult:
        points = tuple(str(point).strip() for point in scoring_points)
        if not points or any(not point for point in points):
            raise ValueError("OpenQA scoring_points must be non-empty strings.")
        question = str(question).strip()
        reference_answer = str(reference_answer).strip()
        prediction = str(prediction).strip()
        if not question or not reference_answer:
            raise ValueError("OpenQA question and reference answer must be non-empty.")

        request = {
            "judge": self._identity,
            "sample_id": str(sample_id),
            "question": question,
            "reference_answer": reference_answer,
            "scoring_points": list(points),
            "prediction": prediction,
        }
        cache_key = _hash_json(request)
        cached = self._load(cache_key, request)
        if cached is not None:
            return cached

        if not prediction:
            coverage = [False] * len(points)
            correctness = [False] * len(points)
        else:
            prompt = self._render(
                question=question,
                reference_answer=reference_answer,
                scoring_points=points,
                prediction=prediction,
            )
            schema = self._schema(len(points))
            response = self.model.json_prompt(
                prompt,
                json_schema=schema,
                schema_name="open_qa_coverage_correctness",
                system_prompt=SYSTEM_PROMPT,
            )
            if response.get("status") != "ok":
                raise RuntimeError(
                    "OpenQA judge returned invalid structured output: "
                    + str(response.get("error") or "unknown error")
                )
            payload = response.get("value")
            if not isinstance(payload, Mapping):
                raise RuntimeError("OpenQA judge returned no structured value.")
            coverage = list(payload.get("coverage") or ())
            correctness = list(payload.get("correctness") or ())
            self._validate_flags(coverage, correctness, len(points))

        score = (sum(coverage) + sum(correctness)) / (2 * len(points))
        feedback = (
            f"OpenQA judge: covered {sum(coverage)}/{len(points)} scoring points; "
            f"fully correct {sum(correctness)}/{len(points)}."
        )
        result = ScoreResult(
            score,
            "" if score >= 1.0 else feedback,
            reflection_success=self._reflection_success(correctness),
        )
        self._store(
            cache_key,
            request,
            coverage=coverage,
            correctness=correctness,
            result=result,
        )
        return result

    def _render(
        self,
        *,
        question: str,
        reference_answer: str,
        scoring_points: Sequence[str],
        prediction: str,
    ) -> str:
        values = {
            "{question}": question,
            "{reference_answer}": reference_answer,
            "{scoring_points}": json.dumps(
                list(scoring_points), ensure_ascii=False
            ),
            "{prediction}": prediction,
        }
        return _PLACEHOLDER_PATTERN.sub(
            lambda match: values[match.group(0)],
            self.prompt_template,
        )

    @staticmethod
    def _schema(point_count: int) -> dict[str, Any]:
        flags = {
            "type": "array",
            "items": {"type": "boolean"},
            "minItems": point_count,
            "maxItems": point_count,
        }
        return {
            "type": "object",
            "properties": {
                "coverage": flags,
                "correctness": flags,
            },
            "required": ["coverage", "correctness"],
            "additionalProperties": False,
        }

    @staticmethod
    def _validate_flags(
        coverage: Sequence[Any],
        correctness: Sequence[Any],
        point_count: int,
    ) -> None:
        if len(coverage) != point_count or len(correctness) != point_count:
            raise RuntimeError(
                "OpenQA judge coverage/correctness lengths must match scoring points."
            )
        if not all(isinstance(value, bool) for value in (*coverage, *correctness)):
            raise RuntimeError("OpenQA judge flags must be JSON booleans.")
        if any(correct and not covered for covered, correct in zip(coverage, correctness)):
            raise RuntimeError(
                "OpenQA judge correctness cannot be true for an uncovered point."
            )

    @staticmethod
    def _reflection_success(correctness: Sequence[bool]) -> bool:
        return (
            OPEN_QA_REFLECTION_SUCCESS_CORRECT_DENOMINATOR * sum(correctness)
            >= OPEN_QA_REFLECTION_SUCCESS_CORRECT_NUMERATOR * len(correctness)
        )

    def _path(self, cache_key: str) -> Path:
        return self.cache_dir / cache_key[:2] / f"{cache_key}.json"

    def _load(
        self,
        cache_key: str,
        request: Mapping[str, Any],
    ) -> ScoreResult | None:
        path = self._path(cache_key)
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Corrupt OpenQA judge cache: {path}") from exc
        if payload.get("cache_key") != cache_key or payload.get("request") != request:
            raise RuntimeError(f"Mismatched OpenQA judge cache: {path}")
        coverage = list(payload.get("coverage") or ())
        correctness = list(payload.get("correctness") or ())
        point_count = len(request["scoring_points"])
        self._validate_flags(coverage, correctness, point_count)
        expected_score = (sum(coverage) + sum(correctness)) / (2 * point_count)
        stored_score = float(payload.get("score"))
        if stored_score != expected_score:
            raise RuntimeError(f"Invalid score in OpenQA judge cache: {path}")
        return ScoreResult(
            stored_score,
            str(payload.get("feedback") or ""),
            reflection_success=self._reflection_success(correctness),
        )

    def _store(
        self,
        cache_key: str,
        request: Mapping[str, Any],
        *,
        coverage: Sequence[bool],
        correctness: Sequence[bool],
        result: ScoreResult,
    ) -> None:
        path = self._path(cache_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "cache_key": cache_key,
            "request": dict(request),
            "coverage": list(coverage),
            "correctness": list(correctness),
            "score": result.score,
            "feedback": result.feedback,
        }
        temporary = path.parent / f".{path.name}.{uuid4().hex}.tmp"
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        if path.exists():
            temporary.unlink()
            self._load(cache_key, request)
            return
        temporary.replace(path)


class BoundOpenQAScorer:
    """Keep the private reference answer outside the common Sample contract."""

    def __init__(
        self,
        *,
        judge: FixedOpenQAJudge,
        sample_id: str,
        question: str,
        reference_answer: str,
        scoring_points: Sequence[str],
    ) -> None:
        self.judge = judge
        self.sample_id = str(sample_id)
        self.question = str(question)
        self.reference_answer = str(reference_answer)
        self.scoring_points = tuple(str(point) for point in scoring_points)

    def score(self, *, prediction: str, sample: EvaluationSample) -> ScoreResult:
        if sample.task is not SampleTask.OPEN_QA:
            raise ValueError("BoundOpenQAScorer requires task=open_qa.")
        if tuple(str(point) for point in sample.ground_truth) != self.scoring_points:
            raise ValueError("OpenQA scorer points do not match the EvaluationSample.")
        return self.judge.score(
            sample_id=self.sample_id,
            question=self.question,
            reference_answer=self.reference_answer,
            scoring_points=self.scoring_points,
            prediction=prediction,
        )


__all__ = [
    "BoundOpenQAScorer",
    "DEFAULT_PROMPT_PATH",
    "FixedOpenQAJudge",
    "PROTOCOL_VERSION",
    "SYSTEM_PROMPT",
]
