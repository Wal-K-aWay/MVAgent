"""Benchmark-independent samples, answer scoring, and score aggregation."""

from .adapters import choice_sample, crossvid_sample, cvbench_sample, mvu_eval_sample
from .aggregation import HierarchicalScoreAggregator, MeanScoreAggregator, ScoreAggregation
from .catalog import (
    BenchmarkFoundation,
    BenchmarkRecord,
    build_benchmark_foundation,
    extract_prediction,
    load_multibench_records,
)
from .contracts import EvaluationSample, SampleTask
from .open_qa import BoundOpenQAScorer, FixedOpenQAJudge
from .scoring import (
    AnswerScorer,
    ChoiceScorer,
    DatasetScorer,
    OPEN_QA_REFLECTION_SUCCESS_CORRECT_DENOMINATOR,
    OPEN_QA_REFLECTION_SUCCESS_CORRECT_NUMERATOR,
    OpenQAJudge,
    OpenQAScorer,
    OrderingScorer,
    REFLECTION_SUCCESS_POLICY,
    ScoreResult,
    ScorerRegistry,
    TEMPORAL_REFLECTION_SUCCESS_IOU,
    TemporalLocalizationScorer,
)


__all__ = [
    "AnswerScorer",
    "choice_sample",
    "ChoiceScorer",
    "BoundOpenQAScorer",
    "BenchmarkFoundation",
    "BenchmarkRecord",
    "build_benchmark_foundation",
    "DatasetScorer",
    "EvaluationSample",
    "extract_prediction",
    "HierarchicalScoreAggregator",
    "crossvid_sample",
    "cvbench_sample",
    "MeanScoreAggregator",
    "load_multibench_records",
    "mvu_eval_sample",
    "FixedOpenQAJudge",
    "OPEN_QA_REFLECTION_SUCCESS_CORRECT_DENOMINATOR",
    "OPEN_QA_REFLECTION_SUCCESS_CORRECT_NUMERATOR",
    "OpenQAJudge",
    "OpenQAScorer",
    "OrderingScorer",
    "REFLECTION_SUCCESS_POLICY",
    "SampleTask",
    "ScoreAggregation",
    "ScoreResult",
    "ScorerRegistry",
    "TEMPORAL_REFLECTION_SUCCESS_IOU",
    "TemporalLocalizationScorer",
]
