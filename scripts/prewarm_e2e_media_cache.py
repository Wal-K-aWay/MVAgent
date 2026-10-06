#!/usr/bin/env python3
"""Precompute model-independent CVBench/MVU-Eval frame-cache entries.

The command is deliberately sequential: each video is decoded and released before
the next one, so a background prewarm cannot multiply the 512-frame memory peak.
Existing entries are audited without loading their Base64 payload into memory.
"""

from __future__ import annotations

import argparse
import gc
import json
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import run_official_cvbench_mvu as runner


@dataclass(frozen=True)
class MediaSpec:
    benchmark: str
    path: Path
    frames: int
    max_side: int
    quality: int
    decode_threads: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Prewarm the shared encoded-frame cache without making model requests."
        )
    )
    parser.add_argument(
        "--only", choices=("all", "cvbench", "mvu-eval"), default="all"
    )
    parser.add_argument(
        "--cvbench-root",
        type=Path,
        default=Path("/home/kww/datasets/Multi-Video/CVBench"),
    )
    parser.add_argument(
        "--mvu-root",
        type=Path,
        default=Path("/home/kww/datasets/Multi-Video/MVU-Eval"),
    )
    parser.add_argument(
        "--cache-dir", type=Path, default=PROJECT_ROOT / ".cache/e2e_media"
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("outputs/e2e_media_cache_prewarm.json"),
    )
    parser.add_argument("--cv-frames-per-video", type=int, default=512)
    parser.add_argument("--cv-question-frame-cap", type=int, default=512)
    parser.add_argument("--cv-max-side", type=int, default=720)
    parser.add_argument("--mvu-frames-per-video", type=int, default=512)
    parser.add_argument("--mvu-question-frame-cap", type=int, default=512)
    parser.add_argument("--mvu-max-side", type=int, default=720)
    parser.add_argument("--decode-batch-frames", type=int, default=64)
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional deterministic row limit per selected benchmark.",
    )
    parser.add_argument(
        "--audit-only",
        action="store_true",
        help="Report cache coverage without decoding missing media.",
    )
    args = parser.parse_args()
    positive = {
        "cv_frames_per_video": args.cv_frames_per_video,
        "cv_question_frame_cap": args.cv_question_frame_cap,
        "cv_max_side": args.cv_max_side,
        "mvu_frames_per_video": args.mvu_frames_per_video,
        "mvu_question_frame_cap": args.mvu_question_frame_cap,
        "mvu_max_side": args.mvu_max_side,
        "decode_batch_frames": args.decode_batch_frames,
    }
    invalid = [name for name, value in positive.items() if value <= 0]
    if invalid:
        parser.error("must be positive: " + ", ".join(invalid))
    if args.limit is not None and args.limit <= 0:
        parser.error("--limit must be positive")
    return args


def read_rows(path: Path, limit: int | None) -> list[dict[str, Any]]:
    rows = runner.read_json(path)
    if not isinstance(rows, list):
        raise ValueError(f"expected a JSON list: {path}")
    return rows if limit is None else rows[:limit]


