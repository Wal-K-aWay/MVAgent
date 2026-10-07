#!/usr/bin/env python3
"""Export CrossVid question IDs whose source recordings never appear in the excluded panel (Lite2500).

A source is a recording, not a file: Assembly101 camera views of one take share a recording, and
MovieChat clips named `<TITLE>-<n>.mp4` share their movie title. UAV questions use their sequence `vid`.
A question is kept only if none of its sources is used by any excluded question, in any task.
Output is a JSON array of full IDs (`crossvid:<task>:<id>`) in task order then numeric ID, like
`eval/crossvid_2500.json`.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

TASKS = ("BU", "CC", "CCQA", "FSA", "MOC", "MSR", "NC", "PEA", "PI", "PSS")
ASSEMBLY = re.compile(r"assembly/(nusar-2021_action_both_\d+-[a-z0-9]+_\d+_user_id_\d{4}-\d\d-\d\d_\d{6})_.+\.mp4")
MOVIE_CLIP = re.compile(r"movie/([A-Za-z0-9]+)-\d+\.mp4")
MOVIE = re.compile(r"movie/\d+\.mp4")


def source(path: str) -> str:
    if path.startswith("assembly/"):
        match = ASSEMBLY.fullmatch(path)
        if not match:
            raise ValueError(f"Unrecognized Assembly101 file name: {path}")
        return "assembly:" + match[1]
    if path.startswith("movie/"):
        if match := MOVIE_CLIP.fullmatch(path):
            return "movie:" + match[1]
        if MOVIE.fullmatch(path):
            return path
        raise ValueError(f"Unrecognized movie file name: {path}")
    return path


def sources(task: str, row: dict) -> set[str]:
    if task in ("MOC", "MSR"):
        return {f"uav:{row['vid']}"}
    paths = []
    for field in ("videos", "video", "video A", "video B"):
        value = row.get(field)
        paths += value if isinstance(value, list) else [value] if value else []
    if not paths:
        raise ValueError(f"crossvid:{task}:{row['id']} has no video")
    return {source(path) for path in paths}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--qa-dir", type=Path, required=True, help="CrossVid QA/ directory")
    ap.add_argument("--exclude", type=Path, default=Path("eval/crossvid_2500.json"), help="JSON array of excluded IDs")
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()

    rows = {}
    for task in TASKS:
        for row in json.loads((args.qa_dir / f"{task}.json").read_text(encoding="utf-8")):
            rows[f"crossvid:{task}:{row['id']}"] = sources(task, row)
    excluded = set(json.loads(args.exclude.read_text(encoding="utf-8")))
    if missing := excluded - rows.keys():
        raise ValueError(f"{len(missing)} excluded IDs are not CrossVid questions, e.g. {sorted(missing)[:3]}")
    used = set().union(*(rows[sid] for sid in excluded))

    clean = [sid for sid in rows if sid not in excluded and not rows[sid] & used]
    clean.sort(key=lambda sid: (TASKS.index(sid.split(":")[1]), int(sid.split(":")[2])))
    args.output.write_text(json.dumps(clean, indent=2) + "\n", encoding="utf-8")

    total = Counter(sid.split(":")[1] for sid in rows if sid not in excluded)
    kept = Counter(sid.split(":")[1] for sid in clean)
    print(" ".join(f"{task}={kept[task]}/{total[task]}" for task in TASKS))
    print(f"{len(clean)} of {sum(total.values())} non-excluded questions share no source with {len(excluded)} excluded")


if __name__ == "__main__":
    main()
