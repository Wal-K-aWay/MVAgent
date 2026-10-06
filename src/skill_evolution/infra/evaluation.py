from __future__ import annotations
import math
from models.execution import output_metrics
from pathlib import Path
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Mapping, MutableMapping, Sequence, Protocol
from .skills import Role, SkillSet, hash_json
from .data import EvaluationContext, EvaluationRequest, RolloutArtifact, RolloutExecutor
from .trajectory import TraceCase
from .trajectory import TrajectoryProjector
from .benchmarks.aggregation import MeanScoreAggregator, ScoreAggregation


class CachedScorer:
    """One scoring lane consumes completed questions independently of GPU workers."""
    def __init__(self, scorer, records, identity, cache_dir):
        self.scorer, self.records, self.identity = scorer, records, identity
        self.root = Path(cache_dir) / "scores"
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mvagent-score")
        self.pending = {}

    def _key(self, episode):
        record = self.records[episode.sample_id]
        return hash_json({"scorer": self.identity, "sample": episode.sample_id,
                          "prediction": episode.artifact.get("prediction", ""),
                          "ground_truth": record.sample.ground_truth,
                          "reference": record.reference_answer,
                          "judge_question": record.judge_question})

    def _score(self, episode, key):
        from dataclasses import asdict
        from .benchmarks.scoring import ScoreResult
        from .store import write_json
        path = self.root / (key + ".json")
        if path.exists():
            return ScoreResult(**json.loads(path.read_text()))
        score = self.scorer.score_prediction(episode.sample_id, episode.artifact.get("prediction", ""))
        write_json(path, asdict(score))
        return score

    def submit(self, episode):
        key = self._key(episode)
        if key not in self.pending:
            self.pending[key] = self.pool.submit(self._score, episode, key)

    def score_results(self, episodes):
        for episode in episodes:
            self.submit(episode)
        results = {}
        for episode in episodes:
            key = self._key(episode)
            try:
                results[episode.sample_id] = self.pending[key].result()
            except Exception:
                del self.pending[key]
                raise
        return results

    def score(self, episodes):
        return {sid: result.score for sid, result in self.score_results(episodes).items()}

    def feedback(self, artifact):
        return self.scorer.feedback(artifact)

    def close(self):
        self.pool.shutdown(wait=True)


def evaluate_batch(executor, cache, scorer, aggregator, request):
    from .rollout import collect_rollouts
    episodes = collect_rollouts(executor, cache, request)
    if len(episodes) != len(request.sample_ids) or {e.sample_id for e in episodes} != set(request.sample_ids):
        raise ValueError("Incomplete or duplicate rollout results")
    scores = scorer.score_results(episodes)
    if set(scores) != set(request.sample_ids) or any(
            not math.isfinite(s.score) or not 0 <= s.score <= 1 for s in scores.values()):
        raise ValueError("Scoring must be complete, finite and in [0, 1]")
    aggregate = aggregator.aggregate(sample_ids=request.sample_ids,
        scores={sid: score.score for sid, score in scores.items()},
        buckets={e.sample_id: e.bucket for e in episodes})
    return {"score": aggregate.official_score, "bucket_scores": dict(aggregate.bucket_scores),
            "scores": scores, "episodes": {e.sample_id: e for e in episodes},
            "health": {e.sample_id: episode_health(e) for e in episodes},
            "pair_hash": request.skill_set.skill_set_hash()}


def compare(parent, candidate):
    if set(parent["episodes"]) != set(candidate["episodes"]):
        raise ValueError("Comparison requires the same question IDs")
    rows = {}
    for sid in parent["episodes"]:
        rows[sid] = {"score_delta": candidate["scores"][sid].score - parent["scores"][sid].score,
                     "parent": execution_metrics(parent["episodes"][sid]),
                     "candidate": execution_metrics(candidate["episodes"][sid])}
    return {"score_delta": candidate["score"] - parent["score"],
            "improved": sum(row["score_delta"] > 0 for row in rows.values()),
            "regressed": sum(row["score_delta"] < 0 for row in rows.values()), "samples": rows}


def execution_metrics(episode):
    """Facts only; the algorithm decides which outcomes prohibit an update."""
    result = episode.artifact.get("result", episode.artifact)
    answer = result.get("answer", {})
    events = episode.artifact.get("events", [])
    video_runs = [e.get("output", {}) for e in result.get("trajectory", []) if e.get("agent") == "VideoAgent"]
    return {**episode_health(episode), **output_metrics(events), "answer_status": answer.get("status"),
            "has_answer": bool(str(answer.get("answer", "")).strip()),
            "terminal_answer": bool(answer.get("terminal")),
            "failed_video_requests": sum(r.get("status") in ("partial", "error") for r in video_runs),
            "model_calls": sum(e["kind"] == "model_start" for e in events),
            "model_errors": sum(e["kind"] == "model_error" for e in events),
            "request_queue_seconds": sum(e.get("queue_seconds", 0) for e in events if e["kind"] == "request_admitted"),
            "request_seconds": sum(e.get("seconds", 0) for e in events if e["kind"] == "model_end"),
            "media_seconds": sum(e.get("seconds", 0) for e in events if e["kind"] == "media"),
            "total_tokens": sum((e.get("usage") or {}).get("total_tokens", 0) for e in events if e["kind"] == "model_response"),
            "seconds": result.get("time"), "stop_reason": result.get("stop_reason")}

