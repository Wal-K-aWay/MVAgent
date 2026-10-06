#!/usr/bin/env python3
"""Render question-referenced CrossVid UAV objects during their first visible second.

The source frame sequences remain unchanged on disk.  For one MOC/MSR question this
script creates question-scoped ``view_A.mp4`` and ``view_B.mp4`` files where only
objects explicitly referenced as ``{A1}``, ``{B5}``, or their occasional bare
``A1``/``B5`` forms in the question or options receive overlays.  Each referenced
object follows its dense GT boxes for a
short window beginning at its first visible frame.  The rest of each video is clean.

The generated ``sample.json`` keeps the original question and options verbatim and also
materializes the protocol-aware ``agent_question`` used directly by ``demo.py --input``.
It needs no textual bbox guidance.  This is an MVAgent-specific visualization protocol,
not the official CrossVid coordinate-only inference protocol.
"""

from __future__ import annotations

import argparse
import colorsys
import json
import math
import os
import re
import sys
from pathlib import Path
from typing import Any, Iterable, Sequence

import cv2
import numpy as np


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.frames_to_video import frames_to_video, list_image_frames
from scripts.crossvid_protocol import (
    MOC_MSR_PROTOCOL_QUESTION_BOXES,
    crossvid_prompt_profile,
    format_crossvid_question,
)


DEFAULT_CROSSVID_ROOT = Path("/home/kww/datasets/Multi-Video/CrossVid")
SUPPORTED_TASKS = {"MOC", "MSR"}
OBJECT_REFERENCE_RE = re.compile(
    r"\{([AB])([1-9][0-9]*)\}"
    r"|(?<![A-Za-z0-9_{])([AB])([1-9][0-9]*)(?![A-Za-z0-9_}])"
)

# OpenCV BGR colors chosen to remain vivid after MP4 compression and downscaling.
BOX_COLORS_BGR: tuple[tuple[int, int, int], ...] = (
    (0, 0, 255),       # red
    (0, 220, 0),       # green
    (255, 80, 0),      # blue
    (0, 220, 255),     # yellow
    (220, 0, 220),     # magenta
    (220, 220, 0),     # cyan
    (0, 128, 255),     # orange
    (255, 0, 128),     # violet
)


def _read_json_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(f"CrossVid annotation file not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"Expected a JSON list in: {path}")
    return [row for row in data if isinstance(row, dict)]


def _write_json(path: Path, payload: Any) -> None:
    output = path.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    os.replace(temporary, output)


def _normalize_options(raw_options: Any) -> list[str]:
    if raw_options is None:
        return []
    if isinstance(raw_options, dict):
        values: Iterable[Any] = raw_options.values()
    elif isinstance(raw_options, (list, tuple)):
        values = raw_options
    else:
        values = [raw_options]
    return [str(value) for value in values]


def _find_row(rows: Sequence[dict[str, Any]], sample_id: str) -> dict[str, Any]:
    matches = [row for row in rows if str(row.get("id")) == str(sample_id)]
    if not matches:
        raise ValueError(f"CrossVid sample id not found: {sample_id}")
    if len(matches) > 1:
        raise ValueError(f"CrossVid sample id is not unique: {sample_id}")
    return matches[0]


def extract_question_object_references(row: dict[str, Any]) -> list[dict[str, Any]]:
    """Resolve question-local ``A1/B5`` aliases without changing prompt text."""

    objects = [item for item in (row.get("objects") or []) if isinstance(item, dict)]
    text_parts = [str(row.get("question") or ""), *_normalize_options(row.get("options"))]
    seen: set[tuple[str, int]] = set()
    references: list[dict[str, Any]] = []
    for match in OBJECT_REFERENCE_RE.finditer("\n".join(text_parts)):
        view_prefix = str(match.group(1) or match.group(3))
        ordinal = int(match.group(2) or match.group(4))
        key = (view_prefix, ordinal)
        if key in seen:
            continue
        seen.add(key)
        if ordinal > len(objects):
            raise ValueError(
                f"Object reference {match.group(0)} exceeds the row's "
                f"{len(objects)} objects"
            )
        item = objects[ordinal - 1]
        if item.get("id") is None:
            raise ValueError(f"Object reference {match.group(0)} has no source track id")
        references.append(
            {
                "display_id": f"{view_prefix}{ordinal}",
                "view_prefix": view_prefix,
                "view_id": "view_A" if view_prefix == "A" else "view_B",
                "view_number": "1" if view_prefix == "A" else "2",
                "ordinal": ordinal,
                "track_id": int(item["id"]),
            }
        )
    return references


def _load_tracks(path: Path) -> dict[int, dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"CrossVid bbox file must contain a list: {path}")
    return {
        int(item["id"]): item
        for item in data
        if isinstance(item, dict) and item.get("id") is not None
    }


def _is_visible_bbox(value: Any) -> bool:
    return isinstance(value, dict) and not bool(value.get("outside"))


def _first_visible_index(track: dict[str, Any], frame_count: int) -> int | None:
    boxes = track.get("bbox") or {}
    for frame_index in range(frame_count):
        if _is_visible_bbox(boxes.get(str(frame_index))):
            return frame_index
    return None


def _output_geometry(frame: np.ndarray, max_side: int | None) -> tuple[int, int, float, float]:
    source_height, source_width = frame.shape[:2]
    if max_side is not None and max(source_width, source_height) > int(max_side):
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
    )


