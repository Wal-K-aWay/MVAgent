#!/usr/bin/env python3
"""Prepare a compact ``qa.jsonl`` manifest for CrossVid."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import Counter
from numbers import Real
from pathlib import Path
from typing import Any, Iterable, Sequence

import cv2


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.frames_to_video import frames_to_video, list_image_frames
from scripts.crossvid_protocol import (
    CROSSVID_MANIFEST_SCHEMA_VERSION,
    CROSSVID_PROMPT_PROFILE_VERSION,
    MOC_MSR_INPUT_PROTOCOLS,
    MOC_MSR_PROTOCOL_CURRENT_TEXT_BBOX,
    MOC_MSR_PROTOCOL_QUESTION_BOXES,
    format_crossvid_question,
    normalize_crossvid_input_protocol,
)
from scripts.visualize_crossvid_question_boxes import (
    render_crossvid_question_box_row,
)


DEFAULT_ROOTS = {
    "crossvid": Path("/home/kww/datasets/Multi-Video/CrossVid"),
}
CROSSVID_TASK_ORDER = (
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
VIDEO_SUFFIXES = {".avi", ".mkv", ".mov", ".mp4", ".webm"}
IMAGE_SUFFIXES = {".bmp", ".jpeg", ".jpg", ".png", ".webp"}


def write_jsonl(path: str | Path, rows: Iterable[dict[str, Any]]) -> None:
    """Atomically replace one JSONL file."""
    output = Path(path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    os.replace(temporary, output)


def _read_json_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Annotation file not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"Annotation file must contain a JSON list: {path}")
    return [row for row in data if isinstance(row, dict)]


def _relative_path(root: Path, path: Path) -> str:
    try:
        return path.expanduser().resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError(f"Media path is outside benchmark root: {path}") from exc


def _normalize_gt(value: Any) -> Any:
    if isinstance(value, list) and len(value) == 1:
        return value[0]
    return value


def _normalize_text_options(raw_options: Any) -> list[str]:
    if raw_options is None:
        return []
    if isinstance(raw_options, dict):
        values: Iterable[Any] = raw_options.values()
    elif isinstance(raw_options, (list, tuple)):
        values = raw_options
    else:
        values = [raw_options]
    return [str(value).strip() for value in values if str(value).strip()]


def _selected(sample_id: str, local_id: Any, ids: set[str] | None) -> bool:
    if not ids:
        return True
    return sample_id in ids or str(local_id) in ids


def _manifest_sha256(records: Sequence[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for record in records:
        digest.update(
            json.dumps(
                record,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        digest.update(b"\n")
    return digest.hexdigest()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    output = path.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    os.replace(temporary, output)


def _crossvid_video(root: Path, raw_path: Any) -> str:
    rel = str(raw_path or "").replace("\\", "/").strip().lstrip("/")
    if ".." in Path(rel).parts:
        raise ValueError(f"CrossVid media path cannot contain '..': {raw_path}")
    path = (root / "videos" / rel).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"CrossVid video not found: {path}")
    return _relative_path(root, path)


def _cut_video_ranges(
    source_path: Path,
    ranges: Sequence[Sequence[float]],
    output_path: Path,
    *,
    overwrite: bool,
) -> str:
    """Concatenate selected source ranges into one visual-only MP4."""
    output = output_path.expanduser().resolve()
    if output.exists() and output.stat().st_size > 0 and not overwrite:
        return str(output)
    if not source_path.is_file():
        raise FileNotFoundError(f"Source video not found: {source_path}")
    normalized = [
        [float(time_range[0]), float(time_range[1])]
        for time_range in ranges
        if len(time_range) == 2 and float(time_range[1]) > float(time_range[0])
    ]
    if not normalized:
        raise ValueError(f"No valid ranges supplied for {source_path}")

    capture = cv2.VideoCapture(str(source_path))
    try:
        if not capture.isOpened():
            raise ValueError(f"Cannot open source video: {source_path}")
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0) or 25.0
        frame_count = int(round(float(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0)))
        width = int(round(float(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0.0)))
        height = int(round(float(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0.0)))
        if width <= 0 or height <= 0:
            raise ValueError(f"Cannot determine video resolution: {source_path}")

        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_name(f".{output.stem}.tmp{output.suffix or '.mp4'}")
        temporary.unlink(missing_ok=True)
        writer = cv2.VideoWriter(
            str(temporary),
            cv2.VideoWriter_fourcc(*"mp4v"),
            fps,
            (width, height),
        )
        if not writer.isOpened():
            temporary.unlink(missing_ok=True)
            raise ValueError(f"Cannot create derived video: {temporary}")

        written = 0
        try:
            for start_sec, end_sec in normalized:
                start_frame = max(0, int(start_sec * fps))
                end_frame = max(start_frame + 1, int(end_sec * fps))
                if frame_count > 0:
                    start_frame = min(start_frame, frame_count - 1)
                    end_frame = min(max(end_frame, start_frame + 1), frame_count)
                capture.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
                for _ in range(start_frame, end_frame):
                    ok, frame = capture.read()
                    if not ok:
                        break
                    writer.write(frame)
                    written += 1
        except Exception:
            writer.release()
            temporary.unlink(missing_ok=True)
            raise
        else:
            writer.release()
        if written <= 0 or not temporary.exists() or temporary.stat().st_size <= 0:
            temporary.unlink(missing_ok=True)
            raise ValueError(f"No frames written from {source_path} ranges={normalized}")
        os.replace(temporary, output)
        return str(output)
    finally:
        capture.release()


def _derived_crossvid_clip(
    root: Path,
    *,
    task: str,
    source_id: Any,
    role: str,
    source_rel: Any,
    ranges: Sequence[Sequence[float]],
    overwrite: bool,
) -> str:
    raw_source = str(source_rel).replace("\\", "/").strip().lstrip("/")
    if ".." in Path(raw_source).parts:
        raise ValueError(f"CrossVid media path cannot contain '..': {source_rel}")
    source = (root / "videos" / raw_source).resolve()
    output = root / ".mvagent_media" / task / str(source_id) / f"{role}.mp4"
    _cut_video_ranges(source, ranges, output, overwrite=overwrite)
    return _relative_path(root, output)


def _uav_output_geometry(
    frame_dir: Path,
    *,
    max_side: int,
) -> tuple[int, int, float, float, int]:
    """Return generated-video geometry and source-to-output coordinate scales."""

    frame_paths = list_image_frames(frame_dir)
    first = cv2.imread(str(frame_paths[0]), cv2.IMREAD_COLOR)
    if first is None:
        raise ValueError(f"Cannot decode CrossVid UAV frame: {frame_paths[0]}")
    source_height, source_width = first.shape[:2]
    if max(source_width, source_height) > int(max_side):
        scale = float(max_side) / float(max(source_width, source_height))
        output_width = max(2, int(round(source_width * scale)))
        output_height = max(2, int(round(source_height * scale)))
    else:
        output_width, output_height = source_width, source_height
    return (
        output_width,
        output_height,
        output_width / float(source_width),
        output_height / float(source_height),
        len(frame_paths),
    )


def _load_uav_tracks(bbox_path: Path) -> dict[int, dict[str, Any]]:
    raw_tracks = json.loads(bbox_path.read_text(encoding="utf-8"))
    if not isinstance(raw_tracks, list):
        raise ValueError(f"CrossVid UAV bbox file must contain a list: {bbox_path}")
    return {
        int(track["id"]): track
        for track in raw_tracks
        if isinstance(track, dict) and track.get("id") is not None
    }


def _first_visible_uav_anchor(
    track: dict[str, Any] | None,
    *,
    frame_count: int,
    scale_x: float,
    scale_y: float,
    output_width: int,
    output_height: int,
    fps: float,
) -> dict[str, Any] | None:
    """Locate one selected object without exposing its dense track."""

    if not track:
        return None
    boxes = track.get("bbox") or {}
    for frame_index in range(frame_count):
        bbox = boxes.get(str(frame_index))
        if not isinstance(bbox, dict) or bool(bbox.get("outside")):
            continue
        x1 = max(
            0,
            min(output_width - 1, int(round(float(bbox.get("xtl", 0)) * scale_x))),
        )
        y1 = max(
            0,
            min(output_height - 1, int(round(float(bbox.get("ytl", 0)) * scale_y))),
        )
        x2 = max(
            0,
            min(output_width - 1, int(round(float(bbox.get("xbr", 0)) * scale_x))),
        )
        y2 = max(
            0,
            min(output_height - 1, int(round(float(bbox.get("ybr", 0)) * scale_y))),
        )
        return {
            "frame_number": frame_index + 1,
            "time_sec": frame_index / float(fps),
            "bbox": [x1, y1, x2, y2],
        }
    return None


def _crossvid_uav_videos(
    root: Path,
    *,
    row: dict[str, Any],
    frame_fps: float,
    frame_max_side: int,
    overwrite: bool,
) -> tuple[dict[str, str], str]:
    video_number = str(row.get("vid"))
    objects = [
        item
        for item in (row.get("objects") or [])
        if isinstance(item, dict) and item.get("id") is not None
    ]
    videos: dict[str, str] = {}
    descriptions: list[str] = []
    anchors: dict[str, dict[int, dict[str, Any] | None]] = {}
    for view_number, view_name, prefix in (
        ("1", "view_A", "A"),
        ("2", "view_B", "B"),
    ):
        frame_dir = root / "uav" / "frames" / view_number / f"{video_number}-{view_number}"
        bbox_path = root / "uav" / "bbox" / view_number / f"{video_number}.json"
        if not frame_dir.is_dir():
            raise FileNotFoundError(f"CrossVid UAV frames not found: {frame_dir}")
        if not bbox_path.is_file():
            raise FileNotFoundError(f"CrossVid UAV boxes not found: {bbox_path}")
        output = (
            root
            / ".mvagent_media"
            / "uav_unmarked"
            / video_number
            / f"{view_name}.mp4"
        )
        output_width, output_height, scale_x, scale_y, frame_count = (
            _uav_output_geometry(frame_dir, max_side=frame_max_side)
        )
        frames_to_video(
            frame_dir,
            output,
            fps=frame_fps,
            max_side=frame_max_side,
            overwrite=overwrite,
        )
        videos[view_name] = _relative_path(root, output)
        tracks = _load_uav_tracks(bbox_path)
        anchors[prefix] = {
            int(item["id"]): _first_visible_uav_anchor(
                tracks.get(int(item["id"])),
                frame_count=frame_count,
                scale_x=scale_x,
                scale_y=scale_y,
                output_width=output_width,
                output_height=output_height,
                fps=frame_fps,
            )
            for item in objects
        }

    for item in objects:
        track_id = int(item["id"])
        object_label = str(item.get("label") or "object")
        descriptions.append(
            f"A{track_id} and B{track_id} identify the same {object_label}"
        )
        for prefix, view_name in (("A", "view_A"), ("B", "view_B")):
            anchor = anchors[prefix][track_id]
            if anchor is None:
                descriptions.append(
                    f"{prefix}{track_id} ({object_label}) is not visible in {view_name}"
                )
                continue
            descriptions.append(
                f"{prefix}{track_id} ({object_label}) first appears in frame "
                f"{anchor['frame_number']} at {anchor['time_sec']:.3f}s in "
                f"{view_name} with bbox {anchor['bbox']}"
            )
    context = (
        "view_A and view_B are synchronized camera views without visual markings. "
        "Bounding boxes use [xtl, ytl, xbr, ybr] coordinates in the generated "
        "videos and provide only the first visible anchor; track each object "
        "from its anchor when answering. "
        + "; ".join(descriptions)
        + "."
    )
    return videos, context


def _crossvid_row(
    root: Path,
    task: str,
    row: dict[str, Any],
    *,
    frame_fps: float,
    frame_max_side: int,
    moc_msr_protocol: str,
    overlay_seconds: float,
    overwrite: bool,
) -> dict[str, Any]:
    source_id = row.get("id")
    options = _normalize_text_options(row.get("options"))
    raw_question = str(row.get("question") or "").strip()
    question = raw_question
    question_details = ""
    ref_segment_values: tuple[Any, Any] | None = None
    input_protocol = normalize_crossvid_input_protocol(task, moc_msr_protocol)

    if task in {"BU", "CC", "NC"}:
        videos = {
            f"video_{index}": _crossvid_video(root, raw)
            for index, raw in enumerate(row.get("videos") or [], 1)
        }
    elif task == "CCQA":
        videos = {
            "video_A": _crossvid_video(root, row.get("video A")),
            "video_B": _crossvid_video(root, row.get("video B")),
        }
    elif task == "FSA":
        ref_segment = row.get("ref_segment")
        if (
            not isinstance(ref_segment, (list, tuple))
            or len(ref_segment) != 2
            or any(
                isinstance(value, bool) or not isinstance(value, Real)
                for value in ref_segment
            )
            or float(ref_segment[1]) <= float(ref_segment[0])
        ):
            raise ValueError(
                "CrossVid FSA ref_segment must be two increasing numeric timestamps "
                f"for id={source_id}: {ref_segment!r}"
            )
        begin, end = ref_segment
        ref_segment_values = (begin, end)
        videos = {
            "video_1": _crossvid_video(root, row.get("video A")),
            "video_2": _crossvid_video(root, row.get("video B")),
        }
    elif task == "PEA":
        raw_videos = row.get("videos") or []
        begins = row.get("begin") or []
        ends = row.get("end") or []
        if not (len(raw_videos) == len(begins) == len(ends)):
            raise ValueError(f"CrossVid PEA ranges do not align for id={source_id}")
        videos = {
            f"video_{index}": _derived_crossvid_clip(
                root,
                task=task,
                source_id=source_id,
                role=f"video_{index}",
                source_rel=raw,
                ranges=[[begins[index - 1], ends[index - 1]]],
                overwrite=overwrite,
            )
            for index, raw in enumerate(raw_videos, 1)
        }
    elif task == "PI":
        raw_video = row.get("video")
        videos = {
            "beginning": _derived_crossvid_clip(
                root,
                task=task,
                source_id=source_id,
                role="beginning",
                source_rel=raw_video,
                ranges=[row.get("beginning") or []],
                overwrite=overwrite,
            ),
            "ending": _derived_crossvid_clip(
                root,
                task=task,
                source_id=source_id,
                role="ending",
                source_rel=raw_video,
                ranges=[row.get("ending") or []],
                overwrite=overwrite,
            ),
        }
    elif task == "PSS":
        videos = {}
        for label, ranges in (row.get("segments") or {}).items():
            role = f"segment_{label}"
            videos[role] = _derived_crossvid_clip(
                root,
                task=task,
                source_id=source_id,
                role=role,
                source_rel=row.get("video"),
                ranges=ranges,
                overwrite=overwrite,
            )
    elif task in {"MOC", "MSR"}:
        if input_protocol == MOC_MSR_PROTOCOL_QUESTION_BOXES:
            destination = (
                root
                / ".mvagent_media"
                / "uav_question_boxes"
                / task
                / str(source_id)
            )
            rendered = render_crossvid_question_box_row(
                root,
                task=task,
                row=row,
                output_dir=destination,
                overlay_seconds=overlay_seconds,
                fps=frame_fps,
                max_side=frame_max_side,
                overwrite=overwrite,
                write_sample=False,
                write_preview=False,
                write_metadata=True,
            )
            videos = {
                role: _relative_path(root, Path(path))
                for role, path in rendered["videos"].items()
            }
        elif input_protocol == MOC_MSR_PROTOCOL_CURRENT_TEXT_BBOX:
            videos, question_details = _crossvid_uav_videos(
                root,
                row=row,
                frame_fps=frame_fps,
                frame_max_side=frame_max_side,
                overwrite=overwrite,
            )
            for ordinal, item in enumerate(row.get("objects") or [], 1):
                track_id = item.get("id")
                question = question.replace(f"{{A{ordinal}}}", f"A{track_id}")
                question = question.replace(f"{{B{ordinal}}}", f"B{track_id}")
        else:
            raise ValueError(
                "prepare_crossvid does not synthesize official_coordinate inputs; "
                "use current_text_bbox for the historical baseline or "
                "mvagent_question_boxes for the video-label protocol"
            )
    else:
        raise ValueError(f"Unsupported CrossVid task: {task}")

    if not question:
        if task not in {"FSA", "PI", "PSS"}:
            raise ValueError(f"CrossVid question is empty for task={task} id={source_id}")
    if not videos:
        raise ValueError(f"CrossVid sample has no videos for task={task} id={source_id}")
    question = format_crossvid_question(
        task=task,
        question=question,
        options=options,
        video_count=len(videos),
        ref_segment=ref_segment_values,
        objects_information=question_details if task in {"MOC", "MSR"} else "",
        task_details=question_details if task not in {"MOC", "MSR"} else "",
        input_protocol=input_protocol,
    )

    record: dict[str, Any] = {
        "id": f"crossvid:{task}:{source_id}",
        "task": task,
        "question": question,
        "videos": videos,
        "options": options,
        "answer": _normalize_gt(row.get("answer")),
    }
    if row.get("scoring_points") is not None:
        record["scoring_points"] = row["scoring_points"]
    return record


def prepare_crossvid(
    root: str | Path,
    *,
    output_path: str | Path | None = None,
    tasks: Sequence[str] | None = None,
    ids: Sequence[str] | None = None,
    frame_fps: float = 10.0,
    frame_max_side: int = 960,
    moc_msr_protocol: str = MOC_MSR_PROTOCOL_QUESTION_BOXES,
    overlay_seconds: float = 1.0,
    overwrite: bool = False,
) -> list[dict[str, Any]]:
    """Prepare selected CrossVid tasks and write one compact manifest."""
    benchmark_root = Path(root).expanduser().resolve()
    available_tasks = [
        task
        for task in CROSSVID_TASK_ORDER
        if (benchmark_root / "QA" / f"{task}.json").exists()
    ]
    selected_tasks = (
        [str(task).upper() for task in tasks]
        if tasks
        else list(available_tasks)
    )
    unknown = sorted(set(selected_tasks) - set(CROSSVID_TASK_ORDER))
    if unknown:
        raise ValueError(f"Unsupported CrossVid tasks: {', '.join(unknown)}")
    if len(selected_tasks) != len(set(selected_tasks)):
        raise ValueError("CrossVid tasks must not contain duplicates")
    if moc_msr_protocol not in MOC_MSR_INPUT_PROTOCOLS:
        raise ValueError(
            "Unsupported MOC/MSR input protocol: "
            f"{moc_msr_protocol}. Expected one of: "
            f"{', '.join(sorted(MOC_MSR_INPUT_PROTOCOLS))}"
        )
    selected_ids = {str(value) for value in ids} if ids else None
    full_manifest = selected_ids is None and set(selected_tasks) == set(available_tasks)

    records: list[dict[str, Any]] = []
    for task in selected_tasks:
        for row in _read_json_rows(benchmark_root / "QA" / f"{task}.json"):
            sample_id = f"crossvid:{task}:{row.get('id')}"
            if not _selected(sample_id, row.get("id"), selected_ids):
                continue
            records.append(
                _crossvid_row(
                    benchmark_root,
                    task,
                    row,
                    frame_fps=frame_fps,
                    frame_max_side=frame_max_side,
                    moc_msr_protocol=moc_msr_protocol,
                    overlay_seconds=overlay_seconds,
                    overwrite=overwrite,
                )
            )
    manifest_path = Path(output_path) if output_path else benchmark_root / "qa.jsonl"
    write_jsonl(manifest_path, records)
    manifest_path = manifest_path.expanduser().resolve()
    metadata_path = manifest_path.with_suffix(".meta.json")
    _write_json(
        metadata_path,
        {
            "schema_version": CROSSVID_MANIFEST_SCHEMA_VERSION,
            "benchmark": "crossvid",
            "manifest_path": str(manifest_path),
            "manifest_sha256": _manifest_sha256(records),
            "scope": "full" if full_manifest else "filtered",
            "tasks": selected_tasks,
            "task_counts": dict(sorted(Counter(row["task"] for row in records).items())),
            "sample_count": len(records),
            "moc_msr_protocol": moc_msr_protocol,
            "prompt_profile_version": CROSSVID_PROMPT_PROFILE_VERSION,
        },
    )
    return records


def _split_csv(raw: str | None) -> list[str] | None:
    if raw is None:
        return None
    values = [item.strip() for item in raw.split(",") if item.strip()]
    return values or None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("benchmark", choices=sorted(DEFAULT_ROOTS))
    parser.add_argument("--root", default=None, help="Benchmark root; defaults to the project dataset locations")
    parser.add_argument("--output", default=None, help="Manifest path; defaults to <root>/qa.jsonl")
    parser.add_argument("--tasks", default=None, help="Comma-separated task names")
    parser.add_argument("--ids", default=None, help="Comma-separated local or complete sample IDs")
    parser.add_argument("--frame-fps", type=float, default=10.0)
    parser.add_argument("--frame-max-side", type=int, default=960)
    parser.add_argument(
        "--moc-msr-protocol",
        choices=sorted(MOC_MSR_INPUT_PROTOCOLS - {"official_coordinate"}),
        default=MOC_MSR_PROTOCOL_QUESTION_BOXES,
        help=(
            "MOC/MSR media contract: historical clean-video/text-bbox baseline or "
            "question-scoped first-visible-second visual labels"
        ),
    )
    parser.add_argument("--overlay-seconds", type=float, default=1.0)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = Path(args.root).expanduser() if args.root else DEFAULT_ROOTS[args.benchmark]
    kwargs = {
        "output_path": args.output,
        "tasks": _split_csv(args.tasks),
        "ids": _split_csv(args.ids),
        "frame_fps": args.frame_fps,
        "frame_max_side": args.frame_max_side,
        "moc_msr_protocol": args.moc_msr_protocol,
        "overlay_seconds": args.overlay_seconds,
        "overwrite": args.overwrite,
    }
    rows = prepare_crossvid(root, **kwargs)
    destination = Path(args.output).expanduser().resolve() if args.output else root / "qa.jsonl"
    print(f"Prepared {len(rows)} samples: {destination}")


if __name__ == "__main__":
    main()