@dataclass(frozen=True)
class EvaluationKey:
    skill_set_hash: str
    context_hash: str

    def __post_init__(self) -> None:
        for name in ("skill_set_hash", "context_hash"):
            value = str(getattr(self, name)).strip().lower()
            if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
                raise ValueError(f"{name} must be a 64-character SHA256 digest.")
            object.__setattr__(self, name, value)

    @property
    def cache_key(self) -> str:
        return hash_json(
            {
                "skill_set_hash": self.skill_set_hash,
                "context_hash": self.context_hash,
            }
        )


@dataclass(frozen=True)
class EvaluationMetrics:
    sample_count: int
    official_score: float
    fatal_rate: float = 0.0
    invalid_action_rate: float = 0.0
    observe_calls_per_sample: float = 0.0
    watch_calls_per_sample: float = 0.0
    bucket_scores: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if int(self.sample_count) < 0:
            raise ValueError("sample_count must be non-negative.")
        object.__setattr__(self, "sample_count", int(self.sample_count))
        object.__setattr__(self, "official_score", float(self.official_score))
        for name in ("fatal_rate", "invalid_action_rate"):
            value = float(getattr(self, name))
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be in [0, 1].")
            object.__setattr__(self, name, value)
        for name in ("observe_calls_per_sample", "watch_calls_per_sample"):
            object.__setattr__(self, name, float(getattr(self, name)))
        object.__setattr__(
            self,
            "bucket_scores",
            {str(key): float(value) for key, value in dict(self.bucket_scores).items()},
        )


    def to_dict(self) -> dict[str, object]:
        return {
            "sample_count": self.sample_count,
            "official_score": self.official_score,
            "fatal_rate": self.fatal_rate,
            "invalid_action_rate": self.invalid_action_rate,
            "observe_calls_per_sample": self.observe_calls_per_sample,
            "watch_calls_per_sample": self.watch_calls_per_sample,
            "bucket_scores": dict(self.bucket_scores),
        }


@dataclass(frozen=True)
class EvaluationResult:
    key: EvaluationKey
    metrics: EvaluationMetrics
    evidence_ids: tuple[str, ...] = ()
    cases: tuple[TraceCase, ...] = ()
    reused_sample_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_ids", tuple(self.evidence_ids))
        object.__setattr__(self, "cases", tuple(self.cases))
        reused = tuple(
            dict.fromkeys(
                str(item).strip()
                for item in self.reused_sample_ids
                if str(item).strip()
            )
        )
        object.__setattr__(self, "reused_sample_ids", reused)
        if self.cases:
            unknown = set(self.evidence_ids) - {case.case_id for case in self.cases}
            if unknown:
                raise ValueError("Evaluation evidence IDs must reference its TraceCases.")




def role_was_invoked(episode: RolloutArtifact, role: Role) -> bool:
    """Return whether an immutable episode proves that one Planner ran."""

    if Role(role) is Role.GLOBAL:
        return True
    artifact = episode.artifact
    nested = artifact.get("result")
    result = nested if isinstance(nested, Mapping) else artifact
    trajectory = result.get("trajectory")
    if isinstance(trajectory, Sequence) and not isinstance(
        trajectory, (str, bytes)
    ):
        if any(
            isinstance(item, Mapping) and item.get("agent") == "VideoAgent"
            for item in trajectory
        ):
            return True
        if trajectory:
            return False
    history = result.get("action_history")
    if isinstance(history, Sequence) and not isinstance(history, (str, bytes)):
        return any(
            isinstance(item, Mapping) and item.get("action") == "analyze_videos"
            for item in history
        )
    # Legacy or incomplete artifacts cannot prove inactivity, so rerun.
    return True


class BatchScorer(Protocol):
    """Return official per-sample scores; may use a benchmark batch judge."""

    def score(self, artifacts: Sequence[RolloutArtifact]) -> Mapping[str, float]: ...


class ScoreAggregator(Protocol):
    """Combine normalized per-sample scores without depending on an optimizer."""

    identity: str

    def aggregate(
        self,
        *,
        sample_ids: Sequence[str],
        scores: Mapping[str, float],
        buckets: Mapping[str, str],
    ) -> ScoreAggregation: ...

