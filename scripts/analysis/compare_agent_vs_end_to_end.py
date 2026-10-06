from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, pstdev
from typing import Any


BENCHMARKS = ("cvbench", "mvu-eval", "crossvid")
CROSSVID_TASKS = ("BU", "NC", "CC", "PEA", "PI", "FSA", "PSS", "MSR", "MOC", "CCQA")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_tsv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def load_agent_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def prepare_predictions(
    *,
    agent_tsv: Path,
    official_root: Path,
    output_path: Path,
) -> dict[str, Any]:
    selected = load_agent_rows(agent_tsv)
    selected_ids = {(row["benchmark"], row["sample_id"]) for row in selected}

    cv_rows = {
        str(row["id"]): row
        for row in read_jsonl(official_root / "qwen36_official_cvbench_mvu/raw/cvbench_predictions.jsonl")
    }
    mvu_rows = {
        str(row["QA_index"]): row
        for row in read_jsonl(official_root / "qwen36_official_cvbench_mvu/raw/mvu_eval_predictions.jsonl")
    }
    crossvid_rows: dict[str, dict[str, Any]] = {}
    for task in CROSSVID_TASKS:
        rows = json.loads(
            (official_root / f"qwen36_official_crossvid/raw/{task}_result.json").read_text(
                encoding="utf-8"
            )
        )
        for row in rows:
            crossvid_rows[f"crossvid:{task}:{row['id']}"] = row

    predictions: list[dict[str, Any]] = []
    missing: list[dict[str, str]] = []
    for row in selected:
        benchmark = row["benchmark"]
        sample_id = row["sample_id"]
        source: dict[str, Any] | None
        prediction: str
        duration: float | None = None
        if benchmark == "cvbench":
            source = cv_rows.get(sample_id)
            prediction = str((source or {}).get("model_output") or "")
            direct_task = str((source or {}).get("task_type") or "Unknown")
            raw_duration = (source or {}).get("elapsed_seconds")
            duration = float(raw_duration) if isinstance(raw_duration, (int, float)) else None
        elif benchmark == "mvu-eval":
            source = mvu_rows.get(sample_id)
            direct_task = str((source or {}).get("task") or row["task"])
            prediction = str(
                ((source or {}).get("model_results") or {}).get("qwen35_local", {}).get(
                    "model_output"
                )
                or ""
            )
        else:
            source = crossvid_rows.get(sample_id)
            direct_task = row["task"]
            prediction = str((source or {}).get("answer") or "")

        status = "ok" if source is not None else "error"
        if source is None:
            missing.append({"benchmark": benchmark, "sample_id": sample_id})
        predictions.append(
            {
                "id": sample_id,
                "benchmark": benchmark,
                "prediction": prediction,
                "task": direct_task,
                "status": status,
                "duration_seconds": duration,
            }
        )

    actual_ids = {(row["benchmark"], str(row["id"])) for row in predictions}
    if len(predictions) != 1500 or len(actual_ids) != 1500 or actual_ids != selected_ids:
        raise ValueError("prepared end-to-end predictions do not exactly match the selected 1,500 IDs")
    write_jsonl(output_path, predictions)
    return {
        "total": len(predictions),
        "by_benchmark": {
            benchmark: sum(row["benchmark"] == benchmark for row in predictions)
            for benchmark in BENCHMARKS
        },
        "missing_predictions": missing,
        "output": str(output_path.resolve()),
    }


def _score_map(scored_root: Path, benchmark: str) -> dict[str, dict[str, Any]]:
    name = benchmark.replace("-", "_")
    rows = read_jsonl(scored_root / benchmark / f"{name}_matrix_details.jsonl")
    output = {str(row["id"]): row for row in rows}
    retry_path = scored_root / benchmark / "retries" / f"{name}_matrix_details.jsonl"
    if retry_path.exists():
        output.update({str(row["id"]): row for row in read_jsonl(retry_path)})
    return output


def _as_bool(value: str) -> bool:
    return value.strip().lower() == "true"


def _as_float(value: str) -> float | None:
    text = value.strip()
    return float(text) if text else None


def _ci95(values: list[float]) -> tuple[float, float, float]:
    center = mean(values)
    if len(values) == 1:
        return center, center, center
    margin = 1.96 * pstdev(values) / math.sqrt(len(values))
    return center, center - margin, center + margin


