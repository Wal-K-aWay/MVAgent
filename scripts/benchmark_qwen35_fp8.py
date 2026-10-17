#!/usr/bin/env python3
"""Matched BF16/FP8 latency and exact-token repeatability probe; run on Modal only.

Uses one eight-GPU host, one TP=8/DP=1 vLLM server at a time, concurrency one.
Raw requests, streaming token IDs, logs, and summaries stay in the runs volume.
This is an inference-system benchmark, not a benchmark-accuracy evaluation.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import signal
import statistics
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval/e2e_eval"))


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2) + "\n")
    tmp.replace(path)


def event(out, phase, **data):
    entry = {"time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "phase": phase, **data}
    print(json.dumps(entry), flush=True)
    with (out / "events.jsonl").open("a") as handle:
        handle.write(json.dumps(entry) + "\n")
    save(out / "progress.json", entry)


def prepare_inputs(out, frame_counts):
    from harness.media import sample_frames

    path = out / "inputs.json"
    if path.exists():
        cases = json.loads(path.read_text())
        expected_names = ["text", *(f"video_{n}frames" for n in frame_counts)]
        if [case["name"] for case in cases] != expected_names:
            raise ValueError("Saved input workloads differ from --frames; use a new output directory")
        for case in cases:
            if case["messages_sha256"] != digest(case["messages"]):
                raise ValueError(f"Saved input hash mismatch: {case['name']}")
        return cases
    spec = (ROOT / "src/skill_evolution/infra/global_skill_specification.md").read_text()[:10000]
    cases = [{"name": "text", "frames": 0, "messages": [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Read the specification below and explain its main rules and their implications in detail. "
         "Write at least 400 words.\n\n" + spec},
    ]}]
    # Fixed real CVBench videos. Decode once; every request reuses identical JPEG bytes.
    videos = ["0/0Hd95ulYOT8.mp4", "0/XW-lrijc1oQ.mp4"]
    for count in frame_counts:
        content, metadata = [], []
        for number, relative in enumerate(videos, 1):
            frames, meta = sample_frames(Path("/assets/cvbench") / relative, count=count // 2, max_side=448)
            content.append({"type": "text", "text": f"Video {number}:"})
            content.extend({"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + frame}}
                           for frame in frames)
            metadata.append({"path": relative, **meta})
        content.append({"type": "text", "text": "Describe the visible events in each video in temporal order, "
                        "then compare the scenes, participants, actions, and outcomes. Base your explanation on "
                        "visible evidence and distinguish uncertainty. Write at least 400 words."})
        cases.append({"name": f"video_{count}frames", "frames": sum(m["frames"] for m in metadata),
                      "media": metadata, "messages": [
                          {"role": "system", "content": "You are a helpful assistant."},
                          {"role": "user", "content": content}]})
    for case in cases:
        case["messages_sha256"] = digest(case["messages"])
    save(path, cases)
    return cases


def request_once(client, body_bytes, *, endpoint="http://127.0.0.1:8100"):
    started = time.perf_counter()
    tokens, token_chunks, prompt_ids, text = [], [], None, []
    first_at = last_at = None
    first_chunk_tokens = 0
    usage, finish = None, None
    with client.stream("POST", endpoint.rstrip("/") + "/v1/chat/completions", content=body_bytes,
                       headers={"Content-Type": "application/json"}) as response:
        if response.status_code != 200:
            raise RuntimeError(f"HTTP {response.status_code}: {response.read().decode()[:2000]}")
        for line in response.iter_lines():
            if not line.startswith("data: "):
                continue
            payload = line[6:]
            if payload == "[DONE]":
                break
            chunk = json.loads(payload)
            if "error" in chunk:
                raise RuntimeError(str(chunk["error"]))
            if chunk.get("prompt_token_ids") is not None:
                prompt_ids = chunk["prompt_token_ids"]
            if chunk.get("usage") is not None:
                usage = chunk["usage"]
            for choice in chunk.get("choices", []):
                ids = choice.get("token_ids") or []
                if ids:
                    arrived = time.perf_counter()
                    if first_at is None:
                        first_at, first_chunk_tokens = arrived, len(ids)
                    last_at = arrived
                    tokens.extend(ids)
                    token_chunks.append({"seconds": arrived - started, "token_ids": ids})
                delta = choice.get("delta", {})
                text.append(delta.get("content") or "")
                text.append(delta.get("reasoning") or delta.get("reasoning_content") or "")
                finish = choice.get("finish_reason") or finish
    ended = time.perf_counter()
    if not tokens or prompt_ids is None or usage is None:
        raise RuntimeError("Response omitted generated token IDs, prompt token IDs, or usage")
    if len(tokens) != usage["completion_tokens"]:
        raise RuntimeError(f"Token count differs from usage: {len(tokens)} vs {usage}")
    decode_seconds = last_at - first_at
    return {"seconds": ended - started, "ttft_seconds": first_at - started,
            "decode_seconds": decode_seconds,
            "decode_tokens_per_second": (len(tokens) - first_chunk_tokens) / decode_seconds if decode_seconds else None,
            "end_to_end_tokens_per_second": len(tokens) / (ended - started),
            "token_ids": tokens, "token_ids_sha256": digest(tokens),
            "prompt_token_ids_sha256": digest(prompt_ids), "prompt_tokens": len(prompt_ids),
            "output_tokens": len(tokens), "text": "".join(text), "usage": usage,
            "finish_reason": finish, "token_chunks": token_chunks}


def summarize(records):
    grouped = {}
    for row in records:
        if row["warmup"]:
            continue
        grouped.setdefault(row["case"], []).append(row)
    result = {}
    for name, rows in grouped.items():
        base = rows[0]["token_ids"]
        mismatches = []
        for row in rows[1:]:
            if row["token_ids"] != base:
                pos = next((i for i, (a, b) in enumerate(zip(base, row["token_ids"])) if a != b),
                           min(len(base), len(row["token_ids"])))
                mismatches.append({"repeat": row["repeat"], "first_different_token_index": pos})
        result[name] = {"samples": len(rows), "prompt_tokens": rows[0]["prompt_tokens"],
                        "output_tokens": sorted({r["output_tokens"] for r in rows}),
                        "unique_outputs": len({r["token_ids_sha256"] for r in rows}),
                        "identical_to_first": sum(r["token_ids"] == base for r in rows),
                        "unique_prompt_token_hashes": len({r["prompt_token_ids_sha256"] for r in rows}),
                        "mismatches": mismatches}
        all_rows = [r for r in records if r["case"] == name]
        result[name]["unique_outputs_including_warmup"] = len({r["token_ids_sha256"] for r in all_rows})
        result[name]["warmup_matches_measured_first"] = all(
            r["token_ids"] == base for r in all_rows if r["warmup"])
        for field in ["seconds", "ttft_seconds", "decode_tokens_per_second", "end_to_end_tokens_per_second"]:
            vals = [r[field] for r in rows if r[field] is not None]
            result[name][field + "_median"] = statistics.median(vals) if vals else None
            result[name][field + "_min"] = min(vals) if vals else None
            result[name][field + "_max"] = max(vals) if vals else None
    return result


def stop_server(process):
    # This process group belongs exclusively to the server this script started.
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=45)
    except ProcessLookupError:
        pass
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=15)
    time.sleep(3)


def run_cell(args, model, precision, cases):
    import httpx

    out = args.output
    key = f"{model}_{precision}"
    cell = out / key
    cell.mkdir(exist_ok=True)
    base = Path("/weights") / model
    checkpoint = Path(str(base) + ("-FP8" if precision == "fp8" else ""))
    command = ["vllm", "serve", str(checkpoint), "--served-model-name", "bench",
               "--tokenizer", str(base), "--host", "127.0.0.1", "--port", "8100",
               "--tensor-parallel-size", "8", "--data-parallel-size", "1",
               "--dtype", "bfloat16", "--kv-cache-dtype", "auto", "--seed", "0",
               "--generation-config", "vllm", "--max-model-len", str(args.max_model_len),
               "--max-num-seqs", "1", "--max-num-batched-tokens", "8192",
               "--gpu-memory-utilization", "0.85", "--no-enable-prefix-caching",
               "--mm-processor-cache-gb", "0", "--mm-encoder-tp-mode", "weights",
               "--limit-mm-per-prompt", json.dumps({"image": {"count": max(args.frames), "width": 448, "height": 448}, "video": 0}),
               "--default-chat-template-kwargs", '{"enable_thinking": false}']
    env = os.environ.copy()
    env.update({"CUDA_VISIBLE_DEVICES": "0,1,2,3,4,5,6,7", "CUDA_DEVICE_ORDER": "PCI_BUS_ID",
                "VLLM_BATCH_INVARIANT": "0", "TOKENIZERS_PARALLELISM": "false"})
    config = json.loads((checkpoint / "config.json").read_text())
    provenance = checkpoint / "_download_manifest.json"
    save(cell / "config.json", {"command": command, "quantization_config": config.get("quantization_config"),
                               "source": json.loads(provenance.read_text()) if provenance.exists() else None})
    records = []
    event(out, "loading", cell=key, valid_samples=0)
    started = time.monotonic()
    with (cell / "server.log").open("w") as log:
        process = subprocess.Popen(command, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            with httpx.Client(timeout=900, trust_env=False) as client:
                while True:
                    if process.poll() is not None:
                        raise RuntimeError(f"vLLM exited with {process.returncode}; see {cell}/server.log")
                    try:
                        response = client.get("http://127.0.0.1:8100/health", timeout=2)
                        if response.status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    if time.monotonic() - started > args.startup_timeout:
                        raise TimeoutError("vLLM startup exceeded the per-cell time budget")
                    time.sleep(5)
                event(out, "ready", cell=key, load_seconds=round(time.monotonic() - started, 2))
                bodies = {}
                for case in cases:
                    body = {"model": "bench", "messages": case["messages"], "temperature": 0,
                            "top_p": 1, "seed": 0, "max_tokens": args.output_tokens,
                            "min_tokens": args.output_tokens, "ignore_eos": True,
                            "stream": True, "stream_options": {"include_usage": True},
                            "return_token_ids": True, "chat_template_kwargs": {"enable_thinking": False}}
                    bodies[case["name"]] = json.dumps(body, separators=(",", ":")).encode()
                    save(cell / f"request_{case['name']}.json", body)
                # Warm each shape once; interleave measured repeats across shapes to exercise normal cache history.
                with (cell / "records.jsonl").open("a", buffering=1) as raw:
                    for repeat in range(-1, args.repeats):
                        for case in cases:
                            body_bytes = bodies[case["name"]]
                            row = {"model": model, "precision": precision, "case": case["name"],
                                   "repeat": repeat, "warmup": repeat == -1,
                                   "request_sha256": hashlib.sha256(body_bytes).hexdigest(),
                                   **request_once(client, body_bytes)}
                            if row["output_tokens"] != args.output_tokens:
                                raise RuntimeError(f"Unexpected output length: {row['output_tokens']}")
                            raw.write(json.dumps(row) + "\n")
                            raw.flush()
                            records.append(row)
                            result = summarize(records)
                            save(cell / "summary.json", result)
                            event(out, "measuring", cell=key, case=case["name"], repeat=repeat,
                                  valid_samples=sum(not r["warmup"] for r in records),
                                  seconds=round(row["seconds"], 4), token_hash=row["token_ids_sha256"])
                save(cell / "complete.json", {"cell": key, "summary": result})
                return result
        finally:
            stop_server(process)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--frames", type=int, nargs="+", default=[32, 128, 512])
    parser.add_argument("--repeats", type=int, default=10)
    parser.add_argument("--output-tokens", type=int, default=256)
    parser.add_argument("--max-model-len", type=int, default=131072)
    parser.add_argument("--startup-timeout", type=int, default=1200)
    parser.add_argument("--models", nargs="+", default=["Qwen3.5-9B", "Qwen3.5-27B", "Qwen3.5-35B-A3B"])
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if not str(args.output).startswith("/runs/"):
        raise SystemExit("Experiment artifacts must stay in the Modal runs volume")
    if (args.output / "manifest.json").exists():
        raise SystemExit("Use a new output directory; this probe does not append to an old experiment")
    inventory = subprocess.check_output(["nvidia-smi", "--query-gpu=index,name,uuid,memory.total,driver_version", "--format=csv"], text=True)
    if inventory.count("H100") != 8:
        raise SystemExit(f"Expected exactly eight H100 GPUs: {inventory}")
    source = Path(__file__).read_text()
    (args.output / "benchmark_source.py").write_text(source)
    save(args.output / "manifest.json", {"arguments": {**vars(args), "output": str(args.output)},
         "gpu_inventory": inventory, "versions": {p: importlib.metadata.version(p) for p in ["vllm", "torch", "transformers"]},
         "git_commit": subprocess.check_output(["git", "-c", f"safe.directory={ROOT}", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip(),
         "script_sha256": hashlib.sha256(source.encode()).hexdigest(), "tp": 8, "dp": 1,
         "concurrency": 1, "prefix_cache": False, "mm_processor_cache_gb": 0,
         "sampling": "greedy, seed=0, thinking off; fixed output length with min_tokens and ignore_eos",
         "limits": "Within-server repeatability for the recorded inputs; not cross-restart, cross-hardware, concurrent-load, or accuracy evidence."})
    event(args.output, "preparing_inputs", valid_samples=0)
    cases = prepare_inputs(args.output, args.frames)
    save(args.output / "input_manifest.json", [{k: v for k, v in c.items() if k != "messages"} for c in cases])
    matrix = {}
    for i, model in enumerate(args.models):
        for precision in (["bf16", "fp8"] if i % 2 == 0 else ["fp8", "bf16"]):
            key = f"{model}_{precision}"
            try:
                matrix[key] = {"status": "complete", "cases": run_cell(args, model, precision, cases)}
            except Exception as exc:
                matrix[key] = {"status": "failed", "error": str(exc), "traceback": traceback.format_exc()}
                event(args.output, "cell_failed", cell=key, error=str(exc))
            save(args.output / "summary.json", matrix)
    event(args.output, "finished", completed_cells=sum(v["status"] == "complete" for v in matrix.values()),
          failed_cells=sum(v["status"] == "failed" for v in matrix.values()))


if __name__ == "__main__":
    main()