def _fallback_color(index: int) -> tuple[int, int, int]:
    hue = (float(index) * 0.61803398875) % 1.0
    red, green, blue = colorsys.hsv_to_rgb(hue, 0.9, 1.0)
    return int(round(blue * 255)), int(round(green * 255)), int(round(red * 255))


def _assign_track_colors(references: Sequence[dict[str, Any]]) -> dict[int, tuple[int, int, int]]:
    colors: dict[int, tuple[int, int, int]] = {}
    for reference in references:
        track_id = int(reference["track_id"])
        if track_id in colors:
            continue
        index = len(colors)
        colors[track_id] = (
            BOX_COLORS_BGR[index]
            if index < len(BOX_COLORS_BGR)
            else _fallback_color(index)
        )
    return colors


def _scaled_bbox(
    bbox: dict[str, Any],
    *,
    scale_x: float,
    scale_y: float,
    width: int,
    height: int,
) -> tuple[int, int, int, int]:
    raw_x1 = int(round(float(bbox.get("xtl", 0)) * scale_x))
    raw_y1 = int(round(float(bbox.get("ytl", 0)) * scale_y))
    raw_x2 = int(round(float(bbox.get("xbr", 0)) * scale_x))
    raw_y2 = int(round(float(bbox.get("ybr", 0)) * scale_y))
    x1 = max(0, min(width - 1, min(raw_x1, raw_x2)))
    y1 = max(0, min(height - 1, min(raw_y1, raw_y2)))
    x2 = max(0, min(width - 1, max(raw_x1, raw_x2)))
    y2 = max(0, min(height - 1, max(raw_y1, raw_y2)))
    if x2 <= x1:
        x2 = min(width - 1, x1 + 1)
    if y2 <= y1:
        y2 = min(height - 1, y1 + 1)
    return x1, y1, x2, y2


def draw_id_box(
    frame: np.ndarray,
    bbox: tuple[int, int, int, int],
    display_id: str,
    color_bgr: tuple[int, int, int],
) -> None:
    """Draw one box and a same-color ID label without a background fill."""

    height, width = frame.shape[:2]
    x1, y1, x2, y2 = bbox
    thickness = max(2, int(round(max(width, height) / 480.0)))
    font_scale = max(0.55, min(1.2, max(width, height) / 1000.0))
    text_thickness = max(1, thickness - 1)
    padding = max(3, thickness + 1)
    (text_width, text_height), baseline = cv2.getTextSize(
        display_id,
        cv2.FONT_HERSHEY_SIMPLEX,
        font_scale,
        text_thickness,
    )
    cv2.rectangle(frame, (x1, y1), (x2, y2), color_bgr, thickness, cv2.LINE_AA)
    text_x = max(0, min(x1, max(0, width - text_width)))
    text_y = y1 - padding
    if text_y - text_height - baseline < 0:
        text_y = min(height - baseline, y1 + text_height + padding)
    cv2.putText(
        frame,
        display_id,
        (text_x, text_y),
        cv2.FONT_HERSHEY_SIMPLEX,
        font_scale,
        color_bgr,
        max(2, text_thickness),
        cv2.LINE_AA,
    )


