from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median, pstdev
from typing import Any, Iterable


BENCHMARK_DIRS = ("cvbench", "mvu-eval", "crossvid")


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _quantile(values: Iterable[float], probability: float) -> float | None:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _mean_ci(values: list[float]) -> tuple[float | None, float | None, float | None]:
    if not values:
        return None, None, None
    value = mean(values)
    if len(values) == 1:
        return value, value, value
    margin = 1.96 * pstdev(values) / math.sqrt(len(values))
    return value, max(0.0, value - margin), min(1.0, value + margin)


def _timing(values: list[float]) -> dict[str, Any]:
    if not values:
        return {
            "count": 0,
            "mean_sec": None,
            "p50_sec": None,
            "p75_sec": None,
            "p90_sec": None,
            "p95_sec": None,
            "p99_sec": None,
            "max_sec": None,
            "total_hours": 0.0,
        }
    return {
        "count": len(values),
        "mean_sec": mean(values),
        "p50_sec": median(values),
        "p75_sec": _quantile(values, 0.75),
        "p90_sec": _quantile(values, 0.90),
        "p95_sec": _quantile(values, 0.95),
        "p99_sec": _quantile(values, 0.99),
        "max_sec": max(values),
        "total_hours": sum(values) / 3600.0,
    }


def _trajectory_features(payload: dict[str, Any]) -> dict[str, Any]:
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
        run.get("output", {}).get("status") != "ok" for run in video_runs
    )
    watch_actions = sum(
        item.get("agent") == "GlobalAgent"
        and item.get("action") == "decide"
        and item.get("output", {}).get("action") == "watch_videos"
        for item in trajectory
    )
    analyze_actions = sum(
        item.get("agent") == "GlobalAgent"
        and item.get("action") == "decide"
        and item.get("output", {}).get("action") == "analyze_videos"
        for item in trajectory
    )
    return {
        "global_decisions": len(global_decisions),
        "analyze_actions": analyze_actions,
        "watch_actions": watch_actions,
        "uses_watch": watch_actions > 0,
        "video_runs": len(video_runs),
        "observe_steps": observe_steps,
        "failed_video_runs": failed_video_runs,
        "stop_reason": str(result.get("stop_reason") or "unknown"),
    }


def _correct_zero_id_score(benchmark: str, payload: dict[str, Any]) -> tuple[str, float, str]:
    prediction = str(payload.get("prediction") or "").strip().upper().rstrip(".")
    answer = str(payload.get("ground_truth") or "").strip().upper().rstrip(".")
    score = 1.0 if prediction == answer and bool(answer) else 0.0
    task = "Unknown" if benchmark == "cvbench" else "Counting"
    return task, score, "corrected_zero_id"


def _score_map(output_dir: Path, benchmark: str) -> dict[str, dict[str, Any]]:
    path = output_dir / benchmark / f"{benchmark.replace('-', '_')}_matrix_details.jsonl"
    return {
        str(row.get("id")): row
        for row in _load_jsonl(path)
        if str(row.get("id") or "")
    }


def _task_label(benchmark: str, task: str) -> str:
    if benchmark == "crossvid":
        return f"CrossVid {task}"
    if benchmark == "mvu-eval":
        return f"MVU {task}"
    return "CVBench"


