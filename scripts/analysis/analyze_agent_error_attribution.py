from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

DETAIL_FILES = {
    "cvbench": ("cvbench", "cvbench_matrix_details.jsonl"),
    "mvu-eval": ("mvu-eval", "mvu_eval_matrix_details.jsonl"),
    "crossvid": ("crossvid", "crossvid_matrix_details.jsonl"),
}


def _score_details(output_dir: Path) -> list[dict[str, Any]]:
    details: list[dict[str, Any]] = []
    for benchmark, (directory_name, filename) in DETAIL_FILES.items():
        path = output_dir / directory_name / filename
        if not path.is_file():
            raise FileNotFoundError(
                f"Saved score details are required for historical attribution: {path}. "
                "The removed custom eval matrix is no longer recomputed in place."
            )
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                row.setdefault("benchmark", benchmark)
                details.append(row)
    return details


def _trajectory_features(source_path: str) -> dict[str, Any]:
    payload = json.loads(Path(source_path).read_text(encoding="utf-8"))
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    trajectory = result.get("trajectory") if isinstance(result.get("trajectory"), list) else []
    global_decisions = [
        item
        for item in trajectory
        if item.get("agent") == "GlobalAgent" and item.get("action") == "decide"
    ]
    video_runs = [
        item
        for item in trajectory
        if item.get("agent") == "VideoAgent" and item.get("action") == "run"
    ]
    observe_steps = sum(
        1
        for run in video_runs
        for step in (run.get("output", {}).get("steps") or [])
        if step.get("action") == "observe"
    )
    failed_video_runs = sum(
        1 for run in video_runs if run.get("output", {}).get("status") != "ok"
    )
    uses_watch = any(
        item.get("agent") == "GlobalAgent"
        and item.get("action") == "decide"
        and item.get("output", {}).get("action") == "watch_videos"
        for item in trajectory
    )
    return {
        "uses_watch": uses_watch,
        "global_decisions": len(global_decisions),
        "video_runs": len(video_runs),
        "observe_steps": observe_steps,
        "failed_video_runs": failed_video_runs,
        "stop_reason": str(result.get("stop_reason") or "unknown"),
    }


def _group_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"count": 0}
    return {
        "count": len(rows),
        "watch_share": sum(bool(row["features"]["uses_watch"]) for row in rows)
        / len(rows),
        "mean_global_decisions": mean(
            row["features"]["global_decisions"] for row in rows
        ),
        "mean_video_runs": mean(row["features"]["video_runs"] for row in rows),
        "mean_observe_steps": mean(
            row["features"]["observe_steps"] for row in rows
        ),
        "video_run_failure_share": sum(
            row["features"]["failed_video_runs"] > 0 for row in rows
        )
        / len(rows),
        "stop_reasons": dict(
            Counter(row["features"]["stop_reason"] for row in rows)
        ),
    }


def _load_audit(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def build_summary(output_dir: Path, audit_path: Path) -> dict[str, Any]:
    scored_rows: list[dict[str, Any]] = []
    for detail in _score_details(output_dir):
        if detail.get("status") != "ok" or detail.get("score") is None:
            continue
        scored_rows.append(
            {
                **detail,
                "features": _trajectory_features(str(detail["source_path"])),
            }
        )

    benchmark_summary: dict[str, Any] = {}
    for benchmark in DETAIL_FILES:
        rows = [row for row in scored_rows if row["benchmark"] == benchmark]
        benchmark_summary[benchmark] = {
            "scored_ok": len(rows),
            "score_zero": sum(float(row["score"]) == 0.0 for row in rows),
            "score_positive": sum(float(row["score"]) > 0.0 for row in rows),
            "mean_score": mean(float(row["score"]) for row in rows) if rows else None,
            "by_task": {
                task: {
                    "scored_ok": len(task_rows),
                    "score_zero": sum(
                        float(row["score"]) == 0.0 for row in task_rows
                    ),
                    "mean_score": mean(float(row["score"]) for row in task_rows),
                }
                for task in sorted({str(row.get("task") or "Unknown") for row in rows})
                for task_rows in [[row for row in rows if str(row.get("task") or "Unknown") == task]]
            },
        }

    zero_rows = [row for row in scored_rows if float(row["score"]) == 0.0]
    positive_rows = [row for row in scored_rows if float(row["score"]) > 0.0]
    audit_rows = _load_audit(audit_path)
    attribution_counts = Counter(row["attribution"] for row in audit_rows)
    by_benchmark: dict[str, Counter[str]] = defaultdict(Counter)
    for row in audit_rows:
        by_benchmark[row["benchmark"]][row["attribution"]] += 1

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": {
            "output_dir": str(output_dir),
            "population": "status=ok records with an official-style numeric score; CCQA is excluded without an external judge",
            "error_definition": "official-style score exactly 0",
            "manual_audit": "deterministic stratified sample of score-zero records",
        },
        "benchmark_summary": benchmark_summary,
        "trajectory_associations": {
            "score_zero": _group_metrics(zero_rows),
            "score_positive": _group_metrics(positive_rows),
        },
        "manual_attribution": {
            "sample_size": len(audit_rows),
            "counts": dict(attribution_counts),
            "shares": {
                key: value / len(audit_rows)
                for key, value in attribution_counts.items()
            },
            "by_benchmark": {
                benchmark: dict(counts)
                for benchmark, counts in sorted(by_benchmark.items())
            },
            "confidence": dict(Counter(row["confidence"] for row in audit_rows)),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--audit", required=True, type=Path)
    parser.add_argument("--summary", required=True, type=Path)
    args = parser.parse_args()
    summary = build_summary(args.output_dir.resolve(), args.audit.resolve())
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
