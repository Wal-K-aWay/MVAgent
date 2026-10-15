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
from .infra.data import DataSplitManifest, EvaluationRequest, audit_split, build_evaluation_context, group_by_media
from .infra.trajectory import TrajectoryProjector, routing_audit
from models.embeddings import EmbeddingConfig
from .infra.evaluation import CachedScorer, evaluate_batch, execution_metrics
from .infra.bank import BankExecutor, BankSnapshot
from .infra.skills import hash_json
from .infra.store import file_fingerprint, runtime_hash, tree_hash, write_json


def rollout_config_identity(mvconfig, execution):
    # Only model roles used by MVAgent belong to execution identity.
    online = mvconfig.to_dict()
    used = {ref.model_type for _, _, ref in mvconfig.model_roles()}
    online["models"] = {key: value for key, value in online["models"].items() if key in used}
    online["runtime"].pop("output_dir", None)
    online["runtime"].pop("cache_dir", None)
    for role in online["agents"].values():
        settings = role.get("skill", {})
        if not settings.get("enabled") or settings.get("mode") != "dynamic":
            raise ValueError("Evolution requires enabled dynamic Skill configuration on both roles")
        # Candidate content is independently hashed; retrieval/selector/embedding
        # settings remain part of execution identity, even with an empty bank.
        settings.pop("path", None)
        settings.pop("sha256", None)
        settings["enabled"] = True
    return hash_json({"online": online,
        "execution": execution.to_dict(),
        "input_adapter": file_fingerprint(Path(__file__).parent / "infra/benchmarks/adapters.py"),
        "bank_adapter": file_fingerprint(Path(__file__).parent / "infra/bank.py")})


def run(args):
    output = Path(args.output_dir).resolve()
    raw = yaml.safe_load(Path(args.config).read_text())
    if args.mode == "train" and raw.get("algorithm") not in ("global-skilladaptor-v1", "global-cluster-v1", "global-cluster-v2"):
        raise ValueError("Unknown training algorithm")
    runtime = raw["runtime"]
    config_path = Path(runtime["mvagent_config"]).resolve()
    mvconfig = MVAgentConfig.from_yaml(config_path)
    if args.mode == "train":
        settings = mvconfig.to_dict()["agents"]["global_agent"]["skill"]
        if settings.get("selection_scope") != "task" or not settings.get("embedding"):
            raise ValueError("Global evolution requires task-scoped selection and embedding")
    execution = ExecutionConfig.from_yaml(args.execution_config)
    if args.resume and json.loads((output / "runtime_config.json").read_text()) != mask_sensitive_data(mvconfig.to_dict()):
        raise ValueError("Resume requires the frozen MVAgent model/Agent configuration")
    split_path = args.split_manifest or raw.get("split_manifest")
    if not split_path:
        raise ValueError("Supply a frozen --split-manifest with source-disjoint Train/Eval membership")
    if args.mode == "train" and args.limit is not None:
        raise ValueError("--limit is evaluation-only; training uses training.batch_size")
    manifest = DataSplitManifest.from_json(split_path)
    train, evaluation = manifest.ids("train"), manifest.ids("eval")
    partitions = {"train": train, "eval": evaluation}
    if raw.get('algorithm') == 'global-cluster-v2' or (args.mode == 'evaluate' and args.split == 'cal'):
        partitions['cal'] = manifest.ids('cal')
        if not partitions['cal']:
            raise ValueError('cluster_v2 requires an explicit nonempty frozen Cal partition')
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
    if args.mode == "train" and any(audit['overlapping_ids'].values()):
        raise ValueError("Train/Eval share known media content; inspect data_audit.json")
    snapshot = Path(__file__).resolve().parents[1]
    source_identity = runtime_hash(snapshot)
    if "execution" in raw or "rollout_replicas" in runtime:
        raise ValueError("Move execution/rollout_replicas to --execution-config")
    config_identity = rollout_config_identity(mvconfig, execution)
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
        executor = BankExecutor(records=records, output_dir=output, base_config_path=config_path,
            runtime_snapshot_sha256=source_identity, execution_config=execution,
            cache_dir=cache_dir, base_config=mvconfig.to_dict())
        executor.on_complete = scorer.submit
        initial = BankSnapshot.from_dict(json.loads(Path(args.skills).read_text())) if args.skills else BankSnapshot.empty()
        run_manifest = {"mode": args.mode, "runtime_hash": source_identity,
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
            write_json(output / "routing_audit.json", routing_audit(initial, report, audit['media_groups']))
            summary = {"status": "completed", "sample_count": len(selected), "score": report["score"],
                "bucket_scores": report["bucket_scores"], "seconds": time.monotonic() - started,
                "generated": executor.last_generated,
                "samples": {sid: {"score": report["scores"][sid].score,
                    "prediction": episode.artifact["prediction"], **execution_metrics(episode)}
                    for sid, episode in report["episodes"].items()}}
        else:
            from importlib import import_module
            from mvagent.utils.media import probe_video_info
            variant = {'global-skilladaptor-v1': 'adaptor', 'global-cluster-v1': 'cluster', 'global-cluster-v2': 'cluster_v2'}[raw['algorithm']]
            module = import_module('skill_evolution.algorithms.alternating.global.' + variant + '.trainer')
            declared = {s.sample_id: s.group_id for s in manifest.samples}
            groups = group_by_media({sid: ['manifest:' + declared[sid], 'media:' + audit['media_groups'][sid]]
                                     for sid in records})
            write_json(output / 'source_groups.json', groups)
            metadata_cache = {}
            def metadata(videos):
                for path in videos.values():
                    if path not in metadata_cache:
                        metadata_cache[path] = probe_video_info(path)
                return {vid: metadata_cache[path] for vid, path in videos.items()}
            projector = TrajectoryProjector(video_metadata_provider=metadata,
                outcome_feedback_provider=foundation.scorer.feedback, source_group_provider=groups.__getitem__)
            optimizer = ModelFactory.create_model(EvolutionModelConfig(**raw['optimizer']), mvconfig)
            optimizer_ids = train + partitions.get('cal', ()) if variant == 'cluster_v2' else train
            trainer = module.GlobalTrainer(config=module.GlobalConfig(**raw.get('training', {})),
                initial_skill_set=initial, train_context=contexts['train'], eval_context=contexts['eval'],
                executor=executor, scorer=scorer, aggregator=foundation.aggregator, projector=projector,
                optimizer=optimizer,
                embedding_config=EmbeddingConfig.from_dict(settings['embedding']),
                **({'cal_context': contexts['cal']} if variant == 'cluster_v2' else {}),
                sample_metadata={sid: dict(input=dict(question=records[sid].sample.question,
                    options=records[sid].sample.options, videos=[dict(video_id=vid,
                        duration_sec=metadata(records[sid].sample.videos)[vid]['duration_sec'])
                        for vid in records[sid].sample.videos]),
                    reference=dict(ground_truth=list(records[sid].sample.ground_truth),
                    reference_answer=records[sid].reference_answer), source_group=groups[sid]) for sid in optimizer_ids},
                output_dir=output, episode_cache=executor.cache)
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
