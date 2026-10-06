#!/usr/bin/env python3
"""Validate and prepare all Multi-Video benchmark inputs for MVAgent."""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sys
import traceback
from typing import Any, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.prepare_multivideo_benchmarks import (
    MOC_MSR_INPUT_PROTOCOLS,
    MOC_MSR_PROTOCOL_QUESTION_BOXES,
    prepare_crossvid,
)


CROSSVID_TASKS = (
    "BU",
    "CC",
    "CCQA",
    "FSA",
    "MOC",
    "MSR",
    "NC",
    "PEA",
    "PI",
    "PSS",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_rows(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"Expected a JSON list: {path}")
    return [row for row in payload if isinstance(row, dict)]


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _manifest_sha256(rows: Sequence[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for row in rows:
        digest.update(
            json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            .encode("utf-8")
        )
        digest.update(b"\n")
    return digest.hexdigest()


def validate_raw_dataset(root: Path) -> None:
    required_dirs = [
        root / "CrossVid" / "videos",
        root / "CrossVid" / "uav",
        root / "CVBench" / "videos",
        root / "MVU-Eval" / "videos",
    ]
    required_files = [
        root / "CVBench" / "QAs.json",
        root / "MVU-Eval" / "QAs.json",
        *(root / "CrossVid" / "QA" / f"{task}.json" for task in CROSSVID_TASKS),
    ]
    missing = [path for path in required_dirs if not path.is_dir()]
    missing.extend(path for path in required_files if not path.is_file())
    if missing:
        lines = "\n".join(f"  - {path}" for path in missing)
        raise FileNotFoundError(f"Incomplete Multi-Video dataset:\n{lines}")


def _complete(path: Path) -> bool:
    return path.is_file() and path.stat().st_size > 0


def _missing_pea(root: Path) -> list[str]:
    missing: list[str] = []
    for row in _read_rows(root / "QA" / "PEA.json"):
        source_id = row.get("id")
        base = root / ".mvagent_media" / "PEA" / str(source_id)
        expected = [
            base / f"video_{index}.mp4"
            for index in range(1, len(row.get("videos") or []) + 1)
        ]
        if not expected or not all(_complete(path) for path in expected):
            missing.append(f"crossvid:PEA:{source_id}")
    return missing


def _missing_uav(root: Path) -> list[str]:
    missing: list[str] = []
    for task in ("MOC", "MSR"):
        for row in _read_rows(root / "QA" / f"{task}.json"):
            source_id = row.get("id")
            base = root / ".mvagent_media" / "uav_question_boxes" / task / str(source_id)
            expected = [base / "view_A.mp4", base / "view_B.mp4"]
            if not all(_complete(path) for path in expected):
                missing.append(f"crossvid:{task}:{source_id}")
    return missing


def _shards(values: Sequence[str], count: int) -> list[list[str]]:
    return [list(values[index::count]) for index in range(count) if values[index::count]]


def _prepare_shard(
    root: str,
    kind: str,
    ids: Sequence[str],
    output: str,
    frame_fps: float,
    frame_max_side: int,
    moc_msr_protocol: str,
    overlay_seconds: float,
) -> None:
    tasks = "PEA" if kind == "pea" else "MOC,MSR"
    prepare_crossvid(
        root,
        output_path=output,
        tasks=tasks.split(","),
        ids=ids,
        frame_fps=frame_fps,
        frame_max_side=frame_max_side,
        moc_msr_protocol=moc_msr_protocol,
        overlay_seconds=overlay_seconds,
        overwrite=False,
    )


def _run_parallel_attempt(
    root: Path,
    state_dir: Path,
    attempt: int,
    *,
    pea_jobs: int,
    uav_jobs: int,
    frame_fps: float,
    frame_max_side: int,
    moc_msr_protocol: str,
    overlay_seconds: float,
) -> list[dict[str, Any]]:
    missing = {"pea": _missing_pea(root), "uav": _missing_uav(root)}
    specs: list[tuple[str, int, list[str]]] = []
    for kind, jobs in (("pea", pea_jobs), ("uav", uav_jobs)):
        specs.extend(
            (kind, index, ids)
            for index, ids in enumerate(_shards(missing[kind], jobs))
        )
    _write_json(
        state_dir / "status.json",
        {
            "state": "running",
            "phase": "parallel_media",
            "attempt": attempt,
            "missing_at_attempt_start": {key: len(value) for key, value in missing.items()},
            "workers": len(specs),
            "updated_at": _utc_now(),
        },
    )
    if not specs:
        return []

    results: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=len(specs)) as pool:
        futures = {}
        for kind, index, ids in specs:
            output = state_dir / "shards" / f"attempt_{attempt}_{kind}_{index:02d}.jsonl"
            future = pool.submit(
                _prepare_shard,
                str(root),
                kind,
                ids,
                str(output),
                frame_fps,
                frame_max_side,
                moc_msr_protocol,
                overlay_seconds,
            )
            futures[future] = (kind, index, output)
        for future in as_completed(futures):
            kind, index, output = futures[future]
            try:
                future.result()
                result = {"kind": kind, "shard": index, "status": "complete"}
            except Exception as exc:  # noqa: BLE001 - persist worker failures
                result = {
                    "kind": kind,
                    "shard": index,
                    "status": "failed",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            result["output"] = str(output)
            results.append(result)
    _write_json(
        state_dir / "status.json",
        {
            "state": "running",
            "phase": "parallel_media_complete",
            "attempt": attempt,
            "worker_results": results,
            "updated_at": _utc_now(),
        },
    )
    return results


def _validate_prepared_crossvid(root: Path) -> dict[str, Any]:
    manifest = root / "qa.jsonl"
    metadata_path = root / "qa.meta.json"
    if not _complete(manifest) or not _complete(metadata_path):
        raise FileNotFoundError("CrossVid qa.jsonl or qa.meta.json was not generated")

    rows: list[dict[str, Any]] = []
    with manifest.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                raise ValueError(f"Blank line in qa.jsonl at line {line_number}")
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"qa.jsonl line {line_number} is not an object")
            rows.append(row)

    expected_counts = {
        task: len(_read_rows(root / "QA" / f"{task}.json")) for task in CROSSVID_TASKS
    }
    actual_counts = dict(sorted(Counter(str(row.get("task")) for row in rows).items()))
    if actual_counts != dict(sorted(expected_counts.items())):
        raise ValueError(f"Task counts differ: expected={expected_counts}, actual={actual_counts}")

    seen: set[str] = set()
    media_count = 0
    for row in rows:
        sample_id = str(row.get("id") or "")
        if not sample_id or sample_id in seen:
            raise ValueError(f"Missing or duplicate sample id: {sample_id!r}")
        seen.add(sample_id)
        videos = row.get("videos")
        if not isinstance(videos, dict) or not videos:
            raise ValueError(f"Missing videos for {sample_id}")
        for media in videos.values():
            relative = Path(str(media))
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError(f"Unsafe media path for {sample_id}: {media}")
            resolved = (root / relative).resolve()
            try:
                resolved.relative_to(root)
            except ValueError as exc:
                raise ValueError(f"Media path escapes root for {sample_id}: {media}") from exc
            if not _complete(resolved):
                raise FileNotFoundError(f"Missing media for {sample_id}: {resolved}")
            media_count += 1

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    digest = _manifest_sha256(rows)
    if metadata.get("manifest_sha256") != digest:
        raise ValueError("qa.meta.json manifest_sha256 does not match qa.jsonl")
    if metadata.get("sample_count") != len(rows):
        raise ValueError("qa.meta.json sample_count does not match qa.jsonl")
    return {
        "validated_at": _utc_now(),
        "manifest": str(manifest),
        "metadata": str(metadata_path),
        "manifest_sha256": digest,
        "sample_count": len(rows),
        "task_counts": actual_counts,
        "media_path_count": media_count,
    }


def _prepare_crossvid(root: Path, args: argparse.Namespace, state_dir: Path) -> dict[str, Any]:
    state_dir.mkdir(parents=True, exist_ok=True)
    lock_handle = (state_dir / "run.lock").open("a+", encoding="utf-8")
    try:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        lock_handle.close()
        raise RuntimeError(f"Another preparation process holds {state_dir / 'run.lock'}") from exc

    try:
        for attempt in range(1, args.parallel_attempts + 1):
            results = _run_parallel_attempt(
                root,
                state_dir,
                attempt,
                pea_jobs=args.pea_jobs,
                uav_jobs=args.uav_jobs,
                frame_fps=args.frame_fps,
                frame_max_side=args.frame_max_side,
                moc_msr_protocol=args.moc_msr_protocol,
                overlay_seconds=args.overlay_seconds,
            )
            if not _missing_pea(root) and not _missing_uav(root):
                break
            if results and all(result["status"] == "failed" for result in results):
                continue

        if _missing_pea(root) or _missing_uav(root):
            raise RuntimeError("CrossVid media preparation remained incomplete after retries")

        _write_json(
            state_dir / "status.json",
            {"state": "running", "phase": "finalize_manifest", "updated_at": _utc_now()},
        )
        prepare_crossvid(
            root,
            frame_fps=args.frame_fps,
            frame_max_side=args.frame_max_side,
            moc_msr_protocol=args.moc_msr_protocol,
            overlay_seconds=args.overlay_seconds,
            overwrite=False,
        )
        validation = _validate_prepared_crossvid(root)
        _write_json(
            state_dir / "status.json",
            {
                "state": "complete",
                "phase": "complete",
                "validation": validation,
                "updated_at": _utc_now(),
            },
        )
        return validation
    except Exception as exc:
        _write_json(
            state_dir / "status.json",
            {
                "state": "failed",
                "phase": "failed",
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(),
                "updated_at": _utc_now(),
            },
        )
        raise
    finally:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
        lock_handle.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare a downloaded Multi-Video root for MVAgent. "
            "CVBench and MVU-Eval stay as raw videos; CrossVid gets qa.jsonl "
            "and .mvagent_media."
        )
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("/home/kww/datasets/Multi-Video"),
        help="Downloaded Multi-Video dataset root.",
    )
    parser.add_argument("--pea-jobs", type=int, default=12)
    parser.add_argument("--uav-jobs", type=int, default=12)
    parser.add_argument("--parallel-attempts", type=int, default=2)
    parser.add_argument("--frame-fps", type=float, default=10.0)
    parser.add_argument("--frame-max-side", type=int, default=960)
    parser.add_argument(
        "--moc-msr-protocol",
        choices=sorted(MOC_MSR_INPUT_PROTOCOLS - {"official_coordinate"}),
        default=MOC_MSR_PROTOCOL_QUESTION_BOXES,
    )
    parser.add_argument("--overlay-seconds", type=float, default=1.0)
    parser.add_argument(
        "--state-dir",
        type=Path,
        default=None,
        help="Optional persistent preparation state directory.",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Validate raw benchmark layout without generating media.",
    )
    args = parser.parse_args()
    if any(
        value <= 0
        for value in (
            args.pea_jobs,
            args.uav_jobs,
            args.parallel_attempts,
            args.frame_fps,
            args.frame_max_side,
            args.overlay_seconds,
        )
    ):
        parser.error("job counts, frame settings and overlay-seconds must be positive")
    return args


def main() -> int:
    args = parse_args()
    root = args.root.expanduser().resolve()
    validate_raw_dataset(root)
    print(f"Raw benchmark layout OK: {root}")
    if args.check_only:
        prepared = root / "CrossVid" / "qa.jsonl"
        print(
            "CrossVid prepared: yes"
            if prepared.is_file()
            else "CrossVid prepared: no (run without --check-only)"
        )
        return 0

    state_dir = (
        args.state_dir.expanduser().resolve()
        if args.state_dir is not None
        else root / "CrossVid" / ".mvagent_prepare" / "crossvid_qa"
    )
    validation = _prepare_crossvid(root / "CrossVid", args, state_dir)
    print(f"CrossVid prepared: {validation['sample_count']} questions")
    print(f"Manifest: {validation['manifest']}")
    print("CVBench/MVU-Eval need no .mvagent_media; MVAgent creates its runtime cache on demand.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
