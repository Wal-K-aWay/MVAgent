#!/usr/bin/env python3
"""Paired comparison of the 1,500-question MVAgent run with the 512-frame direct run."""

from __future__ import annotations

import csv
import json
import math
import random
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
AGENT = ROOT / "outputs/demo_test_1500_eval_gpu67_current_20260810_01"
DIRECT = ROOT / "outputs/full_3benchmark_end_to_end_512_20260821"
OUT = ROOT / "outputs/analysis/2026-08-24_mvagent_vs_direct_512"
AGENT_CCQA = OUT / "mvagent_ccqa_score_m3.json"


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else float("nan")


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return float("nan")
    pos = (len(ordered) - 1) * q
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return ordered[lo]
    return ordered[lo] * (hi - pos) + ordered[hi] * (pos - lo)


def bootstrap_mean_ci(deltas: list[float], seed: int = 20260824, draws: int = 10_000) -> tuple[float, float]:
    rng = random.Random(seed)
    n = len(deltas)
    samples = [mean([deltas[rng.randrange(n)] for _ in range(n)]) for _ in range(draws)]
    return percentile(samples, 0.025), percentile(samples, 0.975)


def bootstrap_task_macro_ci(rows: list[dict], seed: int = 20260824, draws: int = 10_000) -> tuple[float, float]:
    by_task: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        by_task[row["task"]].append(row["delta"])
    rng = random.Random(seed)
    samples = []
    for _ in range(draws):
        task_means = []
        for values in by_task.values():
            n = len(values)
            task_means.append(mean([values[rng.randrange(n)] for _ in range(n)]))
        samples.append(mean(task_means))
    return percentile(samples, 0.025), percentile(samples, 0.975)


def mcnemar_exact_p(agent_wins: int, direct_wins: int) -> float:
    discordant = agent_wins + direct_wins
    if discordant == 0:
        return 1.0
    tail = sum(math.comb(discordant, k) for k in range(0, min(agent_wins, direct_wins) + 1)) / (2**discordant)
    return min(1.0, 2 * tail)


def paired_summary(rows: list[dict], macro_by_task: bool = False) -> dict:
    deltas = [row["delta"] for row in rows]
    wins = sum(row["delta"] > 1e-12 for row in rows)
    losses = sum(row["delta"] < -1e-12 for row in rows)
    ties = len(rows) - wins - losses
    if macro_by_task:
        tasks = sorted({row["task"] for row in rows})
        agent_score = mean([mean([r["agent_score"] for r in rows if r["task"] == task]) for task in tasks])
        direct_score = mean([mean([r["direct_score"] for r in rows if r["task"] == task]) for task in tasks])
        ci_low, ci_high = bootstrap_task_macro_ci(rows)
    else:
        agent_score = mean([row["agent_score"] for row in rows])
        direct_score = mean([row["direct_score"] for row in rows])
        ci_low, ci_high = bootstrap_mean_ci(deltas)
    return {
        "n": len(rows),
        "agent_score": agent_score,
        "direct_score": direct_score,
        "delta": agent_score - direct_score,
        "delta_ci95_low": ci_low,
        "delta_ci95_high": ci_high,
        "agent_wins": wins,
        "ties": ties,
        "direct_wins": losses,
    }


def normalize_cv(value: str) -> str:
    text = str(value).strip().upper().replace(".", "")
    if text in {"YES", "NO", "A", "B", "C", "D"}:
        return text
    return text[:1]