def row_specs(
    *,
    benchmark: str,
    rows: Iterable[dict[str, Any]],
    video_root: Path,
    frames_per_video: int,
    question_frame_cap: int,
    max_side: int,
    quality: int,
    decode_threads: int,
) -> Iterable[MediaSpec]:
    for row in rows:
        videos = list(row.get("videos") or [])
        if not videos:
            raise ValueError(f"{benchmark} row {row.get('id')} has no videos")
        if len(videos) > question_frame_cap:
            raise ValueError(
                f"{benchmark} row {row.get('id')} has {len(videos)} videos but "
                f"the question frame cap is {question_frame_cap}"
            )
        effective_frames = min(
            frames_per_video, max(1, question_frame_cap // len(videos))
        )
        for relative in videos:
            yield MediaSpec(
                benchmark=benchmark,
                path=video_root / str(relative),
                frames=effective_frames,
                max_side=max_side,
                quality=quality,
                decode_threads=decode_threads,
            )


def collect_specs(args: argparse.Namespace) -> list[tuple[str, MediaSpec]]:
    candidates: list[MediaSpec] = []
    if args.only in {"all", "cvbench"}:
        candidates.extend(
            row_specs(
                benchmark="cvbench",
                rows=read_rows(args.cvbench_root / "QAs.json", args.limit),
                video_root=args.cvbench_root / "videos",
                frames_per_video=args.cv_frames_per_video,
                question_frame_cap=args.cv_question_frame_cap,
                max_side=args.cv_max_side,
                quality=95,
                decode_threads=2,
            )
        )
    if args.only in {"all", "mvu-eval"}:
        candidates.extend(
            row_specs(
                benchmark="mvu-eval",
                rows=read_rows(args.mvu_root / "QAs.json", args.limit),
                video_root=args.mvu_root / "videos",
                frames_per_video=args.mvu_frames_per_video,
                question_frame_cap=args.mvu_question_frame_cap,
                max_side=args.mvu_max_side,
                quality=75,
                decode_threads=4,
            )
        )

    unique: dict[str, MediaSpec] = {}
    for spec in candidates:
        if not spec.path.is_file():
            raise FileNotFoundError(spec.path)
        key = runner.sampled_frame_cache_key(
            spec.path,
            frames=spec.frames,
            max_side=spec.max_side,
            quality=spec.quality,
        )
        unique.setdefault(key, spec)
    return list(unique.items())


def entry_paths(cache_dir: Path, key: str) -> tuple[Path, Path]:
    shard = cache_dir / key[:2]
    return shard / f"{key}.frames", shard / f"{key}.json"


def entry_is_present(cache_dir: Path, key: str) -> bool:
    frames_path, metadata_path = entry_paths(cache_dir, key)
    if not frames_path.is_file() or frames_path.stat().st_size <= 0:
        return False
    if not metadata_path.is_file() or metadata_path.stat().st_size <= 0:
        return False
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        return int(metadata["decoded_frames"]) > 0
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return False


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def write_report(path: Path, report: dict[str, Any]) -> None:
    report["updated_at"] = utc_now()
    runner.write_json(path, report)


def serializable_spec(spec: MediaSpec) -> dict[str, Any]:
    value = asdict(spec)
    value["path"] = str(spec.path)
    return value


def main() -> int:
    args = parse_args()
    specs = collect_specs(args)
    present = [(key, spec) for key, spec in specs if entry_is_present(args.cache_dir, key)]
    missing = [(key, spec) for key, spec in specs if not entry_is_present(args.cache_dir, key)]
    report: dict[str, Any] = {
        "schema_version": 1,
        "started_at": utc_now(),
        "status": "audited" if args.audit_only else "running",
        "settings": {
            "only": args.only,
            "cache_dir": str(args.cache_dir.resolve()),
            "cv_frames_per_video": args.cv_frames_per_video,
            "cv_question_frame_cap": args.cv_question_frame_cap,
            "cv_max_side": args.cv_max_side,
            "mvu_frames_per_video": args.mvu_frames_per_video,
            "mvu_question_frame_cap": args.mvu_question_frame_cap,
            "mvu_max_side": args.mvu_max_side,
            "decode_batch_frames": args.decode_batch_frames,
            "limit": args.limit,
            "sequential_workers": 1,
        },
        "unique_specs": len(specs),
        "initial_hits": len(present),
        "initial_missing": len(missing),
        "completed_missing": 0,
        "failures": [],
    }
    write_report(args.report, report)
    print(
        f"cache audit: {len(present)}/{len(specs)} present, "
        f"{len(missing)} missing",
        flush=True,
    )
    if args.audit_only:
        return 0

    for number, (key, spec) in enumerate(missing, start=1):
        try:
            encoded, _metadata = runner.sample_video_frames(
                spec.path,
                frames=spec.frames,
                max_side=spec.max_side,
                quality=spec.quality,
                decode_threads=spec.decode_threads,
                decode_batch_frames=args.decode_batch_frames,
                cache_dir=args.cache_dir,
            )
            del encoded, _metadata
            report["completed_missing"] = int(report["completed_missing"]) + 1
        except Exception as exc:  # noqa: BLE001 - persist every media failure
            report["failures"].append(
                {
                    "key": key,
                    "spec": serializable_spec(spec),
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
        if number % 10 == 0 or number == len(missing):
            gc.collect()
            write_report(args.report, report)
            print(
                f"cache prewarm: {number}/{len(missing)} attempted, "
                f"{report['completed_missing']} completed, "
                f"{len(report['failures'])} failed",
                flush=True,
            )

    report["status"] = "complete" if not report["failures"] else "complete_with_errors"
    report["final_present"] = sum(
        entry_is_present(args.cache_dir, key) for key, _spec in specs
    )
    write_report(args.report, report)
    return 0 if not report["failures"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
