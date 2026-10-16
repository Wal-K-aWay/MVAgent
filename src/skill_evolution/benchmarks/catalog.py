from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .adapters import crossvid_sample, cvbench_sample, mvu_eval_sample
from .aggregation import HierarchicalScoreAggregator
from .contracts import EvaluationSample, SampleTask
from .open_qa import FixedOpenQAJudge, PROTOCOL_VERSION
from .scoring import (
    ChoiceScorer,
    DatasetScorer,
    OrderingScorer,
    ScorerRegistry,
    TemporalLocalizationScorer,
)


@dataclass(frozen=True)
class BenchmarkRecord:
    """One operator record with provenance kept outside EvaluationSample."""

    sample_id: str
    dataset: str
    native_task: str
    sample: EvaluationSample
    source_record: str
    reference_answer: str = ""
    judge_question: str = ""

    @property
    def sample_weight(self) -> float:
        if self.sample.task is SampleTask.OPEN_QA:
            return float(len(self.sample.ground_truth))
        return 1.0


@dataclass(frozen=True)
class BenchmarkFoundation:
    records: Mapping[str, BenchmarkRecord]
    scorer: DatasetScorer
    aggregator: HierarchicalScoreAggregator
    scorer_identity: Mapping[str, Any]


def extract_prediction(result: Mapping[str, Any]) -> str:
    answer = result.get("answer")
    if isinstance(answer, Mapping):
        answer = answer.get("answer")
    if answer in (None, ""):
        answer = result.get("prediction")
    return str(answer or "").strip()


def _choice_question(question: str, options: Sequence[str]) -> str:
    return "\n\n".join(
        (
            "Provide several videos and a single-choice question with exactly one correct option.\n"
            "Watch the videos carefully. Select one answer choice and output only its uppercase letter.",
            f"Question:\n{str(question).strip()}",
            "Options:\n" + "\n".join(str(option) for option in options),
            "Your answer:",
        )
    )


def _with_question(sample: EvaluationSample, question: str) -> EvaluationSample:
    return EvaluationSample(
        task=sample.task,
        question=question,
        videos=sample.videos,
        options=list(sample.options),
        ground_truth=list(sample.ground_truth),
    )


def _open_qa_judge_question(question: str) -> str:
    """Extract the native question from CrossVid's Runtime task wrapper."""

    text = str(question).strip()
    marker = "Question:\n"
    if text.startswith(marker):
        body = text[len(marker) :]
    elif f"\n{marker}" in text:
        body = text.split(f"\n{marker}", 1)[1]
    else:
        return text
    suffix = "\n\nYour answer:"
    if suffix in body:
        body = body.split(suffix, 1)[0]
    return body.strip() or text


def _jsonl_rows(path: Path):
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        1,
    ):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON at {path}:{line_number}") from exc
        if not isinstance(row, Mapping):
            raise ValueError(f"{path}:{line_number} must contain one JSON object.")
        yield row


def _json_rows(path: Path) -> Sequence[Mapping[str, Any]]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rows, list) or any(not isinstance(row, Mapping) for row in rows):
        raise ValueError(f"{path} must contain a JSON object list.")
    return rows


def load_multibench_records(
    dataset_root: str | Path,
    sample_ids: Sequence[str],
) -> dict[str, BenchmarkRecord]:
    """Load selected canonical CrossVid, CVBench, and MVU-Eval records."""

    root = Path(dataset_root).expanduser().resolve()
    requested = {str(sample_id) for sample_id in sample_ids}
    if not requested:
        raise ValueError("At least one benchmark sample ID is required.")
    supported_prefixes = {"crossvid", "cvbench", "mvu_eval"}
    unknown = sorted(
        sample_id
        for sample_id in requested
        if sample_id.split(":", 1)[0] not in supported_prefixes
    )
    if unknown:
        raise ValueError(
            "Unsupported benchmark sample IDs: " + ", ".join(unknown[:5])
        )

    records: dict[str, BenchmarkRecord] = {}
    if any(sample_id.startswith("crossvid:") for sample_id in requested):
        source = root / "CrossVid" / "qa.jsonl"
        for row in _jsonl_rows(source):
            sample_id = str(row.get("id") or "").strip()
            if sample_id not in requested:
                continue
            native_task = str(row.get("task") or "").strip().upper()
            sample = crossvid_sample(row, media_root=source.parent)
            records[sample_id] = BenchmarkRecord(
                sample_id=sample_id,
                dataset="crossvid",
                native_task=native_task,
                sample=sample,
                source_record=str(source.resolve()),
                reference_answer=(
                    str(row.get("answer") or "").strip()
                    if sample.task is SampleTask.OPEN_QA
                    else ""
                ),
                judge_question=(
                    _open_qa_judge_question(sample.question)
                    if sample.task is SampleTask.OPEN_QA
                    else ""
                ),
            )

    if any(sample_id.startswith("cvbench:") for sample_id in requested):
        source = root / "CVBench" / "QAs.json"
        media_root = source.parent / "videos"
        for row in _json_rows(source):
            raw_id = str(row.get("id") if row.get("id") is not None else "").strip()
            sample_id = f"cvbench:{raw_id}"
            if sample_id not in requested:
                continue
            sample = cvbench_sample(row, media_root=media_root)
            sample = _with_question(
                sample,
                _choice_question(sample.question, sample.options),
            )
            records[sample_id] = BenchmarkRecord(
                sample_id=sample_id,
                dataset="cvbench",
                native_task="all",
                sample=sample,
                source_record=str(source.resolve()),
            )

    if any(sample_id.startswith("mvu_eval:") for sample_id in requested):
        source = root / "MVU-Eval" / "QAs.json"
        media_root = source.parent / "videos"
        for row in _json_rows(source):
            raw_id = str(row.get("id") if row.get("id") is not None else "").strip()
            native_task = str(row.get("task") or "").strip()
            sample_id = f"mvu_eval:{native_task}:{raw_id}"
            if sample_id not in requested:
                continue
            sample = mvu_eval_sample(row, media_root=media_root)
            sample = _with_question(
                sample,
                _choice_question(sample.question, sample.options),
            )
            records[sample_id] = BenchmarkRecord(
                sample_id=sample_id,
                dataset="mvu_eval",
                native_task=native_task,
                sample=sample,
                source_record=str(source.resolve()),
            )

    missing = sorted(requested - set(records))
    if missing:
        raise FileNotFoundError(
            "Could not load canonical benchmark records for: "
            + ", ".join(missing[:10])
        )
    return records