class SkillSetEvaluator:
    """Evaluate complete Skill pairs using the shared execution and scoring services."""

    def __init__(
        self,
        *,
        executor: RolloutExecutor,
        scorer: BatchScorer,
        context: EvaluationContext,
        projector: TrajectoryProjector | None = None,
        score_aggregator: ScoreAggregator | None = None,
        episode_cache: MutableMapping[str, RolloutArtifact] | None = None,
        evaluation_cache: MutableMapping[str, EvaluationResult] | None = None,
    ) -> None:
        self.executor = executor
        self.scorer = scorer
        self.context = context
        self.projector = projector or TrajectoryProjector()
        self.score_aggregator = score_aggregator or MeanScoreAggregator()
        if self.context.evaluation_identity["aggregator"] != self.score_aggregator.identity:
            raise ValueError(
                "EvaluationContext aggregator identity does not match the configured "
                "score aggregator."
            )
        self.episode_cache = episode_cache if episode_cache is not None else {}
        self.evaluation_cache = evaluation_cache if evaluation_cache is not None else {}

    def evaluate(self, *, skill_set: SkillSet, label: str) -> EvaluationResult:
        return self._evaluate(skill_set=skill_set, label=label)

    def evaluate_role_candidate(
        self,
        *,
        skill_set: SkillSet,
        reference_skill_set: SkillSet,
        changed_role: Role,
        label: str,
    ) -> EvaluationResult:
        """Evaluate one role-local edit without rerunning provably inactive samples.

        A Video Skill cannot affect an episode in which no Video Planner was invoked.
        Reusing the reference artifact for those samples removes unrelated visual-model
        variation from the paired comparison and avoids an unnecessary full rollout.
        Global planning is always on the answer path, so Global edits still rerun every
        sample.
        """

        role = Role(changed_role)
        other = Role.VIDEO if role is Role.GLOBAL else Role.GLOBAL
        if skill_set.get(other) != reference_skill_set.get(other):
            raise ValueError(
                "A role-local candidate evaluation may change exactly one role Skill."
            )
        if skill_set.get(role) == reference_skill_set.get(role):
            return self.evaluate(skill_set=skill_set, label=label)
        if role is Role.GLOBAL:
            return self.evaluate(skill_set=skill_set, label=label)

        # The reference is normally already evaluated by the coordinator. Calling the
        # cached path here also makes this public method safe to use independently.
        self.evaluate(
            skill_set=reference_skill_set,
            label=f"{label}-reference",
        )
        reusable: dict[str, RolloutArtifact] = {}
        for sample_id in self.context.sample_ids:
            reference = self.episode_cache[
                self.context.rollout_cache_key(reference_skill_set, sample_id)
            ]
            if not role_was_invoked(reference, role):
                reusable[sample_id] = reference
        return self._evaluate(
            skill_set=skill_set,
            label=label,
            reusable=reusable,
        )

    def _evaluate(
        self,
        *,
        skill_set: SkillSet,
        label: str,
        reusable: Mapping[str, RolloutArtifact] | None = None,
    ) -> EvaluationResult:
        key = EvaluationKey(
            skill_set_hash=skill_set.skill_set_hash(),
            context_hash=self.context.context_hash,
        )
        if cached := self.evaluation_cache.get(key.cache_key):
            return cached

        from .rollout import collect_rollouts
        reusable = reusable or {}
        for sid, artifact in reusable.items():
            self.episode_cache[self.context.rollout_cache_key(skill_set, sid)] = artifact
        ordered = collect_rollouts(self.executor, self.episode_cache,
            EvaluationRequest(skill_set, self.context, self.context.sample_ids, label))
        scored = self.scorer.score(ordered)
        if set(scored) != set(self.context.sample_ids):
            raise ValueError("Scorer must return exactly one score for every frozen sample ID.")
        score_map: dict[str, float] = {}
        for sample_id in self.context.sample_ids:
            score = float(scored[sample_id])
            if not math.isfinite(score) or not 0.0 <= score <= 1.0:
                raise ValueError(
                    f"Scorer returned an invalid normalized score for {sample_id!r}."
                )
            score_map[sample_id] = score
        scores = tuple(score_map[sample_id] for sample_id in self.context.sample_ids)
        metrics = self._aggregate(ordered, score_map)
        cases = tuple(
            case
            for episode, score in zip(ordered, scores, strict=True)
            for case in self.projector.project(episode.artifact, official_score=score)
        )
        result = EvaluationResult(
            key=key,
            metrics=metrics,
            evidence_ids=tuple(
                case.case_id for case in cases if case.outcome in {"fail", "partial"}
            ),
            cases=cases,
            reused_sample_ids=tuple(
                sample_id
                for sample_id in self.context.sample_ids
                if sample_id in reusable
            ),
        )
        self.evaluation_cache[key.cache_key] = result
        return result


    def _aggregate(
        self,
        episodes: Sequence[RolloutArtifact],
        scores: Mapping[str, float],
    ) -> EvaluationMetrics:
        sample_count = len(episodes)
        if not sample_count:
            raise ValueError("Evaluation requires at least one rollout artifact.")
        fatal = invalid = observe = watch = 0
        aggregation = self.score_aggregator.aggregate(
            sample_ids=tuple(episode.sample_id for episode in episodes),
            scores=scores,
            buckets={episode.sample_id: episode.bucket for episode in episodes},
        )
        for episode in episodes:
            artifact = episode.artifact
            nested = artifact.get("result")
            result = nested if isinstance(nested, Mapping) else artifact
            history = result.get("action_history")
            history = history if isinstance(history, Sequence) and not isinstance(history, (str, bytes)) else ()
            trajectory = result.get("trajectory")
            trajectory = (
                trajectory
                if isinstance(trajectory, Sequence)
                and not isinstance(trajectory, (str, bytes))
                else ()
            )
            fatal += int(episode.status not in {"ok", "answered"})
            invalid += int(
                any(
                    isinstance(item, Mapping)
                    and (item.get("action") == "invalid_decision" or item.get("status") == "invalid")
                    for item in history
                )
            )
            watch += sum(
                1
                for item in history
                if isinstance(item, Mapping) and item.get("action") == "watch_videos"
            )
            for item in trajectory:
                if not isinstance(item, Mapping) or item.get("agent") != "VideoAgent":
                    continue
                output = item.get("output")
                steps = output.get("steps") if isinstance(output, Mapping) else ()
                if not isinstance(steps, Sequence) or isinstance(steps, (str, bytes)):
                    continue
                observe += sum(
                    1
                    for step in steps
                    if isinstance(step, Mapping) and step.get("action") == "observe"
                )
        return EvaluationMetrics(
            sample_count=sample_count,
            official_score=aggregation.official_score,
            fatal_rate=fatal / sample_count,
            invalid_action_rate=invalid / sample_count,
            observe_calls_per_sample=observe / sample_count,
            watch_calls_per_sample=watch / sample_count,
            bucket_scores=aggregation.bucket_scores,
        )



