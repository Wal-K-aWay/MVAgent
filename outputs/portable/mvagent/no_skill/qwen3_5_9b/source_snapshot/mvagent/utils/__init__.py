from __future__ import annotations

from importlib import import_module
from typing import Any

from .tools import (
    cleanup_run_cache_dir,
    compose_question,
    extract_json,
    format_header_line,
    json_safe,
    normalize_video_map,
    prepare_run_dirs,
    resolve_local_path,
)
from .snapshot import (
    activate_snapshot_imports,
    clean_cache,
    configure_workspace_runtime_env,
    create_timestamp_dir,
    ensure_source_snapshot,
    load_runtime_modules,
    mask_sensitive_data,
    prepare_run_environment,
    print_agent_configs,
    read_runtime_output_dir,
    save_config,
)
from .trace import format_trace_event

_MEDIA_EXPORTS = {
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
}


def __getattr__(name: str) -> Any:
    if name in _MEDIA_EXPORTS:
        media = import_module(".media", __name__)
        return getattr(media, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "compose_question",
    "extract_json",
    "format_header_line",
    "json_safe",
    "normalize_time_range",
    "normalize_video_map",
    "activate_snapshot_imports",
    "clean_cache",
    "configure_workspace_runtime_env",
    "create_timestamp_dir",
    "ensure_source_snapshot",
    "load_runtime_modules",
    "mask_sensitive_data",
    "prepare_run_environment",
    "print_agent_configs",
    "cleanup_run_cache_dir",
    "prepare_run_dirs",
    "read_runtime_output_dir",
    "save_config",
    "resolve_local_path",
    "format_trace_event",
    *_MEDIA_EXPORTS,
]
