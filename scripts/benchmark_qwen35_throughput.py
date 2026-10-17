#!/usr/bin/env python3
"""Measure 35B throughput subject to exact-token repeatability, on Modal only.

Independent TP replicas, each DP=1. No response cache; all raw data stay on /runs.
Compare concurrency against each layout's own serial reference, across replicas,
shuffled mixed-length requests, and repeated passes. Reuse the FP8 probe parser.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import random
import queue
import signal
import shutil
import statistics
import subprocess
import time
import traceback

from benchmark_qwen35_fp8 import digest, event, request_once, save, stop_server

ROOT = Path(__file__).resolve().parents[1]


def percentile(values, q):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * q))]


def balanced_tasks(names, replicas, per_case_per_replica, seed):
    queues = []
    for replica in range(replicas):
        tasks = names * per_case_per_replica
        random.Random(seed + replica).shuffle(tasks)
        queues.append(tasks)
    return [queues[replica][i] for i in range(len(queues[0])) for replica in range(replicas)]


def make_bodies(cases, output_tokens, fixed_output=True):
    bodies = {}
    for case in cases:
        body = dict(model="bench", messages=case["messages"], temperature=0,
                    top_p=1, seed=0, max_tokens=output_tokens, stream=True,
                    stream_options={"include_usage": True}, return_token_ids=True,
                    chat_template_kwargs={"enable_thinking": False})
        if fixed_output:
            body.update(min_tokens=output_tokens, ignore_eos=True)
        bodies[case["name"]] = json.dumps(body, separators=(",", ":")).encode()
    return bodies


class Pool:
    def __init__(self, args, directory):
        self.args, self.directory = args, directory
        self.processes, self.logs, self.endpoints = [], [], []

    def start(self, precision, tp, replicas, invariant, max_seqs, batched_tokens, encoder_mode,
              *, gpu_offset=0, port_offset=0, flags=None, env_overrides=None, model_size="35B-A3B",
              data_parallel_size=1):
        import httpx
        replica_gpus = tp * data_parallel_size
        if gpu_offset + replicas * replica_gpus > 8:
            raise ValueError("Layout exceeds the eight-GPU allocation")
        model = f"/weights/Qwen3.5-{model_size}" + ("-FP8" if precision == "fp8" else "")
        commands = []
        for replica in range(replicas):
            port = 8100 + port_offset + replica
            command = ["vllm", "serve", model, "--tokenizer", f"/weights/Qwen3.5-{model_size}",
                       "--served-model-name", "bench", "--host", "127.0.0.1", "--port", str(port),
                       "--tensor-parallel-size", str(tp), "--data-parallel-size", str(data_parallel_size),
                       "--dtype", "bfloat16", "--kv-cache-dtype", "auto", "--seed", "0",
                       "--generation-config", "vllm", "--max-model-len", "131072",
                       "--max-num-seqs", str(max_seqs), "--max-num-batched-tokens", str(batched_tokens),
                       "--gpu-memory-utilization", "0.85", "--no-enable-prefix-caching",
                       "--mm-processor-cache-gb", "0", "--mm-encoder-tp-mode", encoder_mode,
                       "--limit-mm-per-prompt", json.dumps({"image": {"count": 512, "width": 448, "height": 448}, "video": 0}),
                       "--default-chat-template-kwargs", '{"enable_thinking": false}']
            if invariant:
                # vLLM 0.19.1 validates this before automatic backend selection.
                command += ["--attention-backend", "FLASH_ATTN"]
            for key, value in (flags or {}).items():
                # Replace existing options instead of relying on argparse duplicate handling.
                opposite = "--no-" + key[2:] if not key.startswith("--no-") else "--" + key[5:]
                for option in [key, opposite]:
                    if option in command:
                        index = command.index(option)
                        del command[index]
                        if index < len(command) and not command[index].startswith("--"):
                            del command[index]
                command.append(key)
                if value is not None:
                    command.append(str(value))
            gpus = list(range(gpu_offset + replica * replica_gpus, gpu_offset + (replica + 1) * replica_gpus))
            env = {**os.environ, "CUDA_VISIBLE_DEVICES": ",".join(map(str, gpus)),
                   "CUDA_DEVICE_ORDER": "PCI_BUS_ID", "VLLM_BATCH_INVARIANT": str(invariant),
                   "TOKENIZERS_PARALLELISM": "false", "OMP_NUM_THREADS": "1",
                   "MKL_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1"}
            env.update(env_overrides or {})
            log = (self.directory / f"server_{replica}.log").open("w")
            self.logs.append(log)
            self.processes.append(subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                                    env=env, start_new_session=True))
            self.endpoints.append(f"http://127.0.0.1:{port}")
            commands.append({"command": command, "gpus": gpus, "batch_invariant": invariant,
                             "env_overrides": env_overrides or {},
                             "cpu_threads": {k: env[k] for k in ["OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"]}})
        save(self.directory / "servers.json", commands)
        checkpoint = Path(model)
        shutil.copyfile(checkpoint / "config.json", self.directory / "model_config.json")
        if (checkpoint / "_download_manifest.json").exists():
            shutil.copyfile(checkpoint / "_download_manifest.json", self.directory / "weight_manifest.json")
        started = time.monotonic()
        with httpx.Client(timeout=2, trust_env=False) as client:
            pending = set(range(replicas))
            while pending:
                for index in list(pending):
                    if self.processes[index].poll() is not None:
                        raise RuntimeError(f"replica {index} exited with {self.processes[index].returncode}; see server_{index}.log")
                    try:
                        if client.get(self.endpoints[index] + "/health").status_code == 200:
                            pending.remove(index)
                            event(self.args.output, "replica_ready", layout=self.directory.name, replica=index)
                    except httpx.HTTPError:
                        pass
                if time.monotonic() - started > self.args.startup_timeout:
                    raise TimeoutError(f"startup time budget exceeded; pending replicas {sorted(pending)}")
                if pending:
                    time.sleep(5)
        event(self.args.output, "ready", layout=self.directory.name,
              load_seconds=round(time.monotonic() - started, 2))

    def close(self):
        with ThreadPoolExecutor(max_workers=max(1, len(self.processes))) as executor:
            list(executor.map(stop_server, self.processes))
        for log in self.logs:
            log.close()


def run_pass(args, directory, name, endpoints, bodies, per_replica, tasks, references, *, phase,
             client_headers=None, request_timeout=900, dynamic_routing=False):
    import httpx
    rows, errors = [], []
    started = time.perf_counter()
    clients = [httpx.Client(timeout=request_timeout, trust_env=False,
                           headers=client_headers[i] if client_headers else None,
                           limits=httpx.Limits(max_connections=per_replica, max_keepalive_connections=per_replica))
               for i, _ in enumerate(endpoints)]
    # An explicit queue per replica bounds actual in-flight requests. All queues run together.
    def one(replica, case, index):
        row = request_once(clients[replica], bodies[case], endpoint=endpoints[replica])
        return {"case": case, "replica": replica, "task_index": index, "pass": name,
                "phase": phase, "request_sha256": hashlib.sha256(bodies[case]).hexdigest(), **row}
    slots = queue.Queue()
    for replica in range(len(endpoints)):
        for _ in range(per_replica):
            slots.put(replica)
    def dynamic_one(case, index):
        replica = slots.get()
        try:
            return one(replica, case, index)
        finally:
            slots.put(replica)
    with (directory / "records.jsonl").open("a", buffering=1) as raw:
        executors = ([ThreadPoolExecutor(max_workers=per_replica * len(endpoints))] if dynamic_routing else
                     [ThreadPoolExecutor(max_workers=per_replica) for _ in endpoints])
        try:
            if dynamic_routing:
                futures = {executors[0].submit(dynamic_one, case, index): (index, case, None)
                           for index, case in enumerate(tasks)}
            else:
                futures = {executors[index % len(endpoints)].submit(one, index % len(endpoints), case, index):
                           (index, case, index % len(endpoints)) for index, case in enumerate(tasks)}
            for future in as_completed(futures):
                try:
                    row = future.result()
                    raw.write(json.dumps(row) + "\n")
                    rows.append(row)
                    event(args.output, "measuring", layout=directory.name, pass_name=name, phase_name=phase,
                          samples_this_pass=len(rows), case=row["case"], replica=row["replica"],
                          seconds=round(row["seconds"], 3))
                except Exception as exc:
                    index, case, replica = futures[future]
                    error = {"pass": name, "case": case, "replica": replica, "task_index": index,
                             "error": repr(exc), "traceback": traceback.format_exc()}
                    errors.append(error)
                    with (directory / "errors.jsonl").open("a") as handle:
                        handle.write(json.dumps(error) + "\n")
        finally:
            for executor in executors:
                executor.shutdown(wait=True)
            for client in clients:
                client.close()
    elapsed = time.perf_counter() - started
    mismatches = []
    for row in sorted(rows, key=lambda r: r["task_index"]):
        key = row["case"]
        if key not in references:
            references[key] = {field: row[field] for field in
                               ["token_ids", "prompt_token_ids_sha256", "request_sha256"]}
        ref = references[key]
        if row["token_ids"] != ref["token_ids"]:
            pos = next((i for i, (a, b) in enumerate(zip(ref["token_ids"], row["token_ids"])) if a != b),
                       min(len(ref["token_ids"]), len(row["token_ids"])))
            mismatches.append({"case": key, "replica": row["replica"], "task_index": row["task_index"],
                               "first_different_token": pos})
        if any(row[field] != ref[field] for field in ["prompt_token_ids_sha256", "request_sha256"]):
            raise RuntimeError(f"Request/prompt mismatch for {key}")
    result = {"name": name, "phase": phase, "per_replica_concurrency": per_replica,
              "replicas": len(endpoints), "samples": len(rows), "expected_samples": len(tasks),
              "seconds": elapsed, "requests_per_minute": len(rows) * 60 / elapsed,
              "output_tokens_per_second": sum(r["output_tokens"] for r in rows) / elapsed,
              "request_latency_median": statistics.median(r["seconds"] for r in rows) if rows else None,
              "request_latency_p95": percentile([r["seconds"] for r in rows], .95) if rows else None,
              "mismatches": mismatches, "errors": errors,
              "stable": len(rows) == len(tasks) and not errors and not mismatches,
              "by_case": {case: {"samples": sum(r["case"] == case for r in rows),
                                  "unique_outputs": len({r["token_ids_sha256"] for r in rows if r["case"] == case})}
                          for case in sorted(set(tasks))}}
    save(directory / f"{name}.json", result)
    save(directory / "references.json", references)
    event(args.output, "pass_finished", layout=directory.name, pass_name=name, samples=len(rows),
          stable=result["stable"], mismatches=len(mismatches), requests_per_minute=result["requests_per_minute"])
    return result


def run_layout(args, cases, precision, tp, invariant, *, encoder_mode="weights", batched_tokens=8192):
    replicas = 8 // tp
    key = f"{precision}_tp{tp}_r{replicas}_inv{invariant}_{encoder_mode}_bt{batched_tokens}"
    directory = args.output / key
    if directory.exists():
        raise ValueError(f"Refusing to overwrite existing layout {key}")
    directory.mkdir()
    result = {"layout": key, "precision": precision, "tp": tp, "replicas": replicas,
              "invariant": invariant, "encoder_mode": encoder_mode, "batched_tokens": batched_tokens,
              "max_seqs": args.max_seqs,
              "passes": []}
    pool = Pool(args, directory)
    bodies = make_bodies(cases, args.output_tokens)
    names = list(bodies)
    references = {}
    event(args.output, "loading", layout=key)
    try:
        pool.start(precision, tp, replicas, invariant, args.max_seqs, batched_tokens, encoder_mode)
        # Each endpoint sees all shapes sequentially before measuring throughput.
        tasks = [case for case in names for _ in range(replicas)]
        result["passes"].append(run_pass(args, directory, "warmup", pool.endpoints, bodies, 1,
                                         tasks, references, phase="warmup"))
        if not result["passes"][-1]["stable"]:
            result["status"] = "unstable_serial_warmup"
            return result
        for concurrency in args.concurrency:
            for repeat in range(args.passes):
                if args.repeats % replicas:
                    raise ValueError("--repeats must divide evenly across replicas")
                tasks = balanced_tasks(names, replicas, args.repeats // replicas, 12345 + 10 * repeat)
                name = f"c{concurrency}_pass{repeat}"
                measured = run_pass(args, directory, name, pool.endpoints, bodies, concurrency,
                                    tasks, references, phase="screen")
                result["passes"].append(measured)
                save(directory / "summary.json", result)
                if not measured["stable"]:
                    result["status"] = "unstable" if not measured["errors"] else "request_failed"
                    return result
        result["status"] = "stable"
        return result
    except Exception as exc:
        result.update(status="failed", error=repr(exc), traceback=traceback.format_exc())
        event(args.output, "layout_failed", layout=key, error=repr(exc))
        return result
    finally:
        save(directory / "summary.json", result)
        pool.close()


def write_report(args, matrix):
    rows = []
    for layout in matrix:
        for concurrency in args.concurrency:
            passes = [p for p in layout["passes"] if p["phase"] == "screen" and
                      p["per_replica_concurrency"] == concurrency]
            if not passes:
                continue
            stable = len(passes) == args.passes and all(p["stable"] for p in passes)
            rows.append({"layout": layout["layout"], "concurrency_per_replica": concurrency,
                         "total_concurrency": concurrency * layout["replicas"], "stable": stable,
                         "samples": sum(p["samples"] for p in passes),
                         "mismatches": sum(len(p["mismatches"]) for p in passes),
                         "requests_per_minute": sum(p["samples"] for p in passes) * 60 / sum(p["seconds"] for p in passes)})
    eligible = [r for r in rows if r["stable"]]
    best = max(eligible, key=lambda r: r["requests_per_minute"]) if eligible else None
    summary = {"matrix": matrix, "candidates": rows, "best_screened": best,
               "valid_samples": sum(p["samples"] for x in matrix for p in x["passes"] if p["phase"] != "warmup")}
    save(args.output / "summary.json", summary)
    lines = ["# 35B 吞吐与逐 token 重复性", "",
             f"筛选有效样本 {summary['valid_samples']}；输入为文本和 32/128/512 帧，固定生成 {args.output_tokens} token。",
             "各布局独立建立串行参考；跨副本、打乱提交顺序、改变并发后比较完整 token ID。禁用 prefix/MM processor cache。",
             "通过筛选只表示所测输入可复现，不是任意输入或并发的普遍保证。", "",
             "| 布局 | 每副本/总并发 | 样本 | token 不一致请求 | 全部筛选通过 | 请求/分钟 |",
             "|---|---:|---:|---:|---|---:|"]
    for row in rows:
        lines.append(f"| {row['layout']} | {row['concurrency_per_replica']}/{row['total_concurrency']} | "
                     f"{row['samples']} | {row['mismatches']} | {row['stable']} | {row['requests_per_minute']:.2f} |")
    for layout in matrix:
        if layout.get("error"):
            lines += ["", f"启动失败 `{layout['layout']}`：{layout['error']}"]
    lines += ["", f"筛选中最快且通过重复性检查：`{best}`", ""]
    (args.output / "report.md").write_text("\n".join(lines))
    return summary


def main():
    signal.signal(signal.SIGINT, signal.default_int_handler)
    signal.signal(signal.SIGTERM, signal.default_int_handler)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--inputs", type=Path, default=Path("/runs/devbox/fp8_h100_tp8_20261009_r1/inputs.json"))
    parser.add_argument("--precisions", nargs="+", choices=["fp8", "bf16"], default=["fp8"])
    parser.add_argument("--tp", type=int, nargs="+", choices=[1, 2, 4], default=[4, 2])
    parser.add_argument("--concurrency", type=int, nargs="+", default=[1, 2, 4, 8])
    parser.add_argument("--max-seqs", type=int, default=8)
    parser.add_argument("--invariant", type=int, choices=[0, 1], default=0)
    parser.add_argument("--encoder-mode", choices=["weights", "data"], default="weights")
    parser.add_argument("--batched-tokens", type=int, default=8192)
    parser.add_argument("--passes", type=int, default=2)
    parser.add_argument("--repeats", type=int, default=8)
    parser.add_argument("--output-tokens", type=int, default=256)
    parser.add_argument("--startup-timeout", type=int, default=1200)
    args = parser.parse_args()
    if min(args.concurrency) < 1 or max(args.concurrency) > args.max_seqs:
        raise SystemExit("Client concurrency must be positive and <= --max-seqs")
    if not str(args.output).startswith("/runs/"):
        raise SystemExit("All results must stay on the runs volume")
    args.output.mkdir(parents=True, exist_ok=True)
    if (args.output / "manifest.json").exists():
        raise SystemExit("Use a fresh experiment directory")
    inventory = subprocess.check_output(["nvidia-smi", "--query-gpu=index,name,uuid,memory.total,driver_version", "--format=csv"], text=True)
    if inventory.count("H100") != 8:
        raise SystemExit("Expected exactly eight H100 GPUs")
    cases = json.loads(args.inputs.read_text())
    for case in cases:
        if digest(case["messages"]) != case["messages_sha256"]:
            raise ValueError("Frozen input hash mismatch")
    shutil.copyfile(args.inputs, args.output / "inputs.json")
    sources = {}
    for name in [Path(__file__).name, "benchmark_qwen35_fp8.py"]:
        data = (Path(__file__).parent / name).read_bytes()
        (args.output / name).write_bytes(data)
        sources[name] = hashlib.sha256(data).hexdigest()
    save(args.output / "manifest.json", {"arguments": {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()},
         "gpu_inventory": inventory, "sources_sha256": sources,
         "git_commit": subprocess.check_output(["git", "-c", f"safe.directory={ROOT}", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip(),
         "versions": {p: importlib.metadata.version(p) for p in ["vllm", "torch", "transformers"]}})
    matrix = []
    for precision in args.precisions:
        for tp in args.tp:
            result = run_layout(args, cases, precision, tp, args.invariant,
                                encoder_mode=args.encoder_mode, batched_tokens=args.batched_tokens)
            matrix.append(result)
            write_report(args, matrix)
            # Default batching that changes tokens is followed by a separate deterministic-mode attempt.
            if result["status"].startswith("unstable") and not args.invariant:
                matrix.append(run_layout(args, cases, precision, tp, 1,
                                         encoder_mode=args.encoder_mode, batched_tokens=args.batched_tokens))
                write_report(args, matrix)
    summary = write_report(args, matrix)
    event(args.output, "finished", valid_samples=summary["valid_samples"], best=summary["best_screened"])


if __name__ == "__main__":
    main()