def build_rows(output_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    scoring_corrections: list[dict[str, Any]] = []
    maps = {benchmark: _score_map(output_dir, benchmark) for benchmark in BENCHMARK_DIRS}
    for benchmark in BENCHMARK_DIRS:
        question_root = output_dir / benchmark / "questions"
        for result_path in sorted(question_root.glob("*/result.json")):
            payload = json.loads(result_path.read_text(encoding="utf-8"))
            sample_id = str(payload.get("sample_id") or payload.get("question_id") or "")
            status = str(payload.get("status") or "unknown")
            detail = maps[benchmark].get(sample_id)
            score: float | None
            score_status: str
            task: str
            if detail is not None:
                task = str(detail.get("task") or "Unknown")
                raw_score = detail.get("score")
                score = float(raw_score) if raw_score is not None else None
                score_status = str(detail.get("status") or "unknown")
            elif sample_id == "0" and benchmark in {"cvbench", "mvu-eval"}:
                task, score, score_status = _correct_zero_id_score(benchmark, payload)
                scoring_corrections.append(
                    {
                        "benchmark": benchmark,
                        "sample_id": sample_id,
                        "issue": "numeric zero ID was converted to an empty annotation key",
                        "prediction": payload.get("prediction"),
                        "ground_truth": payload.get("ground_truth"),
                        "corrected_score": score,
                    }
                )
            else:
                task, score, score_status = "Unknown", None, "unmatched"
            result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
            runtime = result.get("time")
            runtime_sec = float(runtime) if isinstance(runtime, (int, float)) else None
            features = _trajectory_features(payload)
            rows.append(
                {
                    "benchmark": benchmark,
                    "sample_id": sample_id,
                    "task": task,
                    "task_label": _task_label(benchmark, task),
                    "execution_status": status,
                    "score_status": score_status,
                    "score": score,
                    "full_credit": score == 1.0 if score is not None else None,
                    "zero_score": score == 0.0 if score is not None else None,
                    "partial_score": 0.0 < score < 1.0 if score is not None else None,
                    "lost_score": 1.0 - score if score is not None else None,
                    "runtime_sec": runtime_sec,
                    "num_videos": len(payload.get("videos") or {}),
                    "prediction": payload.get("prediction"),
                    "ground_truth": payload.get("ground_truth"),
                    "error": payload.get("error"),
                    "judge_model": (detail.get("judge") or {}).get("model") if detail else None,
                    "judge_prompt_version": (
                        (detail.get("judge") or {}).get("prompt_version") if detail else None
                    ),
                    "judge_attempts": detail.get("judge_attempts") if detail else None,
                    "judge_score": detail.get("judge_score") if detail else None,
                    "judge_max_score": detail.get("judge_max_score") if detail else None,
                    "ccqa_scoring_points": (
                        len(detail.get("coverage") or []) if detail else None
                    ),
                    "ccqa_coverage_points": (
                        sum(item is True for item in (detail.get("coverage") or []))
                        if detail and detail.get("coverage") is not None
                        else None
                    ),
                    "ccqa_correctness_points": (
                        sum(item is True for item in (detail.get("correctness") or []))
                        if detail and detail.get("correctness") is not None
                        else None
                    ),
                    "source_path": str(result_path.resolve()),
                    **features,
                }
            )
    return rows, scoring_corrections


def _group_summary(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(row[key])].append(row)
    output: list[dict[str, Any]] = []
    for name, group in groups.items():
        scored = [row for row in group if row["score"] is not None]
        scores = [float(row["score"]) for row in scored]
        runtimes = [float(row["runtime_sec"]) for row in group if row["runtime_sec"] is not None]
        score, ci_low, ci_high = _mean_ci(scores)
        lost_score = sum(float(row["lost_score"]) for row in scored)
        output.append(
            {
                key: name,
                "total": len(group),
                "execution_ok": sum(row["execution_status"] == "ok" for row in group),
                "execution_errors": sum(row["execution_status"] != "ok" for row in group),
                "scorable": len(scored),
                "unscored": len(group) - len(scored),
                "mean_score": score,
                "score_ci95_low": ci_low,
                "score_ci95_high": ci_high,
                "full_credit": sum(row["full_credit"] is True for row in scored),
                "zero_score": sum(row["zero_score"] is True for row in scored),
                "partial_score": sum(row["partial_score"] is True for row in scored),
                "lost_score": lost_score,
                "watch_share": (
                    sum(row["uses_watch"] for row in group) / len(group) if group else None
                ),
                "mean_global_decisions": mean(row["global_decisions"] for row in group),
                "mean_video_runs": mean(row["video_runs"] for row in group),
                "mean_observe_steps": mean(row["observe_steps"] for row in group),
                **_timing(runtimes),
            }
        )
    total_gap = sum(float(item["lost_score"]) for item in output)
    total_runtime = sum(float(item["total_hours"]) for item in output)
    for item in output:
        item["lost_score_share"] = item["lost_score"] / total_gap if total_gap else 0.0
        item["runtime_share"] = item["total_hours"] / total_runtime if total_runtime else 0.0
    return sorted(output, key=lambda item: (-float(item["lost_score"]), str(item[key])))


def _segment_summary(rows: list[dict[str, Any]], field: str) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(row[field])].append(row)
    output = []
    for value, group in sorted(groups.items()):
        scored = [row for row in group if row["score"] is not None]
        scores = [float(row["score"]) for row in scored]
        runtimes = [float(row["runtime_sec"]) for row in group if row["runtime_sec"] is not None]
        output.append(
            {
                "segment": field,
                "value": value,
                "total": len(group),
                "scorable": len(scored),
                "mean_score": mean(scores) if scores else None,
                "zero_score_share": (
                    sum(row["zero_score"] is True for row in scored) / len(scored)
                    if scored
                    else None
                ),
                "p50_sec": _quantile(runtimes, 0.5),
                "p90_sec": _quantile(runtimes, 0.9),
                "mean_global_decisions": mean(row["global_decisions"] for row in group),
                "mean_video_runs": mean(row["video_runs"] for row in group),
                "mean_observe_steps": mean(row["observe_steps"] for row in group),
            }
        )
    return output


