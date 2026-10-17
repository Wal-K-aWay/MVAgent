#!/usr/bin/env python3
"""Freeze a small, task-balanced CVBench speed/repro panel using the E2E protocol.

Run on Modal. No model call: retain exact messages, native generation settings,
media provenance, and the official scoring metadata on the runs volume.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval/e2e_eval"))
from harness.cvbench import CVBench, ADAPTER, TASK, QUESTIONS
from harness.media import CACHE_ENV
from benchmark_qwen35_fp8 import digest, event, save


class Capture:
    def complete(self, messages, **generation):
        self.messages, self.generation = messages, generation
        return "", {}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--per-task", type=int, default=2)
    parser.add_argument("--frames", type=int, default=512)
    parser.add_argument("--max-side", type=int, default=448)
    args = parser.parse_args()
    if not str(args.output).startswith("/runs/") or (args.output / "selection.json").exists():
        raise SystemExit("Use a fresh /runs/ directory")
    args.output.mkdir(parents=True, exist_ok=True)
    os.environ[CACHE_ENV] = str(args.output / "media_cache")
    benchmark = CVBench(data_root=Path("/assets"), frames=args.frames, max_side=args.max_side)
    groups = defaultdict(list)
    for item in benchmark.items:
        if item["sample_id"] not in {"cvbench:64", "cvbench:65", "cvbench:66"}:
            groups[item["task"]].append(item)
    selected = []
    for name, group in sorted(groups.items()):
        random.Random(20261010).shuffle(group)
        selected.extend(group[:args.per_task])
    save(args.output / "selection.json", selected)
    save(args.output / "protocol.json", benchmark.protocol())
    save(args.output / "manifest.json", {"arguments": {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()},
         "git_commit": subprocess.check_output(["git", "-c", "safe.directory=/repo", "rev-parse", "HEAD"], text=True).strip(),
         "seed": 20261010, "split_role": "development throughput panel; not held-out accuracy evaluation",
         "excluded_broken_media": ["cvbench:64", "cvbench:65", "cvbench:66"]})
    source_paths = [Path(__file__), *(ROOT / "eval/e2e_eval/harness").glob("*.py"), ADAPTER, TASK / "mvr.yaml", TASK / "utils.py", QUESTIONS]
    hashes = {}
    for path in source_paths:
        relative = path.relative_to(ROOT)
        target = args.output / "source" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes())
        hashes[str(relative)] = hashlib.sha256(path.read_bytes()).hexdigest()
    save(args.output / "source_hashes.json", hashes)
    cases = []
    started = time.monotonic()
    for item in selected:
        capture = Capture()
        record = benchmark.infer(item, capture)
        cases.append({"name": item["sample_id"], "task": item["task"], "frames": record["media"]["frames"],
                      "messages": capture.messages, "messages_sha256": digest(capture.messages),
                      "generation": capture.generation, "media": record["media"]})
        event(args.output, "preparing", completed=len(cases), total=len(selected), case=item["sample_id"])
    save(args.output / "inputs.json", cases)
    event(args.output, "finished", inputs=len(cases), tasks=len(groups),
          seconds=time.monotonic() - started, input_sha256=hashlib.sha256((args.output / "inputs.json").read_bytes()).hexdigest())


if __name__ == "__main__":
    main()
