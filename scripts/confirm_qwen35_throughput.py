#!/usr/bin/env python3
"""Confirm a screened 35B layout with full answers and a fresh server restart.

Run only on Modal. Uses balanced mixed-length work per replica, previously frozen
inputs plus unseen prompt variants, max_tokens=2048 with normal EOS, and two
shuffled measured passes before and after restarting the entire serving pool.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import signal
import time

from benchmark_qwen35_fp8 import digest, event, save
from benchmark_qwen35_throughput import Pool, balanced_tasks, make_bodies, run_pass


def main():
    signal.signal(signal.SIGINT, signal.default_int_handler)
    signal.signal(signal.SIGTERM, signal.default_int_handler)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--screen", type=Path, required=True)
    parser.add_argument("--layout", required=True)
    parser.add_argument("--concurrency", type=int, required=True)
    parser.add_argument("--repeats-per-replica", type=int, default=1)
    parser.add_argument("--restarts", type=int, default=1)
    parser.add_argument("--startup-timeout", type=int, default=1200)
    args = parser.parse_args()
    if not str(args.output).startswith("/runs/"):
        raise SystemExit("Results must stay on the runs volume")
    args.output.mkdir(parents=True, exist_ok=True)
    if (args.output / "manifest.json").exists():
        raise SystemExit("Use a fresh confirmation directory")
    config = json.loads((args.screen / args.layout / "summary.json").read_text())
    candidates = json.loads((args.screen / "summary.json").read_text())["candidates"]
    if not any(c["layout"] == args.layout and c["concurrency_per_replica"] == args.concurrency and c["stable"]
               for c in candidates):
        raise SystemExit("Candidate did not pass screening at the requested concurrency")
    cases = json.loads((args.screen / "inputs.json").read_text())
    original_names = [c["name"] for c in cases]
    variants = []
    for case in cases:
        variant = copy.deepcopy(case)
        variant["name"] += "_new_prompt"
        extra = ("\nOrganize your response as a numbered checklist. Explain three concrete failure modes "
                 "that these rules are intended to prevent." if case["frames"] == 0 else
                 "\nStructure your answer into observations about locations, objects, and actions, followed by "
                 "the strongest visual differences between Video 1 and Video 2. Explicitly identify details "
                 "that cannot be established from the frames.")
        content = variant["messages"][-1]["content"]
        if isinstance(content, str):
            variant["messages"][-1]["content"] += extra
        else:
            content[-1]["text"] += extra
        variant["messages_sha256"] = digest(variant["messages"])
        variants.append(variant)
    cases.extend(variants)
    save(args.output / "inputs.json", cases)
    sources = {}
    for name in [Path(__file__).name, "benchmark_qwen35_throughput.py", "benchmark_qwen35_fp8.py"]:
        data = (Path(__file__).parent / name).read_bytes()
        (args.output / name).write_bytes(data)
        sources[name] = hashlib.sha256(data).hexdigest()
    save(args.output / "manifest.json", {"screen": str(args.screen), "layout": config,
         "arguments": {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()},
         "sources_sha256": sources, "original_cases": original_names, "max_tokens": 2048,
         "fixed_output": False, "selection_note": "Fresh prompt variants share the same two source videos; no task accuracy assessment."})
    bodies = make_bodies(cases, 2048, fixed_output=False)
    references, passes = {}, []
    replicas = config["replicas"]
    started = time.monotonic()
    # This includes source code and configuration snapshots, plus all raw token IDs and timing records.
    try:
        for restart in range(args.restarts + 1):
            directory = args.output / f"restart{restart}"
            directory.mkdir()
            pool = Pool(args, directory)
            event(args.output, "loading", restart=restart, layout=args.layout)
            try:
                pool.start(config["precision"], config["tp"], replicas, config["invariant"],
                           8, config["batched_tokens"], config["encoder_mode"])
                tasks = [name for name in bodies for _ in range(replicas)]
                warmup = run_pass(args, directory, "warmup", pool.endpoints, bodies, 1,
                                  tasks, references, phase="warmup")
                passes.append({"restart": restart, **warmup})
                if not warmup["stable"]:
                    raise RuntimeError("Warmup/cross-replica/restart token mismatch")
                # Same task count, balanced by shape, at serial and selected concurrency.
                levels = sorted({1, args.concurrency}) if restart == 0 else [args.concurrency]
                for concurrency in levels:
                    for repeat in range(2):
                        tasks = balanced_tasks(list(bodies), replicas, args.repeats_per_replica,
                                               91000 + 100 * restart + 10 * repeat)
                        result = run_pass(args, directory, f"c{concurrency}_pass{repeat}", pool.endpoints,
                                          bodies, concurrency, tasks, references, phase="confirmation")
                        passes.append({"restart": restart, **result})
                        save(args.output / "passes.json", passes)
                        if not result["stable"]:
                            raise RuntimeError("Full-answer confirmation changed output token IDs or failed requests")
                # Measure the long-video workload separately from the mixed-shape average.
                long_names = [name for name in bodies if name.startswith("video_512frames")]
                for repeat in range(2):
                    tasks = balanced_tasks(long_names, replicas, max(2, args.repeats_per_replica),
                                           95000 + 100 * restart + 10 * repeat)
                    result = run_pass(args, directory, f"long512_c{args.concurrency}_pass{repeat}",
                                      pool.endpoints, bodies, args.concurrency, tasks, references,
                                      phase="confirmation_long512")
                    passes.append({"restart": restart, **result})
                    save(args.output / "passes.json", passes)
                    if not result["stable"]:
                        raise RuntimeError("Long-video-only confirmation changed output token IDs or failed requests")
            finally:
                pool.close()
        stable, error = True, None
    except Exception as exc:
        stable, error = False, repr(exc)
    save(args.output / "passes.json", passes)
    measured = [p for p in passes if p["phase"].startswith("confirmation")]
    rates, long_rates = {}, {}
    for phase, target in [("confirmation", rates), ("confirmation_long512", long_rates)]:
        for concurrency in sorted({p["per_replica_concurrency"] for p in measured if p["phase"] == phase}):
            selected = [p for p in measured if p["phase"] == phase and p["per_replica_concurrency"] == concurrency]
            target[str(concurrency)] = sum(p["samples"] for p in selected) * 60 / sum(p["seconds"] for p in selected)
    result = {"stable": stable, "error": error, "layout": args.layout, "per_replica_concurrency": args.concurrency,
              "valid_samples": sum(p["samples"] for p in measured),
              "warmup_samples": sum(p["samples"] for p in passes if p["phase"] == "warmup"),
              "mismatches": sum(len(p["mismatches"]) for p in passes), "requests_per_minute": rates,
              "long512_requests_per_minute": long_rates,
              "elapsed_seconds": time.monotonic() - started, "passes": passes}
    save(args.output / "summary.json", result)
    lines = ["# 35B 完整输出与重启复核", "", f"布局 `{args.layout}`；每副本并发 {args.concurrency}。",
             "使用 8 组输入（包含 4 组初筛未见的 prompt 变体），max_tokens=2048，按正常 EOS 结束。",
             "各副本每轮得到相同数量的每种输入，改变顺序；比较串行参考、并发、跨副本及服务重启后的完整 token ID。",
             f"通过：{stable}；正式样本 {result['valid_samples']}；预热 {result['warmup_samples']}；不一致 {result['mismatches']}。",
             f"错误：{error}。混合输入吞吐 {rates}；512 帧专用负载吞吐 {long_rates} 请求/min。", "",
             "| 重启编号 | pass | 样本 | 请求/分钟 | P95 秒 | token 不一致 |",
             "|---|---|---:|---:|---:|---:|"]
    for p in measured:
        lines.append(f"| {p['restart']} | {p['name']} | {p['samples']} | {p['requests_per_minute']:.2f} | "
                     f"{p['request_latency_p95']} | {len(p['mismatches'])} |")
    lines += ["", "有限样本的复现证据不能推广为任意输入的保证；新增 prompt 仍来自相同的两个视频，未评估任务准确率。", ""]
    (args.output / "report.md").write_text("\n".join(lines))
    event(args.output, "finished", stable=stable, valid_samples=result["valid_samples"],
          mismatches=result["mismatches"], requests_per_minute=rates,
          long512_requests_per_minute=long_rates, error=error)


if __name__ == "__main__":
    main()