def _render_view(
    *,
    benchmark_root: Path,
    video_number: str,
    view_number: str,
    view_id: str,
    references: Sequence[dict[str, Any]],
    track_colors: dict[int, tuple[int, int, int]],
    output_path: Path,
    fps: float,
    overlay_seconds: float,
    max_side: int | None,
    overwrite: bool,
) -> tuple[str, list[dict[str, Any]]]:
    frame_dir = benchmark_root / "uav" / "frames" / view_number / f"{video_number}-{view_number}"
    bbox_path = benchmark_root / "uav" / "bbox" / view_number / f"{video_number}.json"
    if not frame_dir.is_dir():
        raise FileNotFoundError(f"CrossVid UAV frames not found: {frame_dir}")
    if not bbox_path.is_file():
        raise FileNotFoundError(f"CrossVid UAV bbox file not found: {bbox_path}")

    frame_paths = list_image_frames(frame_dir)
    first_frame = cv2.imread(str(frame_paths[0]), cv2.IMREAD_COLOR)
    if first_frame is None:
        raise ValueError(f"Cannot decode CrossVid UAV frame: {frame_paths[0]}")
    output_width, output_height, scale_x, scale_y = _output_geometry(first_frame, max_side)
    tracks = _load_tracks(bbox_path)
    window_frames = max(1, int(math.ceil(float(fps) * float(overlay_seconds))))

    prepared: list[dict[str, Any]] = []
    not_visible: list[dict[str, Any]] = []
    for reference in references:
        track_id = int(reference["track_id"])
        track = tracks.get(track_id)
        if track is None:
            raise ValueError(f"Track {track_id} is missing from {bbox_path}")
        first_visible = _first_visible_index(track, len(frame_paths))
        if first_visible is None:
            blue, green, red = track_colors[track_id]
            not_visible.append(
                {
                    "display_id": reference["display_id"],
                    "view_id": view_id,
                    "question_object_ordinal": reference["ordinal"],
                    "source_track_id": reference["track_id"],
                    "status": "not_visible",
                    "color_rgb": [red, green, blue],
                    "color_hex": f"#{red:02X}{green:02X}{blue:02X}",
                }
            )
            continue
        end_frame = min(len(frame_paths), first_visible + window_frames)
        color_bgr = track_colors[track_id]
        prepared.append(
            {
                **reference,
                "track": track,
                "first_visible_index": first_visible,
                "overlay_end_index": end_frame,
                "color_bgr": color_bgr,
            }
        )

    def transform(frame: np.ndarray, frame_index: int) -> np.ndarray:
        if frame.shape[1] != output_width or frame.shape[0] != output_height:
            frame = cv2.resize(frame, (output_width, output_height), interpolation=cv2.INTER_AREA)
        else:
            frame = frame.copy()
        for item in prepared:
            if not (item["first_visible_index"] <= frame_index < item["overlay_end_index"]):
                continue
            bbox = (item["track"].get("bbox") or {}).get(str(frame_index))
            if not _is_visible_bbox(bbox):
                continue
            draw_id_box(
                frame,
                _scaled_bbox(
                    bbox,
                    scale_x=scale_x,
                    scale_y=scale_y,
                    width=output_width,
                    height=output_height,
                ),
                str(item["display_id"]),
                item["color_bgr"],
            )
        return frame

    rendered_path = frames_to_video(
        frame_paths,
        output_path,
        fps=fps,
        overwrite=overwrite,
        frame_transform=transform,
    )
    public_references = list(not_visible)
    for item in prepared:
        blue, green, red = item["color_bgr"]
        public_references.append(
            {
                "display_id": item["display_id"],
                "view_id": view_id,
                "question_object_ordinal": item["ordinal"],
                "source_track_id": item["track_id"],
                "status": "visualized",
                "first_visible_frame": item["first_visible_index"] + 1,
                "first_visible_time_sec": round(item["first_visible_index"] / float(fps), 3),
                "last_overlay_frame": item["overlay_end_index"],
                "overlay_end_time_sec": round(item["overlay_end_index"] / float(fps), 3),
                "color_rgb": [red, green, blue],
                "color_hex": f"#{red:02X}{green:02X}{blue:02X}",
            }
        )
    return rendered_path, public_references