def _quantile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _timing(values: list[float]) -> dict[str, float | int]:
    return {
        "n": len(values),
        "mean_sec": mean(values),
        "p50_sec": _quantile(values, 0.5),
        "p90_sec": _quantile(values, 0.9),
        "total_hours": sum(values) / 3600.0,
    }


def _group_summary(rows: list[dict[str, Any]], field: str) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(row[field])].append(row)
    output: list[dict[str, Any]] = []
    for label, group in groups.items():
        deltas = [float(row["score_delta"]) for row in group]
        delta, ci_low, ci_high = _ci95(deltas)
        output.append(
            {
                field: label,
                "n": len(group),
                "agent_score": mean(float(row["agent_score"]) for row in group),
                "end_to_end_score": mean(float(row["end_to_end_score"]) for row in group),
                "delta": delta,
                "delta_ci95_low": ci_low,
                "delta_ci95_high": ci_high,
                "agent_wins": sum(row["paired_outcome"] == "agent_win" for row in group),
                "ties": sum(row["paired_outcome"] == "tie" for row in group),
                "end_to_end_wins": sum(
                    row["paired_outcome"] == "end_to_end_win" for row in group
                ),
            }
        )
    return sorted(output, key=lambda row: (-float(row["delta"]), str(row[field])))


def summarize_comparison(
    *,
    agent_tsv: Path,
    predictions_path: Path,
    scored_root: Path,
    per_question_path: Path,
    summary_path: Path,
) -> dict[str, Any]:
    agent_rows = load_agent_rows(agent_tsv)
    predictions = {
        (str(row["benchmark"]), str(row["id"])): row for row in read_jsonl(predictions_path)
    }
    score_maps = {benchmark: _score_map(scored_root, benchmark) for benchmark in BENCHMARKS}

    paired: list[dict[str, Any]] = []
    for agent in agent_rows:
        benchmark = agent["benchmark"]
        sample_id = agent["sample_id"]
        detail = score_maps[benchmark].get(sample_id)
        if detail is None or detail.get("score") is None:
            raise ValueError(f"missing end-to-end score for {benchmark}:{sample_id}")
        agent_score = _as_float(agent["score"])
        if agent_score is None:
            raise ValueError(f"missing Agent score for {benchmark}:{sample_id}")
        end_to_end_score = float(detail["score"])
        delta = agent_score - end_to_end_score
        outcome = "agent_win" if delta > 1e-12 else "end_to_end_win" if delta < -1e-12 else "tie"
        direct = predictions[(benchmark, sample_id)]
        comparison_task_label = (
            f"CV {direct['task']}" if benchmark == "cvbench" else agent["task_label"]
        )
        paired.append(
            {
                "benchmark": benchmark,
                "sample_id": sample_id,
                "task": agent["task"],
                "task_label": agent["task_label"],
                "comparison_task_label": comparison_task_label,
                "agent_execution_status": agent["execution_status"],
                "end_to_end_execution_status": direct["status"],
                "agent_score": agent_score,
                "end_to_end_score": end_to_end_score,
                "score_delta": delta,
                "paired_outcome": outcome,
                "agent_prediction": agent["prediction"],
                "end_to_end_prediction": direct["prediction"],
                "ground_truth": agent["ground_truth"],
                "agent_runtime_sec": _as_float(agent["runtime_sec"]),
                "end_to_end_runtime_sec": direct.get("duration_seconds"),
                "agent_uses_watch": _as_bool(agent["uses_watch"]),
                "agent_global_decisions": int(agent["global_decisions"]),
                "agent_observe_steps": int(agent["observe_steps"]),
            }
        )

    if len(paired) != 1500 or len({(r["benchmark"], r["sample_id"]) for r in paired}) != 1500:
        raise ValueError("comparison is not a one-to-one 1,500-question pairing")

    exact = [
        row
        for row in paired
        if not (row["benchmark"] == "crossvid" and row["task"] in {"FSA", "CCQA"})
    ]
    fsa = [row for row in paired if row["benchmark"] == "crossvid" and row["task"] == "FSA"]
    ccqa = [row for row in paired if row["benchmark"] == "crossvid" and row["task"] == "CCQA"]
    crossvid_tasks = _group_summary(
        [row for row in paired if row["benchmark"] == "crossvid"], "task_label"
    )
    cvbench_rows = [row for row in paired if row["benchmark"] == "cvbench"]
    cvbench_agent_times = [float(row["agent_runtime_sec"]) for row in cvbench_rows]
    cvbench_end_to_end_times = [
        float(row["end_to_end_runtime_sec"]) for row in cvbench_rows
    ]

    def metric_block(group: list[dict[str, Any]]) -> dict[str, Any]:
        deltas = [float(row["score_delta"]) for row in group]
        delta, ci_low, ci_high = _ci95(deltas)
        return {
            "n": len(group),
            "agent_score": mean(float(row["agent_score"]) for row in group),
            "end_to_end_score": mean(float(row["end_to_end_score"]) for row in group),
            "delta": delta,
            "delta_ci95_low": ci_low,
            "delta_ci95_high": ci_high,
            "agent_wins": sum(row["paired_outcome"] == "agent_win" for row in group),
            "ties": sum(row["paired_outcome"] == "tie" for row in group),
            "end_to_end_wins": sum(row["paired_outcome"] == "end_to_end_win" for row in group),
        }

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": {
            "paired_questions": len(paired),
            "same_model": "Qwen3.6-27B-FP8",
            "agent_method": "MVAgent GlobalAgent + VideoAgent",
            "end_to_end_method": "official-protocol direct model inference",
            "ccqa_judge_model": "MiniMax-M3",
            "ccqa_judge_prompt": "crossvid-ccqa-coverage-correctness-v2",
            "comparison_basis": "same selected IDs; both outputs rescored with the repository matrix rules",
        },
        "overall_mixed_task_score": metric_block(paired),
        "exact_tasks": metric_block(exact),
        "crossvid_fsa": metric_block(fsa),
        "crossvid_ccqa": metric_block(ccqa),
        "crossvid_task_macro": {
            "n_tasks": len(crossvid_tasks),
            "agent_score": mean(float(row["agent_score"]) for row in crossvid_tasks),
            "end_to_end_score": mean(float(row["end_to_end_score"]) for row in crossvid_tasks),
            "delta": mean(float(row["delta"]) for row in crossvid_tasks),
        },
        "by_benchmark": _group_summary(paired, "benchmark"),
        "by_task": _group_summary(paired, "comparison_task_label"),
        "execution": {
            "agent_errors": sum(row["agent_execution_status"] != "ok" for row in paired),
            "end_to_end_errors": sum(
                row["end_to_end_execution_status"] != "ok" for row in paired
            ),
        },
        "timing": {
            "agent_timed_questions": sum(row["agent_runtime_sec"] is not None for row in paired),
            "agent_worker_hours": sum(
                float(row["agent_runtime_sec"] or 0.0) for row in paired
            )
            / 3600.0,
            "end_to_end_timed_questions": sum(
                row["end_to_end_runtime_sec"] is not None for row in paired
            ),
            "cvbench_agent": _timing(cvbench_agent_times),
            "cvbench_end_to_end": _timing(cvbench_end_to_end_times),
            "note": "Matched end-to-end per-question latency is available only for CVBench. The two runs used different execution topology, so this is an indicative systems-cost comparison, not a controlled latency benchmark.",
        },
    }
    write_tsv(per_question_path, paired)
    write_json(summary_path, summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent-tsv", required=True, type=Path)
    parser.add_argument("--official-root", required=True, type=Path)
    parser.add_argument("--predictions", required=True, type=Path)
    parser.add_argument("--scored-root", type=Path)
    parser.add_argument("--per-question", type=Path)
    parser.add_argument("--summary", type=Path)
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()

    prepared = prepare_predictions(
        agent_tsv=args.agent_tsv.resolve(),
        official_root=args.official_root.resolve(),
        output_path=args.predictions.resolve(),
    )
    if args.prepare_only:
        print(json.dumps(prepared, ensure_ascii=False, indent=2))
        return
    if not args.scored_root or not args.per_question or not args.summary:
        parser.error("--scored-root, --per-question, and --summary are required unless --prepare-only")
    summary = summarize_comparison(
        agent_tsv=args.agent_tsv.resolve(),
        predictions_path=args.predictions.resolve(),
        scored_root=args.scored_root.resolve(),
        per_question_path=args.per_question.resolve(),
        summary_path=args.summary.resolve(),
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
