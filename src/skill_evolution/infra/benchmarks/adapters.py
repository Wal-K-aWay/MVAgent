from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from .contracts import EvaluationSample, SampleTask


_LABEL_RE = re.compile(r"^([A-Z])(?:[.)]|\s)")


def _videos(value: object, *, media_root: str | Path | None) -> dict[str, str]:
    if isinstance(value, Mapping):
        items = [(str(video_id), path) for video_id, path in value.items()]
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        items = [(f"video_{index}", path) for index, path in enumerate(value, 1)]
    else:
        raise ValueError("Benchmark sample videos must be a mapping or sequence.")
    root = Path(media_root).expanduser().resolve() if media_root is not None else None
    resolved: dict[str, str] = {}
    for video_id, raw_path in items:
        path = Path(str(raw_path)).expanduser()
        if root is not None and not path.is_absolute():
            path = root / path
        resolved[video_id] = str(path.resolve()) if path.is_absolute() else str(path)
    return resolved


def _options(value: object) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    options = [str(option).strip() for option in value]
    rendered: list[str] = []
    for index, option in enumerate(options):
        if _LABEL_RE.match(option.upper()):
            rendered.append(option)
        else:
            rendered.append(f"{chr(ord('A') + index)}. {option}")
    return rendered


def _choice_ground_truth(answer: object, options: Sequence[str]) -> list[str]:
    values = (
        list(answer)
        if isinstance(answer, Sequence) and not isinstance(answer, (str, bytes))
        else [answer]
    )
    normalized = [str(value).strip() for value in values if str(value).strip()]
    available_labels = {chr(ord("A") + index) for index in range(len(options))}
    if (
        len(normalized) == 1
        and re.fullmatch(r"[A-Z]+", normalized[0].upper())
        and set(normalized[0].upper()).issubset(available_labels)
    ):
        return list(normalized[0].upper())
    if len(normalized) == 1 and re.fullmatch(
        r"[A-Z](?:\s*[,;/|]\s*[A-Z])+",
        normalized[0].upper(),
    ):
        labels = re.findall(r"[A-Z]", normalized[0].upper())
        if set(labels).issubset(available_labels):
            return labels
    if all(re.fullmatch(r"[A-Z]", value.upper()) for value in normalized):
        return [value.upper() for value in normalized]

    option_text = []
    for index, option in enumerate(options):
        text = re.sub(r"^[A-Z][.)]\s*", "", option, flags=re.IGNORECASE).rstrip(". ")
        option_text.append((chr(ord("A") + index), text.casefold()))
    labels: list[str] = []
    for value in normalized:
        matches = [label for label, text in option_text if text == value.rstrip(". ").casefold()]
        if len(matches) != 1:
            raise ValueError(f"Choice ground truth {value!r} does not identify one option.")
        labels.append(matches[0])
    return labels


def choice_sample(
    record: Mapping[str, Any],
    *,
    media_root: str | Path | None = None,
) -> EvaluationSample:
    options = _options(record.get("options"))
    return EvaluationSample(
        task=SampleTask.CHOICE,
        question=str(record.get("question") or ""),
        videos=_videos(record.get("videos"), media_root=media_root),
        options=options,
        ground_truth=_choice_ground_truth(record.get("answer"), options),
    )


def crossvid_sample(
    record: Mapping[str, Any],
    *,
    media_root: str | Path | None = None,
) -> EvaluationSample:
    """Normalize one compact CrossVid row without retaining its native task code."""

    native_task = str(record.get("task") or "").strip().upper()
    if native_task == "FSA":
        answer = record.get("answer")
        if not isinstance(answer, Sequence) or isinstance(answer, (str, bytes)):
            raise ValueError("CrossVid FSA answer must be [start, end].")
        task = SampleTask.TEMPORAL_LOCALIZATION
        ground_truth = list(answer)
    elif native_task == "PSS":
        task = SampleTask.ORDERING
        ground_truth = [
            part.strip() for part in str(record.get("answer") or "").split("->")
            if part.strip()
        ]
    elif native_task == "CCQA":
        task = SampleTask.OPEN_QA
        points = record.get("scoring_points")
        if isinstance(points, Sequence) and not isinstance(points, (str, bytes)):
            ground_truth = [str(point).strip() for point in points if str(point).strip()]
        else:
            ground_truth = [str(record.get("answer") or "").strip()]
    else:
        return choice_sample(record, media_root=media_root)
    return EvaluationSample(
        task=task,
        question=str(record.get("question") or ""),
        videos=_videos(record.get("videos"), media_root=media_root),
        options=_options(record.get("options")),
        ground_truth=ground_truth,
    )


def cvbench_sample(
    record: Mapping[str, Any],
    *,
    media_root: str | Path | None = None,
) -> EvaluationSample:
    return choice_sample(record, media_root=media_root)


def mvu_eval_sample(
    record: Mapping[str, Any],
    *,
    media_root: str | Path | None = None,
) -> EvaluationSample:
    return choice_sample(record, media_root=media_root)


__all__ = [
    "choice_sample",
    "crossvid_sample",
    "cvbench_sample",
    "mvu_eval_sample",
]
