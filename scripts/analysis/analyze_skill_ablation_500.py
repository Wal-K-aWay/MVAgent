from __future__ import annotations

import csv
import json
import math
import random
import re
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_DIR = ROOT / "outputs" / "analysis" / "2026-08-15_skill_ablation_500"
IDS_PATH = ARTIFACT_DIR / "skill_ablation_500_ids.txt"
TASK_MAP_PATH = ARTIFACT_DIR / "demo_test_1500_end_to_end_predictions.jsonl"
RUN_ROOT = ROOT / "outputs" / "skill_ablation_500_20260813"
RUNS = {
    "enabled": RUN_ROOT / "enabled_gpu6",
    "disabled": RUN_ROOT / "disabled_gpu7",
}
M3_ROOT = ARTIFACT_DIR / "skill_ablation_500_scored_m3"
OUTPUT_JSON = ARTIFACT_DIR / "skill_ablation_500_m3_analysis.json"
OUTPUT_TSV = ARTIFACT_DIR / "skill_ablation_500_m3_per_question.tsv"
OUTPUT_REPORT = ROOT / "analysis" / "reports" / "2026-08-15_skill_ablation_500.md"

CCQA_MANUAL_ATTRIBUTION = {
    "crossvid:CCQA:366": {
        "winner": "disabled",
        "primary_stage": "VideoAgent",
        "finding": "enabled 的 video_A 报告误识别出水煮蛋和生蛋黄，GlobalAgent 直接沿用。",
    },
    "crossvid:CCQA:670": {
        "winner": "disabled",
        "primary_stage": "GlobalAgent",
        "finding": "两侧视频报告都识别了蛋白来源；disabled 的最终比较补充了口感/风味影响，enabled 未展开。",
    },
    "crossvid:CCQA:87": {
        "winner": "disabled",
        "primary_stage": "VideoAgent",
        "finding": "enabled 的 video_A 报告漏掉炸前加辣酱腌制，最终答案原样继承该错误。",
    },
    "crossvid:CCQA:805": {
        "winner": "disabled",
        "primary_stage": "GlobalAgent",
        "finding": "enabled 视频报告已有生花椰菜米和熟藜麦证据，但最终答案省略了切碎/煮制方法。",
    },
    "crossvid:CCQA:862": {
        "winner": "disabled",
        "primary_stage": "VideoAgent",
        "finding": "enabled 的 video_A 报告误判锅中煮汁和增稠物；两侧均不完整，但 disabled 覆盖更多流程结构。",
    },
    "crossvid:CCQA:121": {
        "winner": "disabled",
        "primary_stage": "VideoAgent",
        "finding": "enabled 报告漏掉 Video A 红酒以及 Video B 番茄膏/番茄酱信息。",
    },
    "crossvid:CCQA:808": {
        "winner": "disabled",
        "primary_stage": "GlobalAgent",
        "finding": "enabled 的 video_B 报告明确有 cabbage cups，但最终答案未保留该呈现差异。",
    },
    "crossvid:CCQA:145": {
        "winner": "disabled",
        "primary_stage": "mixed",
        "finding": "两侧都无法可靠识别 Video B 酱汁；disabled 多轮观察后作出部分推断，仅获得 coverage、无 correctness 增益。",
    },
    "crossvid:CCQA:719": {
        "winner": "disabled",
        "primary_stage": "VideoAgent",
        "finding": "enabled 视频报告把切刀角度与摆盘重点判断反了，且两侧都未充分抓住花形与 nigiri 功能差异。",
    },
    "crossvid:CCQA:720": {
        "winner": "enabled",
        "primary_stage": "GlobalAgent",
        "finding": "视频报告近似；enabled 最终文本多覆盖一个点，但该新增点未获 correctness。",
    },
    "crossvid:CCQA:707": {
        "winner": "enabled",
        "primary_stage": "GlobalAgent",
        "finding": "视频证据相近，最终答案对应用方式的措辞和不确定性处理不同。",
    },
    "crossvid:CCQA:124": {
        "winner": "enabled",
        "primary_stage": "VideoAgent",
        "finding": "enabled 观察到 Video A 从罐中倒入液态油；但新增得分仅来自 coverage，脂肪类型仍不正确。",
    },
    "crossvid:CCQA:563": {
        "winner": "enabled",
        "primary_stage": "VideoAgent",
        "finding": "enabled 的 video_B 报告保留奶油奶酪和蛋黄酱混合成抹酱，disabled 报告漏掉。",
    },
    "crossvid:CCQA:122": {
        "winner": "enabled",
        "primary_stage": "VideoAgent",
        "finding": "enabled 正确识别 Video B 肉丸先烤后入酱；disabled 报告误称未经预处理直接入酱。",
    },
}


