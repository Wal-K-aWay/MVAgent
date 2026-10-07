#!/usr/bin/env python3
"""Where does the E2E frame budget meet the limits of the official preprocessing code?

For every question this reports how many frames the official code can actually deliver under a
given per-call budget F, and flags the cases the official code handles badly:
- CrossVid FSA/CCQA write a fixed F/2 frame placeholders per video, but `process_video` returns
  only min(F/2, video frames): a shorter video makes the official evaluate() fail.
- CrossVid MOC/MSR sample F/2 frames from a frame directory without capping, so a directory with
  fewer files yields repeated frames.
- Everything else delivers fewer frames than allocated for short videos/segments (harmless).
Also checks that every Lite2500 ID exists in the QA files. Run where /assets is mounted.
"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2


def videos_of(task: str, row: dict) -> list[str]:
    """Video files a CrossVid task script opens for one question (relative to crossvid/videos)."""
    if task in ("FSA", "CCQA"):
        return [row["video A"], row["video B"]]
    if task in ("PI", "PSS"):
        return [row["video"]]
    return list(row["videos"])


def frame_count(path: Path) -> int:
    capture = cv2.VideoCapture(str(path))
    count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    capture.release()
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=Path("/assets"))
    parser.add_argument("--frames", type=int, default=512)
    parser.add_argument("--lite", type=Path, default=Path("eval/crossvid_2500.json"))
    args = parser.parse_args()
    crossvid = args.data_root / "crossvid"
    lite = set(json.loads(args.lite.read_text()))
    report: dict = {"frames": args.frames}

    qa = {task: json.loads((crossvid / "QA" / f"{task}.json").read_text())
          for task in ("BU", "CC", "CCQA", "FSA", "MOC", "MSR", "NC", "PEA", "PI", "PSS")}
    known = {f"crossvid:{task}:{row['id']}" for task, rows in qa.items() for row in rows}
    report["lite2500_missing_ids"] = sorted(lite - known)[:20]

    # Count frames of every referenced CrossVid video once.
    paths = {video for task in ("BU", "CC", "NC", "PEA", "FSA", "CCQA") for row in qa[task] for video in videos_of(task, row)}
    with ThreadPoolExecutor(32) as pool:
        counts = dict(zip(sorted(paths), pool.map(lambda v: frame_count(crossvid / "videos" / v), sorted(paths))))
    report["crossvid_videos_counted"] = len(counts)

    half = args.frames // 2
    fixed = defaultdict(Counter)  # FSA/CCQA: video shorter than the fixed F/2 placeholders
    for task in ("FSA", "CCQA"):
        for row in qa[task]:
            sample_id = f"crossvid:{task}:{row['id']}"
            videos = videos_of(task, row)
            short = any(counts[v] < half for v in videos)
            fixed[task]["questions"] += 1
            fixed[task]["fail_if_run"] += short
            fixed[task]["fail_in_lite2500"] += short and sample_id in lite
            fixed[task]["fail_at_official_128"] += any(counts[v] < 64 for v in videos)
    report["fixed_placeholder_tasks"] = {task: dict(value) for task, value in fixed.items()}

    uav = defaultdict(Counter)  # MOC/MSR: frame directories with fewer files than F/2
    for task in ("MOC", "MSR"):
        for row in qa[task]:
            sample_id = f"crossvid:{task}:{row['id']}"
            sizes = [len(os.listdir(crossvid / "uav" / "frames" / str(view) / f"{row['vid']}-{view}")) for view in (1, 2)]
            uav[task]["questions"] += 1
            uav[task]["repeated_frames"] += min(sizes) < half
            uav[task]["repeated_in_lite2500"] += min(sizes) < half and sample_id in lite
            uav[task]["min_dir_frames"] = min(uav[task].get("min_dir_frames", 10**9), min(sizes))
    report["uav_tasks"] = {task: dict(value) for task, value in uav.items()}

    short_videos = Counter()  # equal-split tasks: fewer frames than allocated (harmless)
    for task in ("BU", "CC", "NC", "PEA"):
        for row in qa[task]:
            per_video = args.frames // len(row["videos"])
            short_videos[task] += any(counts[v] < per_video for v in row["videos"])
    report["equal_split_questions_with_a_short_video"] = dict(short_videos)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
