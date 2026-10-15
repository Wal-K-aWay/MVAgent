from __future__ import annotations

from collections.abc import Iterable
from copy import deepcopy
from typing import Any

from mvagent.schema import text_schema

MIN_OBSERVE_FPS = 0.1
MAX_OBSERVE_FPS = 25.0


VISUAL_OBSERVATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["text", "uncertainty"],
    "properties": {
        "text": {
            **text_schema("text"),
            "description": (
                "Grounded visible facts that resolve WHAT. When WHAT requires "
                "temporal localization, use source-video seconds from the "
                "supplied clip timeline mapping."
            ),
        },
        "uncertainty": {
            **text_schema("uncertainty", allow_empty=True),
            "description": (
                "Answer-relevant ambiguity, occlusion, missing detail, or "
                "sampling limitation; empty when none."
            ),
        },
    },
}

OBSERVE_PARAMETERS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["what", "where", "fps"],
    "properties": {
        "what": text_schema("what"),
        "where": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "array",
                "minItems": 2,
                "maxItems": 2,
                "items": {"type": "number"},
            },
        },
        "fps": {
            "type": "number",
            "minimum": MIN_OBSERVE_FPS,
            "maximum": MAX_OBSERVE_FPS,
            "enum": [value / 10 if value % 10 else value // 10 for value in range(1, 251)],
            "description": "Planned sampling FPS in 0.1 increments.",
        },
    },
}


FINISH_PARAMETERS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["summary"],
    "properties": {
        "summary": {
            **text_schema("summary"),
            "description": (
                "Concise self-contained summary of the answer-relevant visible "
                "facts established by accumulated usable same-video "
                "observations, including any answer-relevant uncertainty or "
                "limitation when present."
            ),
        },
    },
}

VIDEO_FINISH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["summary"],
    "properties": deepcopy(FINISH_PARAMETERS_SCHEMA["properties"]),
}

ACTION_PARAMETER_SCHEMAS = {
    "observe": OBSERVE_PARAMETERS_SCHEMA,
    "finish": FINISH_PARAMETERS_SCHEMA,
}


def build_video_action_schema(
    action_names: Iterable[str], *,
    duration_sec: float | None = None, max_ranges: int | None = None,
) -> dict[str, Any]:
    """Build the exact Planner contract for supplied runtime actions."""
    schemas = deepcopy(ACTION_PARAMETER_SCHEMAS)
    ranges = schemas["observe"]["properties"]["where"]
    ranges["items"]["items"]["minimum"] = 0
    if duration_sec is not None:
        ranges["items"]["items"]["maximum"] = duration_sec
    if max_ranges is not None:
        ranges["maxItems"] = max_ranges
    names: list[str] = []
    for raw_name in action_names:
        name = str(raw_name).strip()
        if name and name not in names:
            if name not in schemas:
                raise ValueError(f"Unknown Planner action schema: {name}")
            names.append(name)
    if not names:
        raise ValueError("At least one Planner action schema is required")

    parameter_properties: dict[str, Any] = {}
    branches: list[dict[str, Any]] = []
    for name in names:
        schema = schemas[name]
        for property_name, property_schema in schema["properties"].items():
            parameter_properties[property_name] = deepcopy(property_schema)
        branches.append(
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["action", "parameters"],
                "properties": {
                    "action": {"const": name},
                    "parameters": deepcopy(schema),
                }
            }
        )
    return {
        "type": "object",
        "required": ["action", "parameters"],
        "properties": {
            "action": {"type": "string", "enum": names},
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": parameter_properties,
            },
        },
        "additionalProperties": False,
        "anyOf": branches,
    }


__all__ = [
    "ACTION_PARAMETER_SCHEMAS",
    "FINISH_PARAMETERS_SCHEMA",
    "MAX_OBSERVE_FPS",
    "MIN_OBSERVE_FPS",
    "OBSERVE_PARAMETERS_SCHEMA",
    "VISUAL_OBSERVATION_SCHEMA",
    "VIDEO_FINISH_SCHEMA",
    "build_video_action_schema",
]
