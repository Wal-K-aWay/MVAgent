"""Compose shared services; optimization loops live exclusively in algorithms/."""
from __future__ import annotations

import json
from pathlib import Path
import time

import yaml
from models.factory import ModelFactory
from mvagent.configs import MVAgentConfig
from mvagent.batch import ExecutionConfig
from mvagent.utils import mask_sensitive_data
from .infra.benchmarks import FixedOpenQAJudge, SampleTask, build_benchmark_foundation, load_multibench_records
from .configs.model_config import EvolutionModelConfig
from .infra.data import DataSplitManifest, EvaluationRequest, audit_split, build_evaluation_context
from .infra.evaluation import CachedScorer, evaluate_batch, execution_metrics
from .infra.rollout import FrozenMVAgentExecutor
from .infra.skills import SkillSet, hash_json, validate_text
from .infra.store import file_fingerprint, runtime_hash, tree_hash, write_json
from .infra.trajectory import TrajectoryProjector
from .infra.trajectory import build_role_architectures


def run(args):
    output = Path(args.output_dir).resolve()
    raw = yaml.safe_load(Path(args.config).read_text())
    runtime = raw["runtime"]
    config_path = Path(runtime["mvagent_config"]).resolve()
    mvconfig = MVAgentConfig.from_yaml(config_path)
    execution = ExecutionConfig.from_yaml(args.execution_config)
    if args.resume and json.loads((output / "runtime_config.json").read_text()) != mask_sensitive_data(mvconfig.to_dict()):
        raise ValueError("Resume requires the frozen MVAgent model/Agent configuration")
    manifest = DataSplitManifest.from_json(args.split_manifest or raw["split_manifest"])
    train, evaluation = manifest.ids("train"), manifest.ids("eval")
    partitions = {"train": train, "eval": evaluation}
    if args.mode == "evaluate":
        partitions["test"] = manifest.ids("test")
        if not partitions[args.split]:
            raise ValueError(f"The manifest has no {args.split} samples")
    elif not train or not evaluation:
        raise ValueError("Training requires non-empty Train and Eval partitions")
    ids = tuple(sid for members in partitions.values() for sid in members)
    records = load_multibench_records(args.dataset_root or raw["dataset_root"], ids)
    cache_dir = Path(runtime.get("cache_dir", ".cache/skill_evolution")).resolve()
    cache_dir.mkdir(parents=True, exist_ok=True)
    fingerprints = {path: file_fingerprint(path) for path in sorted({path for record in records.values() for path in record.sample.videos.values()})}
    audit = audit_split(manifest, records, fingerprints)
    write_json(output / "data_audit.json", audit)
    snapshot = Path(__file__).resolve().parents[1]
    source_identity = runtime_hash(snapshot)
    # Only model roles used by MVAgent belong to execution identity.
    online = mvconfig.to_dict()
    used = {ref.model_type for _, _, ref in mvconfig.model_roles()}
    online["models"] = {key: value for key, value in online["models"].items() if key in used}
    online["runtime"].pop("output_dir", None)
    online["runtime"].pop("cache_dir", None)
    for role in online["agents"].values():
        role.pop("skill", None)
    if "execution" in raw or "rollout_replicas" in runtime:
        raise ValueError("Move execution/rollout_replicas to --execution-config")
    config_identity = hash_json({"online": online,
        "question_timeout_sec": execution.question_timeout_sec,
        "question_retries": execution.question_retries,
        "input_adapter": file_fingerprint(Path(__file__).parent / "infra/benchmarks/adapters.py")})
    judge_model = optimizer = None
    scorer = executor = None
    try:
        judge = None
        if any(record.sample.task is SampleTask.OPEN_QA for record in records.values()):
            cfg = raw.get("open_qa_judge", {})
            if not cfg.get("enabled"):
                raise ValueError("OpenQA requires an enabled fixed Judge")
            judge_model = ModelFactory.create_model(EvolutionModelConfig(**cfg["model"]), mvconfig)
            judge = FixedOpenQAJudge(model=judge_model, cache_dir=cache_dir / "open_qa_judge",
                                     prompt_path=cfg.get("prompt_path") or None)
        foundation = build_benchmark_foundation(records, open_qa_judge=judge)
        scorer_identity = {**foundation.scorer_identity,
                           "code": tree_hash(Path(__file__).parent / "infra" / "benchmarks")}
        scorer = CachedScorer(foundation.scorer, records, scorer_identity, cache_dir)
        contexts = {name: build_evaluation_context(name=name, sample_ids=members, records=records,
            base_config_sha256=config_identity, runtime_snapshot_sha256=source_identity,
            manifest_hash=manifest.manifest_hash, scorer_identity=scorer_identity,
            aggregator_identity=foundation.aggregator.identity, repeat_id=args.repeat_id,
            media_fingerprints=fingerprints) for name, members in partitions.items() if members}
        executor = FrozenMVAgentExecutor(records=records, output_dir=output, base_config_path=config_path,
            runtime_snapshot_sha256=source_identity, execution_config=execution,
            cache_dir=cache_dir, base_config=mvconfig.to_dict())
        executor.on_complete = scorer.submit
        initial = SkillSet(**json.loads(Path(args.skills).read_text())) if args.skills else SkillSet.zero()
        for text in (initial.global_skill, initial.video_skill):
            validate_text(text)
        run_manifest = {"algorithm": "alternating", "mode": args.mode, "runtime_hash": source_identity,
            "source_hash": tree_hash(snapshot), "execution_config_hash": config_identity,
            "split_hash": manifest.manifest_hash, "repeat_id": args.repeat_id,
            "selected_split": args.split, "limit": args.limit, "media_fingerprints": fingerprints,
            "config": mask_sensitive_data(raw), "cache_dir": str(cache_dir),
            "initial_skills": initial.to_dict(), "scorer": scorer_identity}
        path = output / "manifest.json"
        if args.resume and json.loads(path.read_text()) != run_manifest:
            raise ValueError("Resume requires exactly the same experiment identity")
        write_json(path, run_manifest)
        write_json(output / "executions" / f"{time.time_ns()}.json", execution.to_dict())
        write_json(output / "runtime_config.json", mask_sensitive_data(mvconfig.to_dict()))
        write_json(output / "split_manifest.json", manifest.to_dict())
        if args.mode == "evaluate":
            context = contexts[args.split]
            selected = context.sample_ids[:args.limit] if args.limit else context.sample_ids
            started = time.monotonic()
            report = evaluate_batch(executor, executor.cache, scorer, foundation.aggregator,
                                    EvaluationRequest(initial, context, tuple(selected), "evaluation"))
            summary = {"status": "completed", "sample_count": len(selected), "score": report["score"],
                "bucket_scores": report["bucket_scores"], "seconds": time.monotonic() - started,
                "generated": executor.last_generated,
                "samples": {sid: {"score": report["scores"][sid].score,
                    "prediction": episode.artifact["prediction"], **execution_metrics(episode)}
                    for sid, episode in report["episodes"].items()}}
        else:
            from mvagent.utils.media import probe_video_info
            metadata_cache = {}
            def metadata(videos):
                for path in videos.values():
                    if path not in metadata_cache:
                        metadata_cache[path] = probe_video_info(path)
                return {vid: metadata_cache[path] for vid, path in videos.items()}
            groups = {s.sample_id: s.group_id for s in manifest.samples}
            projector = TrajectoryProjector(video_metadata_provider=metadata,
                outcome_feedback_provider=foundation.scorer.feedback, source_group_provider=groups.__getitem__)
            sample_metadata = {sid: {"task": record.sample.question, "task_type": record.sample.task.value,
                "reference": "Ground truth: " + json.dumps(list(record.sample.ground_truth)) +
                    ("\nReference answer: " + record.reference_answer if record.reference_answer else "")}
                for sid, record in records.items()}
            from .algorithms.alternating import AlternatingConfig, AlternatingTrainer
            optimizer = ModelFactory.create_model(EvolutionModelConfig(**raw["optimizer"]), mvconfig)
            ref = mvconfig.video_agent.observer
            observer = mvconfig.models[ref.model_type].to_runtime_config(ref.model_type, ref)
            architectures = build_role_architectures(max_videos_per_watch=mvconfig.global_agent.max_videos_per_watch,
                max_video_inputs_per_request=observer.max_videos_per_request,
                max_video_frames_per_request=observer.max_video_frames_per_request,
                max_ranges_per_action=mvconfig.video_agent.max_ranges_per_action)
            trainer = AlternatingTrainer(config=AlternatingConfig(**raw["training"]), initial_skill_set=initial,
                train_context=contexts["train"], eval_context=contexts["eval"], executor=executor,
                scorer=scorer, aggregator=foundation.aggregator, projector=projector, optimizer=optimizer,
                role_architectures=architectures, sample_metadata=sample_metadata, output_dir=output,
                episode_cache=executor.cache)
            summary = trainer.run(resume=args.resume)
        write_json(output / "summary.json", summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
        return summary
    except BaseException as exc:
        write_json(output / "summary.json", {"status": "incomplete", "error": str(exc)})
        raise
    finally:
        if scorer:
            scorer.close()
        if executor:
            executor.close()
        for model in (judge_model, optimizer):
            if model:
                model.close()
