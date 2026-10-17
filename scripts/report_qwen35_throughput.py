#!/usr/bin/env python3
"""Read completed throughput experiments on Modal and write a consolidated report."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import statistics


def read(path):
    return json.loads(path.read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--roots", type=Path, nargs="+", required=True)
    parser.add_argument("--confirmation", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not str(args.output).startswith("/runs/"):
        raise SystemExit("Raw analysis belongs on the runs volume")
    args.output.mkdir(parents=True, exist_ok=True)
    records_total = warmups_total = 0
    candidates, problems = [], []
    request_hashes, prompt_hashes, output_lengths = {}, {}, set()
    manifests = sorted({p for root in args.roots for p in root.rglob("manifest.json")})
    for manifest_path in manifests:
        root, manifest = manifest_path.parent, read(manifest_path)
        if "arguments" not in manifest or "passes" not in manifest["arguments"]:
            continue
        expected_passes = manifest["arguments"]["passes"]
        for directory in sorted(root.iterdir()):
            summary_path = directory / "summary.json"
            if not directory.is_dir() or not summary_path.exists():
                continue
            layout = read(summary_path)
            if "passes" not in layout:
                continue
            if layout.get("error") or layout.get("status", "").startswith("unstable_serial"):
                problems.append({"path": str(directory), "status": layout.get("status"), "error": layout.get("error"),
                                 "warmup_mismatches": sum(len(p["mismatches"]) for p in layout["passes"] if p["phase"] == "warmup")})
            rows_path = directory / "records.jsonl"
            rows = [json.loads(line) for line in rows_path.read_text().splitlines()] if rows_path.exists() else []
            warmups_total += sum(row["phase"] == "warmup" for row in rows)
            rows = [row for row in rows if row["phase"] == "screen"]
            records_total += len(rows)
            for row in rows:
                request_hashes.setdefault(row["case"], set()).add(row["request_sha256"])
                prompt_hashes.setdefault(row["case"], set()).add(row["prompt_token_ids_sha256"])
                output_lengths.add(row["output_tokens"])
            for concurrency in sorted({p["per_replica_concurrency"] for p in layout["passes"] if p["phase"] == "screen"}):
                passes = [p for p in layout["passes"] if p["phase"] == "screen" and p["per_replica_concurrency"] == concurrency]
                stable = len(passes) == expected_passes and all(p["stable"] for p in passes)
                selected_names = {p["name"] for p in passes}
                subset = [row for row in rows if row["pass"] in selected_names]
                case_stats = {}
                for name in sorted({r["case"] for r in subset}):
                    timings = [r["seconds"] for r in subset if r["case"] == name]
                    case_stats[name] = {"samples": len(timings), "median_seconds": statistics.median(timings),
                                        "cv": statistics.pstdev(timings) / statistics.mean(timings)}
                candidates.append({"path": str(directory), "layout": layout["layout"], "precision": layout["precision"],
                    "tp": layout["tp"], "replicas": layout["replicas"], "invariant": layout["invariant"],
                    "encoder_mode": layout["encoder_mode"], "batched_tokens": layout["batched_tokens"],
                    "concurrency_per_replica": concurrency, "samples": len(subset), "stable": stable,
                    "mismatches": sum(len(p["mismatches"]) for p in passes),
                    "requests_per_minute": len(subset) * 60 / sum(p["seconds"] for p in passes), "cases": case_stats})
    comparable = (all(len(v) == 1 for v in request_hashes.values()) and
                  all(len(v) == 1 for v in prompt_hashes.values()) and output_lengths == {256})
    eligible = sorted((c for c in candidates if c["stable"]), key=lambda c: c["requests_per_minute"], reverse=True)
    confirmed = read(args.confirmation / "summary.json") if args.confirmation else None
    result = {"formal_samples": records_total, "warmup_samples": warmups_total, "comparable": comparable,
              "candidates": candidates, "eligible_ranked": eligible, "problems": problems, "confirmation": confirmed,
              "sources": [str(p.parent) for p in manifests]}
    (args.output / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    lines = ["# Qwen3.5-35B-A3B：可复现吞吐测试", "",
             f"初筛正式请求 {records_total} 次，冒烟/预热 {warmups_total} 次；跨配置输入与固定输出长度可比：{comparable}。",
             "硬件为同一台 8×H100 80GB，vLLM 0.19.1；每个副本 DP=1。OMP/MKL/OpenBLAS 线程数均显式设为 1。",
             "KV cache 开启并使用 BF16；跨请求 prefix caching 与 MM processor cache 关闭。",
             "初筛使用文本和 32/128/512 帧（最长边 448），固定输出 256 token。各副本分配同样数量的各类输入，再打乱顺序。",
             "通过要求：两轮正式测量的每条输出都与该配置的串行预热参考 token ID 序列完全相同，包括跨副本。",
             "不同 TP、精度或确定性模式之间不要求答案相同；本轮未评估任务准确率。", "",
             "| 精度 | TP×副本数 | 确定性模式 | 视觉模式 | prefill 预算 | 每副本并发 | 样本 | 不一致请求 | 通过 | 请求/min |",
             "|---|---|---|---|---:|---:|---:|---:|---|---:|"]
    for c in candidates:
        lines.append(f"| {c['precision']} | {c['tp']}×{c['replicas']} | {c['invariant']} | {c['encoder_mode']} | "
                     f"{c['batched_tokens']} | {c['concurrency_per_replica']} | {c['samples']} | {c['mismatches']} | "
                     f"{c['stable']} | {c['requests_per_minute']:.2f} |")
    if eligible:
        best = eligible[0]
        lines += ["", f"最快的通过初筛候选：`{best['layout']}`，每副本并发 {best['concurrency_per_replica']}，"
                  f"{best['requests_per_minute']:.2f} 请求/min；结果目录 `{best['path']}`。"]
    lines += ["", "## 稳定配置的逐输入延时", "", "| 配置 | 每副本并发 | 文本 s | 32 帧 s | 128 帧 s | 512 帧 s |",
              "|---|---:|---:|---:|---:|---:|"]
    for c in eligible:
        values = [f"{c['cases'][name]['median_seconds']:.3f}" for name in ["text", "video_32frames", "video_128frames", "video_512frames"]]
        lines.append(f"| {c['layout']} | {c['concurrency_per_replica']} | " + " | ".join(values) + " |")
    if problems:
        lines += ["", "## 启动或预热阶段的负结果", ""]
        for p in problems:
            lines.append(f"- `{p['path']}`：{p['status']}；预热不一致 {p['warmup_mismatches']}；{p['error']}。")
    if confirmed:
        servers = read(args.confirmation / "restart0" / "servers.json")
        command = servers[0]["command"]
        flag = lambda name: command[command.index(name) + 1]
        lines += ["", "## 完整输出与重启复核", "",
                  f"目录：`{args.confirmation}`；布局 `{confirmed['layout']}`，每副本并发 {confirmed['per_replica_concurrency']}。",
                  "采用 8 组输入（4 组新增 prompt），max_tokens=2048、正常 EOS，并重启整个服务池后再次测量。",
                  f"通过：{confirmed['stable']}；正式 {confirmed['valid_samples']} 次、预热 {confirmed['warmup_samples']} 次；"
                  f"token 不一致 {confirmed['mismatches']}；吞吐 {confirmed['requests_per_minute']} 请求/min。",
                  f"其中 512 帧专用负载的实测吞吐：{confirmed['long512_requests_per_minute']} 请求/min。",
                  f"错误：{confirmed['error']}。", "", "## 实测部署参数", "",
                  f"{len(servers)} 个独立服务，GPU 分组：`{[server['gpus'] for server in servers]}`。",
                  f"每服务 TP={flag('--tensor-parallel-size')}、DP={flag('--data-parallel-size')}；客户端每服务仅 "
                  f"{confirmed['per_replica_concurrency']} 个在途请求。服务端 max_num_seqs={flag('--max-num-seqs')} 是容量上限。",
                  f"max_model_len={flag('--max-model-len')}，max_num_batched_tokens={flag('--max-num-batched-tokens')}，"
                  f"gpu_memory_utilization={flag('--gpu-memory-utilization')}，mm_encoder_tp_mode={flag('--mm-encoder-tp-mode')}。",
                  f"VLLM_BATCH_INVARIANT={servers[0]['batch_invariant']}；CPU 线程限制：`{servers[0]['cpu_threads']}`。",
                  "完整 vLLM 启动命令在 `restart0/servers.json`；本报告的吞吐不包含加载、视频解码或 Judge 评分。"]
    lines += ["", "## 限制与留档", "",
              "有限输入上的重复一致不能证明任意输入、其他硬件/版本、任意并发或长期运行下都确定。",
              "新 prompt 仍来自同样的两个视频；未运行完整准确率 benchmark。预处理复用冻结 JPEG，计时不包含视频解码和模型启动。",
              "首次启动曾因每个 worker 继承 OMP/MKL=93 而极慢；限制为 1 后，TP4 两副本的权重加载约 17.5 秒。",
              "确定性模式在此版本需显式指定 FLASH_ATTN。即使开启，所测 FP8 动态 batch 仍可能改变输出，详见上表。",
              "每轮 manifest 保存硬件、版本、commit 和实际执行源码 hash；原始请求哈希、prompt 哈希、完整输出 token IDs、配置和日志均保存在各 runs 目录。", ""]
    (args.output / "report.md").write_text("\n".join(lines))
    source = Path(__file__).read_bytes()
    (args.output / Path(__file__).name).write_bytes(source)
    print(json.dumps({"formal_samples": records_total, "warmup_samples": warmups_total,
                      "comparable": comparable, "best": eligible[0] if eligible else None,
                      "confirmation_stable": confirmed["stable"] if confirmed else None,
                      "report_source_sha256": hashlib.sha256(source).hexdigest()}))


if __name__ == "__main__":
    main()
