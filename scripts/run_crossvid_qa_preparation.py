#!/usr/bin/env python3
"""Resume CrossVid media preparation, finalize ``qa.jsonl``, and validate it.

This is the durable batch wrapper around ``prepare_multivideo_benchmarks.py``.
It parallelizes the two expensive media families, reuses every completed output,
then runs the canonical full preparation command so the final manifest and its
metadata are written by one process.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import traceback
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PREPARE_SCRIPT = PROJECT_ROOT / "scripts" / "prepare_multivideo_benchmarks.py"
TASK_ORDER = ("BU", "CC", "CCQA", "FSA", "MOC", "MSR", "NC", "PEA", "PI", "PSS")
BASE_ROW_KEYS = {"id", "task", "question", "videos", "options", "answer"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_rows(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"Expected a JSON list: {path}")
    return [row for row in payload if isinstance(row, dict)]


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _is_complete_file(path: Path) -> bool:
    return path.is_file() and path.stat().st_size > 0


def _missing_pea(root: Path) -> list[str]:
    missing: list[str] = []
    for row in _read_rows(root / "QA" / "PEA.json"):
        source_id = row.get("id")
        base = root / ".mvagent_media" / "PEA" / str(source_id)
        expected = [base / f"video_{index}.mp4" for index in range(1, len(row.get("videos") or []) + 1)]
        if not expected or not all(_is_complete_file(path) for path in expected):
            missing.append(f"crossvid:PEA:{source_id}")
    return missing


def _missing_uav(root: Path) -> list[str]:
    missing: list[str] = []
    for task in ("MOC", "MSR"):
        for row in _read_rows(root / "QA" / f"{task}.json"):
            source_id = row.get("id")
            base = root / ".mvagent_media" / "uav_question_boxes" / task / str(source_id)
            expected = [base / "view_A.mp4", base / "view_B.mp4"]
            if not all(_is_complete_file(path) for path in expected):
                missing.append(f"crossvid:{task}:{source_id}")
    return missing


def _media_progress(root: Path) -> dict[str, Any]:
    pea_rows = _read_rows(root / "QA" / "PEA.json")
    pea_expected = 0
    pea_complete = 0
    pea_duration = 0.0
    pea_complete_duration = 0.0
    for row in pea_rows:
        base = root / ".mvagent_media" / "PEA" / str(row.get("id"))
        for index, (begin, end) in enumerate(zip(row.get("begin") or [], row.get("end") or []), 1):
            duration = max(0.0, float(end) - float(begin))
            pea_expected += 1
            pea_duration += duration
            if _is_complete_file(base / f"video_{index}.mp4"):
                pea_complete += 1
                pea_complete_duration += duration

    uav: dict[str, dict[str, int]] = {}
    for task in ("MOC", "MSR"):
        rows = _read_rows(root / "QA" / f"{task}.json")
        complete = 0
        complete_videos = 0
        for row in rows:
            base = root / ".mvagent_media" / "uav_question_boxes" / task / str(row.get("id"))
            flags = [_is_complete_file(base / "view_A.mp4"), _is_complete_file(base / "view_B.mp4")]
            complete_videos += sum(flags)
            complete += int(all(flags))
        uav[task] = {
            "complete_samples": complete,
            "expected_samples": len(rows),
            "complete_videos": complete_videos,
            "expected_videos": len(rows) * 2,
        }

    disk = shutil.disk_usage(root)
    return {
        "pea": {
            "complete_clips": pea_complete,
            "expected_clips": pea_expected,
            "complete_target_hours": round(pea_complete_duration / 3600.0, 3),
            "expected_target_hours": round(pea_duration / 3600.0, 3),
        },
        "uav": uav,
        "disk_free_bytes": disk.free,
    }


def _shards(values: Sequence[str], count: int) -> list[list[str]]:
    return [list(values[index::count]) for index in range(count) if values[index::count]]


def _python_env() -> dict[str, str]:
    env = dict(os.environ)
    additions = [str(PROJECT_ROOT / "src"), str(PROJECT_ROOT)]
    existing = env.get("PYTHONPATH")
    if existing:
        additions.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(additions)
    return env


def _worker_command(root: Path, kind: str, ids: Sequence[str], output: Path) -> list[str]:
    command = [
        sys.executable,
        str(PREPARE_SCRIPT),
        "crossvid",
        "--root",
        str(root),
        "--tasks",
        "PEA" if kind == "pea" else "MOC,MSR",
        "--ids",
        ",".join(ids),
        "--output",
        str(output),
    ]
    if kind == "uav":
        command.extend(
            [
                "--moc-msr-protocol",
                "mvagent_question_boxes",
                "--overlay-seconds",
                "1",
            ]
        )
    return command


def _run_parallel_attempt(
    root: Path,
    state_dir: Path,
    *,
    attempt: int,
    pea_jobs: int,
    uav_jobs: int,
    status: dict[str, Any],
) -> list[dict[str, Any]]:
    missing = {"pea": _missing_pea(root), "uav": _missing_uav(root)}
    specs: list[tuple[str, int, list[str]]] = []
    for kind, jobs in (("pea", pea_jobs), ("uav", uav_jobs)):
        for shard_index, ids in enumerate(_shards(missing[kind], jobs)):
            specs.append((kind, shard_index, ids))

    status.update(
        {
            "phase": "parallel_media",
            "attempt": attempt,
            "missing_at_attempt_start": {key: len(value) for key, value in missing.items()},
            "active_workers": len(specs),
            "progress": _media_progress(root),
            "updated_at": _utc_now(),
        }
    )
    _write_json_atomic(state_dir / "status.json", status)
    if not specs:
        return []

    processes: list[tuple[str, int, subprocess.Popen[bytes], Any, Path]] = []
    for kind, shard_index, ids in specs:
        stem = f"attempt_{attempt}_{kind}_{shard_index:02d}"
        log_path = state_dir / "logs" / f"{stem}.log"
        output_path = state_dir / "shards" / f"{stem}.jsonl"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        log_handle = log_path.open("wb")
        process = subprocess.Popen(
            _worker_command(root, kind, ids, output_path),
            cwd=PROJECT_ROOT,
            env=_python_env(),
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
        )
        processes.append((kind, shard_index, process, log_handle, log_path))

    while any(process.poll() is None for _, _, process, _, _ in processes):
        status.update(
            {
                "active_workers": sum(process.poll() is None for _, _, process, _, _ in processes),
                "progress": _media_progress(root),
                "updated_at": _utc_now(),
            }
        )
        _write_json_atomic(state_dir / "status.json", status)
        time.sleep(30)

    results: list[dict[str, Any]] = []
    for kind, shard_index, process, log_handle, log_path in processes:
        return_code = process.wait()
        log_handle.close()
        results.append(
            {
                "kind": kind,
                "shard": shard_index,
                "return_code": return_code,
                "log": str(log_path),
            }
        )
    status.update(
        {
            "active_workers": 0,
            "worker_results": results,
            "progress": _media_progress(root),
            "updated_at": _utc_now(),
        }
    )
    _write_json_atomic(state_dir / "status.json", status)
    return results


def _run_finalizer(root: Path, state_dir: Path, status: dict[str, Any]) -> None:
    status.update({"phase": "finalize_manifest", "updated_at": _utc_now()})
    _write_json_atomic(state_dir / "status.json", status)
    command = [
        sys.executable,
        str(PREPARE_SCRIPT),
        "crossvid",
        "--root",
        str(root),
        "--moc-msr-protocol",
        "mvagent_question_boxes",
        "--overlay-seconds",
        "1",
    ]
    log_path = state_dir / "logs" / "finalize.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("wb") as handle:
        subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            env=_python_env(),
            stdin=subprocess.DEVNULL,
            stdout=handle,
            stderr=subprocess.STDOUT,
            check=True,
        )


def _manifest_sha256(rows: Sequence[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for row in rows:
        digest.update(
            json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        )
        digest.update(b"\n")
    return digest.hexdigest()


def _validate_manifest(root: Path, state_dir: Path) -> dict[str, Any]:
    manifest = root / "qa.jsonl"
    metadata_path = root / "qa.meta.json"
    if not manifest.is_file() or not metadata_path.is_file():
        raise FileNotFoundError("qa.jsonl or qa.meta.json was not generated")

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
        task: len(_read_rows(root / "QA" / f"{task}.json"))
        for task in TASK_ORDER
        if (root / "QA" / f"{task}.json").is_file()
    }
    actual_counts = dict(sorted(Counter(str(row.get("task")) for row in rows).items()))
    if actual_counts != dict(sorted(expected_counts.items())):
        raise ValueError(f"Task counts differ: expected={expected_counts}, actual={actual_counts}")

    seen_ids: set[str] = set()
    media_paths = 0
    for index, row in enumerate(rows, 1):
        expected_keys = BASE_ROW_KEYS | ({"scoring_points"} if row.get("task") == "CCQA" else set())
        if set(row) != expected_keys:
            raise ValueError(f"Unexpected keys at qa.jsonl line {index}: {sorted(row)}")
        sample_id = str(row.get("id") or "")
        if not sample_id or sample_id in seen_ids:
            raise ValueError(f"Missing or duplicate sample id at line {index}: {sample_id!r}")
        seen_ids.add(sample_id)
        if not str(row.get("question") or "").strip():
            raise ValueError(f"Empty question for {sample_id}")
        videos = row.get("videos")
        if not isinstance(videos, dict) or not videos:
            raise ValueError(f"Missing videos for {sample_id}")
        options = row.get("options")
        if not isinstance(options, list):
            raise ValueError(f"Options must be a list for {sample_id}")
        if options and str(row["question"]).count("Options:") != 1:
            raise ValueError(f"Expected exactly one Options block for {sample_id}")
        for media in videos.values():
            relative = Path(str(media))
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError(f"Unsafe media path for {sample_id}: {media}")
            resolved = (root / relative).resolve()
            try:
                resolved.relative_to(root)
            except ValueError as exc:
                raise ValueError(f"Media path escapes root for {sample_id}: {media}") from exc
            if not _is_complete_file(resolved):
                raise FileNotFoundError(f"Missing media for {sample_id}: {resolved}")
            media_paths += 1

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    digest = _manifest_sha256(rows)
    if metadata.get("manifest_sha256") != digest:
        raise ValueError("qa.meta.json manifest_sha256 does not match qa.jsonl")
    if metadata.get("sample_count") != len(rows) or metadata.get("scope") != "full":
        raise ValueError("qa.meta.json does not describe a full manifest")
    if metadata.get("task_counts") != actual_counts:
        raise ValueError("qa.meta.json task_counts do not match qa.jsonl")

    result = {
        "validated_at": _utc_now(),
        "manifest": str(manifest),
        "metadata": str(metadata_path),
        "manifest_sha256": digest,
        "sample_count": len(rows),
        "task_counts": actual_counts,
        "media_path_count": media_paths,
        "progress": _media_progress(root),
    }
    _write_json_atomic(state_dir / "validation.json", result)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--pea-jobs", type=int, default=12)
    parser.add_argument("--uav-jobs", type=int, default=12)
    parser.add_argument("--parallel-attempts", type=int, default=2)
    parser.add_argument("--state-dir", type=Path, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.root.expanduser().resolve()
    if args.pea_jobs <= 0 or args.uav_jobs <= 0 or args.parallel_attempts <= 0:
        raise ValueError("Job counts and parallel attempts must be positive")
    state_dir = (
        args.state_dir.expanduser().resolve()
        if args.state_dir is not None
        else root / ".mvagent_prepare" / "crossvid_qa"
    )
    state_dir.mkdir(parents=True, exist_ok=True)
    lock_handle = (state_dir / "run.lock").open("a+", encoding="utf-8")
    try:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print(f"Another CrossVid preparation process holds {state_dir / 'run.lock'}", file=sys.stderr)
        return 2
    lock_handle.seek(0)
    lock_handle.truncate()
    lock_handle.write(f"{os.getpid()}\n")
    lock_handle.flush()

    status: dict[str, Any] = {
        "state": "running",
        "pid": os.getpid(),
        "root": str(root),
        "started_at": _utc_now(),
        "updated_at": _utc_now(),
    }
    _write_json_atomic(state_dir / "status.json", status)
    try:
        for attempt in range(1, args.parallel_attempts + 1):
            _run_parallel_attempt(
                root,
                state_dir,
                attempt=attempt,
                pea_jobs=args.pea_jobs,
                uav_jobs=args.uav_jobs,
                status=status,
            )
            if not _missing_pea(root) and not _missing_uav(root):
                break
        _run_finalizer(root, state_dir, status)
        status.update({"phase": "validate", "updated_at": _utc_now()})
        _write_json_atomic(state_dir / "status.json", status)
        validation = _validate_manifest(root, state_dir)
        status.update(
            {
                "state": "complete",
                "phase": "complete",
                "completed_at": _utc_now(),
                "updated_at": _utc_now(),
                "validation": validation,
            }
        )
        _write_json_atomic(state_dir / "status.json", status)
        return 0
    except Exception as exc:
        status.update(
            {
                "state": "failed",
                "phase": "failed",
                "failed_at": _utc_now(),
                "updated_at": _utc_now(),
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(),
                "progress": _media_progress(root),
            }
        )
        _write_json_atomic(state_dir / "status.json", status)
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
