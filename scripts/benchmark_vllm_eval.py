#!/usr/bin/env python3
"""Measure the real CVBench E2E pipeline and exact output tokens on a frozen panel.

Default timing includes media-cache reads, request construction, serving, and
official scoring. --prepared reuses request bytes; --cold-media includes initial
video decoding. Each mode still invokes the model for every request. Run on Modal.
"""
from __future__ import annotations

import argparse
import base64
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import copy
import hashlib
import heapq
import importlib.metadata
import json
import os
from pathlib import Path
import queue
import random
import signal
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
import traceback

from benchmark_qwen35_fp8 import digest, event, request_once, save
from benchmark_qwen35_throughput import Pool
from benchmark_vllm_options import VARIANTS, metrics

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval/e2e_eval"))
from harness.cvbench import CVBench
from harness.media import CACHE_ENV


def encode_request(messages, generation):
    body = dict(model="bench", messages=messages, **generation, seed=0, stream=True,
                stream_options={"include_usage": True}, return_token_ids=True,
                chat_template_kwargs={"enable_thinking": False})
    return json.dumps(body, separators=(",", ":")).encode()


class TokenBackend:
    def __init__(self, endpoints, concurrency, routing=None):
        self.endpoints, self.routing = endpoints, routing
        self.per_replica = [threading.BoundedSemaphore(concurrency) for _ in endpoints]
        self.slots = queue.Queue()
        for index, endpoint in enumerate(endpoints):
            for _ in range(concurrency):
                self.slots.put((index, endpoint))
        self.local = threading.local()

    def complete(self, messages, **generation):
        return self.send(encode_request(messages, generation), digest(messages), generation)

    def send(self, wire, messages_hash, generation, semantic_request_sha256=None):
        import httpx
        if not hasattr(self.local, "client"):
            self.local.client = httpx.Client(timeout=900, trust_env=False)
        if self.routing is None:
            replica, endpoint = self.slots.get()
        else:
            replica = self.routing[messages_hash]
            endpoint = self.endpoints[replica]
            self.per_replica[replica].acquire()
        try:
            row = request_once(self.local.client, wire, endpoint=endpoint)
        finally:
            if self.routing is None:
                self.slots.put((replica, endpoint))
            else:
                self.per_replica[replica].release()
        row.update(replica=replica, messages_sha256=messages_hash,
                   request_sha256=hashlib.sha256(wire).hexdigest(), generation=generation)
        if semantic_request_sha256 is not None:
            row['semantic_request_sha256'] = semantic_request_sha256
        return row["text"], row


def evaluate_pass(args, directory, label, benchmark, selected, expected, backend, references, seed, prepared):
    items = selected.copy()
    random.Random(seed).shuffle(items)
    rows, scored, errors, mismatches = [], [], [], []
    def infer(item):
        if prepared is None:
            return benchmark.infer(item, backend)
        case = prepared[item["sample_id"]]
        wire_key = ('wire_plain' if label == 'base_reference' else
                    'wire' if label == 'pass0' else 'wire_cached') if args.media_uuids else 'wire'
        wire = case[wire_key]
        text, request = backend.send(wire, case["messages_sha256"], case["generation"],
                                     case.get('semantic_request_sha256'))
        return {"output": text, "request": request, "media": case["media"]}
    started = time.perf_counter()
    with (directory / "raw.jsonl").open("a", buffering=1) as raw, ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(infer, item): item for item in items}
        for future in as_completed(futures):
            item = futures[future]
            try:
                record = {"sample_id": item["sample_id"], "task": item["task"], "pass": label, **future.result()}
                raw.write(json.dumps(record) + "\n")  # Save unscored model output first.
                request = record["request"]
                key = item["sample_id"]
                if request["messages_sha256"] != expected[key]:
                    raise RuntimeError(f"Frozen input mismatch: {key}")
                if key not in references:
                    fields = ["token_ids", "prompt_token_ids_sha256", "request_sha256"]
                    if args.media_uuids:
                        fields.append('semantic_request_sha256')
                    references[key] = {k: request[k] for k in fields}
                reference = references[key]
                request_key = 'semantic_request_sha256' if args.media_uuids else 'request_sha256'
                if any(reference[k] != request[k] for k in ["prompt_token_ids_sha256", request_key]):
                    raise RuntimeError(f"Request/prompt token hash mismatch: {key}")
                if args.media_uuids:
                    wire_key = ('semantic_request_sha256' if label == 'base_reference' else
                                'full_sha256' if label == 'pass0' else 'cached_sha256')
                    if request['request_sha256'] != prepared[key][wire_key]:
                        raise RuntimeError(f'Unexpected UUID wire payload: {key}')
                if request["token_ids"] != reference["token_ids"]:
                    pos = next((i for i, (a, b) in enumerate(zip(reference["token_ids"], request["token_ids"])) if a != b),
                               min(len(reference["token_ids"]), len(request["token_ids"])))
                    mismatches.append({"sample_id": key, "replica": request["replica"], "first_different_token": pos})
                rows.append(record)
                scored.append({"sample_id": key, "task": item["task"], **benchmark.score(item, record["output"])})
                event(directory, "measuring", pass_name=label, samples=len(rows), mismatches=len(mismatches), sample_id=key)
            except Exception as exc:
                errors.append({"sample_id": item["sample_id"], "error": repr(exc), "traceback": traceback.format_exc()})
    elapsed = time.perf_counter() - started
    save(directory / f"{label}_scored.json", scored)
    save(directory / "references.json", references)
    population = Counter(item["task"] for item in benchmark.items)
    by_task = {task: [r for r in scored if r["task"] == task] for task in {r["task"] for r in scored}}
    def estimated_score(field):
        weight = sum(population[t] for t in by_task)
        return sum(population[t] * sum(r[field] for r in group) / len(group) for t, group in by_task.items()) / weight if weight else None
    result = {"name": label, "samples": len(rows), "seconds": elapsed, "questions_per_minute": len(rows) * 60 / elapsed,
              "stable": len(rows) == len(items) and not errors and not mismatches, "mismatches": mismatches, "errors": errors,
              "panel_accuracy": sum(r["score"] for r in scored) / len(scored) if scored else None,
              "estimated_official_accuracy": estimated_score("score"),
              "estimated_robust_accuracy": estimated_score("robust_score"),
              "output_tokens": sum(r["request"]["output_tokens"] for r in rows),
              "replicas_used": sorted({r["request"]["replica"] for r in rows})}
    save(directory / f"{label}.json", result)
    return result


