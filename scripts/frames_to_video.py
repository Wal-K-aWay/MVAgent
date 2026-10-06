#!/usr/bin/env python3
"""Convert one image or an ordered image directory into an MP4 video."""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

import cv2


IMAGE_SUFFIXES = {".bmp", ".jpeg", ".jpg", ".png", ".webp"}


def natural_path_key(path: Path) -> list[Any]:
    """Sort numeric frame names chronologically instead of lexicographically."""
    return [
        int(part) if part.isdigit() else part.lower()
        for part in re.split(r"(\d+)", path.name)
    ]


def list_image_frames(source: str | Path | Sequence[str | Path]) -> list[Path]:
    """Resolve one image, image directory, or explicit frame list."""
    if isinstance(source, (str, Path)):
        source_path = Path(source).expanduser().resolve()
        if source_path.is_file():
            candidates: Iterable[Path] = [source_path]
        elif source_path.is_dir():
            candidates = source_path.iterdir()
        else:
            raise FileNotFoundError(f"Image source not found: {source_path}")
    else:
        candidates = (Path(item).expanduser().resolve() for item in source)

    frames = sorted(
        (
            path
            for path in candidates
            if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
        ),
        key=natural_path_key,
    )
    if not frames:
        raise ValueError(f"No supported image frames found in: {source}")
    return frames


def frames_to_video(
    source: str | Path | Sequence[str | Path],
    output_path: str | Path,
    *,
    fps: float = 10.0,
    min_duration_sec: float = 0.0,
    max_side: int | None = None,
    overwrite: bool = False,
    frame_transform: Callable[[Any, int], Any] | None = None,
) -> str:
    """Encode naturally ordered images as an MP4 and return its absolute path.

    ``frame_transform`` lets benchmark preparation draw annotations without
    creating a second directory of intermediate images.
    """
    output = Path(output_path).expanduser().resolve()
    if output.exists() and output.stat().st_size > 0 and not overwrite:
        return str(output)
    if fps <= 0:
        raise ValueError("fps must be greater than zero.")
    if min_duration_sec < 0:
        raise ValueError("min_duration_sec cannot be negative.")
    if max_side is not None and int(max_side) <= 0:
        raise ValueError("max_side must be greater than zero when provided.")

    frame_paths = list_image_frames(source)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.stem}.tmp{output.suffix or '.mp4'}")
    temporary.unlink(missing_ok=True)

    first = cv2.imread(str(frame_paths[0]), cv2.IMREAD_COLOR)
    if first is None:
        raise ValueError(f"Cannot decode image frame: {frame_paths[0]}")
    if frame_transform is not None:
        first = frame_transform(first, 0)
    source_height, source_width = first.shape[:2]
    if max_side is not None and max(source_width, source_height) > int(max_side):
        scale = float(max_side) / float(max(source_width, source_height))
        width = max(2, int(round(source_width * scale)))
        height = max(2, int(round(source_height * scale)))
        first = cv2.resize(first, (width, height), interpolation=cv2.INTER_AREA)
    else:
        height, width = source_height, source_width
    if width <= 0 or height <= 0:
        raise ValueError(f"Invalid first-frame dimensions: {frame_paths[0]}")

    writer = cv2.VideoWriter(
        str(temporary),
        cv2.VideoWriter_fourcc(*"mp4v"),
        float(fps),
        (width, height),
    )
    if not writer.isOpened():
        temporary.unlink(missing_ok=True)
        raise ValueError(f"Cannot create MP4 writer: {temporary}")

    frames_written = 0
    try:
        for index, frame_path in enumerate(frame_paths):
            frame = first if index == 0 else cv2.imread(str(frame_path), cv2.IMREAD_COLOR)
            if frame is None:
                raise ValueError(f"Cannot decode image frame: {frame_path}")
            if index > 0 and frame_transform is not None:
                frame = frame_transform(frame, index)
            if frame.shape[1] != width or frame.shape[0] != height:
                frame = cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)
            writer.write(frame)
            frames_written += 1

        if len(frame_paths) == 1:
            minimum_frames = max(1, int(round(float(fps) * float(min_duration_sec))))
            while frames_written < minimum_frames:
                writer.write(first)
                frames_written += 1
    except Exception:
        writer.release()
        temporary.unlink(missing_ok=True)
        raise
    else:
        writer.release()

    if frames_written <= 0 or not temporary.exists() or temporary.stat().st_size <= 0:
        temporary.unlink(missing_ok=True)
        raise ValueError(f"No frames were written to: {output}")
    os.replace(temporary, output)
    return str(output)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", help="One image file or a directory of ordered images")
    parser.add_argument("output", help="Output MP4 path")
    parser.add_argument("--fps", type=float, default=10.0, help="Output frames per second")
    parser.add_argument(
        "--min-duration-sec",
        type=float,
        default=1.0,
        help="Minimum duration for a single-image video",
    )
    parser.add_argument(
        "--max-side",
        type=int,
        default=None,
        help="Optionally downscale so the longest side is at most this many pixels",
    )
    parser.add_argument("--overwrite", action="store_true", help="Replace an existing output")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output = frames_to_video(
        args.source,
        args.output,
        fps=args.fps,
        min_duration_sec=args.min_duration_sec,
        max_side=args.max_side,
        overwrite=args.overwrite,
    )
    print(output)


if __name__ == "__main__":
    main()
