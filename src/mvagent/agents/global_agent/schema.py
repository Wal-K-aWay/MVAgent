from __future__ import annotations

from collections.abc import Iterable
from copy import deepcopy
from typing import Any

from mvagent.schema import text_schema, analyze_instruction_limit


_ANSWER_PARAMETERS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {},
}

_ANALYZE_VIDEOS_PARAMETERS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["videoagent_request"],
    "properties": {
        "videoagent_request": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["video_id", "instruction"],
                "properties": {
                    "video_id": {"type": "string", "minLength": 1},
                    "instruction": text_schema("instruction"),
                },
            },
        },
    },
}

_WATCH_VIDEOS_PARAMETERS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["instruction", "videos"],
    "properties": {
        "instruction": {
            **text_schema("instruction"),
            "description": (
                "Self-contained cross-video visual-analysis instruction "
                "sent as the sole task to the visual model."
            ),
        },
        "videos": {
            "type": "array",
            "minItems": 2,
            "description": (
                "At least two distinct videos whose single selected clips are "
                "analyzed together in one visual call."
            ),
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["video_id", "clip"],
                "properties": {
                    "video_id": {"type": "string", "minLength": 1},
                    "clip": {
                        "type": "array",
                        "minItems": 2,
                        "maxItems": 2,
                        "items": {"type": "number"},
                    },
                },
            },
        },
    },
}

_GLOBAL_ACTION_PARAMETER_SCHEMAS: dict[str, dict[str, Any]] = {
    "answer": _ANSWER_PARAMETERS_SCHEMA,
    "analyze_videos": _ANALYZE_VIDEOS_PARAMETERS_SCHEMA,
    "watch_videos": _WATCH_VIDEOS_PARAMETERS_SCHEMA,
}


_GLOBAL_DECISION_PROPERTIES: dict[str, Any] = {
    "reason": text_schema("reason"),
    "action": {
        "type": "string",
        "enum": list(_GLOBAL_ACTION_PARAMETER_SCHEMAS),
    },
    "parameters": {
        "type": "object",
        "additionalProperties": False,
        "properties": {},
    },
}


def available_global_action_names(
    *,
    watch_videos_available: bool,
) -> tuple[str, ...]:
    """Return GlobalAgent actions available for one decision call."""
    names = ["answer", "analyze_videos"]
    if watch_videos_available:
        names.append("watch_videos")
    return tuple(names)


def build_global_decision_schema(
    action_names: Iterable[str],
    *,
    video_ids: Iterable[str] | None = None,
    video_durations: dict[str, float] | None = None,
    max_watch_videos: int | None = None,
) -> dict[str, Any]:
    """Build the GlobalAgent contract for exactly the supplied actions."""
    normalized_names: list[str] = []
    seen: set[str] = set()
    for raw_name in action_names:
        name = str(raw_name).strip()
        if name in seen:
            continue
        if name not in _GLOBAL_ACTION_PARAMETER_SCHEMAS:
            raise ValueError(f"Unknown GlobalAgent action schema: {name}")
        seen.add(name)
        normalized_names.append(name)
    if not normalized_names:
        raise ValueError("At least one GlobalAgent action schema is required")

    schemas = deepcopy(_GLOBAL_ACTION_PARAMETER_SCHEMAS)
    if video_ids is not None:
        ids = list(video_ids)
        requests = schemas["analyze_videos"]["properties"]["videoagent_request"]
        requests["maxItems"] = len(ids)
        requests["items"]["properties"]["video_id"] = {"enum": ids}
        # Linear-size alternatives allocate text space by actual request count.
        requests["anyOf"] = []
        for count in range(1, len(ids) + 1):
            item = deepcopy(requests["items"])
            item["properties"]["instruction"]["maxLength"] = analyze_instruction_limit(count)
            requests["anyOf"].append({
                "type": "array", "minItems": count, "maxItems": count, "items": item,
            })
        videos = schemas["watch_videos"]["properties"]["videos"]
        videos["maxItems"] = min(len(ids), max_watch_videos if max_watch_videos is not None else len(ids))
        # Each video has its own source-time bounds; no global maximum duration.
        selections = []
        for video_id in ids:
            item = deepcopy(videos["items"])
            item["properties"]["video_id"] = {"const": video_id}
            bounds = {"type": "number", "minimum": 0}
            if video_durations is not None and video_id in video_durations:
                bounds["maximum"] = video_durations[video_id]
            item["properties"]["clip"]["items"] = bounds
            selections.append(item)
        videos["items"] = {"anyOf": selections}
        # Full-schema validation catches duplicate IDs even if payloads differ.
        # This runs inside the existing text repair path, before action execution.
        for array in (requests, videos):
            array["allOf"] = [
                {"contains": {"type": "object", "required": ["video_id"],
                              "properties": {"video_id": {"const": video_id}}},
                 "minContains": 0, "maxContains": 1}
                for video_id in ids
            ]

    parameter_properties: dict[str, Any] = {}
    action_branches: list[dict[str, Any]] = []
    for name in normalized_names:
        parameter_schema = schemas[name]
        for property_name, property_schema in parameter_schema[
            "properties"
        ].items():
            parameter_properties[property_name] = deepcopy(property_schema)
        action_branches.append(
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["reason", "action", "parameters"],
                "properties": {
                    "reason": text_schema("reason"),
                    "action": {"const": name},
                    "parameters": deepcopy(parameter_schema),
                }
            }
        )

    properties = deepcopy(_GLOBAL_DECISION_PROPERTIES)
    properties["action"]["enum"] = list(normalized_names)
    properties["parameters"]["properties"] = parameter_properties
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["reason", "action", "parameters"],
        "properties": properties,
        "anyOf": action_branches,
    }


GLOBAL_DECISION_SCHEMA: dict[str, Any] = build_global_decision_schema(
    _GLOBAL_ACTION_PARAMETER_SCHEMAS
)

GLOBAL_ANSWER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["reason", "answer"],
    "properties": {
        "reason": text_schema("reason"),
        "answer": text_schema("answer"),
    },
}


__all__ = [
    "GLOBAL_ANSWER_SCHEMA",
    "GLOBAL_DECISION_SCHEMA",
    "available_global_action_names",
    "build_global_decision_schema",
]
