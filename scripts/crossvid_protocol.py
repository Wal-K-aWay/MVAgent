"""MVAgent-specific CrossVid manifest and prompt-format helpers.

Benchmark inference and scoring live only in the vendored official source under
``eval/e2e_eval``.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping, Sequence



CHOICE_TASKS = {"BU", "CC", "MOC", "MSR", "NC", "PEA", "PI"}
QUESTION_CHOICE_TASKS = {"BU", "CC", "MOC", "MSR", "NC", "PEA"}
CROSSVID_MANIFEST_SCHEMA_VERSION = "mvagent.qa.v1"
CROSSVID_PROMPT_PROFILE_VERSION = "crossvid.task-context.v2"
LEGACY_CROSSVID_PROMPT_PROFILE_VERSIONS = {"crossvid.task-context.v1"}
MOC_MSR_PROTOCOL_CURRENT_TEXT_BBOX = "current_text_bbox"
MOC_MSR_PROTOCOL_OFFICIAL_COORDINATE = "official_coordinate"
MOC_MSR_PROTOCOL_QUESTION_BOXES = "mvagent_question_boxes"
MOC_MSR_INPUT_PROTOCOLS = {
    MOC_MSR_PROTOCOL_CURRENT_TEXT_BBOX,
    MOC_MSR_PROTOCOL_OFFICIAL_COORDINATE,
    MOC_MSR_PROTOCOL_QUESTION_BOXES,
}
OFFICIAL_PROMPT_PREFIXES = {
    "BU": "Provide you several videos and a multiple-choice question",
    "CC": "Provide you four videos and a single-choice question",
    "CCQA": "Provide you two cooking videos (Video A + Video B)",
    "FSA": "Provide you two cooking videos, which step in Video 2",
    "MOC": "Provide you two synchronized UAV road recording videos",
    "MSR": "Provide you two synchronized UAV road recording videos",
    "NC": "Provide you four videos and a single-choice question",
    "PEA": "Provide you three videos assembling the same toy car",
    "PI": "Provide you the beginning and the ending of a movie clip",
    "PSS": "Provide you ",
}

SCORER_BY_TASK = {
    "BU": "crossvid.multi_choice_exact.v1",
    "CC": "crossvid.single_choice_exact.v1",
    "CCQA": "crossvid.ccqa_m3_coverage_correctness.v2",
    "FSA": "crossvid.interval_iou.v1",
    "MOC": "crossvid.single_choice_exact.v1",
    "MSR": "crossvid.single_choice_exact.v1",
    "NC": "crossvid.single_choice_exact.v1",
    "PEA": "crossvid.single_choice_exact.v1",
    "PI": "crossvid.single_choice_exact.v1",
    "PSS": "crossvid.sequence_exact.v1",
}


def infer_crossvid_task(row: Mapping[str, Any]) -> str:
    task = str(row.get("task") or "").strip().upper()
    if task:
        return task
    sample_id = str(row.get("id") or "")
    parts = sample_id.split(":")
    if len(parts) >= 3 and parts[0].lower() == "crossvid":
        return parts[1].upper()
    return ""


def normalize_crossvid_input_protocol(task: str, input_protocol: str = "") -> str:
    """Return the explicit media/prompt protocol for one CrossVid task."""

    normalized_task = str(task or "").strip().upper()
    protocol = str(input_protocol or "").strip()
    if normalized_task not in {"MOC", "MSR"}:
        return "official"
    if not protocol:
        return MOC_MSR_PROTOCOL_CURRENT_TEXT_BBOX
    if protocol not in MOC_MSR_INPUT_PROTOCOLS:
        raise ValueError(
            f"Unsupported CrossVid {normalized_task} input protocol: {protocol}. "
            f"Expected one of: {', '.join(sorted(MOC_MSR_INPUT_PROTOCOLS))}"
        )
    return protocol


def crossvid_prompt_profile(task: str, input_protocol: str = "") -> str:
    """Return a versioned identifier for deterministic Agent-question rendering."""

    normalized_task = str(task or "").strip().upper()
    protocol = normalize_crossvid_input_protocol(normalized_task, input_protocol)
    return f"{CROSSVID_PROMPT_PROFILE_VERSION}:{normalized_task}:{protocol}"


def crossvid_scorer(task: str) -> str:
    """Return the frozen scorer identifier recorded in prepared manifests."""

    normalized_task = str(task or "").strip().upper()
    try:
        return SCORER_BY_TASK[normalized_task]
    except KeyError as exc:
        raise ValueError(f"Unsupported CrossVid task: {normalized_task or task}") from exc


def format_crossvid_question(
    *,
    task: str,
    question: str,
    options: Iterable[str] = (),
    video_count: int | None = None,
    ref_segment: Sequence[Any] | None = None,
    objects_information: str = "",
    task_details: str = "",
    input_protocol: str = "",
) -> str:
    """Format one CrossVid user question with task- and media-protocol context."""

    normalized_task = str(task or "").strip().upper()
    normalized_protocol = normalize_crossvid_input_protocol(
        normalized_task,
        input_protocol,
    )
    question_text = _strip_crossvid_task_details(str(question or "").strip())
    if _looks_like_official_prompt(
        normalized_task,
        question_text,
        normalized_protocol,
    ):
        return _ensure_answer_suffix(question_text)

    option_lines = _normalize_options(options)
    parts: list[str]
    if normalized_task == "BU":
        parts = [
            "\n".join(
                [
                    "Provide you several videos and a multiple-choice question with 1-3 correct answer choices.",
                    "Watch the videos carefully, and think about the question based on the information from the videos.",
                    'Only output the capital letters of ALL your choices, e.g., "BCD".',
                ]
            ),
            _question_block(question_text),
            _options_block(option_lines),
        ]
    elif normalized_task == "CC":
        parts = [
            "\n".join(
                [
                    "Provide you four videos and a single-choice question with only one correct option.",
                    "Watch the videos carefully, and think about the question based on the information from these videos.",
                    "Select one answer choice, and only output the capital letter of your choice.",
                ]
            ),
            _question_block(question_text),
            _options_block(option_lines),
        ]
    elif normalized_task == "NC":
        parts = [
            "\n".join(
                [
                    "Provide you four videos and a single-choice question with only one correct option.",
                    "Watch the videos carefully, and think about the question based on the information from the four videos.",
                    "Select one answer choice, and only output the capital letter of your choice.",
                ]
            ),
            _question_block(question_text),
            _options_block(option_lines),
        ]
    elif normalized_task == "CCQA":
        parts = [
            "\n".join(
                [
                    "Provide you two cooking videos (Video A + Video B) and an open-ended question.",
                    "Watch the videos carefully, and think about the question based on the information from both videos.",
                ]
            ),
            _question_block(question_text),
        ]
    elif normalized_task == "FSA":
        begin, end = _ref_segment_bounds(ref_segment, question_text)
        parts = [
            "\n".join(
                [
                    (
                        "Provide you two cooking videos, which step in Video 2 is "
                        f"functionally equivalent to the step shown between {begin}s and {end}s in Video 1?"
                    ),
                    "Watch the two videos carefully, and think about the question based on the information of the two videos.",
                    'Only output a time interval in seconds and separate the beginning and ending time with a comma, e.g., "15,23".',
                ]
            ),
        ]
    elif normalized_task in {"MOC", "MSR"}:
        if normalized_protocol == MOC_MSR_PROTOCOL_QUESTION_BOXES:
            task_background = "\n".join(
                [
                    "Provide you two synchronized UAV road recording videos with question-referenced objects visually labeled and a single-choice question.",
                    "The videos show the same road scene from two camera views synchronized in time; IDs beginning with A belong to view_A, and IDs beginning with B belong to view_B.",
                    "Each referenced object ID is shown with a colored box during its first visible second in the corresponding view; use that labeled window to initialize its identity, then track it through the synchronized videos.",
                    "Watch the videos first, then track the objects in both views and think about the question based on the information.",
                    "Select one answer choice, and only output the capital letter of your choice.",
                ]
            )
        else:
            task_background = "\n".join(
                [
                    "Provide you two synchronized UAV road recording videos, objects' positional information and a single-choice question.",
                    "The videos show the same road scene from two camera views synchronized in time; IDs beginning with A belong to view_A, and IDs beginning with B belong to view_B.",
                    "The positional information contains the bounding box coordinates ([xtl, ytl, xbr, ybr]) of the objects positioned in one appearing frame.",
                    "Watch the videos first, then track the objects in both views and think about the question based on the information.",
                    "Select one answer choice, and only output the capital letter of your choice.",
                ]
            )
        parts = [
            task_background,
            _question_block(question_text),
            _options_block(option_lines),
        ]
        if normalized_protocol != MOC_MSR_PROTOCOL_QUESTION_BOXES:
            parts.append(_objects_block(objects_information))
    elif normalized_task == "PEA":
        parts = [
            "\n".join(
                [
                    "Provide you three videos assembling the same toy car and a single-choice question.",
                    "In addition, provide you four predefined error types that may assist you answer.",
                    "- wrong order: this action is an ordering mistake.",
                    "- previous one is mistake: this action is also an ordering mistake but is caused by the preceding ordering mistakes in the context.",
                    "- shouldn't have happened: this action is unnecessary in the assembly.",
                    "- wrong position: the two parts are not attached at their correct position.",
                    "Watch the videos carefully, and think about the question based on the information from these videos.",
                    "Select one answer choice, and only output the capital letter of your choice.",
                ]
            ),
            _question_block(question_text),
            _options_block(option_lines),
        ]
    elif normalized_task == "PI":
        parts = [
            "\n".join(
                [
                    "Provide you the beginning and the ending of a movie clip, what is most likely to happen in the middle?",
                    "Watch the video segments carefully, and think about the question based on the context information.",
                    "Select one answer choice, and only output the capital letter of your choice.",
                ]
            ),
            _options_block(option_lines),
        ]
    elif normalized_task == "PSS":
        n_segments = max(1, int(video_count or _infer_segment_count(question_text) or 1))
        parts = [
            "\n".join(
                [
                    f"Provide you {n_segments} shuffled segments of a cooking video, what's the correct order of these segments?",
                    "Watch the segments carefully, and think about the question based on the relationship between these segments.",
                    'Only output the correct segment number sequence separated by "->", e.g., "2->3->1->4".',
                ]
            ),
        ]
    else:
        parts = [question_text]
        if option_lines:
            parts.append(_options_block(option_lines))

    details = str(task_details or "").strip()
    if details:
        parts.append(f"Task details:\n{details}")
    parts.append("Your answer:")
    return "\n\n".join(part for part in parts if str(part).strip()).strip()


def _looks_like_official_prompt(
    task: str,
    question: str,
    input_protocol: str,
) -> bool:
    prefix = OFFICIAL_PROMPT_PREFIXES.get(task)
    if not prefix:
        return False
    if task not in {"MOC", "MSR"}:
        return question.startswith(prefix)
    if input_protocol == MOC_MSR_PROTOCOL_QUESTION_BOXES:
        return question.startswith(
            "Provide you two synchronized UAV road recording videos with "
            "question-referenced objects visually labeled"
        )
    return question.startswith(prefix) and not question.startswith(
        "Provide you two synchronized UAV road recording videos with "
        "question-referenced objects visually labeled"
    )


def _normalize_options(options: Iterable[str]) -> list[str]:
    return [str(option).strip() for option in (options or ()) if str(option).strip()]


def _question_block(question: str) -> str:
    text = str(question or "").strip()
    return f"Question:\n{text}" if text else ""


def _options_block(options: Iterable[str]) -> str:
    lines = _normalize_options(options)
    return "Options:\n" + "\n".join(lines) if lines else ""


def _objects_block(objects_information: str) -> str:
    text = str(objects_information or "").strip()
    return f"Objects information:\n{text}" if text else ""


def _ref_segment_bounds(ref_segment: Sequence[Any] | None, question: str) -> tuple[str, str]:
    if ref_segment is not None and len(ref_segment) == 2:
        return _format_time(ref_segment[0]), _format_time(ref_segment[1])
    match = re.search(r"between\s+([0-9.]+)s\s+and\s+([0-9.]+)s", question)
    if match:
        return _format_time(match.group(1)), _format_time(match.group(2))
    return "{BEGIN}", "{END}"


def _format_time(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number.is_integer():
        return str(int(number))
    return f"{number:g}"


def _infer_segment_count(question: str) -> int | None:
    labels = {
        int(value)
        for value in re.findall(r"\bsegment[_ ]?(\d+)\b", question, flags=re.IGNORECASE)
    }
    return max(labels) if labels else None


def _strip_crossvid_task_details(question: str) -> str:
    text = str(question or "").strip()
    match = re.search(r"\n\nTask details:\n", text)
    if match:
        return text[: match.start()].strip()
    return text


def _ensure_answer_suffix(question: str) -> str:
    text = str(question or "").strip()
    if re.search(r"\bYour answer:\s*$", text):
        return text
    return f"{text}\n\nYour answer:"

