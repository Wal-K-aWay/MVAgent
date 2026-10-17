#!/usr/bin/env python3
"""Summarize saved FP8/BF16 probe records on Modal; no model calls."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics


def load(path):
    return json.loads(path.read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    root = args.output
    manifest = load(root / "manifest.json")
    expected_cells = 2 * len(manifest["arguments"]["models"])
    matrix = load(root / "summary.json") if (root / "summary.json").exists() else {}
    cells, records = {}, {}
    for directory in sorted(root.iterdir()):
        if not directory.is_dir() or not (directory / "records.jsonl").exists():
            continue
        # Only complete lines are durable records when summarizing a still-running probe.
        lines = (directory / "records.jsonl").read_text().splitlines(keepends=True)
        data = [json.loads(line) for line in lines if line.endswith("\n") and line.strip()]
        data = [row for row in data if not row["warmup"]]
        records[directory.name] = data
        if (directory / "summary.json").exists():
            cells[directory.name] = load(directory / "summary.json")
    comparisons = []
    for model in manifest["arguments"]["models"]:
        bf_key, fp_key = model + "_bf16", model + "_fp8"
        bf, fp = cells.get(bf_key, {}), cells.get(fp_key, {})
        for case in sorted(set(bf) | set(fp)):
            if case not in bf or case not in fp:
                continue
            b_rows = [row for row in records[bf_key] if row["case"] == case]
            f_rows = [row for row in records[fp_key] if row["case"] == case]
            request_hashes = {r["request_sha256"] for r in b_rows + f_rows}
            prompt_hashes = {r["prompt_token_ids_sha256"] for r in b_rows + f_rows}
            same_length = len({r["output_tokens"] for r in b_rows + f_rows}) == 1
            comparable = len(request_hashes) == 1 and len(prompt_hashes) == 1 and same_length
            row = {"model": model, "case": case, "comparable": comparable,
                   "request_bytes_identical": len(request_hashes) == 1,
                   "prompt_token_ids_identical": len(prompt_hashes) == 1,
                   "output_lengths_identical": same_length, "bf16": bf[case], "fp8": fp[case],
                   "bf16_fp8_first_output_equal": b_rows[0]["token_ids"] == f_rows[0]["token_ids"]}
            if comparable:
                row["total_latency_speedup"] = bf[case]["seconds_median"] / fp[case]["seconds_median"]
                row["ttft_speedup"] = bf[case]["ttft_seconds_median"] / fp[case]["ttft_seconds_median"]
                row["decode_speedup"] = fp[case]["decode_tokens_per_second_median"] / bf[case]["decode_tokens_per_second_median"]
            for precision, rows in [("bf16", b_rows), ("fp8", f_rows)]:
                timings = [r["seconds"] for r in rows]
                row[precision]["latency_cv"] = statistics.pstdev(timings) / statistics.mean(timings)
            comparisons.append(row)
    stability = {key: {case: {field: values[field] for field in [
        "samples", "unique_outputs", "unique_outputs_including_warmup", "warmup_matches_measured_first"]}
        for case, values in cases.items()} for key, cases in cells.items()}
    result = {"manifest": manifest, "matrix_status": matrix, "comparisons": comparisons,
              "stability": stability,
              "valid_samples": sum(len(rows) for rows in records.values()),
              "complete_cells": sum((root / key / "complete.json").exists() for key in cells),
              "failed_cells": {key: value["error"] for key, value in matrix.items() if value["status"] == "failed"}}
    (root / "comparison.json").write_text(json.dumps(result, indent=2) + "\n")
    lines = ["# Qwen3.5 FP8/BF16：8×H100、TP=8、DP=1", "",
             f"结果目录：`{root}`。有效测量 {result['valid_samples']} 次，成功配置 {result['complete_cells']}/{expected_cells}，失败配置 {len(result['failed_cells'])}。", "",
             "协议：单请求并发、greedy、seed=0、thinking 关闭；prefix cache 和 multimodal processor cache 关闭。",
             f"帧最长边 448；固定生成 {manifest['arguments']['output_tokens']} token（min_tokens + ignore_eos），"
             f"每个输入预热一次后测量 {manifest['arguments']['repeats']} 次。",
             "时间不包含权重加载与视频解码；包含请求传输、模型图像预处理、视觉编码、prefill 和 decode。", "",
             "9B FP8 来源为社区 lovedheart；27B 与 35B-A3B FP8 为官方 Qwen。", "",
             f"环境：{manifest['versions']}；TP={manifest['tp']}、DP={manifest['dp']}、并发={manifest['concurrency']}。",
             f"源码 commit：`{manifest['git_commit']}`；实际执行脚本 SHA256：`{manifest['script_sha256']}`。",
             "执行脚本已冻结为 `benchmark_source.py`，完整参数在 `manifest.json`，每个配置的启动命令与权重来源在其 `config.json`。", "",
             "| 配置 | 状态 | 有效样本 |", "|---|---|---:|"]
    for model in manifest["arguments"]["models"]:
        for precision in ["bf16", "fp8"]:
            key = model + "_" + precision
            lines.append(f"| {key} | {matrix.get(key, {}).get('status', 'pending')} | {len(records.get(key, []))} |")
    lines += ["", "| 模型 | 输入 | BF16 延时 s | FP8 延时 s | 总延时加速 | BF16/FP8 TTFT s | BF16/FP8 decode tok/s | BF16/FP8 唯一输出数 |",
              "|---|---|---:|---:|---:|---|---|---|"]
    for row in comparisons:
        b, f = row["bf16"], row["fp8"]
        speed = f"{row['total_latency_speedup']:.3f}×" if row["comparable"] else "输入不一致，不能比较"
        lines.append(f"| {row['model']} | {row['case']} | {b['seconds_median']:.3f} | {f['seconds_median']:.3f} | {speed} | "
                     f"{b['ttft_seconds_median']:.3f} / {f['ttft_seconds_median']:.3f} | "
                     f"{b['decode_tokens_per_second_median']:.2f} / {f['decode_tokens_per_second_median']:.2f} | "
                     f"{b['unique_outputs']} / {f['unique_outputs']} |")
    lines += ["", "总延时加速 = BF16 延时 / FP8 延时；小于 1 表示 FP8 更慢。表中延时和速度均取预热后的中位数。", "",
              "## 延时波动", "",
              "CV = 标准差 / 平均值；范围与 CV 均只描述本轮样本，不是置信区间。", "",
              "| 模型 | 输入 | BF16/FP8 样本数 | BF16 范围 s | FP8 范围 s | BF16/FP8 CV | 输入可比 |",
              "|---|---|---:|---|---|---|---|"]
    for row in comparisons:
        b, f = row["bf16"], row["fp8"]
        lines.append(f"| {row['model']} | {row['case']} | {b['samples']} / {f['samples']} | "
                     f"{b['seconds_min']:.3f}–{b['seconds_max']:.3f} | "
                     f"{f['seconds_min']:.3f}–{f['seconds_max']:.3f} | "
                     f"{b['latency_cv']:.1%} / {f['latency_cv']:.1%} | {row['comparable']} |")
    unpaired = [(key, case, values) for key, cases in cells.items() for case, values in cases.items()
                if not any(row["model"] + "_bf16" == key or row["model"] + "_fp8" == key
                           for row in comparisons if row["case"] == case)]
    if unpaired:
        lines += ["", "## 尚无配对的有效测量", "",
                  "| 配置 | 输入 | 样本 | 延时中位数 s | TTFT s | decode tok/s | 唯一输出数 |",
                  "|---|---|---:|---:|---:|---:|---:|"]
        for key, case, values in unpaired:
            lines.append(f"| {key} | {case} | {values['samples']} | {values['seconds_median']:.3f} | "
                         f"{values['ttft_seconds_median']:.3f} | {values['decode_tokens_per_second_median']:.2f} | "
                         f"{values['unique_outputs']} |")
    measured_cases = [case for cases in stability.values() for case in cases.values()]
    stable_cases = sum(case["unique_outputs"] == 1 for case in measured_cases)
    warmup_matches = sum(case["warmup_matches_measured_first"] for case in measured_cases)
    lines += ["", "## 重复性与限制", "",
              f"已有测量的模型/精度/输入组合 {len(measured_cases)} 组，其中 {stable_cases} 组所有正式测量的输出完全一致；"
              f"{warmup_matches} 组预热输出也与正式测量一致。",
              "唯一输出数以完整生成 token ID 序列计，1 表示该输入在测量重复中全部一致；预热比较另记录于 JSON。",
              "有限重复一致不能证明任意输入、跨重启、不同硬件或并发负载下都确定；FP8 与 BF16 的答案也不要求相同。",
              "本实验是速度与重复性探针，未评估任务准确率，不能推断量化对准确率无影响。", ""]
    for key, value in matrix.items():
        if value["status"] == "failed":
            lines += [f"- 未完成配置 `{key}`：{value['error']}"]
    (root / "report.md").write_text("\n".join(lines) + "\n")
    print(json.dumps({"valid_samples": result["valid_samples"], "complete_cells": result["complete_cells"],
                      "failed_cells": result["failed_cells"], "paired_cases": len(comparisons)}))


if __name__ == "__main__":
    main()