def _read_video_frame(path: Path, frame_index: int) -> np.ndarray:
    capture = cv2.VideoCapture(str(path))
    try:
        if not capture.isOpened():
            raise ValueError(f"Cannot open rendered video: {path}")
        capture.set(cv2.CAP_PROP_POS_FRAMES, int(frame_index))
        ok, frame = capture.read()
        if not ok or frame is None:
            raise ValueError(f"Cannot decode frame {frame_index} from: {path}")
        return frame
    finally:
        capture.release()


def _write_preview(
    *,
    output_path: Path,
    videos: dict[str, str],
    references: Sequence[dict[str, Any]],
) -> str | None:
    visible_references = [
        reference
        for reference in references
        if reference.get("status") == "visualized"
    ]
    if not visible_references:
        return None
    groups: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for reference in visible_references:
        key = (str(reference["view_id"]), int(reference["first_visible_frame"]))
        groups.setdefault(key, []).append(reference)

    tiles: list[np.ndarray] = []
    for (view_id, first_visible_frame), group in groups.items():
        video_path = Path(videos[view_id]).resolve()
        frame = _read_video_frame(video_path, first_visible_frame - 1)
        max_tile_width = 640
        if frame.shape[1] > max_tile_width:
            scale = max_tile_width / float(frame.shape[1])
            frame = cv2.resize(
                frame,
                (max_tile_width, max(2, int(round(frame.shape[0] * scale)))),
                interpolation=cv2.INTER_AREA,
            )
        caption_height = 44
        tile = np.full(
            (frame.shape[0] + caption_height, frame.shape[1], 3),
            (24, 24, 24),
            dtype=np.uint8,
        )
        tile[caption_height:, :] = frame
        display_ids = ", ".join(str(reference["display_id"]) for reference in group)
        caption = f"{view_id}  {display_ids}  frame {first_visible_frame}"
        cv2.putText(
            tile,
            caption,
            (12, 29),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )
        tiles.append(tile)

    columns = min(2, len(tiles))
    rows = int(math.ceil(len(tiles) / float(columns)))
    cell_width = max(tile.shape[1] for tile in tiles)
    cell_height = max(tile.shape[0] for tile in tiles)
    canvas = np.full((rows * cell_height, columns * cell_width, 3), (12, 12, 12), dtype=np.uint8)
    for index, tile in enumerate(tiles):
        row, column = divmod(index, columns)
        y = row * cell_height
        x = column * cell_width
        canvas[y : y + tile.shape[0], x : x + tile.shape[1]] = tile
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(output_path), canvas):
        raise ValueError(f"Cannot write preview image: {output_path}")
    return str(output_path.resolve())


