#!/usr/bin/env python3
"""Resumable multi-GPU MVAgent evaluation on CVBench, MVU-Eval, and CrossVid."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import shutil
import subprocess
import threading
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import Any, Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATASET_ROOT = Path("/home/kww/datasets/Multi-Video")
DEFAULT_CONFIG = Path(__file__).resolve().with_name("config.yaml")
CROSSVID_TASKS = ("BU", "CC", "FSA", "MOC", "MSR", "NC", "PEA", "PI", "PSS", "CCQA")
CROSSVID_CHOICE_TASKS = frozenset(
    {"BU", "CC", "MOC", "MSR", "NC", "PEA", "PI"}
)
CROSSVID_TEMPORAL_TASKS = frozenset({"FSA"})
CROSSVID_ORDERING_TASKS = frozenset({"PSS"})
CROSSVID_OPEN_QA_TASKS = frozenset({"CCQA"})
CVBENCH_TASKS_PATH = (
    PROJECT_ROOT
    / "eval/e2e_eval/CVBench/Video-R1/src/r1-v/Evaluation/CVBench.json"
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _load_snapshot_bootstrap():
    path = PROJECT_ROOT / "src/mvagent/utils/snapshot.py"
    spec = spec_from_file_location("_agent_eval_snapshot_bootstrap", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load snapshot helper: {path}")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _crossvid_sample_ids(
    dataset_root: Path,
    limit: int | None,
) -> tuple[str, ...]:
    source = dataset_root / "CrossVid" / "qa.jsonl"
    if not source.is_file():
        raise FileNotFoundError(f"CrossVid manifest not found: {source}")
    counts: Counter[str] = Counter()
    sample_ids: list[str] = []
    with source.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            row_id = str(row.get("id") or "").strip()
            if not row_id:
                continue
            task = str(row.get("task") or "").strip().upper()
            if task not in CROSSVID_TASKS:
                continue
            if limit is not None and counts[task] >= limit:
                continue
            sample_ids.append(row_id)
            counts[task] += 1
    return tuple(sample_ids)


def _split_sample_ids(path: Path) -> tuple[str, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("samples") if isinstance(payload, Mapping) else None
    if not isinstance(rows, list):
        raise ValueError(f"Split manifest must contain a samples list: {path}")
    sample_ids = tuple(
        str(row.get("sample_id") or "").strip()
        for row in rows
        if isinstance(row, Mapping) and str(row.get("split") or "eval") == "eval"
    )
    if not sample_ids or any(not sample_id for sample_id in sample_ids):
        raise ValueError(f"Split manifest contains no valid eval sample IDs: {path}")
    if len(set(sample_ids)) != len(sample_ids):
        raise ValueError(f"Split manifest contains duplicate eval sample IDs: {path}")
    return sample_ids


def _sample_ids(
    dataset_root: Path,
    benchmarks: tuple[str, ...],
    limit: int | None,
    split_manifest: Path | None = None,
) -> tuple[str, ...]:
    sample_ids: list[str] = []
    if "cvbench" in benchmarks:
        rows = json.loads((dataset_root / "CVBench/QAs.json").read_text(encoding="utf-8"))
        sample_ids.extend(f"cvbench:{row['id']}" for row in rows[:limit])
    if "mvu_eval" in benchmarks:
        rows = json.loads((dataset_root / "MVU-Eval/QAs.json").read_text(encoding="utf-8"))
        sample_ids.extend(
            f"mvu_eval:{row.get('task') or 'Unknown'}:{row['id']}"
            for row in rows[:limit]
        )
    if "crossvid" in benchmarks:
        if split_manifest is None:
            sample_ids.extend(_crossvid_sample_ids(dataset_root, limit))
        else:
            selected = _split_sample_ids(split_manifest)
            if any(not sample_id.startswith("crossvid:") for sample_id in selected):
                raise ValueError("--split-manifest may only select CrossVid samples")
            available = set(_crossvid_sample_ids(dataset_root, None))
            missing = [sample_id for sample_id in selected if sample_id not in available]
            if missing:
                raise ValueError(
                    f"Split manifest contains {len(missing)} unknown CrossVid IDs; first: {missing[0]}"
                )
            sample_ids.extend(selected)
    return tuple(sample_ids)


def _select_exact_sample_ids(path: Path, available: tuple[str, ...]) -> tuple[str, ...]:
    """Select an ordered diagnostic panel without changing benchmark inputs."""
    selected = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(selected, list) or not selected or any(
        not isinstance(sid, str) or not sid.strip() for sid in selected
    ):
        raise ValueError("--sample-ids-file must contain a nonempty JSON array of IDs")
    if len(set(selected)) != len(selected):
        raise ValueError("--sample-ids-file contains duplicate IDs")
    missing = set(selected) - set(available)
    if missing:
        raise ValueError(f"Unknown or excluded benchmark IDs: {sorted(missing)[:3]}")
    return tuple(selected)


def _record_path(output_dir: Path, sample_id: str) -> Path:
    dataset = sample_id.split(":", 1)[0]
    return output_dir / "records" / dataset / sample_id / "result.json"


def _load_completed(output_dir: Path, sample_ids: tuple[str, ...]) -> dict[str, dict[str, Any]]:
    completed: dict[str, dict[str, Any]] = {}
    for sample_id in sample_ids:
        path = _record_path(output_dir, sample_id)
        if not path.is_file():
            continue
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if row.get("sample_id") == sample_id and row.get("status") == "ok":
            completed[sample_id] = {key: row.get(key) for key in ("sample_id", "status", "scoring_status")}
    return completed


def _extract_prediction(result: Mapping[str, Any]) -> str:
    answer = result.get("answer")
    if isinstance(answer, Mapping):
        answer = answer.get("answer")
    return str(answer or "").strip()


def _task_family(native_task: str) -> str:
    task = str(native_task or "").strip().upper()
    if task in CROSSVID_TEMPORAL_TASKS:
        return "temporal"
    if task in CROSSVID_ORDERING_TASKS:
        return "ordering"
    if task in CROSSVID_OPEN_QA_TASKS:
        return "open_qa"
    return "choice"


def _is_crossvid_open_qa_sample(sample_id: str) -> bool:
    """Return whether ``sample_id`` belongs to a CrossVid open-QA sample."""

    if not sample_id.startswith("crossvid:"):
        return False
    parts = sample_id.split(":")
    if len(parts) < 3:
        return False
    return parts[1].upper() in CROSSVID_OPEN_QA_TASKS


def _build_crossvid_scorer(
    records: Mapping[str, Any],
    *,
    judge_model: Any,
    cache_dir: Path,
) -> tuple[Any, Mapping[str, Any]]:
    """Construct a :class:`DatasetScorer` covering all CrossVid task families."""

    benchmark_module = importlib.import_module("skill_evolution.infra.benchmarks")
    scoring_module = importlib.import_module("skill_evolution.infra.benchmarks.scoring")
    contracts_module = importlib.import_module("skill_evolution.infra.benchmarks.contracts")

    samples = {
        sample_id: record.sample for sample_id, record in records.items()
    }
    open_ids = [
        sample_id
        for sample_id, record in records.items()
        if record.sample.task is contracts_module.SampleTask.OPEN_QA
    ]
    private_scorers: dict[str, Any] = {}
    if open_ids:
        if judge_model is None:
            raise ValueError("CrossVid OpenQA requires an explicit --judge-model")
        judge = benchmark_module.FixedOpenQAJudge(
            model=judge_model,
            cache_dir=str(cache_dir),
        )
        for sample_id in open_ids:
            record = records[sample_id]
            private_scorers[sample_id] = judge.bind(
                sample_id=sample_id,
                question=(
                    record.judge_question
                    or record.sample.question
                ),
                reference_answer=record.reference_answer,
                scoring_points=[
                    str(point) for point in record.sample.ground_truth
                ],
            )

    registry = scoring_module.ScorerRegistry(
        {
            contracts_module.SampleTask.CHOICE: scoring_module.ChoiceScorer(
                strict_format=True,
                separator="",
            ),
            contracts_module.SampleTask.ORDERING: scoring_module.OrderingScorer(
                separator="->",
                strict_format=True,
            ),
            contracts_module.SampleTask.TEMPORAL_LOCALIZATION: scoring_module.TemporalLocalizationScorer(
                separator=",",
                strict_format=True,
            ),
        }
    )
    scorer = benchmark_module.DatasetScorer(
        samples=samples,
        registry=registry,
        scorer_by_sample=private_scorers,
        prediction_getter=lambda artifact: str(
            artifact.get("prediction") or ""
        ).strip(),
    )
    scorer_identity = {
        "choice": "strict-normalized-option-label-v1",
        "ordering": "crossvid-sequence-exact-v1",
        "temporal_localization": "crossvid-interval-iou-strict-v1",
        "open_qa": (
            dict(private_scorers[open_ids[0]].judge.identity)
            if open_ids
            else {"enabled": False}
        ),
    }
    return scorer, scorer_identity


def _cvbench_categories() -> dict[str, str]:
    if not CVBENCH_TASKS_PATH.is_file():
        return {}
    rows = json.loads(CVBENCH_TASKS_PATH.read_text(encoding="utf-8"))
    return {f"cvbench:{row['id']}": str(row["task_type"]) for row in rows}


def _summarize(
    *,
    output_dir: Path,
    sample_ids: tuple[str, ...],
    crossvid_scorer: Any = None,
) -> dict[str, Any]:
    from models.execution import output_metrics

    categories = _cvbench_categories()
    output_counts = Counter()
    by_dataset: dict[str, Counter[str]] = defaultdict(Counter)
    by_task: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    by_task_family: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    for sample_id in sample_ids:
        path = _record_path(output_dir, sample_id)
        if not path.is_file():
            continue
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        output_counts.update(output_metrics(row.get("events", [])))
        dataset = str(row.get("dataset") or sample_id.split(":", 1)[0])
        native_task = str(row.get("native_task") or "all")
        category = categories.get(sample_id, native_task)
        by_dataset[dataset]["records"] += 1
        if row.get("status") == "ok":
            by_dataset[dataset]["inference_completed"] += 1
        if row.get("status") == "ok" and row.get("scoring_status") == "deferred":
            by_dataset[dataset]["deferred"] += 1
            continue
        score = row.get("score") if dataset == "crossvid" else None
        if row.get("status") == "ok" and row.get("scoring_status") == "ok":
            by_dataset[dataset]["completed"] += 1
            if score is None:
                score = float(bool(row.get("correct")))
            by_dataset[dataset]["correct"] += float(score)
            by_task[(dataset, category)]["completed"] += 1
            by_task[(dataset, category)]["correct"] += float(score)
            family = _task_family(native_task) if dataset == "crossvid" else "choice"
            by_task_family[(dataset, family)]["completed"] += 1
            by_task_family[(dataset, family)]["correct"] += float(score)
        else:
            by_dataset[dataset]["errors"] += 1

    expected = Counter(sample_id.split(":", 1)[0] for sample_id in sample_ids)
    datasets = {}
    for dataset, count in sorted(expected.items()):
        stats = by_dataset[dataset]
        completed = stats["completed"]
        datasets[dataset] = {
            "expected": count,
            "completed": completed,
            "inference_completed": stats["inference_completed"],
            "deferred": stats["deferred"],
            "errors": stats["errors"],
            "pending": count - stats["records"],
            "score_sum": stats["correct"],
            "accuracy": stats["correct"] / completed if completed and not stats["deferred"] else None,
            "scored_subset_accuracy": stats["correct"] / completed if completed else None,
            "by_task": {
                task: {
                    "score_sum": values["correct"],
                    "total": values["completed"],
                    "accuracy": (
                        values["correct"] / values["completed"]
                        if values["completed"]
                        else None
                    ),
                }
                for (item_dataset, task), values in sorted(by_task.items())
                if item_dataset == dataset
            },
            "by_task_family": {
                family: {
                    "score_sum": values["correct"],
                    "total": values["completed"],
                    "accuracy": (
                        values["correct"] / values["completed"]
                        if values["completed"]
                        else None
                    ),
                }
                for (item_dataset, family), values in sorted(by_task_family.items())
                if item_dataset == dataset
            },
        }

    summary: dict[str, Any] = {
        "updated_at_utc": _utc_now(),
        "scoring": (
            "strict per-task-family scorer"
            " (choice strict-normalized option label, ordering '->', temporal IoU,"
            " open-QA coverage/correctness judge when enabled; deferred answers are unscored)"
            if any(sid.startswith("crossvid:") for sid in sample_ids)
            else "strict exact uppercase option label"
        ),
        "output_metrics": dict(output_counts),
        "datasets": datasets,
        "total_expected": len(sample_ids),
        "total_completed": sum(item["completed"] for item in datasets.values()),
        "total_inference_completed": sum(item["inference_completed"] for item in datasets.values()),
        "total_deferred": sum(item["deferred"] for item in datasets.values()),
        "score_complete": all(not item["deferred"] and not item["pending"] and not item["errors"] for item in datasets.values()),
        "total_errors": sum(item["errors"] for item in datasets.values()),
        "total_pending": sum(item["pending"] for item in datasets.values()),
    }
    return summary


def _prepare_output(
    *,
    output_dir: Path,
    config_path: Path,
    dataset_root: Path,
    sample_ids: tuple[str, ...],
    judge_model: str | None,
    resume: bool,
    defer_open_qa_judge: bool = False,
    split_manifest: Path | None = None,
):
    bootstrap = _load_snapshot_bootstrap()
    bootstrap.configure_workspace_runtime_env()
    output_dir.mkdir(parents=True, exist_ok=True)
    frozen_config = output_dir / "input_config.yaml"
    frozen_runner = output_dir / "protocol_source/run.py"
    snapshot_dir = output_dir / "src/mvagent"
    if resume:
        if not snapshot_dir.is_dir() or not frozen_config.is_file() or not frozen_runner.is_file():
            raise FileNotFoundError("--resume requires the existing source, config, and runner snapshots.")
        if frozen_runner.read_bytes() != Path(__file__).read_bytes():
            raise RuntimeError("The current runner differs from the frozen run.py; do not mix protocols.")
    else:
        if snapshot_dir.exists() or frozen_config.exists() or frozen_runner.exists():
            raise FileExistsError("Output already contains a run; use --resume.")
        bootstrap.ensure_source_snapshot(output_dir)
        import yaml
        frozen_config.write_text(yaml.safe_dump(bootstrap.mask_sensitive_data(
            yaml.safe_load(config_path.read_text())), sort_keys=False))
        frozen_runner.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(Path(__file__), frozen_runner)

    configs_module, engine_module, _utils_module = bootstrap.load_runtime_modules(snapshot_dir)
    benchmark_module = importlib.import_module("skill_evolution.infra.benchmarks")
    operator_module = importlib.import_module("skill_evolution.infra.store")
    records = benchmark_module.load_multibench_records(dataset_root, sample_ids)

    crossvid_ids = [sid for sid in sample_ids if sid.startswith("crossvid:")]
    cvbench_present = any(sid.startswith("cvbench:") for sid in sample_ids)
    mvu_present = any(sid.startswith("mvu_eval:") for sid in sample_ids)
    identity = {
        "protocol": "mvagent-agent-eval-v2",
        "runner_sha256": _sha256(frozen_runner),
        "config_sha256": _sha256(frozen_config),
        "runtime_snapshot_sha256": operator_module.tree_hash(snapshot_dir.parent),
        "dataset_root": str(dataset_root),
        "dataset_sha256": {
            "cvbench": (
                _sha256(dataset_root / "CVBench/QAs.json") if cvbench_present else None
            ),
            "mvu_eval": (
                _sha256(dataset_root / "MVU-Eval/QAs.json") if mvu_present else None
            ),
            "crossvid": (
                _sha256(dataset_root / "CrossVid/qa.jsonl") if crossvid_ids else None
            ),
        },
        "sample_ids_sha256": hashlib.sha256(
            "\n".join(sample_ids).encode("utf-8")
        ).hexdigest(),
        "sample_count": len(sample_ids),
        "split_manifest": (
            {
                "path": str(split_manifest),
                "sha256": _sha256(split_manifest),
            }
            if split_manifest is not None
            else None
        ),
        "judge_model": judge_model,
        "defer_open_qa_judge": defer_open_qa_judge,
    }
    manifest_path = output_dir / "run_manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("identity") != identity:
            raise RuntimeError("Resume identity differs from the existing run manifest.")
    else:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            check=False,
            capture_output=True,
            text=True,
        ).stdout.strip()
        manifest = {
            "status": "running",
            "started_at_utc": _utc_now(),
            "git_commit": commit,
            "identity": identity,
        }
        _atomic_json(manifest_path, manifest)
    return bootstrap, configs_module, engine_module, records, manifest


def _score_sample(
    *,
    crossvid_scorer: Any,
    sample_id: str,
    dataset: str,
    native_task: str,
    prediction: str,
) -> tuple[float, str | None]:
    """Score one crossvid sample using its task-family scorer."""

    if dataset != "crossvid" or crossvid_scorer is None:
        # Exact-match correctness is stored in ``correct`` by the caller;
        # keep ``score`` empty so summaries fall back to it.
        return None, None
    try:
        result = crossvid_scorer.score_prediction(sample_id, prediction)
    except Exception as exc:
        return None, f"scorer-error: {exc}"
    return float(result.score), None


def _score_saved_row(row, record, scorer, *, defer_open_qa_judge):
    if defer_open_qa_judge and _is_crossvid_open_qa_sample(row['sample_id']):
        row.update(score=None, correct=None, scoring_status='deferred', scoring_error='')
        return
    score, error = _score_sample(crossvid_scorer=scorer, sample_id=row['sample_id'],
        dataset=record.dataset, native_task=record.native_task, prediction=row['prediction'])
    row.update(score=score, scoring_status='error' if error else 'ok', scoring_error=error or '',
        correct=bool(score is not None and score >= 1) if record.dataset == 'crossvid'
        else row['prediction'] == str(record.sample.ground_truth[0]))


def _run(args: argparse.Namespace) -> None:
    output_dir = args.output.expanduser().resolve()
    config_path = args.config.expanduser().resolve()
    dataset_root = args.dataset_root.expanduser().resolve()
    split_manifest = args.split_manifest.expanduser().resolve() if args.split_manifest else None
    sample_ids = _sample_ids(
        dataset_root,
        tuple(dict.fromkeys(args.benchmarks)),
        args.limit,
        split_manifest,
    )
    if args.sample_ids_file:
        sample_ids = _select_exact_sample_ids(args.sample_ids_file, sample_ids)
    if not sample_ids:
        raise ValueError("No benchmark samples selected")
    _, configs_module, _, records, manifest = _prepare_output(
        output_dir=output_dir, config_path=config_path, dataset_root=dataset_root,
        sample_ids=sample_ids, judge_model=args.judge_model, resume=args.resume,
        defer_open_qa_judge=args.defer_open_qa_judge,
        split_manifest=split_manifest)
    from mvagent.batch import BatchExecutor, ExecutionConfig
    from models.factory import ModelFactory
    from mvagent.configs.agent_config import Agent_Model_Config
    from mvagent.utils import mask_sensitive_data
    execution = ExecutionConfig.from_yaml(args.execution_config)
    import yaml
    live = yaml.safe_load(config_path.read_text())
    if mask_sensitive_data(live) != yaml.safe_load((output_dir / "input_config.yaml").read_text()):
        raise ValueError("Runtime configuration differs from the frozen configuration")
    config = configs_module.MVAgentConfig.from_dict(live)
    if any(_is_crossvid_open_qa_sample(sid) for sid in sample_ids) and not args.judge_model and not args.defer_open_qa_judge:
        raise ValueError("OpenQA requires --judge-model naming a configured model")
    _atomic_json(output_dir / "executions" / (str(__import__('time').time_ns()) + '.json'), execution.to_dict())
    event_lock = threading.Lock()
    def on_event(event):
        with event_lock, (output_dir / "execution_events.jsonl").open("a") as stream:
            stream.write(json.dumps(event) + "\n")
    finished = _load_completed(output_dir, sample_ids)
    done_scores = {"ok", "deferred"} if args.defer_open_qa_judge else {"ok"}
    if len(finished) == len(sample_ids) and all(row.get("scoring_status") in done_scores for row in finished.values()):
        summary = _summarize(output_dir=output_dir, sample_ids=sample_ids)
        _atomic_json(output_dir / 'summary.json', summary)
        manifest.update(status='completed', finished_at_utc=_utc_now())
        _atomic_json(output_dir / 'run_manifest.json', manifest)
        print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
        return
    batch = BatchExecutor(execution, on_event=on_event)
    judge_model, scorer = None, None
    scoring = ThreadPoolExecutor(max_workers=1, thread_name_prefix="agent-scoring")
    futures = []
    try:
        batch.prepare(config.to_dict())
        if args.judge_model:
            judge_model = ModelFactory.create_model(Agent_Model_Config(model_type=args.judge_model,
                temperature=0.0, max_tokens=512), config)
        crossvid = {sid: record for sid, record in records.items() if sid.startswith("crossvid:")
                    and not (args.defer_open_qa_judge and _is_crossvid_open_qa_sample(sid))}
        if crossvid:
            scorer, scorer_identity = _build_crossvid_scorer(crossvid, judge_model=judge_model,
                                                            cache_dir=output_dir / "crossvid_judge_cache")
            if args.defer_open_qa_judge:
                scorer_identity = {**scorer_identity, "open_qa": {"enabled": False, "status": "deferred"}}
            if args.resume and manifest.get('scorer_identity') != scorer_identity:
                raise ValueError('Scorer identity changed on resume')
            manifest['scorer_identity'] = scorer_identity
            _atomic_json(output_dir / "run_manifest.json", manifest)
        def score_saved(path):
            row = json.loads(path.read_text())
            record = records[row['sample_id']]
            _score_saved_row(row, record, scorer, defer_open_qa_judge=args.defer_open_qa_judge)
            _atomic_json(path, row)
            if row.get('scoring_error'):
                raise RuntimeError(row['scoring_error'])
        for sid in finished:
            path = _record_path(output_dir, sid)
            if json.loads(path.read_text()).get('scoring_status') not in done_scores:
                futures.append(scoring.submit(score_saved, path))
        progress = {'finished': len(finished)}
        def completed(payload):
            sid = payload['sample_id']
            record = records[sid]
            row = dict(sample_id=sid, dataset=record.dataset, native_task=record.native_task,
                task_family=_task_family(record.native_task) if record.dataset == 'crossvid' else 'choice',
                prediction=_extract_prediction(payload['result']), ground_truth=list(record.sample.ground_truth),
                judge_question=record.judge_question, reference_answer=record.reference_answer,
                score=None, correct=False, scoring_status='pending',
                status=payload['status'], error=payload.get('error', ''),
                worker={'pid': payload['worker_pid']}, attempt=payload['attempt'],
                result=payload['result'], events=payload['events'])
            path = _record_path(output_dir, sid)
            _atomic_json(path, row)
            if row['status'] == 'ok':
                futures.append(scoring.submit(score_saved, path))
            progress['finished'] += 1
            state = dict(finished=progress['finished'], total=len(sample_ids), updated_at_utc=_utc_now())
            _atomic_json(output_dir / 'progress.json', state)
            print(f"[PROGRESS] {progress['finished']}/{len(sample_ids)}", flush=True)
        jobs = [dict(sample_id=sid, question=records[sid].sample.question,
                     videos=dict(records[sid].sample.videos)) for sid in sample_ids if sid not in finished]
        batch.run(jobs, config.to_dict(), on_complete=completed)
        for future in futures:
            future.result()
        summary = _summarize(output_dir=output_dir, sample_ids=sample_ids)
        _atomic_json(output_dir / 'summary.json', summary)
        manifest.update(status='completed', finished_at_utc=_utc_now())
        _atomic_json(output_dir / 'run_manifest.json', manifest)
        print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    except BaseException as exc:
        manifest.update(status='incomplete', error=str(exc))
        _atomic_json(output_dir / 'run_manifest.json', manifest)
        raise
    finally:
        scoring.shutdown(wait=True)
        batch.close()
        if judge_model:
            judge_model.close()


def _self_check() -> None:
    assert str(_record_path(Path("/tmp/run"), "mvu_eval:Counting:7")).endswith(
        "records/mvu_eval/mvu_eval:Counting:7/result.json"
    )
    assert str(_record_path(Path("/tmp/run"), "crossvid:BU:0")).endswith(
        "records/crossvid/crossvid:BU:0/result.json"
    )
    assert _task_family("BU") == "choice"
    assert _task_family("FSA") == "temporal"
    assert _task_family("PSS") == "ordering"
    assert _task_family("CCQA") == "open_qa"
    assert _is_crossvid_open_qa_sample("crossvid:CCQA:0")
    assert not _is_crossvid_open_qa_sample("crossvid:BU:0")
    print("agent_eval self-check passed")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--dataset-root", type=Path, default=DEFAULT_DATASET_ROOT)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--benchmarks",
        nargs="+",
        choices=("cvbench", "mvu_eval", "crossvid"),
        default=("cvbench", "mvu_eval", "crossvid"),
        help="Benchmarks to evaluate in one unified run (default: all three).",
    )
    parser.add_argument("--execution-config", type=Path, help="Shared question/model pool configuration")
    parser.add_argument("--judge-model", help="Explicit configured model for OpenQA scoring")
    parser.add_argument("--defer-open-qa-judge", action="store_true",
                        help="Save OpenQA answers and references without scoring or loading a Judge")
    parser.add_argument("--limit", type=int, help="Smoke limit applied to each benchmark")
    parser.add_argument("--sample-ids-file", type=Path,
                        help="JSON array selecting exact IDs across the requested benchmarks")
    parser.add_argument(
        "--split-manifest",
        type=Path,
        help="Frozen eval split manifest used to select CrossVid samples.",
    )
    parser.add_argument("--progress-every", type=int, default=10)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--self-check", action="store_true")
    return parser


def main() -> None:
    args = _parser().parse_args()
    if args.self_check:
        _self_check()
        return
    if args.defer_open_qa_judge and args.judge_model:
        raise SystemExit("--defer-open-qa-judge cannot be combined with --judge-model")
    if args.execution_config is None:
        raise SystemExit("--execution-config is required")
    if args.output is None:
        raise SystemExit("--output is required")
    if args.limit is not None and args.limit < 1:
        raise SystemExit("--limit must be positive")
    if args.limit is not None and args.split_manifest is not None:
        raise SystemExit("--limit cannot be combined with --split-manifest")
    if args.sample_ids_file and (args.limit is not None or args.split_manifest is not None):
        raise SystemExit("--sample-ids-file cannot be combined with --limit or --split-manifest")
    if args.split_manifest is not None and "crossvid" not in args.benchmarks:
        raise SystemExit("--split-manifest requires the crossvid benchmark")
    if args.progress_every < 1:
        raise SystemExit("--progress-every must be positive")
    _run(args)


if __name__ == "__main__":
    main()