def benchmark_rows(benchmark: str) -> tuple[list[dict], dict]:
    agent_predictions = load_jsonl(AGENT / benchmark / "predictions.jsonl")
    direct_predictions = load_jsonl(
        DIRECT / ("cvbench/raw/cvbench_predictions.jsonl" if benchmark == "cvbench" else "mvu_eval/raw/mvu_eval_predictions.jsonl")
    )
    direct_by_id = {int(row["id"]): row for row in direct_predictions}
    detail_rows = load_jsonl(AGENT / benchmark / f"{benchmark.replace('-', '_')}_matrix_details.jsonl")
    detail_by_id = {int(row["id"]): row for row in detail_rows if str(row.get("id", "")).strip()}
    rows = []
    missing_direct_ids = []
    for prediction in agent_predictions:
        item_id = int(prediction["id"])
        direct = direct_by_id.get(item_id)
        detail = detail_by_id.get(item_id)
        if detail is not None:
            task = (direct or {}).get("task_type") or detail.get("task") or "Unknown"
            agent_score = float(detail.get("score") or 0.0)
        elif direct is not None:
            task = direct["task_type"]
            expected = str(direct["answer"]).strip().upper()
            if benchmark == "cvbench":
                agent_score = float(normalize_cv(prediction["prediction"]) == expected)
            else:
                agent_score = float(str(prediction["prediction"]).strip().upper()[:1] == expected)
        else:
            raise RuntimeError(f"Cannot recover annotation for {benchmark}:{item_id}")
        if direct is None:
            direct_score = 0.0
            missing_direct_ids.append(item_id)
            direct_strict_score = 0.0
        else:
            direct_score = float(
                direct["correct"] if benchmark == "cvbench" else direct["legacy_first_character_correct"]
            )
            direct_strict_score = float(direct.get("correct", direct_score))
        rows.append(
            {
                "benchmark": benchmark,
                "id": str(item_id),
                "task": task,
                "agent_score": agent_score,
                "direct_score": direct_score,
                "direct_strict_score": direct_strict_score,
                "delta": agent_score - direct_score,
            }
        )
    metadata = {
        "selected": len(agent_predictions),
        "direct_completed": len(agent_predictions) - len(missing_direct_ids),
        "direct_failures_counted_as_zero": missing_direct_ids,
    }
    return rows, metadata


def crossvid_rows() -> tuple[list[dict], dict]:
    agent_details = load_jsonl(AGENT / "crossvid/crossvid_matrix_details.jsonl")
    agent_by_task_id = {}
    selected_ids: dict[str, set[int]] = defaultdict(set)
    for row in agent_details:
        task = row["task"]
        item_id = int(str(row["id"]).split(":")[-1])
        if task != "CCQA":
            agent_by_task_id[(task, item_id)] = float(row["score"])
        selected_ids[task].add(item_id)

    agent_ccqa = {int(row["id"]): row for row in load_json(AGENT_CCQA)}
    direct_ccqa = {
        int(row["id"]): row
        for row in load_json(DIRECT / "crossvid/raw/CCQA_score_m3.json")
        if "error" not in row
    }
    direct_by_task_id = {}
    for task in sorted(selected_ids):
        if task == "CCQA":
            continue
        raw = load_json(DIRECT / f"crossvid/raw/{task}_result.json")
        for row in raw:
            score = float(row["iou"] if task == "FSA" else row["correct"])
            direct_by_task_id[(task, int(row["id"]))] = score

    rows = []
    for task, ids in selected_ids.items():
        for item_id in sorted(ids):
            if task == "CCQA":
                agent_row = agent_ccqa[item_id]
                direct_row = direct_ccqa[item_id]
                agent_score = agent_row["score"] / agent_row["max_score"]
                direct_score = direct_row["score"] / direct_row["max_score"]
            else:
                agent_score = agent_by_task_id[(task, item_id)]
                direct_score = direct_by_task_id[(task, item_id)]
            rows.append(
                {
                    "benchmark": "crossvid",
                    "id": f"crossvid:{task}:{item_id}",
                    "task": task,
                    "agent_score": agent_score,
                    "direct_score": direct_score,
                    "direct_strict_score": direct_score,
                    "delta": agent_score - direct_score,
                }
            )

    def pooled_ccqa(source: dict[int, dict], ids: set[int]) -> float:
        return sum(source[i]["score"] for i in ids) / sum(source[i]["max_score"] for i in ids)

    metadata = {
        "selected": len(rows),
        "direct_completed": len(rows),
        "direct_failures_counted_as_zero": [],
        "ccqa": {
            "agent_score": pooled_ccqa(agent_ccqa, selected_ids["CCQA"]),
            "direct_score": pooled_ccqa(direct_ccqa, selected_ids["CCQA"]),
            "n": len(selected_ids["CCQA"]),
            "judge": "MiniMax-M3",
            "protocol": "official SCORE prompt; pooled scoring points",
        },
    }
    return rows, metadata