def render_crossvid_question_box_row(
    root: str | Path,
    *,
    task: str,
    row: dict[str, Any],
    output_dir: str | Path,
    overlay_seconds: float = 1.0,
    fps: float = 10.0,
    max_side: int | None = 960,
    overwrite: bool = False,
    write_sample: bool = False,
    write_preview: bool = False,
    write_metadata: bool = True,
) -> dict[str, Any]:
    """Render one already-loaded MOC/MSR row for batch or interactive use."""

    normalized_task = str(task).strip().upper()
    if normalized_task not in SUPPORTED_TASKS:
        raise ValueError(f"Task must be one of: {', '.join(sorted(SUPPORTED_TASKS))}")
    if not math.isfinite(float(overlay_seconds)) or float(overlay_seconds) <= 0:
        raise ValueError("overlay_seconds must be a finite positive number")
    if not math.isfinite(float(fps)) or float(fps) <= 0:
        raise ValueError("fps must be a finite positive number")
    if max_side is not None and int(max_side) <= 0:
        raise ValueError("max_side must be positive when provided")

    benchmark_root = Path(root).expanduser().resolve()
    sample_id = row.get("id")
    if row.get("vid") is None:
        raise ValueError(f"CrossVid {normalized_task}:{sample_id} has no UAV video id")
    video_number = str(row["vid"])
    references = extract_question_object_references(row)
    track_colors = _assign_track_colors(references)
    destination = Path(output_dir).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)

    videos: dict[str, str] = {}
    rendered_references: list[dict[str, Any]] = []
    for view_number, view_id in (("1", "view_A"), ("2", "view_B")):
        view_references = [item for item in references if item["view_id"] == view_id]
        rendered_path, view_details = _render_view(
            benchmark_root=benchmark_root,
            video_number=video_number,
            view_number=view_number,
            view_id=view_id,
            references=view_references,
            track_colors=track_colors,
            output_path=destination / f"{view_id}.mp4",
            fps=float(fps),
            overlay_seconds=float(overlay_seconds),
            max_side=int(max_side) if max_side is not None else None,
            overwrite=overwrite,
        )
        videos[view_id] = rendered_path
        rendered_references.extend(view_details)

    raw_question = str(row.get("question") or "")
    options = _normalize_options(row.get("options"))
    sample = {
        "sample_id": f"crossvid:{normalized_task}:{row.get('id')}",
        "question": raw_question,
        "agent_question": format_crossvid_question(
            task=normalized_task,
            question=raw_question,
            options=options,
            video_count=len(videos),
            input_protocol=MOC_MSR_PROTOCOL_QUESTION_BOXES,
        ),
        "options": options,
        "prompt_profile": crossvid_prompt_profile(
            normalized_task,
            MOC_MSR_PROTOCOL_QUESTION_BOXES,
        ),
        "input_protocol": MOC_MSR_PROTOCOL_QUESTION_BOXES,
        "videos": {
            view_id: Path(path).resolve().relative_to(destination).as_posix()
            for view_id, path in videos.items()
        },
    }
    sample_path: Path | None = None
    if write_sample:
        sample_path = destination / "sample.json"
        _write_json(sample_path, sample)

    preview_path = None
    if write_preview:
        preview_path = _write_preview(
            output_path=destination / "preview.jpg",
            videos=videos,
            references=rendered_references,
        )
    metadata = {
        "sample_id": sample["sample_id"],
        "task": normalized_task,
        "source_uav_video_id": video_number,
        "protocol": "mvagent_question_boxes",
        "raw_question_unchanged": True,
        "agent_question_materialized": True,
        "overlay_seconds": float(overlay_seconds),
        "fps": float(fps),
        "max_side": max_side,
        "videos": videos,
        "sample_path": str(sample_path.resolve()) if sample_path is not None else None,
        "preview_path": preview_path,
        "references": rendered_references,
    }
    metadata_path: Path | None = None
    if write_metadata:
        metadata_path = destination / "metadata.json"
        _write_json(metadata_path, metadata)
    return {
        **metadata,
        "metadata_path": (
            str(metadata_path.resolve()) if metadata_path is not None else None
        ),
    }


def visualize_crossvid_question_boxes(
    root: str | Path,
    *,
    task: str,
    sample_id: str | int,
    output_dir: str | Path | None = None,
    overlay_seconds: float = 1.0,
    fps: float = 10.0,
    max_side: int | None = 960,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Create question-scoped annotated videos and a ``demo.py`` sample file."""

    normalized_task = str(task).strip().upper()
    benchmark_root = Path(root).expanduser().resolve()
    row = _find_row(
        _read_json_rows(benchmark_root / "QA" / f"{normalized_task}.json"),
        str(sample_id),
    )
    destination = (
        Path(output_dir).expanduser().resolve()
        if output_dir is not None
        else (
            benchmark_root
            / ".mvagent_media"
            / "uav_question_boxes"
            / normalized_task
            / str(sample_id)
        ).resolve()
    )
    return render_crossvid_question_box_row(
        benchmark_root,
        task=normalized_task,
        row=row,
        output_dir=destination,
        overlay_seconds=overlay_seconds,
        fps=fps,
        max_side=max_side,
        overwrite=overwrite,
        write_sample=True,
        write_preview=True,
        write_metadata=True,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(DEFAULT_CROSSVID_ROOT))
    parser.add_argument("--task", required=True, choices=sorted(SUPPORTED_TASKS))
    parser.add_argument("--id", required=True, dest="sample_id")
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--overlay-seconds", type=float, default=1.0)
    parser.add_argument("--fps", type=float, default=10.0)
    parser.add_argument("--max-side", type=int, default=960)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = visualize_crossvid_question_boxes(
        args.root,
        task=args.task,
        sample_id=args.sample_id,
        output_dir=args.output_dir,
        overlay_seconds=args.overlay_seconds,
        fps=args.fps,
        max_side=args.max_side,
        overwrite=args.overwrite,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
