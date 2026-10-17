#!/usr/bin/env python3
"""Offline vLLM fixed-cohort probe: distinguish repeatability from batch independence."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

from benchmark_qwen35_fp8 import digest, event, save


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--inputs", type=Path, default=Path("/runs/devbox/qwen35_confirmation_20261010/inputs.json"))
    parser.add_argument("--synchronous", action="store_true",
                        help="Disable engine multiprocessing and async scheduling so the whole cohort is queued before stepping")
    args = parser.parse_args()
    if not str(args.output).startswith("/runs/") or (args.output / "manifest.json").exists():
        raise SystemExit("Use a fresh /runs/ directory")
    args.output.mkdir(parents=True, exist_ok=True)
    if args.synchronous:
        os.environ["VLLM_ENABLE_V1_MULTIPROCESSING"] = "0"
    from vllm import LLM, SamplingParams
    cases = json.loads(args.inputs.read_text())
    for case in cases:
        assert digest(case["messages"]) == case["messages_sha256"]
    shutil.copyfile(args.inputs, args.output / "inputs.json")
    source = Path(__file__).read_bytes()
    (args.output / Path(__file__).name).write_bytes(source)
    config = dict(model="/weights/Qwen3.5-35B-A3B-FP8", tokenizer="/weights/Qwen3.5-35B-A3B",
                  dtype="bfloat16", kv_cache_dtype="auto", tensor_parallel_size=1, seed=0,
                  generation_config="vllm", max_model_len=131072, max_num_seqs=8,
                  max_num_batched_tokens=16384, gpu_memory_utilization=.85,
                  enable_prefix_caching=False, mm_processor_cache_gb=0, mm_encoder_tp_mode="weights",
                  limit_mm_per_prompt={"image": {"count": 512, "width": 448, "height": 448}, "video": 0})
    if args.synchronous:
        config["async_scheduling"] = False
    for name in ["config.json", "_download_manifest.json"]:
        shutil.copyfile(Path(config["model"]) / name, args.output / name)
    shutil.copyfile(Path(__file__).with_name("benchmark_qwen35_fp8.py"), args.output / "benchmark_qwen35_fp8.py")
    save(args.output / "manifest.json", {"config": config, "source_sha256": hashlib.sha256(source).hexdigest(),
         "input_sha256": hashlib.sha256(args.inputs.read_bytes()).hexdigest(),
         "git_commit": subprocess.check_output(["git", "-c", "safe.directory=/repo", "rev-parse", "HEAD"], text=True).strip(),
         "gpu_inventory": subprocess.check_output(["nvidia-smi", "--query-gpu=index,name,uuid", "--format=csv"], text=True),
         "environment": {k: os.environ.get(k) for k in ["CUDA_VISIBLE_DEVICES", "VLLM_ENABLE_V1_MULTIPROCESSING", "VLLM_BATCH_INVARIANT", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"]},
         "versions": {p: importlib.metadata.version(p) for p in ["vllm", "torch", "transformers"]}})
    event(args.output, "loading")
    llm = LLM(**config)
    params = SamplingParams(temperature=0, top_p=1, seed=0, max_tokens=256, min_tokens=256, ignore_eos=True)
    n = len(cases)
    cohorts = {"serial": [[i] for i in range(n)],
               "fixed_pairs": [[i, i + 1] for i in range(0, n, 2)],
               "reversed_pairs": [[i + 1, i] for i in range(0, n, 2)],
               "changed_pairs": [[i, (i + n // 2) % n] for i in range(n // 2)]}
    references, summaries = {}, []
    with (args.output / "records.jsonl").open("a", buffering=1) as raw:
        for mode, groups in cohorts.items():
            for repeat in range(2):
                started = time.perf_counter()
                changes, serial_changes = [], []
                for indices in groups:
                    output = llm.chat([cases[i]["messages"] for i in indices], sampling_params=params,
                                      use_tqdm=False, chat_template_kwargs={"enable_thinking": False})
                    for index, row in zip(indices, output, strict=True):
                        generated = row.outputs[0]
                        record = {"mode": mode, "repeat": repeat, "case": cases[index]["name"],
                                  "cohort": [cases[i]["name"] for i in indices],
                                  "prompt_token_ids_sha256": digest(row.prompt_token_ids),
                                  "token_ids": list(generated.token_ids), "text": generated.text,
                                  "finish_reason": generated.finish_reason}
                        raw.write(json.dumps(record) + "\n")
                        key = (mode, index)
                        if key not in references:
                            references[key] = record["token_ids"]
                        if references[key] != record["token_ids"]:
                            changes.append(record["case"])
                        if references[("serial", index)] != record["token_ids"]:
                            serial_changes.append(record["case"])
                elapsed = time.perf_counter() - started
                summary = {"mode": mode, "repeat": repeat, "samples": n, "seconds": elapsed,
                           "requests_per_minute": n * 60 / elapsed, "repeat_mismatches": changes,
                           "serial_mismatches": serial_changes}
                summaries.append(summary)
                save(args.output / "summary.json", summaries)
                event(args.output, "pass_finished", **summary)
    event(args.output, "finished", samples=sum(s["samples"] for s in summaries),
          scope="Fixed cohorts may repeat while individual requests remain batch-dependent")


if __name__ == "__main__":
    main()
