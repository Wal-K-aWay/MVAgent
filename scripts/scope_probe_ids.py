#!/usr/bin/env python3
"""Question lists for the scope component probes (standard library only).

  t_ids.json   all Train questions (from scope_k1_prepare.py t_cases.jsonl)
  k3_ids.json  Train questions from closed tasks, equal per task (determinism, reuse, selector fidelity)
  k4_ids.json  non-Lite closed-task questions sharing no video source with Train, equal per task (placebo)
CCQA is left out of K3/K4 so no Judge is needed. Selection is outcome-blind.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from prepare_crossvid_clean_pool import TASKS, sources  # noqa: E402

CLOSED = [t for t in TASKS if t != "CCQA"]


def stratified(ids, per_task, rng):
    by_task = defaultdict(list)
    for sid in sorted(ids):
        by_task[sid.split(":")[1]].append(sid)
    out = []
    for task in CLOSED:
        group = by_task[task]
        rng.shuffle(group)
        out += group[:per_task]
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--t-cases", type=Path, required=True)
    ap.add_argument("--raw-qa", type=Path, required=True)
    ap.add_argument("--panel", type=Path, default=Path("eval/crossvid_2500.json"))
    ap.add_argument("--k3-per-task", type=int, default=6)
    ap.add_argument("--k4-per-task", type=int, default=27)
    ap.add_argument("--seed", type=int, default=20261007)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    train = [json.loads(line)["sid"] for line in args.t_cases.read_text().splitlines()]
    rows = {}
    for task in TASKS:
        for row in json.loads((args.raw_qa / f"{task}.json").read_text()):
            rows[f"crossvid:{task}:{row['id']}"] = sources(task, row)
    panel = set(json.loads(args.panel.read_text()))
    used = set().union(*(rows[s] for s in train))
    rng = random.Random(args.seed)
    k3 = stratified(train, args.k3_per_task, rng)
    pool = [s for s in rows if s not in panel and s not in train and not rows[s] & used]
    k4 = stratified(pool, args.k4_per_task, rng)
    args.out.mkdir(parents=True, exist_ok=True)
    for name, ids in (("t_ids", sorted(train)), ("k3_ids", k3), ("k4_ids", k4)):
        (args.out / f"{name}.json").write_text(json.dumps(ids, indent=1) + "\n")
        print(name, len(ids))


if __name__ == "__main__":
    main()
