#!/usr/bin/env python3
"""Unified end-to-end evaluation of CVBench, MVU-Eval and CrossVid (protocol in README.md).

  run.py infer --output DIR --endpoints 8100-8107 [--ids crossvid=eval/crossvid_2500.json]
  run.py score --output DIR
  run.py preview cvbench:3 crossvid:MOC:0     # the exact messages, without calling a model

`infer` sends every selected question once to the model and appends raw records to
DIR/raw/<benchmark>.jsonl (resumable; only successful records count). `score` applies the official
scoring of each benchmark (CCQA through the fixed judge) and writes DIR/scored/ and DIR/summary.json.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from itertools import chain, zip_longest
from pathlib import Path
from typing import Any

E2E_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(E2E_ROOT))

from harness.common import (  # noqa: E402
    PROJECT_ROOT,
    UPSTREAM_COMMITS,
    JsonlAppender,
    git,
    load_jsonl,
    read_json,
    sha256_file,
    write_json,
)
from harness.media import CACHE_ENV  # noqa: E402

# Unified E2E protocol: at most 512 video frames per model call, longest frame edge at most 448 px.
# Everything else follows each benchmark's official evaluation code.
FRAMES_PER_CALL = 512
MAX_SIDE = 448
BENCHMARKS = ("cvbench", "mvu_eval", "crossvid")


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_endpoints(value: str) -> list[str]:
    endpoints = []
    for token in filter(None, (part.strip() for part in value.split(","))):
        if token.startswith("http"):
            endpoints.append(token)
        elif "-" in token:
            first, last = (int(port) for port in token.split("-"))
            endpoints += [f"http://127.0.0.1:{port}/v1" for port in range(first, last + 1)]
        else:
            endpoints.append(f"http://127.0.0.1:{int(token)}/v1")
    return endpoints


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)

    infer = commands.add_parser("infer", help="run model inference and append raw records")
    infer.add_argument("--output", type=Path, required=True)
    infer.add_argument("--benchmarks", default=",".join(BENCHMARKS))
    infer.add_argument("--crossvid-tasks", default="BU,CC,CCQA,FSA,MOC,MSR,NC,PEA,PI,PSS")
    infer.add_argument("--ids", action="append", default=[], metavar="BENCHMARK=PATH",
                       help="restrict a benchmark to the sample IDs in a JSON list, e.g. crossvid=eval/crossvid_2500.json")
    infer.add_argument("--limit", type=int, help="smoke test: first N questions per benchmark (per task for CrossVid)")
    infer.add_argument("--frames", type=int, default=FRAMES_PER_CALL, help="video frames per model call")
    infer.add_argument("--max-side", type=int, default=MAX_SIDE, help="longest frame edge in pixels")
    infer.add_argument("--data-root", type=Path, default=Path("/assets"))
    infer.add_argument("--endpoints", default="", help="vLLM endpoints: URLs, ports or port ranges (8100-8107)")
    infer.add_argument("--model", help="served model name (default: the only model the endpoints serve)")
    infer.add_argument("--enable-thinking", action="store_true", help="default off, as in the MVAgent runs")
    infer.add_argument("--api-model", help="official API profile (eval/e2e_eval/api) instead of vLLM endpoints")
    infer.add_argument("--api-base-url")
    infer.add_argument("--api-key-env")
    infer.add_argument("--workers", type=int, help="questions prepared concurrently (default: 2 x request slots)")
    infer.add_argument("--timeout", type=float, default=900.0)
    infer.add_argument("--retries", type=int, default=3)
    infer.add_argument("--media-cache-dir", default=str(PROJECT_ROOT / ".cache/e2e_media"),
                       help="model-independent preprocessing cache; empty string disables it")

    score = commands.add_parser("score", help="score raw records with the official rules")
    score.add_argument("--output", type=Path, required=True)
    score.add_argument("--judge-model", default="deepseek-v4-flash")
    score.add_argument("--judge-api-base", default="https://api.deepseek.com")
    score.add_argument("--judge-workers", type=int, default=32)
    score.add_argument("--judge-attempts", type=int, default=3)
    score.add_argument("--judge-timeout", type=float, default=600.0)

    preview = commands.add_parser("preview", help="print the messages built for some questions; no model call")
    preview.add_argument("sample_ids", nargs="+", help="e.g. cvbench:3 mvu_eval:Counting:0 crossvid:MOC:0")
    preview.add_argument("--frames", type=int, default=FRAMES_PER_CALL)
    preview.add_argument("--max-side", type=int, default=MAX_SIDE)
    preview.add_argument("--data-root", type=Path, default=Path("/assets"))
    args = parser.parse_args()
    if args.command == "preview":
        return args
    args.output = args.output.resolve()
    if args.command == "infer":
        args.benchmarks = tuple(dict.fromkeys(name.strip() for name in args.benchmarks.split(",") if name.strip()))
        if not args.benchmarks or set(args.benchmarks) - set(BENCHMARKS):
            parser.error(f"--benchmarks must be a subset of {','.join(BENCHMARKS)}")
        args.crossvid_tasks = tuple(task.strip().upper() for task in args.crossvid_tasks.split(",") if task.strip())
        args.ids = dict(spec.split("=", 1) for spec in args.ids)
        if set(args.ids) - set(args.benchmarks):
            parser.error("--ids names a benchmark that is not selected")
        if bool(args.api_model) == bool(args.endpoints):
            parser.error("give exactly one of --endpoints (vLLM) or --api-model")
        if min(args.frames, args.max_side, args.retries) <= 0 or (args.limit is not None and args.limit <= 0):
            parser.error("numeric options must be positive")
    return args


# ---------------------------------------------------------------------------
# Benchmarks and selection
# ---------------------------------------------------------------------------

def build_benchmarks(config: dict[str, Any]) -> dict[str, Any]:
    from harness.crossvid import CrossVid
    from harness.cvbench import CVBench
    from harness.mvu_eval import MVUEval

    shared = {"data_root": Path(config["data_root"]), "frames": config["frames"], "max_side": config["max_side"]}
    built = {}
    for name in config["benchmarks"]:
        if name == "cvbench":
            built[name] = CVBench(**shared)
        elif name == "mvu_eval":
            built[name] = MVUEval(**shared)
        else:
            built[name] = CrossVid(**shared, tasks=tuple(config["crossvid_tasks"]))
    return built


def select(benchmarks: dict[str, Any], config: dict[str, Any]) -> dict[str, list[str]]:
    selection = {}
    for name, benchmark in benchmarks.items():
        items = benchmark.items
        if name in config["ids"]:
            wanted = [sample_id for sample_id in read_json(PROJECT_ROOT / config["ids"][name]) if sample_id.startswith(f"{name}:")]
            known = {item["sample_id"] for item in items}
            if not wanted or set(wanted) - known:
                raise SystemExit(f"{config['ids'][name]}: {len(set(wanted) - known)} of {len(wanted)} {name} IDs are unknown")
            wanted_set = set(wanted)
            items = [item for item in items if item["sample_id"] in wanted_set]
        if config["limit"] is not None:
            per_task: dict[str, list] = defaultdict(list)
            for item in items:
                key = item["task"] if name == "crossvid" else name
                if len(per_task[key]) < config["limit"]:
                    per_task[key].append(item)
            items = list(chain.from_iterable(per_task.values()))
        selection[name] = [item["sample_id"] for item in items]
    return selection


def source_files() -> list[Path]:
    return [E2E_ROOT / "run.py", *sorted((E2E_ROOT / "harness").glob("*.py"))]


def source_hashes() -> dict[str, str]:
    return {str(path.relative_to(E2E_ROOT)): sha256_file(path) for path in source_files()}


def vendored_hashes() -> dict[str, str]:
    """Official sources (and the shared CCQA judge) whose code decides prompts, frames or scores."""
    files = [
        "CVBench/lmms-eval/lmms_eval/tasks/mvr/utils.py",
        "CVBench/lmms-eval/lmms_eval/tasks/mvr/mvr.yaml",
        "CVBench/lmms-eval/lmms_eval/models/qwen2_5_vl.py",
        "CVBench/Video-R1/src/r1-v/Evaluation/CVBench.json",
        "MVU-Eval/inference/main.py",
        "MVU-Eval/inference/analyze.py",
        *(str(path.relative_to(E2E_ROOT)) for path in sorted((E2E_ROOT / "CrossVid/eval").rglob("*.py"))),
        "../agent_eval/score_crossvid_ccqa.py",
    ]
    return {name: sha256_file(E2E_ROOT / name) for name in files}


def media_cache_root(base: Path) -> Path:
    """Cache directory keyed by the code that produces cached frames, so edited code never reads stale frames."""
    producers = [
        E2E_ROOT / "harness/media.py",
        E2E_ROOT / "MVU-Eval/inference/main.py",
        *sorted((E2E_ROOT / "CrossVid/eval/utils").glob("*.py")),
    ]
    fingerprint = hashlib.sha256("".join(sha256_file(path) for path in producers).encode()).hexdigest()
    return base / f"code-{fingerprint[:12]}"


def freeze_source(output: Path) -> dict[str, str]:
    """Copy the harness into DIR/source once; a resumed run must use identical code."""
    for path in source_files():
        relative = path.relative_to(E2E_ROOT)
        target = output / "source" / relative
        if target.exists() and target.read_bytes() != path.read_bytes():
            raise SystemExit(f"{relative} changed since this run started; use a new --output directory")
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.copy2(path, target)
    return source_hashes()


# ---------------------------------------------------------------------------
# infer
# ---------------------------------------------------------------------------

def make_backend(args: argparse.Namespace):
    from harness.backends import APIBackend, VLLMBackend

    if args.api_model:
        return APIBackend(args.api_model, base_url=args.api_base_url, api_key_env=args.api_key_env,
                          timeout=args.timeout, retries=args.retries)
    return VLLMBackend(parse_endpoints(args.endpoints), model=args.model,
                       timeout=args.timeout, retries=args.retries, enable_thinking=args.enable_thinking)


def run_infer(args: argparse.Namespace) -> None:
    if args.media_cache_dir:
        os.environ[CACHE_ENV] = str(media_cache_root(Path(args.media_cache_dir).resolve()))
    else:
        os.environ.pop(CACHE_ENV, None)
    os.environ.setdefault("DECORD_EOF_RETRY_MAX", "40960")
    config = {
        "benchmarks": list(args.benchmarks),
        "crossvid_tasks": list(args.crossvid_tasks),
        "ids": args.ids,
        "limit": args.limit,
        "frames": args.frames,
        "max_side": args.max_side,
        "data_root": str(args.data_root),
    }
    backend = make_backend(args)
    benchmarks = build_benchmarks(config)
    sampled = {name: b.generation for name, b in benchmarks.items() if b.generation["temperature"] != 0}
    if sampled:  # greedy decoding everywhere: the only setting that is exactly repeatable
        raise SystemExit(f"non-greedy generation settings: {sampled}")
    selection = select(benchmarks, config)
    model_identity = {key: value for key, value in backend.identity().items() if key != "endpoints"}
    identity = {
        "protocol": {"frames_per_call": args.frames, "max_side": args.max_side},
        "config": config,
        "model": model_identity,
        "benchmarks": {name: benchmark.protocol() for name, benchmark in benchmarks.items()},
        "selection": {
            name: {"count": len(ids), "sha256": hashlib.sha256("\n".join(sorted(ids)).encode()).hexdigest()}
            for name, ids in selection.items()
        },
        "source": {"files": freeze_source(args.output), "vendored": vendored_hashes(), "upstream_commits": UPSTREAM_COMMITS},
    }
    manifest_path = args.output / "manifest.json"
    manifest = read_json(manifest_path) if manifest_path.exists() else {"identity": identity, "runs": []}
    if manifest["identity"] != identity:
        raise SystemExit(f"{manifest_path} describes a different protocol, model, selection or source; use a new --output")
    write_json(args.output / "selection.json", selection)
    workers = args.workers or 2 * backend.slots
    try:  # informational; the frozen source hashes above are the binding record
        revision = {
            "commit": git("rev-parse", "HEAD"),
            "dirty": bool(git("status", "--porcelain", "--untracked-files=no", "--", "eval/e2e_eval")),
        }
    except Exception as exc:  # noqa: BLE001 - e.g. no .git in a copied checkout
        revision = {"error": f"{type(exc).__name__}: {exc}"}
    manifest["runs"].append({
        "started_at": now(),
        "backend": backend.identity(),
        "workers": workers,
        "media_cache_dir": os.environ.get(CACHE_ENV),
        "git": revision,
    })
    write_json(manifest_path, manifest)

    pending: dict[str, list[dict[str, Any]]] = {}
    writers = {}
    for name, benchmark in benchmarks.items():
        path = args.output / "raw" / f"{name}.jsonl"
        done = {record["sample_id"] for record in load_jsonl(path) if record["status"] == "ok"}
        wanted = set(selection[name]) - done
        pending[name] = [item for item in benchmark.items if item["sample_id"] in wanted]
        writers[name] = JsonlAppender(path)
        print(f"{name}: {len(selection[name])} selected, {len(done & set(selection[name]))} done, {len(wanted)} to run", flush=True)
    queue = [pair for group in zip_longest(*([(name, item) for item in items] for name, items in pending.items())) for pair in group if pair]

    def run_one(name: str, item: dict[str, Any]) -> dict[str, Any]:
        started = time.monotonic()
        record = {"sample_id": item["sample_id"], "task": item["task"]}
        try:
            record.update(status="ok", **benchmarks[name].infer(item, backend))
        except Exception as exc:  # noqa: BLE001 - recorded and retried on the next run
            record.update(status="error", error=f"{type(exc).__name__}: {exc}")
        record.update(seconds=round(time.monotonic() - started, 3), finished_at=now())
        return record

    counts: dict[str, Counter] = defaultdict(Counter)
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(run_one, name, item): name for name, item in queue}
        for number, future in enumerate(as_completed(futures), start=1):
            name = futures[future]
            record = future.result()
            writers[name].append(record)
            counts[name][record["status"]] += 1
            if record["status"] == "error":
                print(f"[error] {record['sample_id']}: {record['error'][:300]}", flush=True)
            if number % 25 == 0 or number == len(queue):
                rate = number / max(time.monotonic() - started, 1e-9) * 3600
                state = "  ".join(f"{key} ok={value['ok']} err={value['error']}/{len(pending[key])}" for key, value in counts.items())
                print(f"[{now()}] {number}/{len(queue)} ({rate:.0f}/h)  {state}", flush=True)
    manifest["runs"][-1].update(finished_at=now(), results={key: dict(value) for key, value in counts.items()})
    write_json(manifest_path, manifest)
    failed = sum(value["error"] for value in counts.values())
    print(f"inference finished; {failed} errors (rerun the same command to retry them)", flush=True)
    if failed:
        raise SystemExit(1)


# ---------------------------------------------------------------------------
# score
# ---------------------------------------------------------------------------

def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def summarize(name: str, selected: list[str], items: dict[str, dict], raw: dict[str, dict], scored: dict[str, dict]) -> dict[str, Any]:
    by_task: dict[str, list[dict]] = defaultdict(list)
    for sample_id in selected:
        by_task[items[sample_id]["task"]].append(scored.get(sample_id))
    complete = all(row is not None for rows in by_task.values() for row in rows)
    tasks = {}
    for task, rows in sorted(by_task.items()):
        done = [row for row in rows if row is not None]
        if name == "crossvid" and task == "CCQA":
            # score_CCQA.py: total points earned / total points available
            value = sum(row["score"] * row["points"] for row in done) / sum(row["points"] for row in done) if done else None
        else:
            value = _mean([row["score"] for row in done])
        tasks[task] = {"selected": len(rows), "scored": len(done), "score": value}
    all_scores = [row["score"] for rows in by_task.values() for row in rows if row is not None]
    if name == "crossvid":
        headline = {"o_avg": _mean([task["score"] for task in tasks.values()]) if complete else None}
    else:
        headline = {"accuracy": _mean(all_scores) if complete else None}
    records = [raw[sample_id] for sample_id in selected if sample_id in raw]
    requests = [record.get("request") or {} for record in records]
    prompt_tokens = [request["usage"]["prompt_tokens"] for request in requests if (request.get("usage") or {}).get("prompt_tokens")]
    frames = [record["media"]["frames"] for record in records]
    sides = [record["media"]["frame_max_side"] for record in records]
    return {
        **headline,
        "complete": complete,
        "selected": len(selected),
        "inferred": len(records),
        "scored": len(all_scores),
        "scored_mean": _mean(all_scores),
        "by_task": tasks,
        "audit": {
            "max_frames_per_call": max(frames, default=0),
            "max_frame_side": max(sides, default=0),
            "prompt_tokens_mean": _mean(prompt_tokens),
            "prompt_tokens_max": max(prompt_tokens, default=None),
            "finish_reasons": dict(Counter(request.get("finish_reason") for request in requests)),
        },
    }


def run_score(args: argparse.Namespace) -> None:
    manifest = read_json(args.output / "manifest.json")
    config = manifest["identity"]["config"]
    if config["ids"] is None:
        config["ids"] = {}
    benchmarks = build_benchmarks(config)
    selection = read_json(args.output / "selection.json")
    summary: dict[str, Any] = {
        "scored_at": now(),
        "protocol": manifest["identity"]["protocol"],
        "model": manifest["identity"]["model"],
        # Scoring runs the current code; record whether it is the code that produced the raw records.
        "scoring_code_matches_inference": source_hashes() == manifest["identity"]["source"]["files"]
        and vendored_hashes() == manifest["identity"]["source"]["vendored"],
    }
    failures = []
    for name, benchmark in benchmarks.items():
        items = {item["sample_id"]: item for item in benchmark.items}
        raw = {}
        for record in load_jsonl(args.output / "raw" / f"{name}.jsonl"):
            if record["status"] == "ok":
                raw[record["sample_id"]] = record
        scored = {}
        judge_pending = []
        for sample_id in selection[name]:
            if sample_id not in raw:
                continue
            if sample_id.startswith("crossvid:CCQA:"):
                judge_pending.append((items[sample_id], raw[sample_id]["output"]))
            else:
                scored[sample_id] = {"sample_id": sample_id, "task": items[sample_id]["task"],
                                     **benchmark.score(items[sample_id], raw[sample_id]["output"])}
        if judge_pending and not os.environ.get("DEEPSEEK_API_KEY"):
            failures.append(f"CCQA: {len(judge_pending)} answers not judged; set DEEPSEEK_API_KEY and rerun score")
        elif judge_pending:
            from harness.ccqa import judge_outputs

            judged = judge_outputs(judge_pending, cache_dir=args.output / "judge_cache", model=args.judge_model,
                                   api_base=args.judge_api_base, workers=args.judge_workers,
                                   attempts=args.judge_attempts, timeout=args.judge_timeout)
            for sample_id, row in judged.items():
                if row["status"] == "ok":
                    scored[sample_id] = {"task": "CCQA", **row}
                else:
                    failures.append(f"{sample_id}: judge failed: {row['error']}")
            summary["ccqa_judge"] = {"model": args.judge_model, "api_base": args.judge_api_base}
        write_json(args.output / "scored" / f"{name}.json", [scored[sample_id] for sample_id in selection[name] if sample_id in scored])
        summary[name] = summarize(name, selection[name], items, raw, scored)
        missing = summary[name]["selected"] - summary[name]["inferred"]
        if missing:
            failures.append(f"{name}: {missing} selected questions have no successful inference record")
    summary["failures"] = failures
    write_json(args.output / "summary.json", summary)
    print(json.dumps({key: value for key, value in summary.items() if key in BENCHMARKS}, indent=2, ensure_ascii=False)[:4000])
    if failures:
        print("\n".join(failures[:20]), file=sys.stderr)
        raise SystemExit(1)


# ---------------------------------------------------------------------------
# preview
# ---------------------------------------------------------------------------

class _Capture:
    """Stands in for a backend: records the request instead of sending it."""

    def complete(self, messages: list[dict[str, Any]], **generation: Any) -> tuple[str, dict[str, Any]]:
        self.messages, self.generation = messages, generation
        return "", {}


def render_messages(messages: list[dict[str, Any]]) -> str:
    """Message parts in order: text verbatim, consecutive same-size images collapsed into one line."""
    from harness.media import image_sizes

    lines: list[str] = []
    run: list[Any] = [None, 0]

    def flush() -> None:
        if run[1]:
            kind, (width, height) = run[0]
            lines.append(f"[{run[1]} x {kind} {width}x{height}]")
        run[:] = [None, 0]

    for message in messages:
        flush()
        lines.append(f"===== role: {message['role']} =====")
        content = message["content"]
        for part in [{"type": "text", "text": content}] if isinstance(content, str) else content:
            if part["type"] == "text":
                flush()
                lines.append("[text]")
                lines.append(part["text"])
            else:
                url = part["image_url"]["url"]
                key = (url[5 : url.index(";")], tuple(image_sizes([{"content": [part]}])[0]))
                if key != run[0]:
                    flush()
                    run[0] = key
                run[1] += 1
    flush()
    return "\n".join(lines)


def run_preview(args: argparse.Namespace) -> None:
    os.environ.pop(CACHE_ENV, None)
    names = list(dict.fromkeys(sample_id.split(":")[0] for sample_id in args.sample_ids))
    tasks = [sample_id.split(":")[1] for sample_id in args.sample_ids if sample_id.startswith("crossvid:")]
    config = {"benchmarks": names, "crossvid_tasks": list(dict.fromkeys(tasks)),
              "frames": args.frames, "max_side": args.max_side, "data_root": str(args.data_root)}
    benchmarks = build_benchmarks(config)
    for sample_id in args.sample_ids:
        benchmark = benchmarks[sample_id.split(":")[0]]
        item = next(item for item in benchmark.items if item["sample_id"] == sample_id)
        capture = _Capture()
        record = benchmark.infer(item, capture)
        print(f"\n################ {sample_id} ({item['task']}) ################")
        print("generation:", json.dumps(capture.generation))
        print("media:", json.dumps(record["media"], ensure_ascii=False))
        print(render_messages(capture.messages))


def main() -> None:
    args = parse_args()
    if args.command == "preview":
        run_preview(args)
        return
    args.output.mkdir(parents=True, exist_ok=True)
    run_infer(args) if args.command == "infer" else run_score(args)


if __name__ == "__main__":
    main()