def episode_health(episode):
    """Count both Planner levels; one bad sample must not be hidden by averaging."""
    result = episode.artifact.get("result", episode.artifact)
    history = result.get("action_history", [])
    steps = [step for event in result.get("trajectory", [])
             if event.get("agent") == "VideoAgent"
             for step in event.get("output", {}).get("steps", [])]
    decisions = [*history, *steps]
    return {
        "fatal": int(episode.status not in {"ok", "answered"}),
        "invalid": sum(item.get("action") == "invalid_decision" or
                       item.get("status") == "invalid" or
                       item.get("result", {}).get("status") == "invalid" for item in decisions),
        "observe": sum(item.get("action") == "observe" for item in steps),
        "watch": sum(item.get("action") == "watch_videos" for item in history),
    }


def paired_gate(parent, candidate, seed, protected, *, maintenance=False, protected_ids=()):
    ids = set(parent['scores'])
    if not ids or ids != set(candidate['scores']) or ids != set(seed['scores']):
        raise ValueError('Gate requires complete matched sample identities')
    reasons = []
    for sid in ids:
        for key in ('fatal', 'invalid'):
            if candidate['health'][sid][key] > parent['health'][sid][key]:
                reasons.append(f'new_{key}:{sid}')
    keys = set(parent['bucket_scores']) if maintenance else set(protected)
    for key in keys:
        if any(key not in r['bucket_scores'] for r in (parent, candidate, seed)):
            raise ValueError('Unknown protection bucket: ' + key)
        if candidate['bucket_scores'][key] < max(parent['bucket_scores'][key], seed['bucket_scores'][key]):
            reasons.append('bucket_regression:' + key)
    for sid in protected_ids:
        if sid not in ids:
            raise ValueError('Protected question outside paired evaluation')
        if candidate['scores'][sid].score < max(parent['scores'][sid].score, seed['scores'][sid].score):
            reasons.append('protected_loss:' + sid)
    delta = candidate['score'] - parent['score']
    if delta < 0 or (not maintenance and delta <= 0):
        reasons.append('nonpositive_gain' if not maintenance else 'negative_gain')
    return dict(accepted=not reasons, delta=delta, reasons=reasons)


def compact_report(report):
    return dict(score=report['score'], bucket_scores=report['bucket_scores'], health=report['health'],
                scores={sid: s.score for sid, s in report['scores'].items()}, bank_hash=report['pair_hash'])
