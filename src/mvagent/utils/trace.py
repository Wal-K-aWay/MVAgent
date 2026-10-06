from __future__ import annotations

from typing import Any, Iterable, Sequence

from mvagent.utils.tools import format_header_line, format_seconds


TraceItems = Sequence[tuple[str, Any]]
SECTION_WIDTH = 150
SUBSECTION_WIDTH = 150
STEP_WIDTH = 150


def format_trace_event(
    tags: Sequence[str],
    event: str,
    *,
    fields: TraceItems | None = None,
    blocks: TraceItems | None = None,
) -> str:
    """Format a readable multi-line runtime trace event."""
    prefix_lines, header, content_indent = _format_header(tags, event)

    lines = [*prefix_lines]
    if header:
        lines.append(header)
    for key, value in fields or ():
        lines.append(f"{' ' * content_indent}{key}: {_format_trace_value(value)}")
    for key, value in blocks or ():
        if not str(key).strip():
            lines.extend(_indent_block(value, indent=content_indent + 2))
            continue
        lines.append(f"{' ' * content_indent}{key}:")
        lines.extend(_indent_block(value, indent=content_indent + 2))
    return "\n" + "\n".join(lines)


def format_trace_range(time_range: list[Any]) -> str:
    """Render one ``[start_sec, end_sec]`` range as compact ``start-end`` seconds."""
    try:
        start = format_seconds(float(time_range[0]), pad_decimal=False)
        end = format_seconds(float(time_range[1]), pad_decimal=False)
    except (TypeError, ValueError):
        return "unknown"
    return f"{start}-{end}s"


def format_watch_video_selections(videos: list[dict[str, Any]]) -> str:
    """Render selected watch_videos clips as compact terminal lines."""
    lines: list[str] = []
    for video in videos:
        if not isinstance(video, dict):
            continue
        clip = video.get("clip") or []
        if isinstance(clip, list) and len(clip) == 2:
            clip_text = format_trace_range(clip)
        else:
            clip_text = "unknown"
        lines.append(f"- {video.get('video_id')}: {clip_text}")
    return "\n".join(lines) if lines else "(none)"


def format_watch_video_results(videos: list[dict[str, Any]]) -> str:
    """Render executed watch_videos clips as compact terminal lines."""
    lines: list[str] = []
    for video in videos:
        if not isinstance(video, dict):
            continue
        time_range = video.get("time_range") or []
        if isinstance(time_range, list) and len(time_range) == 2:
            range_text = format_trace_range(time_range)
        else:
            range_text = "unknown"
        lines.append(
            "- "
            f"{video.get('video_id')}: {range_text}; "
            f"limit {video.get('video_frame_limit')} frames; "
            f"estimated {video.get('estimated_frames')} frames"
        )
    return "\n".join(lines) if lines else "(none)"


def _format_header(tags: Sequence[str], event: str) -> tuple[list[str], str, int]:
    clean_tags = [str(tag).strip() for tag in tags if str(tag).strip()]
    event_text = str(event or "").strip()
    if not clean_tags:
        return [], event_text, 2

    first = clean_tags[0]
    if first.startswith("ROUND "):
        return _format_round_header(clean_tags, event_text)
    if first == "FINAL":
        return _format_final_header(clean_tags, event_text)
    if first == "RUN":
        if event_text == "Start question":
            return [
                format_header_line(width=SECTION_WIDTH, fill="="),
                format_header_line("QUESTION START", width=SECTION_WIDTH, fill="="),
                format_header_line(width=SECTION_WIDTH, fill="="),
            ], "", 0
        return [], f"RUN | {event_text}", 0
    if first == "MODEL":
        return [], f"MODEL {event_text}".rstrip(), 2

    if any(tag.startswith("STEP ") for tag in clean_tags):
        return [
            format_header_line(
                f"{_format_agent_tags(clean_tags)} {event_text}".rstrip(),
                width=STEP_WIDTH,
                fill=".",
            )
        ], "", 0

    header = _format_agent_tags(clean_tags)
    return [], f"{header} {event_text}".rstrip(), 0


def _format_round_header(tags: list[str], event: str) -> tuple[list[str], str, int]:
    round_tag = tags[0]
    rest = tags[1:]
    if not rest:
        return [format_header_line(round_tag, width=SECTION_WIDTH, fill="=")], "", 2

    is_internal_step = any(tag.startswith("STEP ") for tag in rest)
    if is_internal_step:
        step_tag = next(tag for tag in rest if tag.startswith("STEP "))
        return [
            format_header_line(
                f"[{step_tag}] {event}".rstrip(),
                width=STEP_WIDTH,
                fill=".",
            )
        ], "", 0

    if any(tag.startswith("VideoAgent:") for tag in rest) and event in {"Report", "Final review report"}:
        return [], "[Report]", 0

    agent = _format_agent_tags(rest)
    return [
        format_header_line(
            f"{agent} {event}".rstrip(),
            width=SUBSECTION_WIDTH,
        ),
    ], "", 0


def _format_final_header(tags: list[str], event: str) -> tuple[list[str], str, int]:
    prefix = [format_header_line("FINAL", width=SECTION_WIDTH, fill="="), ""] if event == "Select final evidence" else []
    agent = _format_agent_tags(tags[1:])
    return [
        *prefix,
        format_header_line(
            f"{agent} {event}".rstrip(),
            width=SUBSECTION_WIDTH,
        ),
    ], "", 0


def _format_agent_tags(tags: Sequence[str]) -> str:
    return "".join(f"[{tag}]" for tag in tags if str(tag).strip())


def _format_trace_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "(none)"
    return str(value)


def _indent_block(value: Any, *, indent: int) -> Iterable[str]:
    text = _format_trace_value(value)
    lines = text.splitlines() or [""]
    prefix = " " * indent
    return [f"{prefix}{line}" for line in lines]


__all__ = [
    "format_trace_event",
    "format_trace_range",
    "format_watch_video_results",
    "format_watch_video_selections",
]