def _runtime_bands(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    timed = [row for row in rows if row["runtime_sec"] is not None]
    boundaries = [
        float(_quantile([row["runtime_sec"] for row in timed], probability) or 0.0)
        for probability in (0.5, 0.9, 0.95)
    ]
    bands = (
        (f"≤ p50 ({boundaries[0]:.1f}s)", 0.0, boundaries[0]),
        (f"p50–p90 ({boundaries[0]:.1f}–{boundaries[1]:.1f}s)", boundaries[0], boundaries[1]),
        (f"p90–p95 ({boundaries[1]:.1f}–{boundaries[2]:.1f}s)", boundaries[1], boundaries[2]),
        (f"> p95 ({boundaries[2]:.1f}s)", boundaries[2], math.inf),
    )
    output: list[dict[str, Any]] = []
    for index, (label, lower, upper) in enumerate(bands, start=1):
        if index == 1:
            group = [row for row in timed if row["runtime_sec"] <= upper]
        else:
            group = [row for row in timed if lower < row["runtime_sec"] <= upper]
        scored = [row for row in group if row["score"] is not None]
        output.append(
            {
                "order": index,
                "runtime_band": label,
                "total": len(group),
                "scorable": len(scored),
                "mean_score": mean(float(row["score"]) for row in scored) if scored else None,
                "zero_score_share": (
                    sum(row["zero_score"] is True for row in scored) / len(scored)
                    if scored
                    else None
                ),
                "watch_share": sum(row["uses_watch"] for row in group) / len(group),
                "mean_global_decisions": mean(row["global_decisions"] for row in group),
                "mean_observe_steps": mean(row["observe_steps"] for row in group),
            }
        )
    return output


def build_summary(
    output_dir: Path,
    rows: list[dict[str, Any]],
    scoring_corrections: list[dict[str, Any]],
    attribution_summary_path: Path | None,
) -> dict[str, Any]:
    scored = [row for row in rows if row["score"] is not None]
    runtimes = [float(row["runtime_sec"]) for row in rows if row["runtime_sec"] is not None]
    scores = [float(row["score"]) for row in scored]
    benchmark = _group_summary(rows, "benchmark")
    task = _group_summary(rows, "task_label")
    total_lost_score = sum(float(row["lost_score"]) for row in scored)
    execution_errors = [
        {
            "benchmark": row["benchmark"],
            "sample_id": row["sample_id"],
            "task": row["task"],
            "error": row["error"],
            "score": row["score"],
            "source_path": row["source_path"],
        }
        for row in rows
        if row["execution_status"] != "ok"
    ]
    exact_rows = [
        row
        for row in scored
        if not (
            row["benchmark"] == "crossvid"
            and row["task"] in {"FSA", "CCQA"}
        )
    ]
    fsa_rows = [
        row for row in scored if row["benchmark"] == "crossvid" and row["task"] == "FSA"
    ]
    crossvid_exact_rows = [
        row
        for row in scored
        if row["benchmark"] == "crossvid"
        and row["task"] not in {"FSA", "CCQA"}
    ]
    ccqa_rows = [
        row for row in scored if row["benchmark"] == "crossvid" and row["task"] == "CCQA"
    ]
    ccqa_scoring_points = sum(int(row["ccqa_scoring_points"] or 0) for row in ccqa_rows)
    ccqa_coverage_points = sum(int(row["ccqa_coverage_points"] or 0) for row in ccqa_rows)
    ccqa_correctness_points = sum(
        int(row["ccqa_correctness_points"] or 0) for row in ccqa_rows
    )
    prior_attribution = None
    if attribution_summary_path and attribution_summary_path.exists():
        prior_attribution = json.loads(
            attribution_summary_path.read_text(encoding="utf-8")
        )
    score_mean, score_ci_low, score_ci_high = _mean_ci(scores)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_output_dir": str(output_dir.resolve()),
        "population": {
            "selected_questions": len(rows),
            "execution_ok": sum(row["execution_status"] == "ok" for row in rows),
            "execution_errors": len(execution_errors),
            "execution_success_rate": sum(row["execution_status"] == "ok" for row in rows) / len(rows),
            "numeric_scorable": len(scored),
            "unscored_needs_judge": sum(row["score_status"] == "needs_judge" for row in rows),
            "corrected_zero_id_records": len(scoring_corrections),
            "mixed_task_score": score_mean,
            "mixed_task_score_ci95_low": score_ci_low,
            "mixed_task_score_ci95_high": score_ci_high,
            "full_credit": sum(row["full_credit"] is True for row in scored),
            "zero_score": sum(row["zero_score"] is True for row in scored),
            "partial_score": sum(row["partial_score"] is True for row in scored),
            "lost_score": total_lost_score,
            "exact_task_n": len(exact_rows),
            "exact_task_accuracy": sum(row["full_credit"] is True for row in exact_rows) / len(exact_rows),
            "fsa_n": len(fsa_rows),
            "fsa_mean_iou": mean(float(row["score"]) for row in fsa_rows),
            "crossvid_exact_n": len(crossvid_exact_rows),
            "crossvid_exact_accuracy": (
                sum(row["full_credit"] is True for row in crossvid_exact_rows)
                / len(crossvid_exact_rows)
            ),
            "ccqa_n": len(ccqa_rows),
            "ccqa_mean_score": mean(float(row["score"]) for row in ccqa_rows),
            "ccqa_full_credit": sum(row["full_credit"] is True for row in ccqa_rows),
            "ccqa_zero_score": sum(row["zero_score"] is True for row in ccqa_rows),
            "ccqa_partial_score": sum(row["partial_score"] is True for row in ccqa_rows),
            "ccqa_scoring_points": ccqa_scoring_points,
            "ccqa_coverage_points": ccqa_coverage_points,
            "ccqa_correctness_points": ccqa_correctness_points,
            "ccqa_point_level_score": (
                (ccqa_coverage_points + ccqa_correctness_points)
                / (2 * ccqa_scoring_points)
                if ccqa_scoring_points
                else None
            ),
        },
        "timing": {
            **_timing(runtimes),
            "two_worker_idealized_hours": sum(runtimes) / 7200.0,
            "wall_clock_available": False,
            "wall_clock_note": "The output is resume-assembled; per-question time is available, but a suite-level start/end timestamp is not persisted.",
        },
        "by_benchmark": benchmark,
        "by_task": task,
        "segments": {
            "uses_watch": _segment_summary(rows, "uses_watch"),
            "stop_reason": _segment_summary(rows, "stop_reason"),
            "global_decisions": _segment_summary(rows, "global_decisions"),
            "runtime_band": _runtime_bands(rows),
        },
        "slowest_questions": [
            {
                "benchmark": row["benchmark"],
                "sample_id": row["sample_id"],
                "task_label": row["task_label"],
                "runtime_sec": row["runtime_sec"],
                "score": row["score"],
                "uses_watch": row["uses_watch"],
                "global_decisions": row["global_decisions"],
                "video_runs": row["video_runs"],
                "observe_steps": row["observe_steps"],
                "stop_reason": row["stop_reason"],
                "source_path": row["source_path"],
            }
            for row in sorted(
                (row for row in rows if row["runtime_sec"] is not None),
                key=lambda item: float(item["runtime_sec"]),
                reverse=True,
            )[:20]
        ],
        "execution_errors": execution_errors,
        "scoring_corrections": scoring_corrections,
        "stop_reasons": dict(Counter(row["stop_reason"] for row in rows)),
        "failed_video_run_questions": sum(row["failed_video_runs"] > 0 for row in rows),
        "prior_causal_attribution": prior_attribution,
        "caveats": [
            "CrossVid mixes exact-match task scores with FSA interval IoU and CCQA M3-judged coverage/correctness, so its aggregate is a mean task score rather than plain accuracy.",
            "CCQA is scored by MiniMax-M3 with the crossvid-ccqa-coverage-correctness-v2 prompt; its partial-credit scores are included in mixed task-score summaries but excluded from exact-accuracy denominators.",
            "CVBench and MVU-Eval sample ID 0 were incorrectly emitted as empty annotation IDs by the existing summary path; both were verified correct and restored here.",
            "The run was assembled through resume, so cumulative per-question time is reliable while end-to-end wall-clock duration is not recoverable exactly.",
            "Associations between watch/actions/runtime and score are descriptive and confounded by task difficulty; they are not causal effects.",
        ],
    }


def _write_tsv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--per-question-tsv", required=True, type=Path)
    parser.add_argument("--summary-json", required=True, type=Path)
    parser.add_argument("--attribution-summary", type=Path)
    args = parser.parse_args()

    output_dir = args.output_dir.resolve()
    rows, corrections = build_rows(output_dir)
    if len(rows) != 1500:
        raise ValueError(f"expected 1500 question results, found {len(rows)}")
    summary = build_summary(output_dir, rows, corrections, args.attribution_summary)
    _write_tsv(args.per_question_tsv.resolve(), rows)
    args.summary_json.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.summary_json.resolve().write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
