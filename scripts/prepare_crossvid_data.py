#!/usr/bin/env python3
"""Download pinned CrossVid, restore its deleted BU media, and prepare MVAgent inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys

REPO_ID = "Chuntianli/CrossVid"
CURRENT_REVISION = "4cc98eee034e6f3950c19803485402661f54c1f8"
BEHAVIOR_REVISION = "136f2c09694cc20378f32a9d1a7c3727d7db9879"
BEHAVIOR_PREFIX = "videos/behavior/"
BEHAVIOR_COUNT = 2416
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def behavior_inventory(entries) -> list[dict]:
    """Keep the fixed deleted media family; never restore unrelated old files."""
    result = []
    for entry in entries:
        path = PurePosixPath(entry.path)
        if not entry.path.startswith(BEHAVIOR_PREFIX) or path.suffix != ".mp4":
            raise ValueError(f"Unexpected historical media entry: {entry.path}")
        if path.is_absolute() or ".." in path.parts:
            raise ValueError(f"Unsafe Hub path: {entry.path}")
        digest = entry.lfs.sha256 if entry.lfs else ""
        if (not isinstance(entry.size, int) or entry.size <= 0 or len(digest) != 64
                or any(char not in "0123456789abcdef" for char in digest)):
            raise ValueError(f"Missing size/LFS SHA256: {entry.path}")
        result.append({"path": entry.path, "size": entry.size, "sha256": digest})
    if len(result) != BEHAVIOR_COUNT or len({row["path"] for row in result}) != len(result):
        raise ValueError(f"Expected {BEHAVIOR_COUNT} unique historical media files, got {len(result)}")
    return sorted(result, key=lambda row: row["path"])


def verify_behavior(root: Path, inventory: list[dict]) -> None:
    for entry in inventory:
        path = root / entry["path"]
        if not path.is_file() or path.stat().st_size != entry["size"]:
            raise ValueError(f"Historical media missing or wrong size: {path}")
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != entry["sha256"]:
            raise ValueError(f"Historical media SHA256 mismatch: {path}")
    bu = json.loads((root / "QA" / "BU.json").read_text(encoding="utf-8"))
    available = {entry["path"] for entry in inventory}
    referenced = {"videos/" + video for row in bu for video in row["videos"]}
    if not referenced or not referenced <= available:
        raise ValueError(f"BU references unverified media: {sorted(referenced - available)[:10]}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="CrossVid directory, not its parent")
    parser.add_argument("--download-workers", type=int, default=4)
    parser.add_argument("--pea-jobs", type=int, default=4)
    parser.add_argument("--uav-jobs", type=int, default=4)
    args = parser.parse_args()
    if min(args.download_workers, args.pea_jobs, args.uav_jobs) <= 0:
        parser.error("All worker counts must be positive")

    from huggingface_hub import HfApi, snapshot_download

    root = args.root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    inventory = behavior_inventory(HfApi().list_repo_tree(
        REPO_ID, path_in_repo=BEHAVIOR_PREFIX.rstrip("/"), repo_type="dataset",
        revision=BEHAVIOR_REVISION, recursive=True,
    ))
    for revision, patterns in (
        (CURRENT_REVISION, ["QA/*", "videos/*", "uav/*", "README.md"]),
        (BEHAVIOR_REVISION, [BEHAVIOR_PREFIX + "*"]),
    ):
        print(f"Downloading {REPO_ID}@{revision}: {patterns}", flush=True)
        snapshot_download(
            REPO_ID, repo_type="dataset", revision=revision,
            allow_patterns=patterns, local_dir=root, max_workers=args.download_workers,
        )
    verify_behavior(root, inventory)
    receipt = root / ".mvagent_download" / "sources.json"
    receipt.parent.mkdir(parents=True, exist_ok=True)
    temporary = receipt.with_suffix(".tmp")
    temporary.write_text(json.dumps({
        "repo_id": REPO_ID,
        "current_revision": CURRENT_REVISION,
        "behavior_revision": BEHAVIOR_REVISION,
        "behavior_verification": "every_file_size_and_lfs_sha256",
        "behavior_files": inventory,
        "behavior_bytes": sum(entry["size"] for entry in inventory),
        "other_media_verification": "Hugging Face download; preparation validates referenced files",
    }, indent=2) + "\n", encoding="utf-8")
    temporary.replace(receipt)
    print(f"Verified {len(inventory)} restored BU media files; provenance: {receipt}", flush=True)
    subprocess.run([
        sys.executable, str(PROJECT_ROOT / "eval/data_preparation/crossvid_batch.py"),
        "--root", str(root), "--pea-jobs", str(args.pea_jobs), "--uav-jobs", str(args.uav_jobs),
    ], check=True, cwd=PROJECT_ROOT)


if __name__ == "__main__":
    main()
