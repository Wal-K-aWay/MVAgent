from __future__ import annotations

import hashlib
import json
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from queue import Empty, Queue
from typing import Any, Callable, Mapping, Sequence

from skill_evolution.benchmarks import (
    BenchmarkRecord,
    DatasetScorer,
    extract_prediction,
)
from skill_evolution.configs import RolloutReplicaConfig
from skill_evolution.evaluation import (
    EvaluationContext,
    GateStageEvaluation,
    RolloutArtifact,
    TrajectoryProjector,
)
from skill_evolution.orchestration import CandidateWorkspace
from skill_evolution.strategy import SkillSet
from skill_evolution.strategy.contracts import hash_json


def tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root)
        if "__pycache__" in relative.parts or relative.suffix in {".pyc", ".pyo"}:
            continue
        digest.update(str(relative).encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


@dataclass(frozen=True)
class _CompletedRollout:
    index: int
    sample_id: str
    prediction: str
    status: str
    error: str
    result: Mapping[str, Any]


class FrozenMVAgentExecutor:
    """Run one immutable SkillSet against benchmark-independent records."""

    def __init__(
        self,
        *,
        records: Mapping[str, BenchmarkRecord],
        output_dir: Path,
        base_config_path: Path,
        runtime_snapshot_sha256: str,
        configs_module: Any,
        engine_module: Any,
        scorer: DatasetScorer,
        rollout_replicas: Sequence[RolloutReplicaConfig] = (),
        prediction_extractor: Callable[[Mapping[str, Any]], str] = (
            extract_prediction
        ),
    ) -> None:
        self.records = dict(records)
        self.output_dir = output_dir
        self.base_config_path = base_config_path
        self.runtime_snapshot_sha256 = runtime_snapshot_sha256
        self.configs_module = configs_module
        self.engine_module = engine_module
        self.scorer = scorer
        self.rollout_replicas = tuple(rollout_replicas)
        self.prediction_extractor = prediction_extractor
        self.workspace = CandidateWorkspace(output_dir / "candidates")
        self.materialized: dict[str, Any] = {}
        self.model_statuses: dict[str, Any] = {}

    def _candidate(self, skill_set: SkillSet):
        skill_set_hash = skill_set.skill_set_hash()
        if skill_set_hash in self.materialized:
            return self.materialized[skill_set_hash]
        candidate_id = f"candidate-{skill_set_hash[:16]}"
        candidate_dir = self.workspace.root / candidate_id
        if candidate_dir.exists():
            candidate = self.workspace.load(
                candidate_id=candidate_id,
                expected_skill_set_hash=skill_set_hash,
            )
        else:
            candidate = self.workspace.materialize(
                candidate_id=candidate_id,
                skill_set=skill_set,
                base_config_path=self.base_config_path,
                runtime_snapshot_sha256=self.runtime_snapshot_sha256,
            )
        self.materialized[skill_set_hash] = candidate
        return candidate

    @property
    def primary_replica(self) -> RolloutReplicaConfig | None:
        return self.rollout_replicas[0] if self.rollout_replicas else None

    def _load_config(
        self,
        config_path: Path,
        replica: RolloutReplicaConfig | None = None,
    ):
        config = self.configs_module.MVAgentConfig.from_yaml(config_path)
        if replica is None:
            return config
        local_models = [
            model
            for model in config.models.values()
            if getattr(model, "type", None) == "local_vllm"
        ]
        if len(local_models) != 1:
            raise ValueError(
                "Rollout replicas require exactly one local_vllm model in "
                "the MVAgent config."
            )
        local_model = local_models[0]
        base_gpus = getattr(local_model, "gpus", None)
        if not isinstance(base_gpus, list) or len(base_gpus) != 1:
            raise ValueError(
                "Rollout replicas require a single-GPU local_vllm base model."
            )
        local_model.endpoint = replica.endpoint
        local_model.gpus = list(replica.gpus)
        config.validate()
        return config

    def _run_sample(
        self,
        *,
        engine: Any,
        candidate: Any,
        request: Any,
        index: int,
        sample_id: str,
        worker_index: int,
    ) -> _CompletedRollout:
        record = self.records[sample_id]
        sample = record.sample
        sample_dir = candidate.directory / "questions" / sample_id
        sample_dir.mkdir(parents=True, exist_ok=True)
        print(
            f"[ROLLOUT] {request.label} "
            f"candidate={request.skill_set.skill_set_hash()[:12]} "
            f"worker={worker_index} sample={sample_id}",
            flush=True,
        )
        status = "ok"
        error = ""
        try:
            result = engine.answer(
                videos=sample.videos,
                question=sample.question,
                output_dir=str(sample_dir),
            )
            prediction = self.prediction_extractor(result)
        except Exception as exc:
            status = "error"
            error = str(exc).strip() or type(exc).__name__
            prediction = ""
            result = {
                "input": {
                    "question": sample.question,
                    "videos": dict(sample.videos),
                },
                "answer": {"answer": "", "status": "error"},
                "trajectory": [],
                "action_history": [],
                "stop_reason": error,
            }
        return _CompletedRollout(
            index=index,
            sample_id=sample_id,
            prediction=prediction,
            status=status,
            error=error,
            result=result,
        )

    def _run_worker(
        self,
        *,
        engine: Any,
        candidate: Any,
        request: Any,
        jobs: Queue[tuple[int, str]],
        worker_index: int,
    ) -> tuple[_CompletedRollout, ...]:
        completed: list[_CompletedRollout] = []
        while True:
            try:
                index, sample_id = jobs.get_nowait()
            except Empty:
                break
            completed.append(
                self._run_sample(
                    engine=engine,
                    candidate=candidate,
                    request=request,
                    index=index,
                    sample_id=sample_id,
                    worker_index=worker_index,
                )
            )
        return tuple(completed)

    def _run_rollouts(self, *, candidate: Any, request: Any):
        sample_ids = tuple(request.sample_ids)
        if not sample_ids:
            return ()
        unknown = [sample_id for sample_id in sample_ids if sample_id not in self.records]
        if unknown:
            raise KeyError("Unknown rollout sample IDs: " + ", ".join(unknown))
        worker_replicas: tuple[RolloutReplicaConfig | None, ...] = (
            self.rollout_replicas or (None,)
        )[: len(sample_ids)]
        engines: list[Any] = []
        statuses: list[dict[str, Any]] = []
        try:
            for worker_index, replica in enumerate(worker_replicas):
                config = self._load_config(candidate.config_path, replica)
                engine = self.engine_module.MVAgentEngine(
                    config,
                    logger=lambda _message: None,
                )
                engines.append(engine)
                statuses.append(
                    {
                        "worker": worker_index,
                        "replica": (
                            replica.to_dict() if replica is not None else None
                        ),
                        "models": engine.resolve_models(),
                    }
                )
            self.model_statuses[request.skill_set.skill_set_hash()] = {
                "workers": statuses
            }
            jobs: Queue[tuple[int, str]] = Queue()
            for index, sample_id in enumerate(sample_ids):
                jobs.put((index, sample_id))
            completed: list[_CompletedRollout | None] = [None] * len(sample_ids)
            with ThreadPoolExecutor(
                max_workers=len(engines),
                thread_name_prefix="mvagent-rollout",
            ) as pool:
                futures = [
                    pool.submit(
                        self._run_worker,
                        engine=engine,
                        candidate=candidate,
                        request=request,
                        jobs=jobs,
                        worker_index=worker_index,
                    )
                    for worker_index, engine in enumerate(engines)
                ]
                for future in futures:
                    for item in future.result():
                        completed[item.index] = item
            if any(item is None for item in completed):
                raise RuntimeError("Rollout workers did not return every sample.")
            return tuple(item for item in completed if item is not None)
        finally:
            for engine in engines:
                engine.close()

    def execute(self, request):
        candidate = self._candidate(request.skill_set)
        completed = self._run_rollouts(candidate=candidate, request=request)
        artifacts = []
        for item in completed:
            record = self.records[item.sample_id]
            sample = record.sample
            sample_dir = candidate.directory / "questions" / item.sample_id
            score_result = self.scorer.score_prediction(
                item.sample_id,
                item.prediction,
            )
            saved = {
                "sample_id": item.sample_id,
                "task": record.native_task,
                "dataset": record.dataset,
                "output_task": sample.task.value,
                "prediction": item.prediction,
                "ground_truth": list(sample.ground_truth),
                "score": score_result.score,
                "score_feedback": score_result.feedback,
                "status": item.status,
                "error": item.error,
                "result": item.result,
            }
            (sample_dir / "result.json").write_text(
                json.dumps(saved, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(
                f"[RESULT] sample={item.sample_id} "
                f"prediction={json.dumps(item.prediction, ensure_ascii=False)} "
                f"score={score_result.score:.6f} status={item.status}",
                flush=True,
            )
            artifacts.append(
                RolloutArtifact(
                    sample_id=item.sample_id,
                    artifact={
                        "sample_id": item.sample_id,
                        "task": record.native_task,
                        "dataset": record.dataset,
                        "prediction": item.prediction,
                        "result": item.result,
                    },
                    bucket=f"{record.dataset}/{record.native_task}",
                    status=item.status,
                )
            )
        return tuple(artifacts)


class FrozenPlannerReplayExecutor:
    """Replay saved Train Planner states without executing visual actions."""

    def __init__(
        self,
        *,
        rollout_executor: FrozenMVAgentExecutor,
        projector: TrajectoryProjector,
        max_states_per_case: int,
    ) -> None:
        self.rollout_executor = rollout_executor
        self.projector = projector
        self.max_states_per_case = int(max_states_per_case)
        self._case_sources: dict[
            str,
            dict[str, tuple[dict[str, Any], int]],
        ] = {}
        self._replay_cache: dict[
            tuple[str, str, str, tuple[str, ...]],
            dict[str, tuple[dict[str, object], ...]],
        ] = {}

    @property
    def identity(self) -> Mapping[str, object]:
        return {
            "type": "frozen-mvagent-planner-replay-v1",
            "runtime_snapshot_sha256": (
                self.rollout_executor.runtime_snapshot_sha256
            ),
            "max_states_per_case": self.max_states_per_case,
            "state_policy": "first-and-last-ordinary-decision",
        }

    def replay(
        self,
        *,
        reference_skill_set: SkillSet,
        skill_set: SkillSet,
        role,
        case_ids,
    ):
        normalized_ids = tuple(str(case_id) for case_id in case_ids)
        key = (
            reference_skill_set.skill_set_hash(),
            skill_set.skill_set_hash(),
            role.value,
            normalized_ids,
        )
        cached = self._replay_cache.get(key)
        if cached is not None:
            return cached
        sources = self._sources(reference_skill_set)
        candidate = self.rollout_executor._candidate(skill_set)
        config = self.rollout_executor._load_config(
            candidate.config_path,
            self.rollout_executor.primary_replica,
        )
        engine = self.rollout_executor.engine_module.MVAgentEngine(
            config,
            logger=lambda _message: None,
        )
        replayed: dict[str, tuple[dict[str, object], ...]] = {}
        try:
            engine.resolve_models()
            for case_id in normalized_ids:
                source = sources.get(case_id)
                if source is None:
                    replayed[case_id] = ()
                    continue
                artifact, local_index = source
                record = self.rollout_executor.records[
                    str(artifact["sample_id"])
                ]
                with tempfile.TemporaryDirectory(
                    prefix="mvagent-planner-replay-"
                ) as temp_dir:
                    global_agent, video_agents = engine._preprocess(
                        videos=record.sample.videos,
                        question=record.sample.question,
                        output_dir=temp_dir,
                    )
                    try:
                        result = artifact["result"]
                        replayed[case_id] = (
                            self._replay_global(global_agent, result)
                            if role.value == "global"
                            else self._replay_video(
                                video_agents,
                                result,
                                local_index,
                            )
                        )
                    finally:
                        engine._cleanup_run_cache()
        finally:
            engine.close()
        self._replay_cache[key] = replayed
        return replayed

    def _sources(
        self,
        reference_skill_set: SkillSet,
    ) -> dict[str, tuple[dict[str, Any], int]]:
        reference_hash = reference_skill_set.skill_set_hash()
        cached = self._case_sources.get(reference_hash)
        if cached is not None:
            return cached
        candidate = self.rollout_executor._candidate(reference_skill_set)
        sources: dict[str, tuple[dict[str, Any], int]] = {}
        for path in sorted(candidate.directory.glob("questions/*/result.json")):
            artifact = json.loads(path.read_text(encoding="utf-8"))
            projected = self.projector.project(
                artifact,
                official_score=float(artifact.get("score") or 0.0),
            )
            video_index = 0
            for case in projected:
                local_index = 0
                if case.role.value == "video":
                    local_index = video_index
                    video_index += 1
                sources[case.case_id] = (artifact, local_index)
        self._case_sources[reference_hash] = sources
        return sources

    def _selected_indices(self, count: int) -> tuple[int, ...]:
        if count <= 0:
            return ()
        if self.max_states_per_case == 1 or count == 1:
            return (0,)
        return tuple(dict.fromkeys((0, count - 1)))[: self.max_states_per_case]

    def _replay_global(self, agent, result):
        trajectory = [
            event
            for event in result.get("trajectory", ())
            if event.get("agent") == "GlobalAgent"
            and event.get("action") == "decide"
        ]
        history = list(result.get("action_history") or ())
        prefixes = []
        history_index = 0
        for event in trajectory:
            prefixes.append(history[:history_index])
            output = event.get("output") or {}
            action = str(output.get("action") or "")
            if (
                action in {"analyze_videos", "watch_videos"}
                or output.get("status") == "invalid"
            ) and history_index < len(history):
                history_index += 1
        decisions = []
        for index in self._selected_indices(len(prefixes)):
            agent.memory.action_history = json.loads(
                json.dumps(prefixes[index], ensure_ascii=False)
            )
            decisions.append(self._normalize_global_attempt(agent.decide()))
        return tuple(decisions)

    @staticmethod
    def _normalize_global_attempt(attempt):
        if attempt.get("status") != "ok":
            return {
                "status": "invalid",
                "error": str(attempt.get("error") or ""),
            }
        decision = attempt.get("decision")
        if not isinstance(decision, Mapping):
            return {"status": "invalid", "error": "missing decision"}
        return {"status": "ok", "decision": dict(decision)}

    def _replay_video(self, video_agents, result, local_index):
        runs = [
            event
            for event in result.get("trajectory", ())
            if event.get("agent") == "VideoAgent"
            and event.get("action") == "run"
        ]
        if local_index >= len(runs):
            return ()
        target = runs[local_index]
        target_output = target.get("output") or {}
        steps = [
            step
            for step in target_output.get("steps", ())
            if not (step.get("result") or {}).get("terminal")
        ]
        decisions = []
        for step_index in self._selected_indices(len(steps)):
            video_id = str(target.get("video_id") or "")
            agent = video_agents.get(video_id)
            if agent is None:
                decisions.append(
                    {"status": "invalid", "error": "missing video agent"}
                )
                continue
            try:
                instruction, request_id = self._restore_video_state(
                    agent,
                    runs,
                    local_index,
                    step_index,
                )
                attempt = agent._call_planner(
                    instruction=instruction,
                    request_id=request_id,
                )
                decisions.append(self._normalize_video_attempt(agent, attempt))
            except Exception as exc:
                decisions.append(
                    {
                        "status": "invalid",
                        "error": str(exc).strip() or type(exc).__name__,
                    }
                )
        return tuple(decisions)

    @staticmethod
    def _restore_video_state(agent, runs, target_index, step_index):
        agent.memory.reset()
        agent._run_trajectory = type(agent._run_trajectory)()
        target_instruction = ""
        target_request_id = ""
        target_video_id = str(runs[target_index].get("video_id") or "")
        for run_index, run in enumerate(runs[: target_index + 1]):
            if str(run.get("video_id") or "") != target_video_id:
                continue
            instruction = str((run.get("input") or {}).get("instruction") or "")
            request_id = agent.memory.begin_request(instruction)
            output_steps = list((run.get("output") or {}).get("steps") or ())
            limit = step_index if run_index == target_index else len(output_steps)
            for step in output_steps[:limit]:
                action_record = {
                    key: value for key, value in step.items() if key != "step"
                }
                result = action_record.get("result") or {}
                if (
                    action_record.get("action") == "observe"
                    and result.get("status") != "invalid"
                ):
                    agent.memory.add_action(
                        action_record,
                        request_id=request_id,
                    )
                agent._run_trajectory.record(action_record)
            if run_index == target_index:
                target_instruction = instruction
                target_request_id = request_id
        return target_instruction, target_request_id

    @staticmethod
    def _normalize_video_attempt(agent, attempt):
        if attempt.get("status") != "ok":
            return {
                "status": "invalid",
                "error": str(attempt.get("error") or ""),
            }
        decision = attempt.get("value")
        if not isinstance(decision, Mapping):
            return {"status": "invalid", "error": "missing decision"}
        action = str(decision.get("action") or "")
        parameters = decision.get("parameters")
        if not isinstance(parameters, Mapping):
            return {"status": "invalid", "error": "missing parameters"}
        try:
            if action == "observe":
                agent._prepare_observe(dict(parameters))
            elif action == "finish":
                if not agent.memory.has_observations or not str(
                    parameters.get("summary") or ""
                ).strip():
                    raise ValueError("finish lacks usable Memory or summary")
            else:
                raise ValueError(f"unsupported action: {action}")
        except (KeyError, TypeError, ValueError) as exc:
            return {"status": "invalid", "error": str(exc)}
        return {"status": "ok", "decision": dict(decision)}


class EvalParentStageProvider:
    def __init__(self, parent: SkillSet) -> None:
        self.parent = parent
        self.evaluator = None

    @property
    def identity(self):
        return {
            "type": "eval-parent-only-v1",
            "parent_skill_set_hash": self.parent.skill_set_hash(),
        }

    def evaluate(self, *, skill_set, search_evaluation):
        del skill_set
        if self.evaluator is None:
            raise RuntimeError(
                "Eval stage provider has not been bound to eval_evaluator."
            )
        parent = self.evaluator.evaluate(
            skill_set=self.parent,
            label="eval-gate-parent",
        )
        return {
            "eval": GateStageEvaluation(
                candidate=search_evaluation,
                references={"parent": parent},
            )
        }


def build_evaluation_context(
    *,
    name: str,
    sample_ids: tuple[str, ...],
    records: Mapping[str, BenchmarkRecord],
    base_config_sha256: str,
    runtime_snapshot_sha256: str,
    manifest_hash: str,
    scorer_identity: Mapping[str, Any],
    aggregator_identity: str,
) -> EvaluationContext:
    ground_truth_hash = hash_json(
        [
            [sample_id, list(records[sample_id].sample.ground_truth)]
            for sample_id in sample_ids
        ]
    )
    open_qa_annotation_hash = hash_json(
        [
            [
                sample_id,
                records[sample_id].judge_question,
                records[sample_id].reference_answer,
                list(records[sample_id].sample.ground_truth),
            ]
            for sample_id in sample_ids
            if records[sample_id].sample.task.value == "open_qa"
        ]
    )
    return EvaluationContext(
        sample_ids=sample_ids,
        input_hashes={
            sample_id: hash_json(
                {
                    "question": records[sample_id].sample.question,
                    "videos": records[sample_id].sample.videos,
                }
            )
            for sample_id in sample_ids
        },
        rollout_seed=0,
        execution_identity={
            "benchmark_adapter": "mvagent-multibench-canonical-v1",
            "effective_config": base_config_sha256,
            "runtime_snapshot": runtime_snapshot_sha256,
            "decoding": "mvagent-configured-deterministic",
            "split": name,
        },
        evaluation_identity={
            "scorer": (
                str(scorer_identity.get("type") or "multibench-scorer")
                + ":"
                + hash_json(dict(scorer_identity))
            ),
            "aggregator": aggregator_identity,
            "projector": "trajectory-projector-v7-normalized-evaluation",
            "evaluator_prompt": "none",
            "ground_truth_hash": ground_truth_hash,
            "open_qa_annotation_hash": open_qa_annotation_hash,
            "split_manifest_hash": manifest_hash,
        },
    )


def initial_skill_set(source_root: Path, mode: str) -> SkillSet:
    if mode == "zero":
        return SkillSet.zero()
    authored = source_root / "mvagent/skills/skill_sets/authored-v000"
    return SkillSet.from_text(
        global_skill=(authored / "global.md").read_text(encoding="utf-8"),
        video_skill=(authored / "video.md").read_text(encoding="utf-8"),
    )


__all__ = [
    "EvalParentStageProvider",
    "FrozenMVAgentExecutor",
    "FrozenPlannerReplayExecutor",
    "build_evaluation_context",
    "initial_skill_set",
    "tree_hash",
]
