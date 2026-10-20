#!/usr/bin/env python3
"""Build the list-form QAs.json files that MVAgent reads for CVBench and MVU-Eval.

CVBench rows come from the Video-R1 `CVBench.json` shipped in this repository; MVU-Eval rows
come from the upstream `MVU_Eval_QAs.json` (a dict keyed by id). Video paths stay relative to
each benchmark's video root, which MVAgent resolves as `<dataset>/videos/`.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CVBENCH_SOURCE = PROJECT_ROOT / "eval/agent_eval/metadata/CVBench.json"


def cvbench_rows(source: Path) -> list[dict[str, Any]]:
    rows = []
    for row in json.loads(source.read_text(encoding="utf-8")):
        videos = [row[f"video_{index}"] for index in range(1, 5) if row.get(f"video_{index}")]
        rows.append({
            "id": int(row["id"]),
            "task_type": row["task_type"],
            "question": row["question"],
            "options": row["options"],
            "answer": row["answer"],
            "videos": videos,
        })
    return rows


def mvu_rows(source: Path) -> list[dict[str, Any]]:
    payload = json.loads(source.read_text(encoding="utf-8"))
    return [
        {
            "id": int(key),
            "task": value["task"],
            "question": value["question"],
            "options": value["options"],
            "answer": value["ground_truth"],
            "videos": value["video_paths"],
        }
        for key, value in sorted(payload.items(), key=lambda item: int(item[0]))
    ]


def validate(name: str, rows: list[dict[str, Any]], media_root: Path | None) -> None:
    ids = [row["id"] for row in rows]
    if len(set(ids)) != len(ids):
        raise ValueError(f"{name}: duplicate ids")
    empty = [row["id"] for row in rows if not row["videos"] or not row["options"]]
    if empty:
        raise ValueError(f"{name}: rows without videos/options: {empty[:5]}")
    if media_root is not None:
        missing = sorted({
            video for row in rows for video in row["videos"] if not (media_root / video).is_file()
        })
        if missing:
            raise FileNotFoundError(f"{name}: {len(missing)} referenced videos missing, e.g. {missing[:5]}")


def write_json(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cvbench-source", type=Path, default=DEFAULT_CVBENCH_SOURCE)
    parser.add_argument("--mvu-source", type=Path, required=True, help="Upstream MVU_Eval_QAs.json")
    parser.add_argument("--cvbench-output", type=Path, required=True)
    parser.add_argument("--mvu-output", type=Path, required=True)
    parser.add_argument("--cvbench-media-root", type=Path, help="Check every referenced CVBench video exists")
    parser.add_argument("--mvu-media-root", type=Path, help="Check every referenced MVU-Eval video exists")
    args = parser.parse_args()

    for name, rows, media_root, output in (
        ("CVBench", cvbench_rows(args.cvbench_source), args.cvbench_media_root, args.cvbench_output),
        ("MVU-Eval", mvu_rows(args.mvu_source), args.mvu_media_root, args.mvu_output),
    ):
        validate(name, rows, media_root)
        write_json(output, rows)
        videos = sum(len(row["videos"]) for row in rows)
        print(f"{name}: {len(rows)} rows, {videos} video references -> {output}")


if __name__ == "__main__":
    main()
