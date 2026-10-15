from __future__ import annotations

import math
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterable, List

import cv2
from PIL import Image

from mvagent.utils.tools import resolve_local_path


MIN_TEMPORAL_VIDEO_FRAMES = 2


def floor_fps(value: float) -> float:
    """Floor one finite FPS value to the runtime's 0.1 precision."""
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("FPS must be finite.")
    return math.floor(number * 10.0 + 1e-9) / 10.0


def _ceil_fps(value: float) -> float:
    """Ceil one finite FPS value to the runtime's 0.1 precision."""
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("FPS must be finite.")
    return math.ceil(number * 10.0 - 1e-9) / 10.0


def normalize_fps(
    value: float,
    *,
    minimum: float = 0.1,
    maximum: float = 25.0,
) -> float:
    """Validate an FPS boundary and normalize it downward to 0.1."""
    number = float(value)
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise ValueError(
            f"FPS must be between {minimum:.1f} and {maximum:.1f}."
        )
    return floor_fps(number)


def fit_video_sampling_fps(
    planned_fps: float,
    *,
    duration_sec: float,
    max_frames: int,
    minimum_frames: int = MIN_TEMPORAL_VIDEO_FRAMES,
    maximum_fps: float = 25.0,
) -> float:
    """Fit sampling to model capacity while preserving a temporal input.

    Ordinary ranges retain the Planner's sampling rate unless the model frame
    limit requires a lower value. Very short ranges may be raised just enough
    to provide the minimum temporal frame count. If the source interval is too
    short to reach that count at ``maximum_fps``, the returned maximum rate is
    paired with deterministic clip padding in :func:`cut_video_segment`.
    """
    duration = float(duration_sec)
    frame_limit = int(max_frames)
    minimum = int(minimum_frames)
    max_fps = float(maximum_fps)
    if not math.isfinite(duration) or duration <= 0.0:
        raise ValueError("Video sampling duration must be finite and positive.")
    if minimum <= 0:
        raise ValueError("minimum_frames must be positive.")
    if frame_limit < minimum:
        raise ValueError(
            f"Video frame limit must allow at least {minimum} temporal frames."
        )
    if not math.isfinite(max_fps) or max_fps <= 0.0:
        raise ValueError("maximum_fps must be finite and positive.")

    planned = normalize_fps(planned_fps, maximum=max_fps)
    capacity_fps = floor_fps(min(max_fps, frame_limit / duration))
    if capacity_fps < 0.1:
        raise ValueError(
            "Frame limit cannot satisfy the minimum 0.1 FPS for this range."
        )
    effective = floor_fps(min(planned, capacity_fps))
    if duration * effective + 1e-9 >= minimum:
        return effective

    required = _ceil_fps(minimum / duration)
    return min(required, capacity_fps)


def normalize_time_range(value: Any) -> list[float]:
    """Normalize one time range into ``[start_sec, end_sec]``."""
    segment = _time_range_segment(value)
    if segment is None and isinstance(value, (list, tuple)):
        for item in value:
            segment = _time_range_segment(item)
            if segment is not None:
                break
    return [segment[0], segment[1]] if segment is not None else []


def _time_range_segment(item: Any) -> tuple[float, float] | None:
    if isinstance(item, dict):
        start_candidate = item.get(
            "start_sec",
            item.get(
                "start",
                item.get("from", item.get("timestamp", item.get("time"))),
            ),
        )
        end_candidate = item.get(
            "end_sec",
            item.get("end", item.get("to", item.get("stop", start_candidate))),
        )
    elif isinstance(item, (list, tuple)):
        if len(item) < 2:
            return _time_range_segment(item[0]) if item else None
        start_candidate, end_candidate = item[0], item[1]
    else:
        start_candidate = end_candidate = item
    try:
        start = round(float(start_candidate), 3)
        end = round(float(end_candidate), 3)
    except (TypeError, ValueError):
        return None
    return (end, start) if end < start else (start, end)


def load_image_source(image: Any) -> Any:
    """Normalize one image-like input into a backend-friendly object."""
    if isinstance(image, str):
        if image.startswith(("http://", "https://")):
            return image
        return Image.open(resolve_local_path(image))
    return image