def quantile(values: list[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def describe(values: list[float]) -> dict[str, float | int | None]:
    return {
        "count": len(values),
        "mean": mean(values) if values else None,
        "p50": median(values) if values else None,
        "p90": quantile(values, 0.90),
        "p95": quantile(values, 0.95),
        "max": max(values) if values else None,
        "sum": sum(values),
    }


def bootstrap_ci(deltas: list[float], *, seed: int, samples: int = 20_000) -> list[float]:
    if not deltas:
        return [0.0, 0.0]
    generator = random.Random(seed)
    estimates = sorted(
        mean(generator.choice(deltas) for _ in deltas)
        for _ in range(samples)
    )
    return [
        estimates[int(0.025 * samples)],
        estimates[int(0.975 * samples)],
    ]


def sign_test(enabled_wins: int, disabled_wins: int) -> float:
    count = enabled_wins + disabled_wins
    if not count:
        return 1.0
    tail = sum(
        math.comb(count, index)
        for index in range(min(enabled_wins, disabled_wins) + 1)
    )
    return min(1.0, 2 * tail / (2**count))


def selected_ids() -> list[tuple[str, str]]:
    ids: list[tuple[str, str]] = []
    for line in IDS_PATH.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"# ID: (.+)", line.strip())
        if not match:
            continue
        canonical = match.group(1)
        benchmark, suffix = canonical.split(":", 1)
        sample_id = canonical if benchmark == "crossvid" else suffix
        ids.append((benchmark, sample_id))
    if len(ids) != 500 or len(set(ids)) != 500:
        raise RuntimeError(f"Expected 500 unique selected IDs, found {len(ids)}")
    return ids


def task_map() -> dict[tuple[str, str], str]:
    mapping: dict[tuple[str, str], str] = {}
    for line in TASK_MAP_PATH.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        mapping[(str(row["benchmark"]), str(row["id"]))] = str(row.get("task") or "Unknown")
    return mapping


def matrix_paths(run: str) -> tuple[Path, Path, Path]:
    root = RUNS[run]
    return (
        root / "cvbench" / "cvbench_matrix_details.jsonl",
        root / "mvu-eval" / "mvu_eval_matrix_details.jsonl",
        M3_ROOT / run / "crossvid_matrix_details.jsonl",
    )


def load_matrix(run: str) -> dict[tuple[str, str], dict[str, Any]]:
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    for path in matrix_paths(run):
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            key = (str(row["benchmark"]), str(row["id"]))
            if key in rows:
                raise RuntimeError(f"Duplicate matrix row for {run}: {key}")
            rows[key] = row
    return rows


def result_payload(run: str, benchmark: str, sample_id: str) -> dict[str, Any]:
    path = RUNS[run] / benchmark / "questions" / sample_id / "result.json"
    return json.loads(path.read_text(encoding="utf-8"))


def action_signature(step: dict[str, Any]) -> str:
    return json.dumps(
        {"action": step.get("action"), "parameters": step.get("parameters")},
        sort_keys=True,
        ensure_ascii=False,
    )


def trajectory_features(payload: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    trajectory = result.get("trajectory") if isinstance(result.get("trajectory"), list) else []
    decisions = [
        item
        for item in trajectory
        if item.get("agent") == "GlobalAgent" and item.get("action") == "decide"
    ]
    global_steps = [
        item
        for item in trajectory
        if item.get("agent") == "GlobalAgent"
        and item.get("action") in {"decide", "terminal_answer"}
    ]
    video_runs = [
        item
        for item in trajectory
        if item.get("agent") == "VideoAgent" and item.get("action") == "run"
    ]
    issues: list[str] = []
    rounds = [item.get("round") for item in global_steps]
    if rounds != list(range(1, len(rounds) + 1)):
        issues.append(f"global rounds: {rounds}")

    observes: list[tuple[str, dict[str, Any]]] = []
    finish_steps = 0
    direct_finish_runs = 0
    failed_observes = 0
    for run in video_runs:
        steps = (run.get("output") or {}).get("steps") or []
        step_numbers = [step.get("step") for step in steps]
        if step_numbers != list(range(1, len(step_numbers) + 1)):
            issues.append(f"video steps: {step_numbers}")
        has_observe = False
        has_finish = False
        for step in steps:
            if step.get("action") == "observe":
                has_observe = True
                observes.append((str(run.get("video_id") or ""), step))
                if (step.get("result") or {}).get("status") != "ok":
                    failed_observes += 1
            elif step.get("action") == "finish":
                has_finish = True
                finish_steps += 1
        direct_finish_runs += int(has_finish and not has_observe)

    signatures: Counter[str] = Counter()
    for video_id, step in observes:
        signatures[f"{video_id}:{action_signature(step)}"] += 1
    duplicate_observes = sum(count - 1 for count in signatures.values() if count > 1)
    decision_failures = sum(
        isinstance(item.get("output"), dict)
        and item["output"].get("status") in {"invalid", "error"}
        for item in decisions
    )
    terminal_answer = any(item.get("action") == "terminal_answer" for item in global_steps)
    return (
        {
            "runtime_sec": float(result.get("time") or 0.0),
            "global_decisions": len(decisions),
            "analyze_actions": sum(
                (item.get("output") or {}).get("action") == "analyze_videos"
                for item in decisions
            ),
            "watch_actions": sum(
                (item.get("output") or {}).get("action") == "watch_videos"
                for item in decisions
            ),
            "video_runs": len(video_runs),
            "observe_steps": len(observes),
            "finish_steps": finish_steps,
            "direct_finish_runs": direct_finish_runs,
            "failed_observe_steps": failed_observes,
            "failed_video_runs": sum(
                (run.get("output") or {}).get("status") != "ok" for run in video_runs
            ),
            "decision_failures": decision_failures,
            "duplicate_observes": duplicate_observes,
            "terminal_answer": terminal_answer,
            "uses_watch": any(
                (item.get("output") or {}).get("action") == "watch_videos"
                for item in decisions
            ),
        },
        issues,
    )


def score_family(metric: str) -> str:
    if metric == "llm_judge_coverage_correctness":
        return "ccqa_m3"
    if metric == "interval_iou":
        return "fsa_iou"
    return "exact"


def paired_summary(rows: list[dict[str, Any]], *, seed: int) -> dict[str, Any]:
    deltas = [float(row["score_delta"]) for row in rows]
    enabled_wins = sum(delta > 1e-12 for delta in deltas)
    disabled_wins = sum(delta < -1e-12 for delta in deltas)
    return {
        "count": len(rows),
        "enabled_mean_score": mean(float(row["enabled_score"]) for row in rows),
        "disabled_mean_score": mean(float(row["disabled_score"]) for row in rows),
        "enabled_minus_disabled": mean(deltas),
        "paired_bootstrap_ci95": bootstrap_ci(deltas, seed=seed),
        "enabled_wins": enabled_wins,
        "ties": len(rows) - enabled_wins - disabled_wins,
        "disabled_wins": disabled_wins,
        "sign_test_p": sign_test(enabled_wins, disabled_wins),
        "enabled_full_credit": sum(float(row["enabled_score"]) == 1.0 for row in rows),
        "disabled_full_credit": sum(float(row["disabled_score"]) == 1.0 for row in rows),
    }


def group_quality(rows: list[dict[str, Any]], field: str, *, seed: int) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(row[field])].append(row)
    return {
        key: paired_summary(value, seed=seed + index)
        for index, (key, value) in enumerate(sorted(groups.items()))
    }


def feature_comparison(rows: list[dict[str, Any]]) -> dict[str, Any]:
    numeric_fields = (
        "runtime_sec",
        "global_decisions",
        "analyze_actions",
        "watch_actions",
        "video_runs",
        "observe_steps",
        "finish_steps",
        "direct_finish_runs",
        "failed_observe_steps",
        "failed_video_runs",
        "decision_failures",
        "duplicate_observes",
    )
    comparison: dict[str, Any] = {}
    for field in numeric_fields:
        enabled = [float(row[f"enabled_{field}"]) for row in rows]
        disabled = [float(row[f"disabled_{field}"]) for row in rows]
        comparison[field] = {
            "enabled_mean": mean(enabled),
            "disabled_mean": mean(disabled),
            "enabled_minus_disabled": mean(a - b for a, b in zip(enabled, disabled)),
            "enabled_total": sum(enabled),
            "disabled_total": sum(disabled),
        }
    for field in ("terminal_answer", "uses_watch"):
        comparison[field] = {
            "enabled_questions": sum(bool(row[f"enabled_{field}"]) for row in rows),
            "disabled_questions": sum(bool(row[f"disabled_{field}"]) for row in rows),
        }
    return comparison


def ccqa_summary(rows: list[dict[str, Any]], matrices: dict[str, dict[tuple[str, str], dict[str, Any]]]) -> dict[str, Any]:
    ccqa_rows = [row for row in rows if row["score_family"] == "ccqa_m3"]
    result: dict[str, Any] = {}
    for run in ("enabled", "disabled"):
        point_count = 0
        covered = 0
        correct = 0
        attempts: list[int] = []
        character_counts: list[int] = []
        word_counts: list[int] = []
        usage = Counter()
        for row in ccqa_rows:
            detail = matrices[run][(row["benchmark"], row["sample_id"])]
            coverage = list(detail["coverage"])
            correctness = list(detail["correctness"])
            point_count += len(coverage)
            covered += sum(coverage)
            correct += sum(correctness)
            attempts.append(int(detail.get("judge_attempts") or 0))
            prediction = str(detail.get("prediction") or "")
            character_counts.append(len(prediction))
            word_counts.append(len(prediction.split()))
            for key, value in (detail.get("judge_usage") or {}).items():
                usage[key] += int(value)
        result[run] = {
            "questions": len(ccqa_rows),
            "scoring_points": point_count,
            "mean_question_score": mean(float(row[f"{run}_score"]) for row in ccqa_rows),
            "point_weighted_score": (covered + correct) / (2 * point_count),
            "coverage_true": covered,
            "coverage_rate": covered / point_count,
            "correctness_true": correct,
            "correctness_rate": correct / point_count,
            "uncovered_points": point_count - covered,
            "covered_but_incorrect_points": covered - correct,
            "judge_attempts": dict(Counter(attempts)),
            "judge_usage": dict(usage),
            "answer_length": {
                "mean_characters": mean(character_counts),
                "mean_whitespace_words": mean(word_counts),
                "median_whitespace_words": median(word_counts),
            },
        }
    identical = [row for row in ccqa_rows if row["same_prediction"]]
    inconsistent = [row for row in identical if abs(float(row["score_delta"])) > 1e-12]
    result["paired"] = paired_summary(ccqa_rows, seed=20260821)
    result["judge_consistency_audit"] = {
        "identical_predictions": len(identical),
        "identical_predictions_with_different_scores": len(inconsistent),
        "affected_ids": [row["sample_id"] for row in inconsistent],
    }
    reviewed = [
        {"sample_id": sample_id, **audit}
        for sample_id, audit in CCQA_MANUAL_ATTRIBUTION.items()
    ]
    result["manual_non_tie_attribution"] = {
        "reviewed": len(reviewed),
        "by_primary_stage": dict(Counter(item["primary_stage"] for item in reviewed)),
        "cases": reviewed,
        "scope_note": (
            "Human review of all 14 CCQA pairs with unequal M3 scores. Stage labels identify "
            "where the decisive error or omission was visible, not isolated causal effects of "
            "the two simultaneously toggled Skills."
        ),
    }
    return result


def log_wall_time(run: str) -> dict[str, Any]:
    path = RUN_ROOT / f"{run}_gpu{'6' if run == 'enabled' else '7'}.screen.log"
    pattern = re.compile(
        r"^\[SUMMARY\] benchmark=(\S+) completed=(\d+) failed=(\d+) resumed=(\d+) elapsed=([0-9.]+)s$"
    )
    benchmarks: dict[str, float] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = pattern.match(line)
        if match:
            benchmarks[match.group(1)] = float(match.group(5))
    return {
        "by_benchmark_seconds": benchmarks,
        "total_seconds": sum(benchmarks.values()),
        "total_hours": sum(benchmarks.values()) / 3600,
    }


def runtime_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    enabled = [float(row["enabled_runtime_sec"]) for row in rows]
    disabled = [float(row["disabled_runtime_sec"]) for row in rows]
    deltas = [a - b for a, b in zip(enabled, disabled)]
    faster = sum(delta < -1e-12 for delta in deltas)
    slower = sum(delta > 1e-12 for delta in deltas)
    return {
        "enabled_question_runtime": describe(enabled),
        "disabled_question_runtime": describe(disabled),
        "enabled_minus_disabled_mean_sec": mean(deltas),
        "paired_bootstrap_ci95_sec": bootstrap_ci(deltas, seed=20260822),
        "enabled_faster": faster,
        "same_to_1e_12": len(rows) - faster - slower,
        "enabled_slower": slower,
        "mean_ratio_enabled_over_disabled": mean(enabled) / mean(disabled),
        "observed_wall_time": {
            "enabled": log_wall_time("enabled"),
            "disabled": log_wall_time("disabled"),
        },
    }


def outcome_behavior(rows: list[dict[str, Any]]) -> dict[str, Any]:
    groups = {
        "enabled_wins": [row for row in rows if float(row["score_delta"]) > 1e-12],
        "ties": [row for row in rows if abs(float(row["score_delta"])) <= 1e-12],
        "disabled_wins": [row for row in rows if float(row["score_delta"]) < -1e-12],
    }
    fields = ("runtime_sec", "global_decisions", "video_runs", "observe_steps", "watch_actions")
    result: dict[str, Any] = {}
    for name, subset in groups.items():
        result[name] = {"count": len(subset)}
        for field in fields:
            result[name][f"enabled_minus_disabled_{field}"] = (
                mean(
                    float(row[f"enabled_{field}"]) - float(row[f"disabled_{field}"])
                    for row in subset
                )
                if subset
                else None
            )
    return result


def markdown_report(summary: dict[str, Any]) -> str:
    overall = summary["quality"]["overall"]
    exact = summary["quality"]["by_score_family"]["exact"]
    ccqa = summary["ccqa"]
    runtime = summary["runtime"]
    behavior = summary["agent_behavior"]
    benchmark_rows = []
    for benchmark, item in summary["quality"]["by_benchmark"].items():
        benchmark_rows.append(
            f"| {benchmark} | {item['count']} | {item['enabled_mean_score']:.3%} | "
            f"{item['disabled_mean_score']:.3%} | {item['enabled_minus_disabled']:+.3%} | "
            f"{item['enabled_wins']}/{item['ties']}/{item['disabled_wins']} |"
        )
    task_items = sorted(
        summary["quality"]["by_task"].items(),
        key=lambda pair: pair[1]["enabled_minus_disabled"],
        reverse=True,
    )
    top_rows = "\n".join(
        f"| {name} | {item['count']} | {item['enabled_mean_score']:.3%} | "
        f"{item['disabled_mean_score']:.3%} | {item['enabled_minus_disabled']:+.3%} |"
        for name, item in task_items[:8]
    )
    bottom_rows = "\n".join(
        f"| {name} | {item['count']} | {item['enabled_mean_score']:.3%} | "
        f"{item['disabled_mean_score']:.3%} | {item['enabled_minus_disabled']:+.3%} |"
        for name, item in task_items[-8:]
    )
    ccqa_inconsistent = ccqa["judge_consistency_audit"]
    ccqa_attribution = ccqa["manual_non_tie_attribution"]
    ccqa_behavior = summary["agent_behavior_by_score_family"]["ccqa_m3"]
    return f"""# 500 题 Skill ablation：M3 CCQA 评分与测评分析

> 历史实验说明：本报告评测的是 2026-08-15 条件式改写之前的两份 seed，不代表当前
> `authored-v000` SkillSet。当前 Skill 尚未由本实验验证；本报告仅保留为配对历史证据。

## 执行摘要

- 500 题全部完成且全部可评分。按每题 task score 等权平均，Skill enabled 为 **{overall['enabled_mean_score']:.3%}**，disabled 为 **{overall['disabled_mean_score']:.3%}**，enabled 低 **{abs(overall['enabled_minus_disabled']):.3%}**；逐题 bootstrap 95% CI 为 [{overall['paired_bootstrap_ci95'][0]:+.3%}, {overall['paired_bootstrap_ci95'][1]:+.3%}]，区间覆盖 0。
- CCQA 使用同一 MiniMax-M3、同一 v2 coverage/correctness rubric 评分，33/33 均成功：enabled **{ccqa['enabled']['mean_question_score']:.3%}**，disabled **{ccqa['disabled']['mean_question_score']:.3%}**，enabled 低 **{abs(ccqa['paired']['enabled_minus_disabled']):.3%}**。
- 二元 exact-match 子集共 {exact['count']} 题，enabled **{exact['enabled_mean_score']:.3%}**，disabled **{exact['disabled_mean_score']:.3%}**，差值 {exact['enabled_minus_disabled']:+.3%}；没有总体提升证据。
- Skill enabled 的平均单题运行时间为 {runtime['enabled_question_runtime']['mean']:.2f}s，disabled 为 {runtime['disabled_question_runtime']['mean']:.2f}s，enabled 慢 {runtime['enabled_minus_disabled_mean_sec']:.2f}s（{(runtime['mean_ratio_enabled_over_disabled'] - 1):+.1%}）。实际三基准顺序运行的 wall time 为 {runtime['observed_wall_time']['enabled']['total_hours']:.2f}h 对 {runtime['observed_wall_time']['disabled']['total_hours']:.2f}h。
- 这是“Global Skill + Video Skill 同时开/关”的联合消融，不能由本实验单独判断差异来自 GlobalAgent 还是 VideoAgent；需要补跑 Global-only 与 Video-only 才能做角色因果归因。

## 实验与数据完整性

- 样本：同一份确定性 500 题 ID；CrossVid 334、CVBench 83、MVU-Eval 83；覆盖 33 个任务分层。
- 推理：两组均为 Qwen3.6-27B-FP8、每 GPU 2 workers、temperature 0；enabled 固定在 GPU 6，disabled 固定在 GPU 7。
- 唯一预期策略差异是两个规划 Skill 的 enabled 状态；但 GPU/服务实例未交叉互换，且没有重复 seed，因此结论是本次运行的配对估计，不是严格无混杂的因果估计。
- CCQA Judge：MiniMax-M3，prompt `crossvid-ccqa-coverage-correctness-v2`，最大输出 2048 tokens、最多 2 次尝试；65 个判断首轮成功，1 个判断第二轮成功，最终 66/66 有效。
- 全部 1,000 个题目执行结果均为 `status=ok`；500 对均有数值分数。轨迹编号完整性问题数：{len(summary['integrity']['issues'])}。

## 总体与基准结果

| 基准 | n | Skill enabled | Skill disabled | enabled-disabled | enabled胜/平/disabled胜 |
|---|---:|---:|---:|---:|---:|
{chr(10).join(benchmark_rows)}

总分是混合 task score：exact-match、FSA interval IoU 和 CCQA M3 分数共同按题等权平均，适合比较同一 500 题上的两个条件；不应把它解释成单一统计口径下的传统准确率。

## CCQA：覆盖与正确性

| 指标 | Skill enabled | Skill disabled | enabled-disabled |
|---|---:|---:|---:|
| 题均 M3 score | {ccqa['enabled']['mean_question_score']:.3%} | {ccqa['disabled']['mean_question_score']:.3%} | {ccqa['paired']['enabled_minus_disabled']:+.3%} |
| point-weighted score | {ccqa['enabled']['point_weighted_score']:.3%} | {ccqa['disabled']['point_weighted_score']:.3%} | {ccqa['enabled']['point_weighted_score'] - ccqa['disabled']['point_weighted_score']:+.3%} |
| scoring-point coverage | {ccqa['enabled']['coverage_true']}/{ccqa['enabled']['scoring_points']} ({ccqa['enabled']['coverage_rate']:.1%}) | {ccqa['disabled']['coverage_true']}/{ccqa['disabled']['scoring_points']} ({ccqa['disabled']['coverage_rate']:.1%}) | {ccqa['enabled']['coverage_rate'] - ccqa['disabled']['coverage_rate']:+.1%} |
| scoring-point correctness | {ccqa['enabled']['correctness_true']}/{ccqa['enabled']['scoring_points']} ({ccqa['enabled']['correctness_rate']:.1%}) | {ccqa['disabled']['correctness_true']}/{ccqa['disabled']['scoring_points']} ({ccqa['disabled']['correctness_rate']:.1%}) | {ccqa['enabled']['correctness_rate'] - ccqa['disabled']['correctness_rate']:+.1%} |
| 未覆盖 points | {ccqa['enabled']['uncovered_points']} | {ccqa['disabled']['uncovered_points']} | {ccqa['enabled']['uncovered_points'] - ccqa['disabled']['uncovered_points']:+d} |
| 已覆盖但错误 points | {ccqa['enabled']['covered_but_incorrect_points']} | {ccqa['disabled']['covered_but_incorrect_points']} | {ccqa['enabled']['covered_but_incorrect_points'] - ccqa['disabled']['covered_but_incorrect_points']:+d} |

CCQA 的主要问题首先是遗漏：两组未覆盖的 scoring points 都明显多于“已覆盖但错误”的 points。disabled 的优势同时来自覆盖和正确性，而不是只靠答案更长或只靠少量事实纠错。CCQA 逐题 enabled/平/disabled 胜为 {ccqa['paired']['enabled_wins']}/{ccqa['paired']['ties']}/{ccqa['paired']['disabled_wins']}。

enabled 的 CCQA 答案平均 {ccqa['enabled']['answer_length']['mean_whitespace_words']:.1f} 个空白分词，disabled 为 {ccqa['disabled']['answer_length']['mean_whitespace_words']:.1f}，差异很小；更直接的差异是 enabled 平均少 {abs(ccqa_behavior['observe_steps']['enabled_minus_disabled']):.3f} 次 Observe、少 {abs(ccqa_behavior['video_runs']['enabled_minus_disabled']):.3f} 次 VideoAgent 运行，并快 {abs(ccqa_behavior['runtime_sec']['enabled_minus_disabled']):.2f}s。这与少覆盖 5 个 scoring points 的方向一致，说明 CCQA 退化主要和证据充分度/事实保留有关，不能简单归因于输出 token 上限。

对全部 {ccqa_attribution['reviewed']} 个 CCQA 非平局做了轨迹人工核查：{ccqa_attribution['by_primary_stage'].get('VideoAgent', 0)} 个决定性差异首先出现在 VideoAgent 证据或摘要，{ccqa_attribution['by_primary_stage'].get('GlobalAgent', 0)} 个首先出现在 GlobalAgent 的最终比较/压缩，{ccqa_attribution['by_primary_stage'].get('mixed', 0)} 个为混合或无法可靠区分。因此两个角色都有问题，CCQA 翻转样例中 VideoAgent 侧更常见。典型案例：`CCQA:87` 漏掉炸前辣酱腌制、`CCQA:366` 误识别水煮蛋，错误都已存在于 Video 报告；`CCQA:805` 和 `CCQA:808` 的 Video 报告已有关键事实，但 Global 最终答案将制备方法或 cabbage-cup 呈现差异压缩掉。

Judge 一致性审计：两组有 {ccqa_inconsistent['identical_predictions']} 道 CCQA 的最终文本完全相同，其中 {ccqa_inconsistent['identical_predictions_with_different_scores']} 道被 M3 判成不同分数。若该数大于 0，应把这部分看作单次 Judge 方差，并在最终晋升门禁中加入 judge cache 或多次复判。

## 任务分布

### enabled 相对最好（按百分点差值排序）

| 任务 | n | enabled | disabled | 差值 |
|---|---:|---:|---:|---:|
{top_rows}

### enabled 相对最差

| 任务 | n | enabled | disabled | 差值 |
|---|---:|---:|---:|---:|
{bottom_rows}

任务级 n 普遍很小，以上用于定位改进方向，不用于独立显著性结论。最可靠的判断仍是整体配对分布和预注册的大类指标。

## 用时与 Agent 行为

| 行为指标（每题均值） | enabled | disabled | 差值 |
|---|---:|---:|---:|
| Global decisions | {behavior['global_decisions']['enabled_mean']:.3f} | {behavior['global_decisions']['disabled_mean']:.3f} | {behavior['global_decisions']['enabled_minus_disabled']:+.3f} |
| analyze actions | {behavior['analyze_actions']['enabled_mean']:.3f} | {behavior['analyze_actions']['disabled_mean']:.3f} | {behavior['analyze_actions']['enabled_minus_disabled']:+.3f} |
| watch actions | {behavior['watch_actions']['enabled_mean']:.3f} | {behavior['watch_actions']['disabled_mean']:.3f} | {behavior['watch_actions']['enabled_minus_disabled']:+.3f} |
| VideoAgent runs | {behavior['video_runs']['enabled_mean']:.3f} | {behavior['video_runs']['disabled_mean']:.3f} | {behavior['video_runs']['enabled_minus_disabled']:+.3f} |
| Observe steps | {behavior['observe_steps']['enabled_mean']:.3f} | {behavior['observe_steps']['disabled_mean']:.3f} | {behavior['observe_steps']['enabled_minus_disabled']:+.3f} |

enabled 的 terminal-answer 问题数为 {behavior['terminal_answer']['enabled_questions']}，disabled 为 {behavior['terminal_answer']['disabled_questions']}；使用 watch 的问题数为 {behavior['uses_watch']['enabled_questions']} 对 {behavior['uses_watch']['disabled_questions']}。这些差异能说明 Skill 改变了执行策略，但因为 Global 与 Video Skill 同时变化，不能把最终分数差异唯一归因到某一角色。

## 结论与后续建议

1. **当前 seed Skill 不应晋升为默认优于 No-Skill 的版本。** 500 题混合分数和 CCQA 都低于 disabled，且运行更慢；总体 95% CI 覆盖 0，说明结果也不足以断言它稳定有害。
2. **先做 2×2 角色消融。** 固定同一 500 题，补跑 Global-only 与 Video-only，并将两张 GPU 对调或做两次交叉复跑，分别估计 Global Skill、Video Skill 和交互项。
3. **优先优化 CCQA 的事实覆盖。** 将 Global 指令从泛化“描述差异”改为逐 scoring-facet 的比较请求；Video Summary 必须保留所有可能改变跨视频答案的可见事实，而不是过度压缩。
4. **为 Judge 加缓存和复判门禁。** 对完全相同的 question/reference/scoring points/model output 复用同一 Judge 结果；对于晋升边界或相同输出不同判分的情况，做 3 次 M3 多数/均值复判。
5. **控制策略成本。** 对 Skill 中会增加重复 analyze/watch/observe 的规则设上限，并将“分数增益/额外视觉调用”作为联合门禁；只有证据不足或跨视频文本不可校准时才升级到 watch。

## 产物

- 机器可读汇总：`outputs/analysis/2026-08-15_skill_ablation_500/skill_ablation_500_m3_analysis.json`
- 逐题配对明细：`outputs/analysis/2026-08-15_skill_ablation_500/skill_ablation_500_m3_per_question.tsv`
- M3 评分明细：`outputs/analysis/2026-08-15_skill_ablation_500/skill_ablation_500_scored_m3/{{enabled,disabled}}/crossvid_matrix_details.jsonl`
- 本报告由 `scripts/analysis/analyze_skill_ablation_500.py` 从上述固定输入重建。
"""


def write_tsv(rows: list[dict[str, Any]]) -> None:
    fields = list(rows[0])
    with OUTPUT_TSV.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    ids = selected_ids()
    tasks = task_map()
    matrices = {run: load_matrix(run) for run in RUNS}
    rows: list[dict[str, Any]] = []
    integrity_issues: list[dict[str, str]] = []

    for benchmark, sample_id in ids:
        key = (benchmark, sample_id)
        details = {run: matrices[run].get(key) for run in RUNS}
        if any(detail is None for detail in details.values()):
            raise RuntimeError(f"Missing scored matrix row: {key}")
        metric = str(details["enabled"]["metric"])
        if metric != str(details["disabled"]["metric"]):
            raise RuntimeError(f"Metric mismatch: {key}")
        payloads = {run: result_payload(run, benchmark, sample_id) for run in RUNS}
        features: dict[str, dict[str, Any]] = {}
        for run, payload in payloads.items():
            feature, issues = trajectory_features(payload)
            features[run] = feature
            for issue in issues:
                integrity_issues.append(
                    {"run": run, "benchmark": benchmark, "sample_id": sample_id, "issue": issue}
                )
        enabled_score = float(details["enabled"]["score"])
        disabled_score = float(details["disabled"]["score"])
        enabled_prediction = str(details["enabled"].get("prediction") or "")
        disabled_prediction = str(details["disabled"].get("prediction") or "")
        task = (
            str(details["enabled"].get("task") or "Unknown")
            if benchmark == "crossvid"
            else tasks.get(key, "Unknown")
        )
        row: dict[str, Any] = {
            "benchmark": benchmark,
            "sample_id": sample_id,
            "task": task,
            "score_family": score_family(metric),
            "metric": metric,
            "enabled_score": enabled_score,
            "disabled_score": disabled_score,
            "score_delta": enabled_score - disabled_score,
            "enabled_prediction": enabled_prediction,
            "disabled_prediction": disabled_prediction,
            "same_prediction": enabled_prediction == disabled_prediction,
            "enabled_execution_status": payloads["enabled"].get("status"),
            "disabled_execution_status": payloads["disabled"].get("status"),
        }
        for run in RUNS:
            row.update({f"{run}_{name}": value for name, value in features[run].items()})
        rows.append(row)

    if len(rows) != 500:
        raise RuntimeError(f"Expected 500 paired rows, found {len(rows)}")
    if any(row["enabled_execution_status"] != "ok" or row["disabled_execution_status"] != "ok" for row in rows):
        raise RuntimeError("One or more executions were not ok")

    overall = paired_summary(rows, seed=20260814)
    by_benchmark = group_quality(rows, "benchmark", seed=20260900)
    by_task = group_quality(rows, "task", seed=20261000)
    by_score_family = group_quality(rows, "score_family", seed=20261100)
    exact_rows = [row for row in rows if row["score_family"] == "exact"]
    exact_enabled_only = sum(
        row["enabled_score"] == 1.0 and row["disabled_score"] == 0.0 for row in exact_rows
    )
    exact_disabled_only = sum(
        row["enabled_score"] == 0.0 and row["disabled_score"] == 1.0 for row in exact_rows
    )
    by_score_family["exact"]["mcnemar_exact_p"] = sign_test(
        exact_enabled_only, exact_disabled_only
    )
    by_score_family["exact"]["enabled_only_correct"] = exact_enabled_only
    by_score_family["exact"]["disabled_only_correct"] = exact_disabled_only

    summary: dict[str, Any] = {
        "generated_at_utc": "2026-08-14",
        "population": {
            "paired_questions": len(rows),
            "benchmarks": dict(Counter(row["benchmark"] for row in rows)),
            "tasks": len(set(row["task"] for row in rows)),
            "score_families": dict(Counter(row["score_family"] for row in rows)),
            "execution_status": {
                run: dict(Counter(str(row[f"{run}_execution_status"]) for row in rows))
                for run in RUNS
            },
            "same_prediction": sum(row["same_prediction"] for row in rows),
            "changed_prediction": sum(not row["same_prediction"] for row in rows),
        },
        "quality": {
            "overall": overall,
            "by_benchmark": by_benchmark,
            "by_task": by_task,
            "by_score_family": by_score_family,
        },
        "ccqa": ccqa_summary(rows, matrices),
        "runtime": runtime_summary(rows),
        "agent_behavior": feature_comparison(rows),
        "agent_behavior_by_score_family": {
            family: feature_comparison([row for row in rows if row["score_family"] == family])
            for family in sorted(set(row["score_family"] for row in rows))
        },
        "behavior_by_score_outcome": outcome_behavior(rows),
        "integrity": {
            "issues": integrity_issues,
            "matrix_rows": {
                run: sum(len(path.read_text(encoding="utf-8").splitlines()) for path in matrix_paths(run))
                for run in RUNS
            },
            "judge_metadata": matrices["enabled"][("crossvid", next(
                row["sample_id"] for row in rows if row["score_family"] == "ccqa_m3"
            ))].get("judge"),
        },
        "largest_enabled_gains": [
            {
                "benchmark": row["benchmark"],
                "sample_id": row["sample_id"],
                "task": row["task"],
                "enabled_score": row["enabled_score"],
                "disabled_score": row["disabled_score"],
                "delta": row["score_delta"],
            }
            for row in sorted(rows, key=lambda item: float(item["score_delta"]), reverse=True)[:20]
        ],
        "largest_enabled_losses": [
            {
                "benchmark": row["benchmark"],
                "sample_id": row["sample_id"],
                "task": row["task"],
                "enabled_score": row["enabled_score"],
                "disabled_score": row["disabled_score"],
                "delta": row["score_delta"],
            }
            for row in sorted(rows, key=lambda item: float(item["score_delta"]))[:20]
        ],
    }
    OUTPUT_JSON.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_tsv(rows)
    OUTPUT_REPORT.write_text(markdown_report(summary), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
