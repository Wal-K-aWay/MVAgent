#!/usr/bin/env python3
"""Run the three vendored benchmarks through official multimodal APIs.

The adapter keeps benchmark prompts, media allocation, preprocessing, and scoring
separate from model transport.  It never persists the API key.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SOURCE_ROOT = PROJECT_ROOT / "eval/e2e_eval"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from client import APIChat, MODEL_PROFILES, profile_for
from scripts import run_official_cvbench_mvu as shared


UPSTREAM_COMMITS = {
    "cvbench": "f8dc8f752fb8e7a3a05ac90e9ff9b3a9e90d79ed",
    "mvu-eval": "a5937adea78e9649af53cd9a4e30a91ed7fd3df2",
    "crossvid": "b53ada63551f9ac4a726b381b627d17ece066281",
}
CROSSVID_TASKS = (
    "BU",
    "CC",
    "CCQA",
    "FSA",
    "MOC",
    "MSR",
    "NC",
    "PEA",
    "PI",
    "PSS",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run CVBench, MVU-Eval, and CrossVid with official multimodal APIs."
    )
    parser.add_argument("--model", required=True, choices=tuple(MODEL_PROFILES))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--benchmarks",
        default="cvbench,mvu-eval,crossvid",
        help="Comma-separated subset of cvbench,mvu-eval,crossvid.",
    )
    parser.add_argument(
        "--frames", type=int, default=512, help="Total video-frame cap per question."
    )
    parser.add_argument(
        "--max-side",
        type=int,
        default=720,
        help="Maximum frame side; aspect ratio is preserved.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Concurrent questions; keep low for 512-frame requests.",
    )
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=900.0)
    parser.add_argument(
        "--limit", type=int, help="Deterministic first-N smoke limit per dataset/task."
    )
    parser.add_argument("--base-url", help="Override the selected profile's official URL.")
    parser.add_argument("--api-key-env", help="Override the selected profile's key variable.")
    parser.add_argument(
        "--media-cache-dir",
        type=Path,
        default=PROJECT_ROOT / ".cache/e2e_media",
    )
    parser.add_argument("--no-media-cache", action="store_true")
    parser.add_argument(
        "--crossvid-tasks",
        default=",".join(CROSSVID_TASKS),
        help="Comma-separated CrossVid task codes.",
    )
    parser.add_argument(
        "--cvbench-root",
        type=Path,
        default=Path("/home/kww/datasets/Multi-Video/CVBench"),
    )
    parser.add_argument(
        "--mvu-root",
        type=Path,
        default=Path("/home/kww/datasets/Multi-Video/MVU-Eval"),
    )
    parser.add_argument(
        "--crossvid-root",
        type=Path,
        default=Path("/home/kww/datasets/Multi-Video/CrossVid"),
    )
    args = parser.parse_args()

    positive = (
        "frames",
        "max_side",
        "workers",
        "max_retries",
        "timeout",
    )
    invalid = [name for name in positive if getattr(args, name) <= 0]
    if invalid:
        parser.error("must be positive: " + ", ".join(invalid))
    if args.limit is not None and args.limit <= 0:
        parser.error("--limit must be positive")
    allowed_benchmarks = {"cvbench", "mvu-eval", "crossvid"}
    args.benchmarks = tuple(
        dict.fromkeys(
            item.strip().lower()
            for item in args.benchmarks.split(",")
            if item.strip()
        )
    )
    unknown = set(args.benchmarks) - allowed_benchmarks
    if not args.benchmarks or unknown:
        invalid_benchmarks = sorted(unknown) if unknown else "empty"
        parser.error(f"invalid --benchmarks values: {invalid_benchmarks}")
    args.crossvid_tasks = tuple(
        dict.fromkeys(
            item.strip().upper()
            for item in args.crossvid_tasks.split(",")
            if item.strip()
        )
    )
    unknown_tasks = set(args.crossvid_tasks) - set(CROSSVID_TASKS)
    if not args.crossvid_tasks or unknown_tasks:
        invalid_tasks = sorted(unknown_tasks) if unknown_tasks else "empty"
        parser.error(f"invalid --crossvid-tasks values: {invalid_tasks}")
    return args


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_output(*args: str) -> str:
    return subprocess.run(
        ("git", *args),
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    temporary.replace(path)


def _append_jsonl(path: Path, value: dict[str, Any], lock: threading.Lock) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with lock, path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False) + "\n")
        handle.flush()


def _retry(
    function: Callable[[], tuple[str, dict[str, Any]]], attempts: int
) -> tuple[str, dict[str, Any]]:
    for attempt in range(1, attempts + 1):
        try:
            return function()
        except Exception:  # noqa: BLE001 - final exception retains provider diagnostics
            if attempt == attempts:
                raise
            time.sleep(min(2**attempt, 8))
    raise AssertionError("unreachable")


def _parallel_records(
    rows: Iterable[dict[str, Any]],
    *,
    workers: int,
    infer: Callable[[dict[str, Any]], dict[str, Any]],
    output: Path,
    label: str,
) -> None:
    lock = threading.Lock()
    rows = list(rows)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(infer, row): row for row in rows}
        for number, future in enumerate(as_completed(futures), start=1):
            row = futures[future]
            try:
                record = future.result()
            except Exception as exc:  # noqa: BLE001 - save error without losing completed work
                record = {
                    "id": row.get("id", row.get("QA_index")),
                    "error": f"{type(exc).__name__}: {exc}",
                }
            _append_jsonl(output, record, lock)
            if number % 10 == 0 or record.get("error"):
                error = f" error={record['error']}" if record.get("error") else ""
                print(f"{label}: {number}/{len(rows)}{error}", flush=True)


def run_cvbench(args: argparse.Namespace, chat: APIChat) -> None:
    rows = shared.read_json(args.cvbench_root / "QAs.json")
    if args.limit is not None:
        rows = rows[: args.limit]
    official_rows = {
        int(row["id"]): row
        for row in shared.read_json(
            SOURCE_ROOT / "CVBench/Video-R1/src/r1-v/Evaluation/CVBench.json"
        )
    }
    output = args.output / "cvbench/raw/cvbench_predictions.jsonl"
    completed = {
        int(row["id"])
        for row in shared.load_jsonl(output)
        if not row.get("error")
    }
    pending = [row for row in rows if int(row["id"]) not in completed]
    cue_root = SOURCE_ROOT / "CVBench/lmms-eval/res"

    def infer(row: dict[str, Any]) -> dict[str, Any]:
        started = time.monotonic()
        messages, frame_budget = shared.cv_messages(
            row,
            args.cvbench_root / "videos",
            cue_root,
            frames_per_video=args.frames,
            question_frame_cap=args.frames,
            max_side=args.max_side,
            cache_dir=None if args.no_media_cache else args.media_cache_dir,
        )
        prepared = time.monotonic()
        text, metadata = _retry(
            lambda: chat.complete(messages, max_output_tokens=16),
            args.max_retries,
        )
        prediction = shared.cv_prediction(text)
        answer = str(row["answer"]).strip().upper()
        return {
            "id": int(row["id"]),
            "task_type": official_rows[int(row["id"])]["task_type"],
            "answer": answer,
            "prediction": prediction,
            "model_output": text,
            "correct": prediction == answer,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "media_preparation_seconds": round(prepared - started, 3),
            "endpoint": chat.base_url,
            "frame_budget": frame_budget,
            "generation": {
                "max_tokens": max(16, chat.profile.minimum_output_tokens),
                "temperature": chat.profile.temperature,
                "top_p": chat.profile.top_p,
            },
            **metadata,
        }

    print(f"CVBench: {len(completed)} complete, {len(pending)} pending", flush=True)
    _parallel_records(pending, workers=args.workers, infer=infer, output=output, label="CVBench")


def run_mvu(args: argparse.Namespace, chat: APIChat) -> None:
    rows = shared.read_json(args.mvu_root / "QAs.json")
    if args.limit is not None:
        rows = rows[: args.limit]
    output = args.output / "mvu_eval/raw/mvu_eval_predictions.jsonl"
    completed = {
        int(row["id"])
        for row in shared.load_jsonl(output)
        if not row.get("error")
    }
    pending = [row for row in rows if int(row["id"]) not in completed]

    def infer(row: dict[str, Any]) -> dict[str, Any]:
        started = time.monotonic()
        messages, frame_budget = shared.mvu_messages(
            row,
            args.mvu_root / "videos",
            frames_per_video=args.frames,
            question_frame_cap=args.frames,
            max_side=args.max_side,
            cache_dir=None if args.no_media_cache else args.media_cache_dir,
        )
        prepared = time.monotonic()
        text, metadata = _retry(
            lambda: chat.complete(messages, max_output_tokens=64),
            args.max_retries,
        )
        prediction, parse_method = shared.extract_final_choice_with_method(
            text, row.get("options") or []
        )
        legacy_prediction = text.strip().upper()[:1]
        answer = str(row["answer"]).strip().upper()
        return {
            "id": int(row["id"]),
            "task_type": str(row.get("task") or "Unknown"),
            "answer": answer,
            "prediction": prediction,
            "answer_parse_method": parse_method,
            "legacy_first_character_prediction": legacy_prediction,
            "model_output": text,
            "correct": prediction == answer,
            "legacy_first_character_correct": legacy_prediction == answer,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "media_preparation_seconds": round(prepared - started, 3),
            "endpoint": chat.base_url,
            "frame_budget": frame_budget,
            "generation": {
                "max_tokens": max(64, chat.profile.minimum_output_tokens),
                "temperature": chat.profile.temperature,
                "top_p": chat.profile.top_p,
                "enable_thinking": chat.profile.thinking_setting != "disabled",
            },
            **metadata,
        }

    print(f"MVU-Eval: {len(completed)} complete, {len(pending)} pending", flush=True)
    _parallel_records(pending, workers=args.workers, infer=infer, output=output, label="MVU-Eval")


def _load_crossvid_task(task: str) -> ModuleType:
    eval_root = SOURCE_ROOT / "CrossVid/eval"
    if str(eval_root) not in sys.path:
        sys.path.insert(0, str(eval_root))
    spec = importlib.util.spec_from_file_location(
        f"crossvid_official_{task}", eval_root / f"{task}.py"
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load CrossVid task {task}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _crossvid_record(
    task: str, module: ModuleType, pair: dict[str, Any], answer: str
) -> dict[str, Any]:
    if task == "FSA":
        try:
            start, end = (float(value) for value in answer.split(","))
            iou = module.interval_iou((start, end), tuple(pair["answer"]))
            return {"id": pair["id"], "answer": [start, end], "iou": iou}
        except (TypeError, ValueError):
            return {"id": pair["id"], "answer": answer, "iou": 0}
    if task == "CCQA":
        return {"id": pair["id"], "answer": answer}
    expected = "".join(pair["answer"]) if task == "BU" else pair["answer"]
    return {"id": pair["id"], "answer": answer, "correct": answer == expected}


def run_crossvid(args: argparse.Namespace, chat: APIChat) -> None:
    for task in args.crossvid_tasks:
        module = _load_crossvid_task(task)
        module.model = args.model
        module.total_frames = args.frames
        module.length = args.max_side
        media_folder = "uav" if task in {"MOC", "MSR"} else "videos"
        module.video_root = str(args.crossvid_root / media_folder)
        module.chat = lambda messages: chat.text(
            messages, max_output_tokens=8192, temperature=0.0, top_p=0.95
        )

        qa_path = args.crossvid_root / "QA" / f"{task}.json"
        rows = shared.read_json(qa_path)
        if args.limit is not None:
            rows = rows[: args.limit]
        output = args.output / "crossvid/raw" / f"{task}_result.json"
        existing = shared.read_json(output) if output.exists() else []
        completed = {str(row["id"]) for row in existing}
        pending = [row for row in rows if str(row["id"]) not in completed]
        results = list(existing)
        result_lock = threading.Lock()

        def infer(pair: dict[str, Any]) -> dict[str, Any] | None:
            started = time.monotonic()
            evaluated = module.evaluate(pair, max_tries=args.max_retries)
            if evaluated is None:
                return None
            input_pair, answer = evaluated
            record = _crossvid_record(task, module, input_pair, answer)
            record["elapsed_seconds"] = round(time.monotonic() - started, 3)
            record["request"] = chat.last_metadata()
            return record

        print(
            f"CrossVid/{task}: {len(completed)} complete, {len(pending)} pending",
            flush=True,
        )
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {executor.submit(infer, row): row for row in pending}
            for number, future in enumerate(as_completed(futures), start=1):
                record = future.result()
                if record is None:
                    print(
                        f"CrossVid/{task}: failed id={futures[future].get('id')}",
                        flush=True,
                    )
                    continue
                with result_lock:
                    results.append(record)
                    results.sort(key=lambda item: str(item["id"]))
                    _write_json(output, results)
                if number % 10 == 0:
                    print(f"CrossVid/{task}: {number}/{len(pending)}", flush=True)


def _choice_summary(
    path: Path, rows: list[dict[str, Any]], *, include_legacy: bool = False
) -> dict[str, Any]:
    latest = {str(row["id"]): row for row in shared.load_jsonl(path)}
    selected = {str(row["id"]) for row in rows}
    valid = [
        row
        for key, row in latest.items()
        if key in selected and not row.get("error")
    ]
    by_task: dict[str, Counter[str]] = defaultdict(Counter)
    for row in valid:
        task = str(row.get("task_type") or "Unknown")
        by_task[task]["total"] += 1
        by_task[task]["correct"] += int(bool(row.get("correct")))
        if include_legacy:
            by_task[task]["legacy_correct"] += int(
                bool(row.get("legacy_first_character_correct"))
            )
    correct = sum(bool(row.get("correct")) for row in valid)
    result = {
        "expected": len(rows),
        "completed": len(valid),
        "errors": sum(bool(row.get("error")) for row in latest.values()),
        "correct": correct,
        "accuracy": correct / len(valid) if valid else None,
        "by_task": {
            task: {
                "correct": stats["correct"],
                "total": stats["total"],
                "accuracy": stats["correct"] / stats["total"],
            }
            for task, stats in sorted(by_task.items())
        },
    }
    if include_legacy:
        legacy_correct = sum(
            bool(row.get("legacy_first_character_correct")) for row in valid
        )
        result.update(
            {
                "legacy_first_character_correct": legacy_correct,
                "legacy_first_character_accuracy": (
                    legacy_correct / len(valid) if valid else None
                ),
                "answer_parse_failures": sum(
                    row.get("answer_parse_method") == "unparsed" for row in valid
                ),
                "answer_parser": "final-choice-v1",
            }
        )
        for task, stats in result["by_task"].items():
            source = by_task[task]
            stats["legacy_first_character_correct"] = source["legacy_correct"]
            stats["legacy_first_character_accuracy"] = (
                source["legacy_correct"] / source["total"]
            )
    return result


def summarize(args: argparse.Namespace) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for benchmark, root, filename in (
        ("cvbench", args.cvbench_root, "cvbench_predictions.jsonl"),
        ("mvu-eval", args.mvu_root, "mvu_eval_predictions.jsonl"),
    ):
        if benchmark not in args.benchmarks:
            continue
        rows = shared.read_json(root / "QAs.json")
        if args.limit is not None:
            rows = rows[: args.limit]
        directory = "cvbench" if benchmark == "cvbench" else "mvu_eval"
        result["cvbench" if benchmark == "cvbench" else "mvu_eval"] = _choice_summary(
            args.output / directory / "raw" / filename,
            rows,
            include_legacy=benchmark == "mvu-eval",
        )
    if "crossvid" in args.benchmarks:
        tasks: dict[str, Any] = {}
        for task in args.crossvid_tasks:
            path = args.output / "crossvid/raw" / f"{task}_result.json"
            rows = shared.read_json(path) if path.exists() else []
            if task == "CCQA":
                tasks[task] = {
                    "completed": len(rows),
                    "metric": "requires official score_CCQA.py judge",
                }
            elif task == "FSA":
                tasks[task] = {
                    "completed": len(rows),
                    "mean_iou": (
                        sum(float(row["iou"]) for row in rows) / len(rows)
                        if rows
                        else None
                    ),
                }
            else:
                correct = sum(bool(row["correct"]) for row in rows)
                tasks[task] = {
                    "completed": len(rows),
                    "correct": correct,
                    "accuracy": correct / len(rows) if rows else None,
                }
        result["crossvid"] = {"tasks": tasks}
    return result


def _manifest(args: argparse.Namespace, chat: APIChat) -> dict[str, Any]:
    diff = _git_output("diff", "--binary", "--", "eval/e2e_eval")
    status = _git_output("status", "--short", "--", "eval/e2e_eval").splitlines()
    return {
        "adapter": "official-api-e2e-v1",
        "model": chat.public_config(),
        "benchmarks": list(args.benchmarks),
        "crossvid_tasks": list(args.crossvid_tasks),
        "media": {
            "question_frame_cap": args.frames,
            "max_side_pixels": args.max_side,
            "allocation": "floor(question_frame_cap / number_of_videos), capped by source length",
            "cache_dir": (
                None if args.no_media_cache else str(args.media_cache_dir.resolve())
            ),
        },
        "execution": {
            "workers": args.workers,
            "max_output_tokens": {"cvbench": 16, "mvu-eval": 64, "crossvid": 8192},
            "max_retries": args.max_retries,
            "limit": args.limit,
            "api_key_env": args.api_key_env,
        },
        "sources": {
            "mvagent_commit": _git_output("rev-parse", "HEAD"),
            "e2e_eval_dirty_paths": status,
            "e2e_eval_diff_sha256": hashlib.sha256(diff.encode()).hexdigest(),
            "upstream_commits": UPSTREAM_COMMITS,
            "adapter_files": {
                path.name: _sha256(path)
                for path in (
                    Path(__file__).resolve(),
                    Path(__file__).with_name("client.py"),
                    Path(chat.provider.__file__).resolve(),
                )
            },
        },
        "protocol": {
            "transport": "official OpenAI-compatible POST /chat/completions",
            "video_input": "uniformly sampled JPEG image inputs, not native video upload",
            "cvbench": (
                "same shared message builder, prompt, cue images, JPEG bytes and order "
                "as local E2E; only the provider transport envelope changes (ordered "
                "image parts, temporary frame URLs, or file references)"
            ),
            "mvu_eval": "same shared message builder and unchanged message parts as local E2E",
            "crossvid": (
                "same official task evaluate functions, prompts, preprocessing and "
                "message parts as local E2E"
            ),
        },
    }


def main() -> None:
    args = parse_args()
    profile = profile_for(args.model)
    args.api_key_env = args.api_key_env or profile.api_key_env
    key = os.environ.get(args.api_key_env, "")
    if not key:
        raise SystemExit(
            f"Set {args.api_key_env} before running; credentials are never read "
            "from files."
        )
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    if args.no_media_cache:
        os.environ.pop("MVAGENT_E2E_MEDIA_CACHE_DIR", None)
    else:
        os.environ["MVAGENT_E2E_MEDIA_CACHE_DIR"] = str(args.media_cache_dir.resolve())
    os.environ.setdefault("DECORD_EOF_RETRY_MAX", "40960")
    chat = APIChat(
        api_key=key,
        model=args.model,
        base_url=args.base_url,
        timeout=args.timeout,
    )
    manifest = _manifest(args, chat)
    manifest_path = args.output / "run_manifest.json"
    if manifest_path.exists() and shared.read_json(manifest_path) != manifest:
        raise SystemExit(
            f"Existing manifest differs: {manifest_path}; use a new output directory."
        )
    _write_json(manifest_path, manifest)

    elapsed: dict[str, float] = {}
    if "cvbench" in args.benchmarks:
        started = time.monotonic()
        run_cvbench(args, chat)
        elapsed["cvbench"] = time.monotonic() - started
    if "mvu-eval" in args.benchmarks:
        started = time.monotonic()
        run_mvu(args, chat)
        elapsed["mvu_eval"] = time.monotonic() - started
    if "crossvid" in args.benchmarks:
        started = time.monotonic()
        run_crossvid(args, chat)
        elapsed["crossvid"] = time.monotonic() - started

    summary = summarize(args)
    if "cvbench" in summary:
        item = summary["cvbench"]
        failures = []
        if item["completed"] != item["expected"] or item["errors"]:
            failures.append(
                "RuntimeError: CVBench incomplete: "
                f"completed={item['completed']} expected={item['expected']} "
                f"errors={item['errors']}"
            )
        _write_json(
            args.output / "cvbench/summary.json",
            {
                "elapsed_seconds": round(elapsed["cvbench"], 3),
                "cvbench": item,
                "mvu_eval": None,
                "failures": failures,
            },
        )
    if "mvu_eval" in summary:
        item = summary["mvu_eval"]
        failures = []
        if item["completed"] != item["expected"] or item["errors"]:
            failures.append(
                "RuntimeError: MVU-Eval incomplete: "
                f"completed={item['completed']} expected={item['expected']} "
                f"errors={item['errors']}"
            )
        _write_json(
            args.output / "mvu_eval/summary.json",
            {
                "elapsed_seconds": round(elapsed["mvu_eval"], 3),
                "cvbench": None,
                "mvu_eval": item,
                "failures": failures,
            },
        )
    if "crossvid" in summary:
        _write_json(
            args.output / "crossvid/summary.json",
            {
                "elapsed_seconds": round(elapsed["crossvid"], 3),
                **summary["crossvid"],
            },
        )
    _write_json(args.output / "summary.json", summary)


if __name__ == "__main__":
    main()
