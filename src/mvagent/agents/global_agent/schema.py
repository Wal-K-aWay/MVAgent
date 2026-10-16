from __future__ import annotations

from collections.abc import Iterable
from copy import deepcopy
from typing import Any


_ANSWER_PARAMETERS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["answer"],
    "properties": {
        "answer": {"type": "string", "minLength": 1},
    },
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
                    "instruction": {"type": "string", "minLength": 1},
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
            "type": "string",
            "minLength": 1,
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
    "reason": {"type": "string", "minLength": 1},
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

    parameter_properties: dict[str, Any] = {}
    action_branches: list[dict[str, Any]] = []
    for name in normalized_names:
        parameter_schema = _GLOBAL_ACTION_PARAMETER_SCHEMAS[name]
        for property_name, property_schema in parameter_schema[
            "properties"
        ].items():
            parameter_properties[property_name] = deepcopy(property_schema)
        action_branches.append(
            {
                "properties": {
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
        "oneOf": action_branches,
    }


GLOBAL_DECISION_SCHEMA: dict[str, Any] = build_global_decision_schema(
    _GLOBAL_ACTION_PARAMETER_SCHEMAS
)

GLOBAL_ANSWER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["reason", "answer"],
    "properties": {
        "reason": {"type": "string", "minLength": 1},
        "answer": {"type": "string", "minLength": 1},
    },
}


__all__ = [
    "GLOBAL_ANSWER_SCHEMA",
    "GLOBAL_DECISION_SCHEMA",
    "available_global_action_names",
    "build_global_decision_schema",
]