def main():
    signal.signal(signal.SIGTERM, signal.default_int_handler)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--panel", type=Path, required=True)
    parser.add_argument("--variants", nargs="+", choices=list(VARIANTS), required=True)
    parser.add_argument("--model-size", choices=["9B", "27B", "35B-A3B"], default="35B-A3B")
    parser.add_argument('--replicas', type=int, default=8)
    parser.add_argument('--gpu-offset', type=int, default=0)
    parser.add_argument('--limit', type=int, help='Bound the frozen panel for a protocol smoke test')
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--routing", choices=["dynamic", "sticky", "balanced"], default="dynamic")
    parser.add_argument("--routing-costs", type=Path,
                        help="Prior variant directory with restart*/raw.jsonl; balance sticky routes by measured warm request times")
    parser.add_argument("--prepared", action="store_true",
                        help="Cache exact input request bytes once; responses are always generated anew")
    parser.add_argument('--media-uuids', action='store_true',
                        help='Prepared/sticky only: first pass uploads content-hashed images; warm passes send cache UUIDs. Cache misses fail.')
    parser.add_argument("--cold-media", action="store_true",
                        help="Start each variant with an empty application media cache; pass0 includes video decoding")
    parser.add_argument("--restarts", type=int, default=1)
    parser.add_argument("--passes", type=int, default=3)
    parser.add_argument("--startup-timeout", type=int, default=1200)
    args = parser.parse_args()
    if not 1 <= args.replicas <= 8 or not 0 <= args.gpu_offset <= 8 - args.replicas:
        raise SystemExit('Invalid GPU allocation')
    if args.limit is not None and args.limit < 1:
        raise SystemExit('Panel limit must be positive')
    if args.prepared and args.cold_media:
        raise SystemExit("Prepared requests cannot measure cold video decoding")
    if args.media_uuids and (not args.prepared or args.routing == 'dynamic'):
        raise SystemExit('Media UUID mode requires prepared inputs and fixed routing')
    if args.media_uuids and any(float(VARIANTS[v].get('flags', {}).get('--mm-processor-cache-gb', 0)) <= 0 for v in args.variants):
        raise SystemExit('Media UUID mode requires an enabled processor cache in every variant')
    if (args.routing == "balanced") != bool(args.routing_costs):
        raise SystemExit("Balanced routing requires --routing-costs; other routing modes do not use it")
    if not str(args.output).startswith("/runs/") or (args.output / "manifest.json").exists():
        raise SystemExit("Use a fresh /runs/ directory")
    args.output.mkdir(parents=True, exist_ok=True)
    preparation_started = time.perf_counter()
    selected = json.loads((args.panel / "selection.json").read_text())
    if args.limit is not None:
        selected = selected[:args.limit]
    cases = json.loads((args.panel / "inputs.json").read_text())
    selected_ids = {item['sample_id'] for item in selected}
    cases = [case for case in cases if case['name'] in selected_ids]
    expected = {c["name"]: c["messages_sha256"] for c in cases}
    prepared = None
    if args.prepared:
        prepared = {}
        for case in cases:
            if digest(case["messages"]) != expected[case["name"]]:
                raise RuntimeError("Frozen messages were modified")
            prepared[case["name"]] = {"wire": encode_request(case["messages"], case["generation"]),
                                     **{k: case[k] for k in ["generation", "messages_sha256", "media"]}}
            if args.media_uuids:
                record = prepared[case['name']]
                record['semantic_request_sha256'] = hashlib.sha256(record['wire']).hexdigest()
                record['wire_plain'] = record['wire']
                full, cached = copy.deepcopy(case['messages']), copy.deepcopy(case['messages'])
                uuids = []
                for full_message, cached_message in zip(full, cached, strict=True):
                    if not isinstance(full_message['content'], list):
                        continue
                    for item, cached_item in zip(full_message['content'], cached_message['content'], strict=True):
                        if item.get('type') != 'image_url':
                            continue
                        url = item['image_url']['url']
                        if not url.startswith('data:image/jpeg;base64,'):
                            raise SystemExit('Frozen UUID experiment only accepts embedded JPEG inputs')
                        uuid = 'sha256:' + hashlib.sha256(base64.b64decode(url.split(',', 1)[1], validate=True)).hexdigest()
                        item['uuid'] = cached_item['uuid'] = uuid
                        cached_item['image_url'] = None
                        uuids.append(uuid)
                record['wire'] = encode_request(full, case['generation'])
                record['wire_cached'] = encode_request(cached, case['generation'])
                record['full_sha256'] = hashlib.sha256(record['wire']).hexdigest()
                record['cached_sha256'] = hashlib.sha256(record['wire_cached']).hexdigest()
                record['media_uuids'] = uuids
    preparation_seconds = time.perf_counter() - preparation_started
    del cases
    routing_base = {expected[item['sample_id']]: i % args.replicas for i, item in enumerate(selected)}
    routing_provenance = None
    if args.routing == 'balanced':
        observed, hashes = defaultdict(list), {}
        for path in sorted(args.routing_costs.glob('restart*/raw.jsonl')):
            hashes[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
            with path.open() as handle:
                for line in handle:
                    row = json.loads(line)
                    if row['pass'] != 'pass0':
                        observed[row['sample_id']].append(row['request']['seconds'])
        costs = {item['sample_id']: sum(observed[item['sample_id']]) / len(observed[item['sample_id']])
                 for item in selected if observed[item['sample_id']]}
        if set(costs) != {item['sample_id'] for item in selected}:
            raise SystemExit('Routing calibration must contain warm measurements for every panel question')
        loads = [(0., i) for i in range(args.replicas)]
        routing_base = {}
        for sample_id in sorted(costs, key=lambda name: (-costs[name], name)):
            load, replica = heapq.heappop(loads)
            routing_base[expected[sample_id]] = replica
            heapq.heappush(loads, (load + costs[sample_id], replica))
        routing_provenance = {'source_sha256': hashes, 'mean_request_seconds': costs,
                              'estimated_replica_seconds': sorted(loads, key=lambda row: row[1]),
                              'scope': 'Routing calibrated on this development panel; no generalization claim'}
    os.environ[CACHE_ENV] = str(args.panel / "media_cache")
    protocol = json.loads((args.panel / "protocol.json").read_text())
    benchmark = CVBench(data_root=Path("/assets"), frames=512, max_side=protocol["max_side"])
    sources = {}
    for path in [Path(__file__), *(ROOT / "eval/e2e_eval/harness").glob("*.py"),
                 *(ROOT / "scripts" / name for name in ["benchmark_qwen35_fp8.py", "benchmark_qwen35_throughput.py", "benchmark_vllm_options.py"])]:
        relative = path.relative_to(ROOT)
        target = args.output / "source" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes())
        sources[str(relative)] = hashlib.sha256(path.read_bytes()).hexdigest()
    inventory = subprocess.check_output(["nvidia-smi", "--query-gpu=index,name,uuid,memory.total", "--format=csv"], text=True)
    if inventory.count("H100") != 8:
        raise SystemExit("Expected eight H100 GPUs")
    save(args.output / "manifest.json", {"arguments": {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()},
         "sources_sha256": sources, "protocol": protocol, "panel_sha256": hashlib.sha256((args.panel / "inputs.json").read_bytes()).hexdigest(),
         "gpu_inventory": inventory, "versions": {p: importlib.metadata.version(p) for p in ["vllm", "torch", "transformers"]},
         "input_preparation_seconds": preparation_seconds,
         "selected_sample_ids": [item['sample_id'] for item in selected],
         "routing_base": routing_base if args.routing != 'dynamic' else None,
         "routing_provenance": routing_provenance,
         "prepared_request_sha256": {name: hashlib.sha256(case["wire"]).hexdigest() for name, case in prepared.items()} if prepared else None,
         "media_uuid_inputs": {name: {k: case[k] for k in ['semantic_request_sha256', 'full_sha256', 'cached_sha256', 'media_uuids']}
                               for name, case in prepared.items()} if args.media_uuids else None,
         "prepared_wire_bytes": sum(len(c['wire']) for c in prepared.values()) if prepared else None,
         "prepared_cached_wire_bytes": sum(len(c['wire_cached']) for c in prepared.values()) if args.media_uuids else None,
         "git_commit": subprocess.check_output(["git", "-c", "safe.directory=/repo", "rev-parse", "HEAD"], text=True).strip(),
         "timing_scope": ("First validate unmodified full JPEG requests, then full JPEGs with content UUIDs; warm passes send UUIDs only and fail on cache misses. All three wire forms must match the original request's prompt and output tokens. Still invokes model on every call."
                          if args.media_uuids else "Exact request bytes cached in memory; includes request send, inference, token/hash audit and official scoring. One-time request preparation recorded separately."
                          if args.prepared else ("First pass starts with empty application media cache and includes video decoding; OS page cache is not controlled. Later passes reuse media cache. All include inference, token/hash audit and scoring."
                          if args.cold_media else "Warm media disk cache; includes cache reads, JSON/JPEG request construction, inference, token/hash audit and official scoring. Excludes initial decode and model loading."))})
    summaries = []
    for name in args.variants:
        config, references, passes = VARIANTS[name], {}, []
        root = args.output / name
        root.mkdir()
        if args.cold_media:
            os.environ[CACHE_ENV] = str(root / "media_cache")
        result = {"variant": name, "passes": passes, "stable": False, "error": None}
        try:
            for restart in range(args.restarts + 1):
                directory = root / f"restart{restart}"
                directory.mkdir()
                pool = Pool(SimpleNamespace(output=directory, startup_timeout=args.startup_timeout), directory)
                try:
                    event(args.output, "loading", variant=name, restart=restart)
                    pool.start(config.get("precision", "fp8"), 1, args.replicas, config.get("invariant", 0), 8, 16384,
                               "weights", flags=config.get("flags"), env_overrides=config.get("env"), model_size=args.model_size,
                               gpu_offset=args.gpu_offset, port_offset=args.gpu_offset)
                    # A frozen, balanced question-to-replica map; avoids tying repeatability to timing.
                    # Shift after restart so the same case is also checked on a different GPU.
                    routing = ({key: (replica + restart) % args.replicas for key, replica in routing_base.items()}
                               if args.routing != "dynamic" else None)
                    backend = TokenBackend(pool.endpoints, args.concurrency, routing)
                    metrics(directory, "start", pool.endpoints)
                    labels = (['base_reference'] if args.media_uuids else []) + [f'pass{i}' for i in range(args.passes)]
                    for label in labels:
                        repeat = -1 if label == 'base_reference' else int(label[4:])
                        measured = evaluate_pass(args, directory, label, benchmark, selected, expected,
                                                 backend, references, 83100 + restart * 100 + repeat, prepared)
                        passes.append({"restart": restart, **measured})
                        save(root / "summary.json", result)
                        event(args.output, "pass_finished", variant=name, restart=restart, **measured)
                        metrics(directory, f'after_{label}', pool.endpoints)
                        if not measured["stable"]:
                            raise RuntimeError("E2E pass failed exact-token validation")
                    metrics(directory, "end", pool.endpoints)
                finally:
                    pool.close()
            result["stable"] = True
        except Exception as exc:
            result.update(error=repr(exc), traceback=traceback.format_exc())
        measured = [p for p in passes if p["name"] not in {"pass0", "base_reference"}]
        result.update(formal_samples=sum(p["samples"] for p in measured), warmup_samples=sum(p["samples"] for p in passes if p["name"] in {"pass0", "base_reference"}),
                      mismatches=sum(len(p["mismatches"]) for p in passes),
                      questions_per_minute=sum(p["samples"] for p in measured) * 60 / sum(p["seconds"] for p in measured) if measured else None)
        save(root / "summary.json", result)
        summaries.append(result)
        save(args.output / "summary.json", summaries)
    event(args.output, "finished", formal_samples=sum(s["formal_samples"] for s in summaries),
          warmup_samples=sum(s["warmup_samples"] for s in summaries), stable=[s["variant"] for s in summaries if s["stable"]])


if __name__ == "__main__":
    main()
