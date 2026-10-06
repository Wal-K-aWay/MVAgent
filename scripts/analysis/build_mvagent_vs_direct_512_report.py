#!/usr/bin/env python3
"""Build the canonical portable-report artifact for the MVAgent comparison."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "outputs" / "analysis" / "2026-08-24_mvagent_vs_direct_512"
SUMMARY_PATH = DATA_DIR / "summary.json"
ARTIFACT_PATH = DATA_DIR / "artifact.json"


def pct(value: float) -> str:
    return f"{value * 100:+.1f}%"


def main() -> None:
    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    benchmarks = summary["by_benchmark"]
    quality = summary["data_quality"]
    latency = summary["latency"]

    benchmark_rows = [
        {
            "benchmark": "CVBench",
            "n": benchmarks["cvbench"]["n"],
            "mvagent": benchmarks["cvbench"]["agent_score"],
            "direct": benchmarks["cvbench"]["direct_score"],
            "delta": benchmarks["cvbench"]["delta"],
            "ci_low": benchmarks["cvbench"]["delta_ci95_low"],
            "ci_high": benchmarks["cvbench"]["delta_ci95_high"],
            "evidence": "显著（McNemar p=0.024）",
            "latency_ratio": latency["cvbench"]["mean_latency_ratio"],
        },
        {
            "benchmark": "MVU-Eval（论文解析）",
            "n": benchmarks["mvu_eval_paper_parser"]["n"],
            "mvagent": benchmarks["mvu_eval_paper_parser"]["agent_score"],
            "direct": benchmarks["mvu_eval_paper_parser"]["direct_score"],
            "delta": benchmarks["mvu_eval_paper_parser"]["delta"],
            "ci_low": benchmarks["mvu_eval_paper_parser"]["delta_ci95_low"],
            "ci_high": benchmarks["mvu_eval_paper_parser"]["delta_ci95_high"],
            "evidence": "不显著（McNemar p=0.519）",
            "latency_ratio": latency["mvu_eval"]["mean_latency_ratio"],
        },
        {
            "benchmark": "CrossVid（官方 O.Avg）",
            "n": benchmarks["crossvid_official_oavg"]["n"],
            "mvagent": benchmarks["crossvid_official_oavg"]["agent_score"],
            "direct": benchmarks["crossvid_official_oavg"]["direct_score"],
            "delta": benchmarks["crossvid_official_oavg"]["delta"],
            "ci_low": benchmarks["crossvid_official_oavg"]["delta_ci95_low"],
            "ci_high": benchmarks["crossvid_official_oavg"]["delta_ci95_high"],
            "evidence": "方向为正，95% CI 跨 0",
            "latency_ratio": None,
        },
    ]

    task_rows = []
    for row in summary["by_task"]:
        task_rows.append(
            {
                **row,
                "direction": "MVAgent 更好" if row["delta"] > 0 else (
                    "端到端更好" if row["delta"] < 0 else "持平"
                ),
            }
        )
    crossvid_rows = [row for row in task_rows if row["benchmark"] == "crossvid"]
    crossvid_rows.sort(key=lambda row: row["delta"], reverse=True)

    routing_rows = []
    labels = {"cvbench": "CVBench", "mvu-eval": "MVU-Eval", "crossvid": "CrossVid"}
    for key, row in summary["task_router_upper_bound"].items():
        routing_rows.append(
            {
                "benchmark": labels[key],
                "best_fixed": max(row["agent_task_macro"], row["direct_task_macro"]),
                "oracle_router": row["oracle_task_router_score"],
                "uplift": row["oracle_uplift_vs_best_fixed_method"],
            }
        )

    source_id = "matched_comparison_summary"
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    title = "MVAgent 相比端到端是否有优势"
    artifact = {
        "surface": "report",
        "manifest": {
            "version": 1,
            "surface": "report",
            "title": title,
            "description": "同模型、同题目的 MVAgent 与 512 帧端到端推理对照分析。",
            "generatedAt": generated_at,
            "filters": [],
            "cards": [],
            "charts": [
                {
                    "id": "crossvid_task_delta",
                    "title": "CrossVid 各任务：MVAgent 相对端到端的分数差",
                    "subtitle": "正值代表 MVAgent 更好；CCQA 已用同一 MiniMax-M3 官方打分流程重评。",
                    "type": "bar",
                    "dataset": "crossvid_tasks",
                    "sourceId": source_id,
                    "valueFormat": "percent",
                    "encodings": {
                        "x": {"field": "task", "type": "nominal", "label": "任务"},
                        "y": {"field": "delta", "type": "quantitative", "label": "MVAgent − 端到端"},
                        "color": {"field": "direction", "type": "nominal", "label": "优势方向"},
                        "tooltip": [
                            {"field": "agent_score", "type": "quantitative", "label": "MVAgent", "format": "percent"},
                            {"field": "direct_score", "type": "quantitative", "label": "端到端", "format": "percent"},
                            {"field": "n", "type": "quantitative", "label": "样本数"},
                        ],
                    },
                }
            ],
            "tables": [
                {
                    "id": "benchmark_overview",
                    "title": "三项 benchmark 总体结果",
                    "subtitle": "95% CI 为配对 bootstrap；CVBench/MVU-Eval 同时给出精确 McNemar 检验。",
                    "dataset": "benchmark_overview",
                    "sourceId": source_id,
                    "defaultSort": {"field": "delta", "direction": "desc"},
                    "columns": [
                        {"field": "benchmark", "label": "Benchmark", "type": "text"},
                        {"field": "n", "label": "n", "format": "integer"},
                        {"field": "mvagent", "label": "MVAgent", "format": "percent"},
                        {"field": "direct", "label": "端到端", "format": "percent"},
                        {"field": "delta", "label": "差值", "format": "percent", "movement": True},
                        {"field": "ci_low", "label": "95% CI 下界", "format": "percent"},
                        {"field": "ci_high", "label": "95% CI 上界", "format": "percent"},
                        {"field": "evidence", "label": "证据强度", "type": "text"},
                        {"field": "latency_ratio", "label": "平均延迟倍数", "format": "number"},
                    ],
                },
                {
                    "id": "crossvid_detail",
                    "title": "CrossVid 任务明细",
                    "subtitle": "官方 O.Avg 是十个任务分数的宏平均。",
                    "dataset": "crossvid_tasks",
                    "sourceId": source_id,
                    "defaultSort": {"field": "delta", "direction": "desc"},
                    "columns": [
                        {"field": "task", "label": "任务", "type": "text"},
                        {"field": "n", "label": "n", "format": "integer"},
                        {"field": "agent_score", "label": "MVAgent", "format": "percent"},
                        {"field": "direct_score", "label": "端到端", "format": "percent"},
                        {"field": "delta", "label": "差值", "format": "percent", "movement": True},
                        {"field": "delta_ci95_low", "label": "95% CI 下界", "format": "percent"},
                        {"field": "delta_ci95_high", "label": "95% CI 上界", "format": "percent"},
                    ],
                },
                {
                    "id": "routing_upper_bound",
                    "title": "按任务路由的样本内上界",
                    "subtitle": "这是用当前样本事后选择较优方法的乐观上界，不是已验证策略。",
                    "dataset": "routing_upper_bound",
                    "sourceId": source_id,
                    "defaultSort": {"field": "uplift", "direction": "desc"},
                    "columns": [
                        {"field": "benchmark", "label": "Benchmark", "type": "text"},
                        {"field": "best_fixed", "label": "最佳固定方法", "format": "percent"},
                        {"field": "oracle_router", "label": "事后路由", "format": "percent"},
                        {"field": "uplift", "label": "潜在增益", "format": "percent", "movement": True},
                    ],
                },
            ],
            "sources": [
                {
                    "id": source_id,
                    "label": "配对复算汇总",
                    "path": "outputs/analysis/2026-08-24_mvagent_vs_direct_512/summary.json",
                }
            ],
            "blocks": [
                {"id": "title", "type": "markdown", "body": f"# {title}"},
                {
                    "id": "executive_summary",
                    "type": "markdown",
                    "sourceId": source_id,
                    "body": (
                        "## Executive Summary\n\n"
                        "**有优势，但只在部分题型成立，不应把 MVAgent 作为所有问题的默认路径。** "
                        "CVBench 提升 **+8.0 个百分点**，配对检验支持真实优势；CrossVid 官方 O.Avg 提升 "
                        "**+3.8 个百分点**，但 95% CI 略跨 0；MVU-Eval 只提升 **+2.4 个百分点**，不显著。\n\n"
                        "收益主要来自时序定位、动作顺序和跨视频空间推理；自由回答 CCQA 则下降 **19.9 个百分点**。"
                        "同时，MVAgent 在 CVBench/MVU-Eval 的平均延迟约为端到端的 **4.0×/2.6×**，且视觉计算预算更高。"
                    ),
                },
                {
                    "id": "overview_heading",
                    "type": "markdown",
                    "body": "## 总体判断：CVBench 明确受益，其他两项证据有限",
                },
                {"id": "overview_table", "type": "table", "tableId": "benchmark_overview"},
                {
                    "id": "crossvid_heading",
                    "type": "markdown",
                    "sourceId": source_id,
                    "body": (
                        "## CrossVid：增益高度集中，CCQA 明显退化\n\n"
                        "PSS、FSA 两类定位/顺序任务分别提升 **+57.5** 和 **+16.8 个百分点**；"
                        "使用相同 MiniMax-M3 官方 SCORE 流程重评后，CCQA 从端到端的 **52.9%** 降到 "
                        "MVAgent 的 **33.0%**。这说明中间摘要有助于定位，但可能丢失自由回答所需的评分点。"
                    ),
                },
                {"id": "crossvid_chart", "type": "chart", "chartId": "crossvid_task_delta"},
                {"id": "crossvid_table", "type": "table", "tableId": "crossvid_detail"},
                {
                    "id": "mvu_heading",
                    "type": "markdown",
                    "sourceId": source_id,
                    "body": (
                        "## MVU-Eval：旧结果中的大幅优势没有保留\n\n"
                        "在修正后的 512 帧端到端基线下，论文兼容解析口径仅提升 **+2.4 个百分点**，"
                        "95% CI 为 **−3.6 到 +8.4 个百分点**。旧对比里约 20 个百分点的优势主要来自"
                        "端到端输出格式/解析问题，而不是稳定的推理能力差异。"
                    ),
                },
                {
                    "id": "routing_heading",
                    "type": "markdown",
                    "sourceId": source_id,
                    "body": (
                        "## 建议按题型路由，而不是全量启用\n\n"
                        "优先把 MVAgent 用于需要反复观察的时序定位、动作先后、长视频证据搜寻和空间导航；"
                        "CCQA、属性识别及简单检索/比较优先走端到端。按当前样本事后选择方法，三个 benchmark "
                        "仍有 **3.3–5.3 个百分点**的理论提升空间，但必须在独立样本上验证。"
                    ),
                },
                {"id": "routing_table", "type": "table", "tableId": "routing_upper_bound"},
                {
                    "id": "next_steps",
                    "type": "markdown",
                    "body": (
                        "## Recommended next steps\n\n"
                        "1. 做一次等计算量 A/B：同一代码快照、同一提示词、同一总帧数与请求次数，隔离 Agent 架构本身的贡献。\n"
                        "2. 用独立验证集训练/冻结题型路由规则，再在完整测试集一次性评估，避免事后选择偏差。\n"
                        "3. 针对 CCQA 改造 VideoAgent 汇总：保留评分点、实体和因果细节，再单独复测自由回答。\n"
                        "4. 同时记录视觉请求次数、总输入帧数、token、GPU 秒和墙钟时间，形成质量—成本前沿。"
                    ),
                },
                {
                    "id": "questions",
                    "type": "markdown",
                    "body": (
                        "## Further questions\n\n"
                        "- PSS 的巨大增益是否来自端到端提示词/解析缺陷，还是确实需要迭代观察？\n"
                        "- 在总视觉帧数受限为 512 时，CVBench 的 +8.0 个百分点还能保留多少？\n"
                        "- CCQA 的损失发生在观察阶段、VideoAgent 摘要阶段，还是 GlobalAgent 最终回答阶段？"
                    ),
                },
                {
                    "id": "caveats",
                    "type": "markdown",
                    "sourceId": source_id,
                    "body": (
                        "## Caveats and assumptions\n\n"
                        f"- 数据质量状态：`{quality['status']}`；三组题目均完整配对，无缺失结果。\n"
                        "- 两边模型和题目 ID 相同，但**总视觉计算量不相同**：端到端每题总计 512 帧，MVAgent 可发起多次、每次最多 512 帧的视觉请求。\n"
                        "- 两批运行来自不同代码/提示词快照，因而结论是系统级比较，不是严格等预算的架构因果效应。\n"
                        "- CrossVid 以官方任务宏平均 O.Avg 为主指标；按题目微平均会被 FSA/PSS 的样本量主导。\n"
                        "- 多个细分任务样本量较小；未做跨全部任务的多重检验校正。延迟也受并发拓扑影响。"
                    ),
                },
            ],
        },
        "snapshot": {
            "version": 1,
            "generatedAt": generated_at,
            "status": "ready",
            "datasets": {
                "benchmark_overview": benchmark_rows,
                "crossvid_tasks": crossvid_rows,
                "routing_upper_bound": routing_rows,
            },
            "accessIssues": [],
        },
        "sources": [
            {
                "id": source_id,
                "path": "outputs/analysis/2026-08-24_mvagent_vs_direct_512/summary.json",
                "query": {
                    "engine": "duckdb",
                    "sql": (
                        "SELECT * FROM read_json_auto("
                        "'outputs/analysis/2026-08-24_mvagent_vs_direct_512/summary.json')"
                    ),
                    "description": "Reads paired question-level predictions, recomputes benchmark/task scores, paired bootstrap intervals, exact tests, latency, and the matched CCQA M3 score.",
                    "tables_used": [
                        "outputs/demo_test_1500_eval_gpu67_current_20260810_01",
                        "outputs/full_3benchmark_end_to_end_512_20260821",
                        "outputs/analysis/2026-08-24_mvagent_vs_direct_512/mvagent_ccqa_score_m3.json",
                    ],
                    "executed_at": generated_at,
                },
            }
        ],
    }
    ARTIFACT_PATH.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Wrote {ARTIFACT_PATH.relative_to(ROOT)}")
    print(
        "Headline deltas:",
        pct(benchmarks["cvbench"]["delta"]),
        pct(benchmarks["mvu_eval_paper_parser"]["delta"]),
        pct(benchmarks["crossvid_official_oavg"]["delta"]),
    )


if __name__ == "__main__":
    main()
