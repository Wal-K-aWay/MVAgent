from __future__ import annotations

import math
import re
import shutil
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from models.utils import (
    extract_json,
    is_loopback_host,
    looks_like_env_var_name,
    resolve_local_path,
    validate_gpu_list,
    validate_json_schema,
)


_VIDEO_ID_RE = re.compile(r"^[a-z][A-Za-z0-9_]*$")


def json_safe(value: Any) -> Any:
    """Convert runtime values into JSON-serializable primitives."""
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "tolist"):
        return json_safe(value.tolist())
    if hasattr(value, "item"):
        return json_safe(value.item())
    return value


def normalize_video_map(videos: Mapping[str, str]) -> dict[str, str]:
    if not isinstance(videos, Mapping) or not videos:
        raise ValueError("At least one role-to-path video mapping is required.")
    normalized: dict[str, str] = {}
    for raw_video_id, raw_path in videos.items():
        video_id = str(raw_video_id).strip()
        path = str(raw_path).strip()
        if not _VIDEO_ID_RE.fullmatch(video_id):
            raise ValueError(f"Invalid video identity: {video_id}")
        if video_id in normalized:
            raise ValueError(f"Duplicate video identity: {video_id}")
        if not path:
            raise ValueError(f"Video path is empty for identity: {video_id}")
        normalized[video_id] = resolve_local_path(path)
    return normalized


def prepare_run_dirs(
    *,
    output_dir: str | Path,
    cache_dir: str | Path,
    cache_prefix: str = "question_",
) -> Path:
    output_path = Path(output_dir).expanduser().resolve()
    output_path.mkdir(parents=True, exist_ok=True)
    cache_root = Path(cache_dir).expanduser().resolve()
    cache_root.mkdir(parents=True, exist_ok=True)
    run_cache = Path(
        tempfile.mkdtemp(prefix=cache_prefix, dir=str(cache_root))
    )
    return run_cache


def cleanup_run_cache_dir(run_cache_dir: str | Path | None) -> None:
    if run_cache_dir is not None:
        shutil.rmtree(Path(run_cache_dir), ignore_errors=True)


def clean_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def is_number(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def format_seconds(
    value: Any,
    *,
    precision: int = 3,
    small_precision: int | None = None,
    pad_decimal: bool = True,
) -> str:
    """Format one finite seconds value as a compact decimal string.

    Trailing zeros are trimmed and, when ``pad_decimal`` is set, at least one
    decimal digit is retained so ``10.0`` renders as ``"10.0"``. Values whose
    magnitude is below ``10**-precision`` use ``small_precision`` decimals when
    supplied, so tiny source times are not collapsed to zero.

    Raises:
        ValueError: If the value is not a finite number.
    """
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Seconds values must be finite.")
    if small_precision is not None and 0.0 < abs(number) < 10.0 ** (-precision):
        rendered = f"{number:.{small_precision}f}"
    else:
        rendered = f"{number:.{precision}f}"
    rendered = rendered.rstrip("0").rstrip(".")
    if rendered in {"", "-0"}:
        rendered = "0"
    if not pad_decimal:
        return rendered
    return rendered if "." in rendered else f"{rendered}.0"


def format_number(value: Any) -> str:
    """Format one numeric value compactly, returning ``""`` when invalid."""
    if not is_number(value):
        return ""
    return format_seconds(value)


def format_time_range(value: Any) -> str:
    if (
        not isinstance(value, (list, tuple))
        or len(value) != 2
        or not all(is_number(item) for item in value)
    ):
        return ""
    return f"{format_number(value[0])}–{format_number(value[1])}s"


def format_fps(value: Any) -> str:
    return f"{float(value):.1f} FPS" if is_number(value) else ""


def compose_question(question: str, options: Any = ()) -> str:
    """Append ordered options unless the question already owns that block."""
    question_text = str(question or "").strip()
    option_lines = [
        str(option).strip()
        for option in (options or ())
        if option is not None and str(option).strip()
    ]
    if not option_lines or re.search(r"(?m)^Options:\s*$", question_text):
        return question_text
    return f"{question_text}\n\nOptions:\n" + "\n".join(option_lines)


def format_header_line(
    text: Any = "",
    *,
    width: int = 150,
    fill: str = "-",
) -> str:
    """Return one fixed-width centered log header line."""
    width = max(1, int(width))
    fill = str(fill or "-")
    label = str(text or "").strip()
    if not label:
        return _repeat_fill(fill, width)
    label = f" {label} "
    if len(label) >= width:
        return label.strip()
    remaining = width - len(label)
    left = remaining // 2
    return (
        f"{_repeat_fill(fill, left)}{label}"
        f"{_repeat_fill(fill, remaining - left)}"
    )


def _repeat_fill(fill: str, count: int) -> str:
    if count <= 0:
        return ""
    repeats = (count + len(fill) - 1) // len(fill)
    return (fill * repeats)[:count]


__all__ = [
    "clean_text",
    "cleanup_run_cache_dir",
    "compose_question",
    "extract_json",
    "format_fps",
    "format_header_line",
    "format_number",
    "format_seconds",
    "format_time_range",
    "is_loopback_host",
    "is_number",
    "json_safe",
    "looks_like_env_var_name",
    "normalize_video_map",
    "prepare_run_dirs",
    "resolve_local_path",
    "validate_gpu_list",
    "validate_json_schema",
]