def task_summaries(rows: list[dict], ccqa_pooled: dict | None = None) -> list[dict]:
    output = []
    for task in sorted({row["task"] for row in rows}):
        task_rows = [row for row in rows if row["task"] == task]
        summary = paired_summary(task_rows)
        if task == "CCQA" and ccqa_pooled is not None:
            summary["agent_score"] = ccqa_pooled["agent_score"]
            summary["direct_score"] = ccqa_pooled["direct_score"]
            summary["delta"] = summary["agent_score"] - summary["direct_score"]
        output.append({"task": task, **summary})
    return output


def latency_summary(benchmark: str, direct_rows: list[dict]) -> dict:
    agent = load_jsonl(AGENT / benchmark / "predictions.jsonl")
    agent_times = [float(row["duration_seconds"]) for row in agent if row.get("duration_seconds") is not None]
    selected = {int(row["id"]) for row in agent}
    direct_times = [float(row["elapsed_seconds"]) for row in direct_rows if int(row["id"]) in selected]
    return {
        "agent_n": len(agent_times),
        "agent_mean_seconds": mean(agent_times),
        "agent_median_seconds": percentile(agent_times, 0.5),
        "direct_n": len(direct_times),
        "direct_mean_seconds": mean(direct_times),
        "direct_median_seconds": percentile(direct_times, 0.5),
        "mean_latency_ratio": mean(agent_times) / mean(direct_times),
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    cv_rows, cv_meta = benchmark_rows("cvbench")
    mvu_rows, mvu_meta = benchmark_rows("mvu-eval")
    crossvid, crossvid_meta = crossvid_rows()

    cv = paired_summary(cv_rows)
    cv["mcnemar_exact_p"] = mcnemar_exact_p(cv["agent_wins"], cv["direct_wins"])
    mvu = paired_summary(mvu_rows)
    mvu["mcnemar_exact_p"] = mcnemar_exact_p(mvu["agent_wins"], mvu["direct_wins"])
    mvu["direct_strict_score"] = mean([row["direct_strict_score"] for row in mvu_rows])
    mvu["agent_minus_direct_strict"] = mvu["agent_score"] - mvu["direct_strict_score"]
    crossvid_macro = paired_summary(crossvid, macro_by_task=True)
    crossvid_micro = paired_summary(crossvid)

    crossvid_tasks = task_summaries(crossvid, crossvid_meta["ccqa"])
    crossvid_macro["agent_score"] = mean([row["agent_score"] for row in crossvid_tasks])
    crossvid_macro["direct_score"] = mean([row["direct_score"] for row in crossvid_tasks])
    crossvid_macro["delta"] = crossvid_macro["agent_score"] - crossvid_macro["direct_score"]

    all_task_rows = []
    for benchmark, rows, pooled in [
        ("cvbench", cv_rows, None),
        ("mvu-eval", mvu_rows, None),
        ("crossvid", crossvid, crossvid_meta["ccqa"]),
    ]:
        for row in task_summaries(rows, pooled):
            all_task_rows.append({"benchmark": benchmark, **row})
    all_task_rows.sort(key=lambda row: row["delta"], reverse=True)

    task_router_upper_bound = {}
    for benchmark in ("cvbench", "mvu-eval", "crossvid"):
        task_rows = [row for row in all_task_rows if row["benchmark"] == benchmark]
        agent_task_macro = mean([row["agent_score"] for row in task_rows])
        direct_task_macro = mean([row["direct_score"] for row in task_rows])
        oracle_score = mean([max(row["agent_score"], row["direct_score"]) for row in task_rows])
        task_router_upper_bound[benchmark] = {
            "agent_task_macro": agent_task_macro,
            "direct_task_macro": direct_task_macro,
            "oracle_task_router_score": oracle_score,
            "oracle_uplift_vs_best_fixed_method": oracle_score - max(agent_task_macro, direct_task_macro),
            "warning": "In-sample upper bound only; not a validated routing policy.",
        }

    direct_cv_rows = load_jsonl(DIRECT / "cvbench/raw/cvbench_predictions.jsonl")
    direct_mvu_rows = load_jsonl(DIRECT / "mvu_eval/raw/mvu_eval_predictions.jsonl")
    summary = {
        "generated_at": "2026-08-24",
        "decision": "Whether MVAgent has a quality advantage over direct 512-frame inference with the same Qwen3.6-27B-FP8 model.",
        "scope": {
            "selected_questions": 1500,
            "cvbench": 250,
            "mvu_eval": 250,
            "crossvid": 1000,
            "model": "Qwen3.6-27B-FP8",
            "agent_config": "max 512 frames per visual request; up to 5 Global and 5 Video steps; multiple visual requests allowed",
            "direct_config": "512 total video frames per question for CVBench and MVU-Eval; 512 frames per CrossVid question",
            "comparison_warning": "Question IDs and model match, but total visual-compute budgets do not: MVAgent may issue multiple 512-frame visual requests.",
        },
        "data_quality": {
            "status": "share_with_caveats",
            "cvbench": cv_meta,
            "mvu_eval": mvu_meta,
            "crossvid": crossvid_meta,
            "known_protocol_changes": [
                "Direct results use the corrected 512-frame protocols from 2026-08-21.",
                "MVAgent CCQA was rescored with the identical MiniMax-M3 official SCORE prompt used for direct inference.",
                "MVU-Eval is reported both with the paper-compatible first-character parser and the stricter final-choice parser for direct outputs.",
            ],
        },
        "by_benchmark": {
            "cvbench": cv,
            "mvu_eval_paper_parser": mvu,
            "crossvid_official_oavg": crossvid_macro,
            "crossvid_question_micro": crossvid_micro,
        },
        "headline_macro_across_benchmarks": {
            "agent_score": mean([cv["agent_score"], mvu["agent_score"], crossvid_macro["agent_score"]]),
            "direct_score": mean([cv["direct_score"], mvu["direct_score"], crossvid_macro["direct_score"]]),
        },
        "by_task": all_task_rows,
        "task_router_upper_bound": task_router_upper_bound,
        "latency": {
            "cvbench": latency_summary("cvbench", direct_cv_rows),
            "mvu_eval": latency_summary("mvu-eval", direct_mvu_rows),
            "crossvid": {
                "agent_mean_seconds": mean(
                    [float(row["duration_seconds"]) for row in load_jsonl(AGENT / "crossvid/predictions.jsonl")]
                ),
                "direct_per_question_unavailable": True,
            },
        },
        "sources": {
            "agent_predictions": str(AGENT.relative_to(ROOT)),
            "direct_predictions": str(DIRECT.relative_to(ROOT)),
            "agent_ccqa_scores": str(AGENT_CCQA.relative_to(ROOT)),
        },
    }
    summary["headline_macro_across_benchmarks"]["delta"] = (
        summary["headline_macro_across_benchmarks"]["agent_score"]
        - summary["headline_macro_across_benchmarks"]["direct_score"]
    )

    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with (OUT / "per_task.tsv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(all_task_rows[0]), delimiter="\t")
        writer.writeheader()
        writer.writerows(all_task_rows)
    with (OUT / "per_question.tsv").open("w", encoding="utf-8", newline="") as handle:
        rows = cv_rows + mvu_rows + crossvid
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps(summary["by_benchmark"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