def probe_video_info(video_path: str) -> Dict[str, Any]:
    """Extract detailed metadata from a video file.

    Args:
        video_path: Path to the input video file.

    Returns:
        Metadata with normalized path, duration, fps, frame count,
        and resolution.
    """
    resolved_path = resolve_local_path(video_path)
    capture = cv2.VideoCapture(resolved_path)
    try:
        if not capture.isOpened():
            raise ValueError(f"Cannot open video for metadata probing: {resolved_path}")

        fps = _positive_capture_float(capture, cv2.CAP_PROP_FPS, "FPS")
        frame_count = _positive_capture_int(
            capture,
            cv2.CAP_PROP_FRAME_COUNT,
            "frame count",
        )
        width = _positive_capture_int(capture, cv2.CAP_PROP_FRAME_WIDTH, "width")
        height = _positive_capture_int(
            capture,
            cv2.CAP_PROP_FRAME_HEIGHT,
            "height",
        )
        ok, first_frame = capture.read()
        if not ok or first_frame is None or first_frame.size <= 0:
            raise ValueError(f"Cannot decode the first video frame: {resolved_path}")
        decoded_height, decoded_width = first_frame.shape[:2]
        if decoded_width <= 0 or decoded_height <= 0:
            raise ValueError(f"Decoded video frame is empty: {resolved_path}")
        width, height = decoded_width, decoded_height
        duration = frame_count / fps
        return {
            "path": video_path,
            "duration_sec": round(duration, 2),
            "fps": round(fps, 2),
            "frame_count": frame_count,
            "width": width,
            "height": height,
            "resolution": f"{width}x{height}",
        }
    finally:
        capture.release()


def cut_video_segment(
    video_path: str,
    time_range: List[float],
    output_dir: str | None = None,
    prefix: str = "segment",
    *,
    temp_dir_prefix: str = "mvagent_segments_",
    sampling_fps: float | None = None,
    minimum_sampled_frames: int = MIN_TEMPORAL_VIDEO_FRAMES,
) -> str:
    """Write one time segment from a video to a temporary mp4 file using OpenCV.

    The returned clip has local timestamps starting at 0s. Callers should keep
    the original absolute ``time_range`` in prompts and evidence records.
    """
    segment = normalize_time_range(time_range)
    if len(segment) < 2:
        raise ValueError(f"Invalid time_range for video segment: {time_range}")

    start_sec, end_sec = float(segment[0]), float(segment[1])
    if end_sec <= start_sec:
        raise ValueError(f"Video segment end must be after start: {segment}")

    resolved_path = resolve_local_path(video_path)
    capture = cv2.VideoCapture(resolved_path)
    try:
        if not capture.isOpened():
            raise ValueError(f"Cannot open video for segment cutting: {resolved_path}")

        fps = _positive_capture_float(capture, cv2.CAP_PROP_FPS, "FPS")
        frame_count = _positive_capture_int(
            capture,
            cv2.CAP_PROP_FRAME_COUNT,
            "frame count",
        )
        width = _positive_capture_int(capture, cv2.CAP_PROP_FRAME_WIDTH, "width")
        height = _positive_capture_int(
            capture,
            cv2.CAP_PROP_FRAME_HEIGHT,
            "height",
        )
        requested_sampling_fps: float | None = None
        if sampling_fps is not None:
            requested_sampling_fps = float(sampling_fps)
            if (
                not math.isfinite(requested_sampling_fps)
                or requested_sampling_fps <= 0.0
            ):
                raise ValueError("Segment sampling_fps must be finite and positive.")
            if int(minimum_sampled_frames) <= 0:
                raise ValueError("minimum_sampled_frames must be positive.")

        start_frame = max(0, int(start_sec * fps))
        end_frame = max(start_frame + 1, int(end_sec * fps))
        if frame_count > 0:
            start_frame = min(start_frame, frame_count - 1)
            end_frame = min(max(end_frame, start_frame + 1), frame_count)

        segment_dir = Path(output_dir) if output_dir else Path(tempfile.mkdtemp(prefix=temp_dir_prefix))
        segment_dir.mkdir(parents=True, exist_ok=True)
        output_path = segment_dir / _segment_filename(prefix, start_sec, end_sec)

        writer = cv2.VideoWriter(
            str(output_path),
            cv2.VideoWriter_fourcc(*"mp4v"),
            fps,
            (width, height),
        )
        if not writer.isOpened():
            raise ValueError(f"Cannot create video segment writer: {output_path}")

        frames_written = 0
        last_frame = None
        try:
            capture.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
            frame_index = start_frame
            while frame_index < end_frame:
                ok, frame = capture.read()
                if not ok:
                    break
                writer.write(frame)
                last_frame = frame
                frames_written += 1
                frame_index += 1
            if requested_sampling_fps is not None and last_frame is not None:
                minimum_encoded_frames = int(
                    math.ceil(
                        int(minimum_sampled_frames)
                        * fps
                        / requested_sampling_fps
                        - 1e-9
                    )
                )
                while frames_written < minimum_encoded_frames:
                    writer.write(last_frame)
                    frames_written += 1
        finally:
            writer.release()

        if frames_written <= 0 or not output_path.exists() or output_path.stat().st_size <= 0:
            raise ValueError(f"No frames written for video segment: {resolved_path} {segment}")
        return str(output_path.resolve())
    finally:
        capture.release()


