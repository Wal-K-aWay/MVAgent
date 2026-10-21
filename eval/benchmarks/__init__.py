"""Benchmark-independent samples, answer scoring, and score aggregation."""

from .adapters import choice_sample, crossvid_sample, cvbench_sample, mvu_eval_sample
from .aggregation import (
    OFFICIAL_DATASET_POLICY,
    HierarchicalScoreAggregator,
    MeanScoreAggregator,
    ScoreAggregation,
)
from .catalog import (
    BenchmarkFoundation,
    BenchmarkRecord,
    build_benchmark_foundation,
    build_official_scorer,
    extract_prediction,
    load_multibench_records,
)
from .contracts import EvaluationSample, SampleTask
from .open_qa import BoundOpenQAScorer, FixedOpenQAJudge
from .scoring import (
    AnswerScorer,
    ChoiceScorer,
    DatasetScorer,
    CHANGE_MARGINS,
    OUTCOME_THRESHOLDS,
    OpenQAJudge,
    OpenQAScorer,
    OrderingScorer,
    ScoreResult,
    ScorerRegistry,
    TemporalLocalizationScorer,
    score_change,
    score_outcome,
)


__all__ = [
    "AnswerScorer",
    "choice_sample",
    "ChoiceScorer",
    "BoundOpenQAScorer",
    "BenchmarkFoundation",
    "BenchmarkRecord",
    "build_benchmark_foundation",
    "build_official_scorer",
    "DatasetScorer",
    "EvaluationSample",
    "extract_prediction",
    "HierarchicalScoreAggregator",
    "crossvid_sample",
    "cvbench_sample",
    "MeanScoreAggregator",
    "OFFICIAL_DATASET_POLICY",
    "load_multibench_records",
    "mvu_eval_sample",
    "FixedOpenQAJudge",
    "CHANGE_MARGINS",
    "OUTCOME_THRESHOLDS",
    "OpenQAJudge",
    "OpenQAScorer",
    "OrderingScorer",
    "SampleTask",
    "ScoreAggregation",
    "ScoreResult",
    "ScorerRegistry",
    "TemporalLocalizationScorer",
    "score_change",
    "score_outcome",
]