def build_benchmark_foundation(
    records: Mapping[str, BenchmarkRecord],
    *,
    open_qa_judge: FixedOpenQAJudge | None,
) -> BenchmarkFoundation:
    if not records:
        raise ValueError("Benchmark foundation requires at least one record.")
    samples = {
        sample_id: record.sample for sample_id, record in records.items()
    }
    open_ids = [
        sample_id
        for sample_id, record in records.items()
        if record.sample.task is SampleTask.OPEN_QA
    ]
    if open_ids and open_qa_judge is None:
        raise ValueError(
            "The selected records contain open_qa samples but no fixed OpenQA judge."
        )
    incomplete_open_ids = [
        sample_id
        for sample_id in open_ids
        if not records[sample_id].judge_question.strip()
        or not records[sample_id].reference_answer.strip()
        or not records[sample_id].sample.ground_truth
    ]
    if incomplete_open_ids:
        raise ValueError(
            "OpenQA records require a native question, full reference answer, "
            "and scoring points: "
            + ", ".join(incomplete_open_ids[:5])
        )
    private_scorers = {}
    if open_qa_judge is not None:
        private_scorers = {
            sample_id: open_qa_judge.bind(
                sample_id=sample_id,
                question=(
                    records[sample_id].judge_question
                    or records[sample_id].sample.question
                ),
                reference_answer=records[sample_id].reference_answer,
                scoring_points=[
                    str(point)
                    for point in records[sample_id].sample.ground_truth
                ],
            )
            for sample_id in open_ids
        }

    registry = ScorerRegistry(
        {
            SampleTask.CHOICE: ChoiceScorer(
                strict_format=True,
                separator="",
            ),
            SampleTask.ORDERING: OrderingScorer(
                separator="->",
                strict_format=True,
            ),
            SampleTask.TEMPORAL_LOCALIZATION: TemporalLocalizationScorer(
                separator=",",
                strict_format=True,
            ),
        }
    )
    scorer = DatasetScorer(
        samples=samples,
        registry=registry,
        scorer_by_sample=private_scorers,
        prediction_getter=lambda artifact: str(
            artifact.get("prediction") or ""
        ).strip(),
    )
    aggregator = HierarchicalScoreAggregator(
        dataset_of={
            sample_id: record.dataset for sample_id, record in records.items()
        },
        category_of={
            sample_id: record.native_task
            for sample_id, record in records.items()
        },
        sample_weights={
            sample_id: record.sample_weight
            for sample_id, record in records.items()
        },
    )
    scorer_identity: dict[str, Any] = {
        "type": "mvagent-multibench-official-v1",
        "choice": "strict-normalized-option-label-v1",
        "ordering": "crossvid-sequence-exact-v1",
        "temporal_localization": "crossvid-interval-iou-v1",
        "open_qa": (
            dict(open_qa_judge.identity)
            if open_qa_judge is not None
            else {"enabled": False, "protocol": PROTOCOL_VERSION}
        ),
    }
    return BenchmarkFoundation(
        records=dict(records),
        scorer=scorer,
        aggregator=aggregator,
        scorer_identity=scorer_identity,
    )


__all__ = [
    "BenchmarkFoundation",
    "BenchmarkRecord",
    "build_benchmark_foundation",
    "extract_prediction",
    "load_multibench_records",
]
