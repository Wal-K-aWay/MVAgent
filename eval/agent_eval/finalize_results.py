#!/usr/bin/env python3
"""Finalize a unified agent-eval run into a tidy benchmark_results.md report.

Reads ``summary.json`` / ``run_manifest.json`` / per-benchmark records from the
run output directory, aggregates per-benchmark and CrossVid per-task tables,
and writes ``benchmark_results.md`` plus ``score/ccqa_scores_local_judge.json``.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import yaml

from score_crossvid_ccqa import REPORT_NAME

CVBENCH_TASKS_PATH = (
    Path(__file__).resolve().parent / "metadata/CVBench.json"
)
CROSSVID_TASK_ORDER = ("BU", "NC", "CC", "PEA", "PI", "FSA", "PSS", "MSR", "MOC", "CCQA")
CVBENCH_CATEGORY_KEYS = ("Object Association", "Event Association", "Complex Reasoning")
# CVBench 官方三分类映射。
CVBENCH_TASK_CATEGORY = {
    "Cross-video Object Recognition": "Object Association",
    "Multi-video Attribute Recognition": "Object Association",
    "Joint-video Counting": "Object Association",
    "Cross-video Entity Matching": "Object Association",
    "Cross-video Anomaly Detection": "Event Association",
    "Cross-video Scene Recognition": "Event Association",
    "Multi-video Key-Action Recognition": "Event Association",
    "Cross-video Event Retrieval": "Event Association",
    "Multi-view Scene Understanding": "Complex Reasoning",
    "Multi-video Temporal Reasoning": "Complex Reasoning",
    "Joint-video Spatial Navigating": "Complex Reasoning",
    "Video Difference Caption": "Complex Reasoning",
    "Cross-video Counterfactual Reasoning": "Complex Reasoning",
    "Cross-video Procedural Transfer": "Complex Reasoning",
    "Joint-video Summarization": "Complex Reasoning",
}


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _pct(fraction: float | None) -> str:
    """Format a 0..1 fraction as a percentage string."""
    return f"{fraction * 100:.2f}" if fraction is not None else "—"


def _duration(start: str | None, finish: str | None) -> str:
    try:
        t0 = datetime.fromisoformat(start)
        t1 = datetime.fromisoformat(finish)
    except (TypeError, ValueError):
        return "—"
    minutes = int((t1 - t0).total_seconds() // 60)
    return f"{minutes // 60} 小时 {minutes % 60} 分"


def _cvbench_category_table(output_dir: Path) -> tuple[dict[str, dict], int, int]:
    """Return per-category micro stats and (correct, total) from records."""
    categories = {}
    if CVBENCH_TASKS_PATH.is_file():
        rows = _load_json(CVBENCH_TASKS_PATH)
        categories = {
            f"cvbench:{row['id']}": CVBENCH_TASK_CATEGORY.get(str(row["task_type"]), "Unknown")
            for row in rows
        }
    stats: dict[str, Counter] = defaultdict(Counter)
    correct = total = 0
    for path in sorted((output_dir / "records" / "cvbench").glob("*/result.json")):
        try:
            row = _load_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        if row.get("dataset") != "cvbench" or row.get("status") != "ok":
            continue
        total += 1
        correct += int(bool(row.get("correct")))
        category = categories.get(str(row.get("sample_id")), "Unknown")
        stats[category]["total"] += 1
        stats[category]["correct"] += int(bool(row.get("correct")))
    return stats, correct, total


def _crossvid_local_ccqa_report(output_dir: Path) -> dict:
    """Aggregate inline local-judge CCQA scores from records into score/."""
    scores = []
    for path in sorted((output_dir / "records" / "crossvid").glob("crossvid:CCQA:*/result.json")):
        try:
            row = _load_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        if row.get("status") == "ok" and row.get("score") is not None:
            scores.append(float(row["score"]))
    report = {
        "task": "CCQA",
        "scorer": "FixedOpenQAJudge local inline (qwen self-judged)",
        "total": len(scores),
        "mean_score": sum(scores) / len(scores) if scores else None,
        "strict_correct": sum(1 for s in scores if s >= 1.0),
        "score_distribution": {
            str(k): v for k, v in sorted(Counter(round(s, 2) for s in scores).items())
        },
    }
    save_path = output_dir / "score" / "ccqa_scores_local_judge.json"
    save_path.parent.mkdir(parents=True, exist_ok=True)
    save_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def _crossvid_stats_from_records(output_dir: Path) -> dict:
    """Recompute CrossVid dataset stats from per-record result.json files.

    Used when ``summary.json`` predates a merged CrossVid run (e.g. the 35B
    output where CrossVid was a separate invocation later moved under
    ``records/``).
    """
    by_task: dict[tuple[str, str], Counter] = defaultdict(Counter)
    by_family: dict[tuple[str, str], Counter] = defaultdict(Counter)
    dataset_counter: Counter = Counter()
    for path in sorted((output_dir / "records" / "crossvid").glob("*/result.json")):
        try:
            row = _load_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        if row.get("dataset") != "crossvid":
            continue
        dataset_counter["records"] += 1
        task = str(row.get("native_task") or "all")
        family = str(row.get("task_family") or "choice")
        if row.get("status") == "ok":
            dataset_counter["completed"] += 1
            score = row.get("score")
            if score is None:
                score = float(bool(row.get("correct")))
            dataset_counter["score_sum"] += float(score)
            by_task[("crossvid", task)]["completed"] += 1
            by_task[("crossvid", task)]["correct"] += float(score)
            by_family[("crossvid", family)]["completed"] += 1
            by_family[("crossvid", family)]["correct"] += float(score)
        else:
            dataset_counter["errors"] += 1

    expected = sum(1 for _ in (output_dir / "records" / "crossvid").glob("*/result.json"))
    return {
        "expected": expected,
        "completed": dataset_counter["completed"],
        "errors": dataset_counter["errors"],
        "pending": expected - dataset_counter["records"],
        "score_sum": dataset_counter["score_sum"],
        "accuracy": (
            dataset_counter["score_sum"] / dataset_counter["completed"]
            if dataset_counter["completed"]
            else None
        ),
        "by_task": {
            task: {
                "score_sum": values["correct"],
                "total": values["completed"],
                "accuracy": values["correct"] / values["completed"] if values["completed"] else None,
            }
            for (_, task), values in sorted(by_task.items())
        },
        "by_task_family": {
            family: {
                "score_sum": values["correct"],
                "total": values["completed"],
                "accuracy": values["correct"] / values["completed"] if values["completed"] else None,
            }
            for (_, family), values in sorted(by_family.items())
        },
    }


def _markdown(output_dir: Path) -> str:
    manifest = _load_json(output_dir / "run_manifest.json")
    scored_path = output_dir / "summary_scored.json"
    summary = _load_json(scored_path if scored_path.exists() else output_dir / "summary.json")
    identity = manifest.get("identity", {})
    datasets = summary["datasets"]
    if "crossvid" not in datasets and (output_dir / "records" / "crossvid").is_dir():
        datasets["crossvid"] = _crossvid_stats_from_records(output_dir)
        datasets["crossvid"]["_recomputed"] = True

    config_text = (output_dir / "input_config.yaml").read_text(encoding="utf-8")
    model_name = next(
        (v.strip() for v in re.findall(r"model_name:\s*(\S+)", config_text)), "—"
    )
    frames = next(
        (v.strip() for v in re.findall(r"max_video_frames_per_request:\s*(\d+)", config_text)),
        "—",
    )
    agents = (yaml.safe_load(config_text) or {}).get('agents', {})
    skill_states = {role: agents.get(role, {}).get('skill', {}).get('enabled')
                    for role in ('global_agent', 'video_agent')}
    skill_label = ('均禁用（no-skill）' if all(value is False for value in skill_states.values())
                   else '；'.join(f"{role}: " + ('启用' if value is True else '禁用' if value is False else '未记录')
                                  for role, value in skill_states.items()))

    lines: list[str] = []
    title_model = Path(model_name).name if model_name != "—" else "model"
    lines.append(f"# {title_model} MVAgent Benchmark 结果")
    lines.append("")
    lines.append("## 测试配置")
    lines.append("")
    lines.append("| 配置项 | 值 |")
    lines.append("|---|---|")
    lines.append(f"| 模型 | {model_name} |")
    lines.append("| Agent 系统 | MVAgent（GlobalAgent / VideoAgent Planner / Observer 同一模型） |")
    lines.append(f"| Skill | {skill_label} |")
    lines.append(f"| 视觉帧容量 | 每次视觉请求最多 {frames} 帧 |")
    prepared = {}
    events = output_dir / "execution_events.jsonl"
    if events.exists():
        with events.open() as stream:
            for line in stream:
                event = json.loads(line)
                if event.get("kind") == "batch_prepared":
                    prepared = event
    replicas = sum(len(pool) for pool in prepared.get("model_pools", {}).values())
    lines.append(f"| 最近执行的并发 | {replicas} 个模型副本；"
                 f"{prepared.get('question_workers', '未记录')} 个共享题目 worker |")
    lines.append(
        f"| 总用时 | {_duration(manifest.get('started_at_utc'), manifest.get('finished_at_utc'))} |"
    )
    lines.append("")

    lines.append("## 总览")
    lines.append("")
    lines.append("| Benchmark | 主指标 | 分数（%） | 覆盖 |")
    lines.append("|---|---|---:|---:|")

    cvbench = datasets.get("cvbench")
    cvbench_stats, cv_correct, cv_total = _cvbench_category_table(output_dir)
    mvu = datasets.get("mvu_eval")
    crossvid = datasets.get("crossvid")
    ccqa_official = None
    official_path = output_dir / "score" / REPORT_NAME
    if crossvid and official_path.is_file():
        ccqa_official = _load_json(official_path).get("official_score")

    if cvbench:
        lines.append(
            f"| CVBench | 官方评分，按 task 总体规模加权 | {_pct(cvbench['official_score'])} "
            f"| {cvbench['completed']}/{cvbench['expected']} |"
        )
    if mvu:
        lines.append(
            f"| MVU-Eval | 官方评分，按 task 总体规模加权 | {_pct(mvu['official_score'])} "
            f"| {mvu['completed']}/{mvu['expected']} |"
        )

    o_avg: float | None = None
    by_task = crossvid["by_task"] if crossvid else {}
    ccqa_display: float | None = None
    if crossvid:
        ccqa_local = by_task["CCQA"]["accuracy"] * 100
        ccqa_display = ccqa_official * 100 if ccqa_official is not None else ccqa_local
        macro_values = [
            by_task[task]["accuracy"] * 100
            for task in CROSSVID_TASK_ORDER
            if task in by_task and task != "CCQA"
        ]
        macro_values.append(ccqa_display)
        o_avg = sum(macro_values) / len(macro_values) if macro_values else None
        ccqa_label = (
            "CCQA 用本地 Qwen3-30B-A3B-Instruct-2507，官方评分协议"
            if ccqa_official is not None
            else "CCQA 暂用本地 judge 口径（官方打分未生成）"
        )
        lines.append(
            f"| CrossVid | O.Avg 十任务宏平均（{ccqa_label}） | {o_avg:.2f} "
            f"| {crossvid['completed']}/{crossvid['expected']} |"
        )
    lines.append("")

    if cvbench:
        lines.append("## CVBench")
        lines.append("")
        header = " | ".join(CVBENCH_CATEGORY_KEYS + ("Overall（严格字母）", "正确数", "覆盖"))
        lines.append(f"| {header} |")
        lines.append("|" + "---:|" * (len(CVBENCH_CATEGORY_KEYS) + 3))
        category_values = " | ".join(
            _pct(
                cvbench_stats[key]["correct"] / cvbench_stats[key]["total"]
                if cvbench_stats.get(key, {}).get("total")
                else None
            )
            for key in CVBENCH_CATEGORY_KEYS
        )
        lines.append(
            f"| {category_values} | {_pct(cvbench['accuracy'])} | {cv_correct} "
            f"| {cv_total}/{cvbench['expected']} |"
        )
        lines.append("")
        lines.append("| 官方任务 | 正确数/总数 | Accuracy |")
        lines.append("|---|---:|---:|")
        for task, stat in sorted(cvbench["by_task"].items()):
            lines.append(
                f"| {task} | {stat['score_sum']:.0f}/{stat['total']} "
                f"| {_pct(stat['accuracy'])}% |"
            )
        lines.append("")

    if mvu:
        lines.append("## MVU-Eval")
        lines.append("")
        tasks = sorted(mvu["by_task"])
        lines.append("| Overall | " + " | ".join(tasks) + " | 覆盖 |")
        lines.append("|" + "---:|" * (len(tasks) + 2))
        lines.append(
            f"| {_pct(mvu['accuracy'])} | "
            + " | ".join(_pct(mvu["by_task"][t]["accuracy"]) for t in tasks)
            + f" | {mvu['completed']}/{mvu['expected']} |"
        )
        lines.append("")

    if crossvid:
        lines.append("## CrossVid")
        lines.append("")
        header = " | ".join(CROSSVID_TASK_ORDER)
        values = " | ".join(
            f"{ccqa_display:.2f}" if task == "CCQA" else _pct(by_task[task]["accuracy"])
            for task in CROSSVID_TASK_ORDER
        )
        counts = " | ".join(str(by_task[task]["total"]) for task in CROSSVID_TASK_ORDER)
        lines.append(f"| Task | {header} |")
        lines.append("|---|" + "---:|" * len(CROSSVID_TASK_ORDER))
        lines.append(f"| 分数（%） | {values} |")
        lines.append(f"| 样例数 | {counts} |")
        lines.append("")

        def _macro(task_names: tuple[str, ...]) -> str:
            values_ = [
                ccqa_display / 100 if task == "CCQA" else by_task[task]["accuracy"]
                for task in task_names
            ]
            return _pct(sum(values_) / len(values_))

        c_avg = _macro(("BU", "NC", "CC", "PEA"))
        t_avg = _macro(("PI", "FSA", "PSS"))
        m_avg = _macro(("MSR", "MOC"))
        lines.append("| #Frames | O.Avg | C.Avg | T.Avg | M.Avg（严格） | CCQA |")
        lines.append("|---:|---:|---:|---:|---:|---:|")
        lines.append(f"| {frames} | {o_avg:.2f} | {c_avg} | {t_avg} | {m_avg} | {ccqa_display:.2f} |")
        lines.append("")
        family = crossvid.get("by_task_family", {})
        if family:
            fam_items = []
            for name in ("choice", "ordering", "open_qa", "temporal"):
                stat = family.get(name)
                if stat:
                    value = ccqa_display if name == "open_qa" else stat["accuracy"] * 100
                    fam_items.append(f"{name} {value:.2f}（{stat['total']}）")
            lines.append("按题型家族：" + " ｜ ".join(fam_items) + "。")
            lines.append("")

    lines.append("## 数据完整性")
    lines.append("")
    for name in ("cvbench", "mvu_eval", "crossvid"):
        stat = datasets.get(name)
        if stat:
            lines.append(
                f"- {name}: {stat['completed']}/{stat['expected']} 完成，"
                f"{stat['errors']} 错误，{stat['pending']} 待跑。"
            )
    sub_manifest_path = output_dir / "crossvid_run" / "run_manifest.json"
    if sub_manifest_path.is_file():
        sub_manifest = _load_json(sub_manifest_path)
        lines.append(
            f"- CrossVid 记录来自独立子运行"
            f"（{_duration(sub_manifest.get('started_at_utc'), sub_manifest.get('finished_at_utc'))}，"
            f"详见 crossvid_run/run_manifest.json）。"
        )
    lines.append("")
    return "\n".join(lines) + "\n"


def _merge_deferred_judge(output_dir: Path, summary: dict) -> dict:
    """Join separately judged answers without modifying frozen inference records."""
    judge_path = output_dir / "score" / REPORT_NAME
    judge = _load_json(judge_path)
    rows = judge["samples"]
    pending = [row for path in (output_dir / "records/crossvid").glob("crossvid:CCQA:*/result.json")
               if (row := _load_json(path)).get("status") == "ok" and row.get("scoring_status") == "deferred"]
    expected = {int(row["sample_id"].rsplit(":", 1)[1]): row for row in pending}
    assert len(rows) == len(expected) == summary["total_deferred"]
    assert len({row["id"] for row in rows}) == len(rows)
    assert {row["id"] for row in rows} == set(expected)
    scores = []
    points = earned = 0
    for row in rows:
        original = expected[row["id"]]
        assert row["status"] == "ok" and row["prediction"] == original["prediction"]
        n = len(original["ground_truth"])
        coverage, correctness = row["coverage"], row["correctness"]
        assert n > 0 and len(coverage) == len(correctness) == n
        assert all(type(x) is bool for x in coverage + correctness)
        assert all(not b or a for a, b in zip(coverage, correctness))
        value = sum(coverage) + sum(correctness)
        assert value == row["score"]
        scores.append(value / (2 * n))
        earned += value
        points += 2 * n
    assert abs(earned / points - judge["official_score"]) < 1e-12
    crossvid = summary["datasets"]["crossvid"]
    stat = {"score_sum": sum(scores), "total": len(scores), "accuracy": earned / points,
            "aggregation": "scoring-point weighted", "question_mean": sum(scores) / len(scores)}
    crossvid["by_task"]["CCQA"] = stat
    crossvid["by_task_family"]["open_qa"] = stat
    crossvid["completed"] += len(scores)
    crossvid["deferred"] = 0
    crossvid["score_sum"] += sum(scores)
    crossvid["accuracy"] = crossvid["score_sum"] / crossvid["expected"]
    crossvid["scored_subset_accuracy"] = crossvid["accuracy"]
    crossvid["official_task_macro"] = sum(crossvid["by_task"][t]["accuracy"] for t in CROSSVID_TASK_ORDER) / 10
    crossvid["official_score"] = crossvid["official_task_macro"]
    summary["total_completed"] += len(scores)
    summary["total_deferred"] = 0
    summary["score_complete"] = True
    summary["external_judge"] = {"path": str(judge_path), "requested_model": judge["judge"]["model"],
                                "updated_at_utc": judge["updated_at_utc"]}
    summary["scoring_note"] = "CCQA uses external Judge; raw inference summary and records retain deferred status. CrossVid primary metric is official_task_macro, not question-weighted accuracy."
    return summary


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="Agent-eval run output dir")
    return parser


def main() -> None:
    args = _parser().parse_args()
    output_dir = args.output.expanduser().resolve()
    if not (output_dir / "summary.json").is_file():
        raise SystemExit(f"summary.json not found under {output_dir}")
    summary = _load_json(output_dir / "summary.json")
    if summary.get("total_deferred"):
        summary = _merge_deferred_judge(output_dir, summary)
        (output_dir / "summary_scored.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    elif (output_dir / "records" / "crossvid").is_dir():
        _crossvid_local_ccqa_report(output_dir)
    report = _markdown(output_dir)
    save_path = output_dir / "benchmark_results.md"
    save_path.write_text(report, encoding="utf-8")
    print(f"[DONE] saved={save_path}")


if __name__ == "__main__":
    main()