def validate_video_ranges(
    ranges: Iterable[Iterable[float]],
    *,
    duration_sec: float,
    max_ranges: int,
) -> list[list[float]]:
    """Validate VLM-selected ranges against the owning video's duration."""
    duration = float(duration_sec)
    limit = max(1, int(max_ranges))
    requested = list(ranges or [])
    if len(requested) > limit:
        raise ValueError(f"Requested {len(requested)} ranges; maximum is {limit}.")

    normalized: list[list[float]] = []
    seen: set[tuple[float, float]] = set()
    for raw_range in requested:
        time_range = normalize_time_range(list(raw_range))
        if len(time_range) != 2 or time_range[1] <= time_range[0]:
            raise ValueError(f"Invalid video range: {raw_range}")
        start_sec, end_sec = time_range
        if not math.isfinite(start_sec) or not math.isfinite(end_sec):
            raise ValueError(f"Video range must use finite seconds: {raw_range}")
        if start_sec < 0 or end_sec > duration + 1e-6:
            raise ValueError(
                f"Requested range {time_range} is outside video duration [0.0, {duration}]."
            )
        key = (start_sec, end_sec)
        if key in seen:
            continue
        seen.add(key)
        normalized.append(time_range)
    return normalized


def validate_action_video_ranges(
    ranges: Iterable[Iterable[float]],
    *,
    mode: str,
    duration_sec: float,
    max_ranges: int,
) -> list[list[float]]:
    """Validate precise source-video ranges for one observation action.

    ``observe`` accepts one or more ordered, non-overlapping ranges whose
    boundaries may use any finite source-video second within the duration.
    """
    action_mode = str(mode or "").strip().lower()
    if action_mode != "observe":
        raise ValueError(f"Unsupported video range mode: {mode}")

    requested = list(ranges or [])
    normalized = validate_video_ranges(
        requested,
        duration_sec=duration_sec,
        max_ranges=max_ranges,
    )
    if not normalized:
        raise ValueError("observe requires at least one range.")
    if len(normalized) != len(requested):
        raise ValueError("observe ranges must be chronological and non-overlapping.")

    previous_end: float | None = None
    for time_range in normalized:
        key = (float(time_range[0]), float(time_range[1]))
        if previous_end is not None and key[0] < previous_end:
            raise ValueError(
                "observe ranges must be chronological and non-overlapping."
            )
        previous_end = key[1]

    return normalized


def _segment_filename(prefix: str, start_sec: float, end_sec: float) -> str:
    safe_prefix = _safe_media_prefix(prefix)
    start = f"{start_sec:.3f}".replace(".", "p")
    end = f"{end_sec:.3f}".replace(".", "p")
    return f"{safe_prefix}_{start}_{end}.mp4"


def _safe_media_prefix(prefix: str) -> str:
    return "".join(
        ch if ch.isalnum() or ch in ("-", "_") else "_"
        for ch in str(prefix or "media")
    )


def _positive_capture_float(
    capture: cv2.VideoCapture,
    property_id: int,
    label: str,
) -> float:
    value = float(capture.get(property_id) or 0.0)
    if not math.isfinite(value) or value <= 0.0:
        raise ValueError(f"Cannot determine positive video {label}.")
    return value


def _positive_capture_int(
    capture: cv2.VideoCapture,
    property_id: int,
    label: str,
) -> int:
    value = _positive_capture_float(capture, property_id, label)
    normalized = int(round(value))
    if normalized <= 0:
        raise ValueError(f"Cannot determine positive video {label}.")
    return normalized


__all__ = [
    "MIN_TEMPORAL_VIDEO_FRAMES",
    "cut_video_segment",
    "fit_video_sampling_fps",
    "floor_fps",
    "load_image_source",
    "normalize_fps",
    "normalize_time_range",
    "probe_video_info",
    "validate_action_video_ranges",
    "validate_video_ranges",
]
