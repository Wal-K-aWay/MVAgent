#!/usr/bin/env python3
"""Build a version-2 Train/Cal/Gate split from CrossVid closed tasks, excluding Lite2500 question IDs.

Questions sharing any source video (or UAV sequence) form one connected source group; a group lives in
exactly one partition. Lite2500 questions are excluded by ID only: excluding every Lite2500 source group
would leave no CC/FSA/NC questions, so source overlap with the panel is reported instead.
Per task, rows are taken in a seeded order until the train/cal/eval quotas are met.
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

CLOSED_TASKS = ("BU", "CC", "FSA", "MOC", "MSR", "NC", "PEA", "PI", "PSS")
ALL_TASKS = (*CLOSED_TASKS, "CCQA")


def source_keys(task: str, row: dict) -> list[str]:
    if task in ("MOC", "MSR"):
        return [f"uav:{row['vid']}"]
    keys = []
    for field in ("videos", "video", "video A", "video B"):
        value = row.get(field)
        for item in value if isinstance(value, list) else [value]:
            if item:
                keys.append(f"video:{item}")
    return keys


def components(rows: dict[str, list[str]]) -> dict[str, str]:
    parent = {sid: sid for sid in rows}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    owner: dict[str, str] = {}
    for sid, keys in rows.items():
        for key in keys:
            if key in owner:
                a, b = find(sid), find(owner[key])
                parent[max(a, b)] = min(a, b)
            else:
                owner[key] = sid
    return {sid: find(sid) for sid in rows}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--qa-dir", type=Path, required=True, help="CrossVid QA/ directory")
    ap.add_argument("--exclude-panel", type=Path, required=True, help="Lite2500 split manifest")
    ap.add_argument("--per-task", default="8,4,4", help="train,cal,eval questions per task")
    ap.add_argument("--seed", type=int, default=20261006)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    quota = dict(zip(("train", "cal", "eval"), map(int, args.per_task.split(","))))

    rows, task_of = {}, {}
    for task in ALL_TASKS:
        for row in json.loads((args.qa_dir / f"{task}.json").read_text(encoding="utf-8")):
            sid = f"crossvid:{task}:{row['id']}"
            rows[sid], task_of[sid] = source_keys(task, row), task
    group = components(rows)
    panel = {s["sample_id"] for s in json.loads(args.exclude_panel.read_text(encoding="utf-8"))["samples"]}
    panel_groups = {group[sid] for sid in panel if sid in group}

    rng = random.Random(args.seed)
    group_split: dict[str, str] = {}
    samples = []
    for task in CLOSED_TASKS:
        candidates = sorted(s for s in rows if task_of[s] == task and s not in panel)
        rng.shuffle(candidates)
        need = dict(quota)
        for sid in candidates:
            if not any(need.values()):
                break
            assigned = group_split.get(group[sid])
            split = assigned if assigned and need.get(assigned) else (
                None if assigned else next((name for name in ("train", "cal", "eval") if need[name]), None))
            if split is None:
                continue
            group_split[group[sid]] = split
            need[split] -= 1
            samples.append({"sample_id": sid, "split": split, "group_id": group[sid]})
        if any(need.values()):
            raise ValueError(f"{task}: not enough source-isolated questions for {need}")

    manifest = {"version": 2, "dataset": "crossvid_closed_outside_lite2500", "seed": args.seed, "samples": samples}
    args.output.write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    counts = {name: sum(s["split"] == name for s in samples) for name in quota}
    shared = sum(s["group_id"] in panel_groups for s in samples)
    print(f"{len(samples)} questions {counts}; {shared} share a source group with Lite2500 (IDs excluded)")


if __name__ == "__main__":
    main()
