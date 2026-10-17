#!/usr/bin/env python3
"""Compare vLLM optimizations under exact-token checks; execute only on Modal.

Screen independent configurations on separate GPUs in one allocation. Confirm
one configuration on the full pool, including cache resets and service restart.
Each configuration owns its reference; warm/cold cache and batching must match it.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import importlib.metadata
import json
from pathlib import Path
import shutil
import signal
import subprocess
import time
from types import SimpleNamespace
import traceback

from benchmark_qwen35_fp8 import digest, event, save
from benchmark_qwen35_throughput import Pool, balanced_tasks, make_bodies, run_pass

VARIANTS = {
    "baseline": {},
    "mm_cache": {"flags": {"--mm-processor-cache-gb": "4", "--mm-processor-cache-type": "shm"}},
    "prefix_cache": {"env": {"VLLM_SERVER_DEV_MODE": "1"},
                     "flags": {"--mm-processor-cache-gb": "4", "--mm-processor-cache-type": "shm",
                               "--enable-prefix-caching": None, "--mamba-cache-mode": "align"}},
    "mtp1": {"flags": {"--mm-processor-cache-gb": "4", "--mm-processor-cache-type": "shm",
                       "--speculative-config": '{"method":"mtp","num_speculative_tokens":1}'}},
    "mtp2": {"flags": {"--mm-processor-cache-gb": "4", "--mm-processor-cache-type": "shm",
                       "--speculative-config": '{"method":"mtp","num_speculative_tokens":2}'}},
    "invariant_eager": {"invariant": 1, "flags": {"--enforce-eager": None}},
    "invariant_nochunk": {"invariant": 1, "flags": {"--no-enable-chunked-prefill": None,
                                                   "--max-model-len": "65536",
                                                   "--max-num-batched-tokens": "65536"}},
    "bf16_single": {"precision": "bf16", "flags": {"--gpu-memory-utilization": "0.95",
                                                    "--max-model-len": "65536"}},
}
DEFAULT_VARIANTS = list(VARIANTS)
# Follow-up options combine measured gains and isolate asynchronous scheduling after the
# initial probes found cache gains and token differences even with fixed cohorts.
VARIANTS.update({
    "prefix_block2048": {"env": {"VLLM_SERVER_DEV_MODE": "1"}, "flags": {
        **VARIANTS["prefix_cache"]["flags"], "--block-size": "2048"}},
    "prefix_mtp2": {"env": {"VLLM_SERVER_DEV_MODE": "1"}, "flags": {
        **VARIANTS["prefix_cache"]["flags"],
        "--speculative-config": '{"method":"mtp","num_speculative_tokens":2}'}},
    "prefix_invariant_sync": {"invariant": 1, "env": {"VLLM_SERVER_DEV_MODE": "1"}, "flags": {
        **VARIANTS["prefix_cache"]["flags"], "--no-async-scheduling": None}},
    "invariant_sync": {"invariant": 1, "flags": {
        "--mm-processor-cache-gb": "4", "--mm-processor-cache-type": "shm", "--no-async-scheduling": None}},
    "bf16_prefix": {"precision": "bf16", "env": {"VLLM_SERVER_DEV_MODE": "1"}, "flags": {
        **VARIANTS["prefix_cache"]["flags"], "--gpu-memory-utilization": "0.95"}},
    "bf16_prefix_invariant_sync": {"precision": "bf16", "invariant": 1,
                                   "env": {"VLLM_SERVER_DEV_MODE": "1"}, "flags": {
        **VARIANTS["prefix_cache"]["flags"], "--gpu-memory-utilization": "0.95", "--no-async-scheduling": None}},
})
# Kernel candidates for the FP8 follow-up. Explicit backend failures remain failures.
VARIANTS.update({
    "bf16_mm_cache": {"precision": "bf16", "flags": {**VARIANTS["mm_cache"]["flags"],
                                                         "--gpu-memory-utilization": "0.95"}},
    "mm_marlin": {"env": {"VLLM_TEST_FORCE_FP8_MARLIN": "1"},
                  "flags": {**VARIANTS["mm_cache"]["flags"]}},
    "mm_moe_marlin": {"flags": {**VARIANTS["mm_cache"]["flags"],
                                 "--kernel-config": '{"moe_backend":"marlin"}'}},
    "prefix_marlin": {"env": {"VLLM_SERVER_DEV_MODE": "1", "VLLM_TEST_FORCE_FP8_MARLIN": "1"},
                      "flags": {**VARIANTS["prefix_cache"]["flags"]}},
    "prefix_marlin_triton": {"env": {"VLLM_SERVER_DEV_MODE": "1", "VLLM_TEST_FORCE_FP8_MARLIN": "1"},
                             "flags": {**VARIANTS["prefix_cache"]["flags"],
                                       "--kernel-config": '{"moe_backend":"triton"}'}},
    "prefix_moe_marlin": {"env": {"VLLM_SERVER_DEV_MODE": "1"}, "flags": {
        **VARIANTS["prefix_cache"]["flags"], "--kernel-config": '{"moe_backend":"marlin"}'}},
    "prefix_cutlass": {"env": {"VLLM_SERVER_DEV_MODE": "1"}, "flags": {
        **VARIANTS["prefix_cache"]["flags"], "--kernel-config": '{"moe_backend":"flashinfer_cutlass"}'}},
    "prefix_deepgemm": {"env": {"VLLM_SERVER_DEV_MODE": "1"}, "flags": {
        **VARIANTS["prefix_cache"]["flags"], "--kernel-config": '{"moe_backend":"deep_gemm"}'}},
    "prefix_prefill64k": {"env": {"VLLM_SERVER_DEV_MODE": "1"}, "flags": {
        **VARIANTS["prefix_cache"]["flags"], "--max-num-batched-tokens": "65536"}},
    "prefix_fp8kv": {"env": {"VLLM_SERVER_DEV_MODE": "1"}, "flags": {
        **VARIANTS["prefix_cache"]["flags"], "--kv-cache-dtype": "fp8", "--calculate-kv-scales": None}},
})


def has_prefix(config):
    return "--enable-prefix-caching" in config.get("flags", {})


def reset_prefix(endpoints):
    import httpx
    for endpoint in endpoints:
        response = httpx.post(endpoint + "/reset_prefix_cache", timeout=60, trust_env=False)
        response.raise_for_status()


def metrics(directory, label, endpoints):
    import httpx
    for i, endpoint in enumerate(endpoints):
        response = httpx.get(endpoint + "/metrics", timeout=30, trust_env=False)
        response.raise_for_status()
        (directory / f"metrics_{label}_{i}.txt").write_text(response.text)


def run_variant(args, name, gpu_offset, cases):
    config = VARIANTS[name]
    root = args.output / name
    root.mkdir()
    local_args = SimpleNamespace(output=root, startup_timeout=args.startup_timeout)
    bodies = make_bodies(cases, args.max_tokens, fixed_output=not args.normal_eos)
    if args.native_generation:
        for case in cases:
            body = json.loads(bodies[case["name"]])
            body.update(case["generation"])
            bodies[case["name"]] = json.dumps(body, separators=(",", ":")).encode()
    refs, passes = {}, []
    result = {"variant": name, "config": config, "replicas": args.replicas,
              "gpu_offset": gpu_offset, "passes": passes, "error": None, "stable": False}
    # A single scalar seed and fixed request bytes; no response cache or deduplication.
    try:
        for restart in range(args.restarts + 1):
            directory = root / f"restart{restart}"
            directory.mkdir()
            pool = Pool(local_args, directory)
            event(root, "loading", restart=restart)
            try:
                pool.start(config.get("precision", "fp8"), 1, args.replicas, config.get("invariant", 0),
                           8, 16384, "weights", gpu_offset=gpu_offset, port_offset=gpu_offset,
                           flags=config.get("flags"), env_overrides=config.get("env"), model_size=args.model_size)
                metrics(directory, "start", pool.endpoints)
                # Reset before each case, so prefix hits cannot contaminate the cold reference.
                # All replicas see each case, and references survive a full service restart.
                cold_cases = [None] if args.fixed_routing else list(bodies)
                for case in cold_cases:
                    if has_prefix(config):
                        reset_prefix(pool.endpoints)
                    cold_tasks = list(bodies) if args.fixed_routing else [case] * args.replicas
                    measured = run_pass(local_args, directory, f"cold_{case or 'fixed_routes'}", pool.endpoints,
                                        bodies, 1, cold_tasks, refs, phase="warmup")
                    passes.append({"restart": restart, **measured})
                    save(root / "summary.json", result)
                    if not measured["stable"]:
                        raise RuntimeError("Cross-replica/restart cold reference mismatch")
                metrics(directory, "cold", pool.endpoints)
                for concurrency in args.concurrency:
                    for repeat in range(2):
                        tasks = (list(bodies) * args.repeats if args.fixed_routing else
                                 balanced_tasks(list(bodies), args.replicas, args.repeats,
                                                17200 + 100 * restart + 10 * repeat))
                        measured = run_pass(local_args, directory, f"c{concurrency}_pass{repeat}",
                                            pool.endpoints, bodies, concurrency, tasks, refs, phase="measure")
                        passes.append({"restart": restart, **measured})
                        metrics(directory, f"c{concurrency}_pass{repeat}", pool.endpoints)
                        save(root / "summary.json", result)
                        if not measured["stable"]:
                            # Faster levels cannot redeem a failed reproducibility level.
                            raise RuntimeError(f"Token mismatch or request failure at concurrency {concurrency}")
                if args.long_passes:
                    for repeat in range(2):
                        tasks = balanced_tasks([n for n in bodies if n.startswith("video_512frames")],
                                               args.replicas, max(2, args.repeats), 17600 + restart * 100 + repeat)
                        measured = run_pass(local_args, directory, f"long512_pass{repeat}", pool.endpoints,
                                            bodies, args.concurrency[-1], tasks, refs, phase="long512")
                        passes.append({"restart": restart, **measured})
                        save(root / "summary.json", result)
                        if not measured["stable"]:
                            raise RuntimeError("Long-input-only token mismatch")
                if has_prefix(config):
                    reset_prefix(pool.endpoints)
                    reset_tasks = (list(bodies) if args.fixed_routing else
                                   balanced_tasks(list(bodies), args.replicas, 1, 17900))
                    measured = run_pass(local_args, directory, "post_reset", pool.endpoints, bodies, 1,
                                        reset_tasks, refs, phase="reset")
                    passes.append({"restart": restart, **measured})
                    if not measured["stable"]:
                        raise RuntimeError("Cache reset changed output")
            finally:
                pool.close()
        result["stable"] = True
    except Exception as exc:
        result.update(error=repr(exc), traceback=traceback.format_exc())
    result["formal_samples"] = sum(p["samples"] for p in passes if p["phase"] != "warmup")
    result["warmup_samples"] = sum(p["samples"] for p in passes if p["phase"] == "warmup")
    result["mismatches"] = sum(len(p["mismatches"]) for p in passes)
    result["levels"] = []
    for concurrency in args.concurrency:
        selected = [p for p in passes if p["phase"] == "measure" and p["per_replica_concurrency"] == concurrency]
        if selected:
            result["levels"].append({"concurrency": concurrency,
                "stable": len(selected) == 2 * (args.restarts + 1) and all(p["stable"] for p in selected),
                "samples": sum(p["samples"] for p in selected),
                "mismatches": sum(len(p["mismatches"]) for p in selected),
                "requests_per_minute": sum(p["samples"] for p in selected) * 60 / sum(p["seconds"] for p in selected)})
    save(root / "summary.json", result)
    event(root, "finished", stable=result["stable"], formal_samples=result["formal_samples"],
          warmup_samples=result["warmup_samples"], mismatches=result["mismatches"], error=result["error"])
    return result


def main():
    signal.signal(signal.SIGTERM, signal.default_int_handler)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--inputs", type=Path, default=Path("/runs/devbox/qwen35_confirmation_20261010/inputs.json"))
    parser.add_argument("--variants", nargs="+", choices=list(VARIANTS), default=DEFAULT_VARIANTS)
    parser.add_argument("--model-size", choices=["9B", "27B", "35B-A3B"], default="35B-A3B")
    parser.add_argument("--case-names", nargs="+", help="Select named frozen cases for a bounded kernel screen")
    parser.add_argument("--replicas", type=int, default=1)
    parser.add_argument("--gpu-offset", type=int, default=0)
    parser.add_argument("--concurrency", nargs="+", type=int, default=[1, 2])
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--restarts", type=int, default=0)
    parser.add_argument("--max-tokens", type=int, default=256)
    parser.add_argument("--normal-eos", action="store_true")
    parser.add_argument("--native-generation", action="store_true",
                        help="Use each frozen case's E2E generation settings")
    parser.add_argument("--long-passes", action="store_true")
    parser.add_argument("--fixed-routing", action="store_true",
                        help="Restricted diagnostic: exactly one frozen case per physical replica; retain routing across restarts")
    parser.add_argument("--startup-timeout", type=int, default=1200)
    args = parser.parse_args()
    if args.native_generation and not args.normal_eos:
        raise SystemExit("Native benchmark generation requires --normal-eos")
    if not str(args.output).startswith("/runs/") or (args.output / "manifest.json").exists():
        raise SystemExit("Use a fresh /runs/ directory")
    if not 0 <= args.gpu_offset < 8 or args.gpu_offset + len(args.variants) * args.replicas > 8 or not 1 <= min(args.concurrency) <= max(args.concurrency) <= 8:
        raise SystemExit("Invalid GPU allocation or concurrency")
    args.output.mkdir(parents=True, exist_ok=True)
    inventory = subprocess.check_output(["nvidia-smi", "--query-gpu=index,name,uuid,memory.total,driver_version", "--format=csv"], text=True)
    if inventory.count("H100") != 8:
        raise SystemExit("Expected eight actual H100 GPUs")
    cases = json.loads(args.inputs.read_text())
    if args.case_names:
        cases = [c for c in cases if c['name'] in args.case_names]
        if {c['name'] for c in cases} != set(args.case_names):
            raise SystemExit('Requested case not found in frozen inputs')
    if args.fixed_routing and (len(cases) != args.replicas or args.long_passes):
        raise SystemExit('Fixed-routing diagnostic requires one case per replica and no long-only passes')
    for case in cases:
        if digest(case["messages"]) != case["messages_sha256"]:
            raise ValueError("Input hash mismatch")
    save(args.output / "inputs.json", cases)
    sources = {}
    for name in [Path(__file__).name, "benchmark_qwen35_throughput.py", "benchmark_qwen35_fp8.py"]:
        data = (Path(__file__).parent / name).read_bytes()
        (args.output / name).write_bytes(data)
        sources[name] = hashlib.sha256(data).hexdigest()
    save(args.output / "manifest.json", {
        "arguments": {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()},
        "input_sha256": hashlib.sha256((args.output / 'inputs.json').read_bytes()).hexdigest(),
        "variants": VARIANTS, "gpu_inventory": inventory, "sources_sha256": sources,
        "git_commit": subprocess.check_output(["git", "-c", "safe.directory=/repo", "rev-parse", "HEAD"], text=True).strip(),
        "versions": {p: importlib.metadata.version(p) for p in ["vllm", "torch", "transformers"]},
        "scope": ("Fixed physical replica per frozen input: no cross-replica or new-allocation reproducibility claim."
                  if args.fixed_routing else
                  "One-GPU screening shares host CPU across unlike configs; no eight-GPU throughput extrapolation. Confirm winner on full pool.")})
    results = []
    event(args.output, "running", variants=args.variants)
    with ThreadPoolExecutor(max_workers=len(args.variants)) as executor:
        futures = [executor.submit(run_variant, args, name, args.gpu_offset + i * args.replicas, cases)
                   for i, name in enumerate(args.variants)]
        for future in as_completed(futures):
            results.append(future.result())
            save(args.output / "summary.json", results)
            event(args.output, "variant_finished", variant=results[-1]["variant"],
                  formal_samples=sum(r["formal_samples"] for r in results), completed=len(results))
    event(args.output, "finished", formal_samples=sum(r["formal_samples"] for r in results),
          warmup_samples=sum(r["warmup_samples"] for r in results), completed=len(results))


if __name__ == "__main__":
    main()
