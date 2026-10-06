#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from skill_evolution.infra.data import DataSplitManifest, SplitSample, group_by_media
from skill_evolution.infra.store import file_fingerprint


def _manifest_paths(root: Path) -> tuple[Path, ...]:
    if root.is_file():
        return (root,) if root.suffix == ".jsonl" else ()
    manifest = root / "qa.jsonl"
    return (manifest,) if manifest.is_file() else ()


def _resolved_videos(videos: Mapping[str, Any], *, base_dir: Path) -> dict[str, str]:
    resolved: dict[str, str] = {}
    for video_id, value in videos.items():
        path = Path(str(value)).expanduser()
        if not path.is_absolute():
            path = base_dir / path
        resolved[str(video_id)] = str(path.resolve())
    return resolved


def _load_records(root: Path) -> list[dict[str, str]]:
    records, media = [], {}
    for manifest in _manifest_paths(root):
        for line in manifest.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            raw = json.loads(line)
            if not re.fullmatch(r"[A-Z]", str(raw.get("answer") or "").strip().upper()):
                continue
            sid = raw["id"]
            if sid in media:
                raise ValueError(f"Duplicate sample ID: {sid}")
            media[sid] = tuple(_resolved_videos(raw["videos"], base_dir=manifest.parent).values())
            records.append({"sample_id": sid, "task": raw["task"]})
    if not records:
        raise ValueError(f"No single-choice records found under {root}.")
    fingerprints = {p: file_fingerprint(p) for p in sorted({p for paths in media.values() for p in paths})}
    groups = group_by_media({sid: [fingerprints[p] for p in paths] for sid, paths in media.items()})
    return [{**record, "group_id": groups[record["sample_id"]]} for record in records]


def _excluded_ids(paths: tuple[str, ...]) -> set[str]:
    excluded: set[str] = set()
    for raw_path in paths:
        manifest = DataSplitManifest.from_json(raw_path)
        excluded.update(item.sample_id for item in manifest.samples)
    return excluded


def _stable_group_order(groups: set[str], *, seed: int, task: str) -> list[str]:
    return sorted(
        groups,
        key=lambda group: hashlib.sha256(
            f"{seed}:{task}:{group}".encode("utf-8")
        ).hexdigest(),
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare a task-stratified, media-group-disjoint CrossVid choice split."
    )
    parser.add_argument(
        "--records-root",
        required=True,
        help="Saved result-record directory, canonical qa.jsonl, or its parent directory.",
    )
    parser.add_argument("--output", required=True)
    parser.add_argument("--dataset", default="crossvid-choice-stratified")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--tasks",
        nargs="+",
        default=[],
        help="Optional task allow-list, for example: BU CC MOC MSR NC PEA PI.",
    )
    parser.add_argument("--train-groups-per-task", type=int, default=4)
    parser.add_argument("--eval-groups-per-task", type=int, default=2)
    parser.add_argument(
        "--one-sample-per-group",
        action="store_true",
        help=(
            "Keep one deterministic representative per selected media group so each "
            "per-task group count is also the exact sample count."
        ),
    )
    parser.add_argument("--exclude-manifest", action="append", default=[])
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    counts = {
        "train": args.train_groups_per_task,
        "eval": args.eval_groups_per_task,
    }
    if any(value < 1 for value in counts.values()):
        raise ValueError("Every per-task split count must be positive.")

    records = _load_records(Path(args.records_root).expanduser().resolve())
    requested_tasks = {str(task).strip() for task in args.tasks if str(task).strip()}
    if requested_tasks:
        available_tasks = {item["task"] for item in records}
        unknown_tasks = sorted(requested_tasks - available_tasks)
        if unknown_tasks:
            raise ValueError("Unknown requested tasks: " + ", ".join(unknown_tasks))
        records = [item for item in records if item["task"] in requested_tasks]
    by_id = {item["sample_id"]: item for item in records}
    excluded_ids = _excluded_ids(tuple(args.exclude_manifest))
    unknown_exclusions = sorted(excluded_ids - set(by_id))
    applicable_exclusions = excluded_ids & set(by_id)
    excluded_groups = {
        by_id[sample_id]["group_id"] for sample_id in applicable_exclusions
    }

    group_samples: dict[str, list[str]] = defaultdict(list)
    group_task: dict[str, str] = {}
    for item in records:
        group = item["group_id"]
        if group in excluded_groups:
            continue
        task = item["task"]
        if group in group_task and group_task[group] != task:
            raise ValueError(f"Media group {group} crosses task strata.")
        group_task[group] = task
        group_samples[group].append(item["sample_id"])

    task_groups: dict[str, set[str]] = defaultdict(set)
    for group, task in group_task.items():
        task_groups[task].add(group)
    required = sum(counts.values())
    insufficient = {
        task: len(groups)
        for task, groups in task_groups.items()
        if len(groups) < required
    }
    if insufficient:
        details = ", ".join(
            f"{task}={available}" for task, available in sorted(insufficient.items())
        )
        raise ValueError(f"Each task needs {required} media groups; insufficient: {details}")

    assignments: dict[str, dict[str, list[str]]] = {
        split: {} for split in ("train", "eval")
    }
    for task in sorted(task_groups):
        ordered = _stable_group_order(task_groups[task], seed=args.seed, task=task)
        offset = 0
        for split in ("train", "eval"):
            end = offset + counts[split]
            assignments[split][task] = ordered[offset:end]
            offset = end

    samples: list[SplitSample] = []
    for split in ("train", "eval"):
        task_names = sorted(assignments[split])
        for index in range(counts[split]):
            for task in task_names:
                group = assignments[split][task][index]
                sample_ids = sorted(group_samples[group])
                if args.one_sample_per_group:
                    sample_ids = sample_ids[:1]
                samples.extend(
                    SplitSample(sample_id=sample_id, split=split, group_id=group)
                    for sample_id in sample_ids
                )

    manifest = DataSplitManifest(
        dataset=args.dataset,
        seed=args.seed,
        samples=tuple(samples),
    )
    target = manifest.write(args.output)
    audit = {
        "output": str(target),
        "manifest_hash": manifest.manifest_hash,
        "excluded_sample_count": len(excluded_ids),
        "applicable_excluded_sample_count": len(applicable_exclusions),
        "absent_excluded_sample_count": len(unknown_exclusions),
        "excluded_group_count": len(excluded_groups),
        "one_sample_per_group": bool(args.one_sample_per_group),
        "sample_counts": {
            split: len(manifest.ids(split)) for split in ("train", "eval")
        },
        "group_counts": {
            split: len(
                {item.group_id for item in manifest.samples if item.split == split}
            )
            for split in ("train", "eval")
        },
        "task_sample_counts": {
            split: {
                task: sum(
                    1
                    for item in manifest.samples
                    if item.split == split and by_id[item.sample_id]["task"] == task
                )
                for task in sorted(task_groups)
            }
            for split in ("train", "eval")
        },
    }
    print(json.dumps(audit, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
