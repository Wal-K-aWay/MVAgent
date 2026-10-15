#!/usr/bin/env python3
"""Local-vLLM compatibility runner for CVBench and MVU-Eval.

The runner keeps the published prompts and frame-sampling mechanics while owning the
OpenAI-compatible request, adaptive per-question frame cap, answer extraction, and
per-question audit metadata.  It does not execute the upstream evaluation entrypoints
and must not be used for new official benchmark claims.  New evaluations run from the
vendored official evaluation sources under ``eval/e2e_eval``.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import shutil
import sys
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO
from pathlib import Path
from typing import Any

import numpy as np
import httpx
from decord import VideoReader, cpu
from openai import OpenAI
from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.answer_parsing import extract_final_choice_with_method


CV_TASKS = [
    "Cross-video Anomaly Detection",
    "Cross-video Scene Recognition",
    "Multi-video Key-Action Recognition",
    "Cross-video Event Retrieval",
    "Cross-video Object Recognition",
    "Multi-video Attribute Recognition",
    "Joint-video Counting",
    "Cross-video Entity Matching",
    "Multi-view Scene Understanding",
    "Multi-video Temporal Reasoning",
    "Joint-video Spatial Navigating",
    "Video Difference Caption",
    "Cross-video Counterfactual Reasoning",
    "Joint-video Summarization",
    "Cross-video Procedural Transfer",
]
CV_CUE_TEXT = (
    "Please pay close attention to the video frames with special cues that are "
    "interspersed at the beginning and end of a video's content. For example, "
    'frames with the words "The video X" represent the beginning of the video '
    'called video X, and frames with the words "Video X End" represent the end '
    "of the video called video X."
)
CV_ANSWER_PREFIXES = (
    "The best answer is",
    "The correct answer is",
    "The answer is",
    "The answer",
    "The best option is",
    "The correct option is",
    "Best answer:",
    "Best option:",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run CVBench/MVU-Eval through a local OpenAI-compatible vLLM endpoint."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/qwen36_official_cvbench_mvu"),
    )
    parser.add_argument(
        "--cvbench-root",
        type=Path,
        default=Path("/home/kww/datasets/Multi-Video/CVBench"),
    )
    parser.add_argument(
        "--mvu-root",
        type=Path,
        default=Path("/home/kww/datasets/Multi-Video/MVU-Eval"),
    )
    parser.add_argument(
        "--cvbench-source",
        type=Path,
        default=PROJECT_ROOT / "eval/e2e_eval/CVBench",
    )
    parser.add_argument(
        "--mvu-source",
        type=Path,
        default=PROJECT_ROOT / "eval/e2e_eval/MVU-Eval",
    )
    parser.add_argument("--model", default="qwen35_local")
    parser.add_argument("--cv-port", type=int, default=8100)
    parser.add_argument(
        "--cv-ports",
        default="",
        help="Optional comma-separated CVBench endpoints; overrides --cv-port.",
    )
    parser.add_argument("--mvu-ports", default="8001,8101")
    parser.add_argument("--cv-workers", type=int, default=2)
    parser.add_argument("--mvu-workers-per-port", type=int, default=1)
    parser.add_argument(
        "--decode-batch-frames",
        type=int,
        default=64,
        help=(
            "Maximum decoded RGB frames retained per media batch before JPEG "
            "encoding. This bounds worker memory without changing sampled frames."
        ),
    )
    parser.add_argument(
        "--media-cache",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Reuse encoded sampled frames from --media-cache-dir (default: enabled).",
    )
    parser.add_argument(
        "--media-cache-dir",
        type=Path,
        default=PROJECT_ROOT / ".cache/e2e_media",
        help=(
            "Shared model-independent encoded-frame cache. Its keys include source "
            "identity, effective frame count, resolution, quality, and protocol version."
        ),
    )
    parser.add_argument("--cv-frames-per-video", type=int, default=8)
    parser.add_argument("--cv-question-frame-cap", type=int, default=512)
    parser.add_argument(
        "--cv-max-side",
        type=int,
        default=448,
        help="CVBench maximum frame side in pixels; preserves aspect ratio.",
    )
    parser.add_argument("--mvu-frames-per-video", type=int, default=32)
    parser.add_argument("--mvu-question-frame-cap", type=int, default=512)
    parser.add_argument("--mvu-max-side", type=int, default=720)
    parser.add_argument("--mvu-max-tokens", type=int, default=64)
    parser.add_argument("--mvu-temperature", type=float, default=0.0)
    parser.add_argument("--mvu-top-p", type=float, default=1.0)
    parser.add_argument(
        "--mvu-enable-thinking",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Enable model thinking for MVU; disabled by default for one-letter output.",
    )
    parser.add_argument("--api-timeout", type=float, default=600.0)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional deterministic per-benchmark row limit for smoke tests.",
    )
    parser.add_argument(
        "--only", choices=("all", "cvbench", "mvu-eval"), default="all"
    )
    args = parser.parse_args()
    positive_fields = {
        "cv_workers": args.cv_workers,
        "mvu_workers_per_port": args.mvu_workers_per_port,
        "decode_batch_frames": args.decode_batch_frames,
        "cv_frames_per_video": args.cv_frames_per_video,
        "cv_question_frame_cap": args.cv_question_frame_cap,
        "cv_max_side": args.cv_max_side,
        "mvu_frames_per_video": args.mvu_frames_per_video,
        "mvu_question_frame_cap": args.mvu_question_frame_cap,
        "mvu_max_side": args.mvu_max_side,
        "mvu_max_tokens": args.mvu_max_tokens,
        "api_timeout": args.api_timeout,
        "max_retries": args.max_retries,
    }
    invalid = [name for name, value in positive_fields.items() if value <= 0]
    if invalid:
        parser.error("must be positive: " + ", ".join(invalid))
    if args.limit is not None and args.limit <= 0:
        parser.error("--limit must be positive")
    if args.mvu_temperature < 0:
        parser.error("--mvu-temperature must be non-negative")
    if not 0 < args.mvu_top_p <= 1:
        parser.error("--mvu-top-p must be in (0, 1]")
    return args


def read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    temporary.replace(path)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def response_usage(response: Any) -> dict[str, int] | None:
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    result: dict[str, int] = {}
    for field in ("prompt_tokens", "completion_tokens", "total_tokens"):
        value = getattr(usage, field, None)
        if isinstance(value, int) and not isinstance(value, bool):
            result[field] = value
    return result or None


def local_openai_client(port: int, *, timeout: float) -> OpenAI:
    """Create a loopback client that never routes through environment proxies."""

    return OpenAI(
        api_key="unused",
        base_url=f"http://127.0.0.1:{port}/v1",
        timeout=timeout,
        max_retries=0,
        http_client=httpx.Client(trust_env=False),
    )


def resolve_official_sources(args: argparse.Namespace) -> tuple[Path, Path]:
    """Use the Git-tracked reduced sources without copying repositories into outputs."""

    cv_source = args.cvbench_source.resolve()
    mvu_source = args.mvu_source.resolve()
    required = (
        cv_source / "lmms-eval/lmms_eval/tasks/mvr/mvr.yaml",
        cv_source / "lmms-eval/lmms_eval/models/qwen2_5_vl.py",
        mvu_source / "inference/main.py",
        mvu_source / "inference/analyze.py",
    )
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing vendored official source files: " + ", ".join(missing))
    return cv_source, mvu_source


def snapshot_runner(output: Path) -> Path:
    source = Path(__file__).resolve()
    target = output / "protocol_source" / source.name
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.read_bytes() != source.read_bytes():
        raise RuntimeError(
            f"Frozen runner differs from current code: {target}. Use a new output directory."
        )
    if not target.exists():
        shutil.copy2(source, target)
    return target


def require_servers(ports: list[int], model: str) -> None:
    failures: list[str] = []
    for port in ports:
        client = local_openai_client(port, timeout=15)
        try:
            models = {item.id for item in client.models.list().data}
        except Exception as exc:  # noqa: BLE001 - report endpoint diagnostics
            failures.append(f"port {port}: {exc}")
            continue
        if model not in models:
            failures.append(f"port {port}: model {model!r} not in {sorted(models)}")
    if failures:
        raise RuntimeError("Unavailable vLLM endpoint(s): " + "; ".join(failures))


def jpeg_b64(image: Image.Image, *, quality: int = 95) -> str:
    output = BytesIO()
    image.convert("RGB").save(output, format="JPEG", quality=quality)
    return base64.b64encode(output.getvalue()).decode("ascii")


_MEDIA_CACHE_LOCKS: dict[str, threading.Lock] = {}
_MEDIA_CACHE_LOCKS_GUARD = threading.Lock()


def media_cache_lock(key: str) -> threading.Lock:
    with _MEDIA_CACHE_LOCKS_GUARD:
        return _MEDIA_CACHE_LOCKS.setdefault(key, threading.Lock())


def sampled_frame_cache_key(
    path: Path,
    *,
    frames: int,
    max_side: int,
    quality: int,
) -> str:
    stat = path.stat()
    identity = {
        "version": 1,
        "path": str(path.resolve()),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "frames": frames,
        "max_side": max_side,
        "quality": quality,
    }
    return hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def encode_sampled_frames(
    reader: VideoReader,
    indices: list[int],
    *,
    quality: int,
    decode_batch_frames: int,
) -> list[str]:
    encoded: list[str] = []
    for offset in range(0, len(indices), decode_batch_frames):
        batch_indices = indices[offset : offset + decode_batch_frames]
        values = reader.get_batch(batch_indices).asnumpy()
        encoded.extend(
            jpeg_b64(Image.fromarray(frame), quality=quality) for frame in values
        )
    return encoded


def sample_video_frames(
    path: Path,
    *,
    frames: int,
    max_side: int,
    quality: int,
    decode_threads: int,
    decode_batch_frames: int,
    cache_dir: Path | None,
) -> tuple[list[str], dict[str, Any]]:
    key = sampled_frame_cache_key(
        path,
        frames=frames,
        max_side=max_side,
        quality=quality,
    )
    lock = media_cache_lock(key)
    with lock:
        frames_path = metadata_path = None
        if cache_dir is not None:
            shard = cache_dir / key[:2]
            frames_path = shard / f"{key}.frames"
            metadata_path = shard / f"{key}.json"
            if frames_path.exists() and metadata_path.exists():
                encoded = frames_path.read_text(encoding="ascii").splitlines()
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                if len(encoded) == int(metadata["decoded_frames"]):
                    return encoded, metadata

        reader = VideoReader(str(path), ctx=cpu(0), num_threads=decode_threads)
        total = len(reader)
        if total < 1:
            raise ValueError(f"Video has no decodable frames: {path}")
        first = reader[0].asnumpy()
        original_height, original_width = first.shape[:2]
        scale = min(1.0, max_side / max(original_width, original_height))
        resized_width = max(1, int(original_width * scale))
        resized_height = max(1, int(original_height * scale))
        if (resized_width, resized_height) != (original_width, original_height):
            reader = VideoReader(
                str(path),
                ctx=cpu(0),
                num_threads=decode_threads,
                width=resized_width,
                height=resized_height,
            )
            total = len(reader)
        indices = np.linspace(0, total - 1, min(frames, total), dtype=int).tolist()
        encoded = encode_sampled_frames(
            reader,
            indices,
            quality=quality,
            decode_batch_frames=decode_batch_frames,
        )
        metadata = {
            "path": str(path),
            "available_frames": total,
            "decoded_frames": len(encoded),
            "original_resolution": [original_width, original_height],
            "input_resolution": [resized_width, resized_height],
        }
        if frames_path is not None and metadata_path is not None:
            frames_path.parent.mkdir(parents=True, exist_ok=True)
            suffix = f".{threading.get_ident()}.tmp"
            frames_tmp = frames_path.with_name(frames_path.name + suffix)
            metadata_tmp = metadata_path.with_name(metadata_path.name + suffix)
            frames_tmp.write_text("\n".join(encoded) + "\n", encoding="ascii")
            metadata_tmp.write_text(
                json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                encoding="utf-8",
            )
            frames_tmp.replace(frames_path)
            metadata_tmp.replace(metadata_path)
        return encoded, metadata


def sample_video_as_jpeg_sequence(
    path: Path,
    frames: int = 8,
    max_side: int = 448,
    *,
    decode_batch_frames: int = 64,
    cache_dir: Path | None = None,
) -> tuple[str, dict[str, Any]]:
    encoded, metadata = sample_video_frames(
        path,
        frames=frames,
        max_side=max_side,
        quality=95,
        decode_threads=2,
        decode_batch_frames=decode_batch_frames,
        cache_dir=cache_dir,
    )
    return ",".join(encoded), metadata


def data_image(path: Path) -> str:
    media = "png" if path.suffix.lower() == ".png" else "jpeg"
    return f"data:image/{media};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def cv_prompt(row: dict[str, Any]) -> str:
    options = row["options"]
    is_yes_no = all(option.strip().strip(".").lower() in {"yes", "no"} for option in options)
    if is_yes_no:
        instruction = (
            "Select the best answer to the following yes-no question based on the "
            "listed all videos. Respond with only the word (Yes or No) of the "
            "correct option."
        )
        suffix = (
            "Answer with the option's word (YES or NO) from the given choices directly."
        )
    else:
        instruction = (
            "Select the best answer to the following multiple-choice based on the "
            "listed all videos. Respond with only the letter (A, B, C, or D) of "
            "the correct option."
        )
        suffix = (
            "Answer with the option's letter (A, B, C, or D) from the given choices directly."
        )
    return "\n".join((instruction, row["question"], *options, suffix))


def cv_prediction(text: str) -> str:
    value = text.strip()
    for prefix in CV_ANSWER_PREFIXES:
        value = value.replace(prefix, "")
    if len(value.split()) > 10 and not re.search(r"[ABCDYESNO]", value):
        return ""
    match = re.search(r"(?i)([ABCD]|YES|NO)", value)
    return match.group(0).upper() if match else ""


def cv_messages(
    row: dict[str, Any],
    video_root: Path,
    cue_root: Path,
    *,
    frames_per_video: int,
    question_frame_cap: int,
    max_side: int,
    decode_batch_frames: int = 64,
    cache_dir: Path | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    content: list[dict[str, Any]] = []
    video_count = len(row["videos"])
    if video_count < 1:
        raise ValueError(f"CVBench row {row.get('id')} has no videos")
    if video_count > question_frame_cap:
        raise ValueError(
            f"CVBench row {row.get('id')} has {video_count} videos but the question "
            f"frame cap is only {question_frame_cap}"
        )
    effective_frames = min(
        frames_per_video,
        max(1, question_frame_cap // video_count),
    )
    media: list[dict[str, Any]] = []
    for index, relative in enumerate(row["videos"], start=1):
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": data_image(cue_root / f"video{index}.png")},
            }
        )
        sequence, metadata = sample_video_as_jpeg_sequence(
            video_root / relative,
            effective_frames,
            max_side,
            decode_batch_frames=decode_batch_frames,
            cache_dir=cache_dir,
        )
        metadata["video"] = relative
        media.append(metadata)
        content.append(
            {
                "type": "video_url",
                "video_url": {"url": f"data:video/jpeg;base64,{sequence}"},
            }
        )
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": data_image(cue_root / f"end{index}.png")},
            }
        )
    content.extend(
        (
            {"type": "text", "text": CV_CUE_TEXT},
            {"type": "text", "text": cv_prompt(row)},
        )
    )
    return (
        [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": content},
        ],
        {
            "nominal_frames_per_video": frames_per_video,
            "effective_frames_per_video": effective_frames,
            "question_frame_cap": question_frame_cap,
            "max_side_pixels": max_side,
            "actual_frames_per_video": [item["decoded_frames"] for item in media],
            "actual_total_video_frames": sum(item["decoded_frames"] for item in media),
            "cue_images": 2 * video_count,
            "media": media,
        },
    )


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                records.append(json.loads(line))
    return records


def run_cvbench(args: argparse.Namespace, cv_source: Path) -> None:
    rows = read_json(args.cvbench_root / "QAs.json")
    if args.limit is not None:
        rows = rows[: args.limit]
    official_rows = {
        int(row["id"]): row
        for row in read_json(
            cv_source / "Video-R1/src/r1-v/Evaluation/CVBench.json"
        )
    }
    output = args.output / "raw/cvbench_predictions.jsonl"
    output.parent.mkdir(parents=True, exist_ok=True)
    completed = {int(row["id"]) for row in load_jsonl(output) if not row.get("error")}
    pending = [row for row in rows if int(row["id"]) not in completed]
    lock = threading.Lock()
    local = threading.local()
    cue_root = cv_source / "lmms-eval/res"
    cv_ports = (
        [int(value) for value in args.cv_ports.split(",") if value.strip()]
        if args.cv_ports
        else [args.cv_port]
    )

    def infer(row: dict[str, Any]) -> dict[str, Any]:
        port = cv_ports[int(row["id"]) % len(cv_ports)]
        if not hasattr(local, "clients"):
            local.clients = {}
        if port not in local.clients:
            local.clients[port] = local_openai_client(
                port,
                timeout=args.api_timeout,
            )
        client = local.clients[port]
        started = time.monotonic()
        error = ""
        media_error = ""
        response_text = ""
        usage = None
        frame_budget: dict[str, Any] = {}
        try:
            messages, frame_budget = cv_messages(
                row,
                args.cvbench_root / "videos",
                cue_root,
                frames_per_video=args.cv_frames_per_video,
                question_frame_cap=args.cv_question_frame_cap,
                max_side=args.cv_max_side,
                decode_batch_frames=args.decode_batch_frames,
                cache_dir=args.media_cache_dir if args.media_cache else None,
            )
        except Exception as exc:  # noqa: BLE001 - persist media failures
            media_error = f"{type(exc).__name__}: {exc}"
            error = media_error
            messages = []
        for attempt in range(1, args.max_retries + 1):
            if media_error:
                break
            try:
                response = client.chat.completions.create(
                    model=args.model,
                    messages=messages,
                    max_tokens=16,
                    temperature=0,
                    top_p=1.0,
                )
                response_text = response.choices[0].message.content or ""
                usage = response_usage(response)
                error = ""
                break
            except Exception as exc:  # noqa: BLE001 - persist actionable failure
                error = f"{type(exc).__name__}: {exc}"
                if attempt < args.max_retries:
                    time.sleep(min(2**attempt, 8))
        official = official_rows[int(row["id"])]
        prediction = cv_prediction(response_text)
        answer = str(row["answer"]).strip().upper()
        return {
            "id": int(row["id"]),
            "task_type": official["task_type"],
            "answer": answer,
            "prediction": prediction,
            "model_output": response_text,
            "correct": prediction == answer,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "endpoint": f"http://127.0.0.1:{port}/v1",
            "frame_budget": frame_budget,
            "usage": usage,
            "generation": {
                "max_tokens": 16,
                "temperature": 0.0,
                "top_p": 1.0,
            },
            **({"error": error} if error else {}),
        }

    print(f"CVBench: {len(completed)} complete, {len(pending)} pending", flush=True)
    with ThreadPoolExecutor(max_workers=args.cv_workers) as executor:
        futures = {executor.submit(infer, row): row for row in pending}
        for number, future in enumerate(as_completed(futures), start=1):
            record = future.result()
            with lock, output.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            if number % 10 == 0 or record.get("error"):
                print(
                    f"CVBench progress: {len(completed) + number}/{len(rows)}"
                    + (f" error={record['error']}" if record.get("error") else ""),
                    flush=True,
                )


def sample_mvu_video(
    path: Path,
    *,
    frames: int,
    max_side: int,
    decode_batch_frames: int = 64,
    cache_dir: Path | None = None,
) -> tuple[list[str], dict[str, Any]]:
    return sample_video_frames(
        path,
        frames=frames,
        max_side=max_side,
        quality=75,
        decode_threads=4,
        decode_batch_frames=decode_batch_frames,
        cache_dir=cache_dir,
    )


def mvu_messages(
    row: dict[str, Any],
    video_root: Path,
    *,
    frames_per_video: int,
    question_frame_cap: int,
    max_side: int,
    decode_batch_frames: int = 64,
    cache_dir: Path | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    videos = list(row.get("videos") or [])
    if not videos:
        raise ValueError(f"MVU-Eval row {row.get('id')} has no videos")
    if len(videos) > question_frame_cap:
        raise ValueError(
            f"MVU-Eval row {row.get('id')} has {len(videos)} videos but the question "
            f"frame cap is only {question_frame_cap}"
        )
    effective_frames = min(
        frames_per_video,
        max(1, question_frame_cap // len(videos)),
    )
    content: list[dict[str, Any]] = []
    media: list[dict[str, Any]] = []
    for index, relative in enumerate(videos, start=1):
        frames, metadata = sample_mvu_video(
            video_root / relative,
            frames=effective_frames,
            max_side=max_side,
            decode_batch_frames=decode_batch_frames,
            cache_dir=cache_dir,
        )
        metadata["video"] = relative
        media.append(metadata)
        content.append({"type": "text", "text": f"[Video {index}] {relative}"})
        content.extend(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{frame}"},
            }
            for frame in frames
        )
    content.extend(
        [
            {"type": "text", "text": str(row["question"])},
            {
                "type": "text",
                "text": (
                    "Select the correct answer from the options. Return exactly one "
                    "uppercase option letter and no explanation."
                ),
            },
            {"type": "text", "text": "\n".join(map(str, row["options"]))},
        ]
    )
    return (
        [{"role": "user", "content": content}],
        {
            "nominal_frames_per_video": frames_per_video,
            "effective_frames_per_video": effective_frames,
            "question_frame_cap": question_frame_cap,
            "actual_frames_per_video": [item["decoded_frames"] for item in media],
            "actual_total_video_frames": sum(item["decoded_frames"] for item in media),
            "max_side_pixels": max_side,
            "media": media,
        },
    )


def run_mvu(args: argparse.Namespace, _mvu_source: Path) -> None:
    rows = read_json(args.mvu_root / "QAs.json")
    if args.limit is not None:
        rows = rows[: args.limit]
    ports = [int(value) for value in args.mvu_ports.split(",") if value.strip()]
    if not ports:
        raise ValueError("--mvu-ports must contain at least one port")
    output = args.output / "raw/mvu_eval_predictions.jsonl"
    output.parent.mkdir(parents=True, exist_ok=True)
    completed = {int(row["id"]) for row in load_jsonl(output) if not row.get("error")}
    pending = [row for row in rows if int(row["id"]) not in completed]
    lock = threading.Lock()
    local = threading.local()

    def infer(row: dict[str, Any]) -> dict[str, Any]:
        port = ports[int(row["id"]) % len(ports)]
        if not hasattr(local, "clients"):
            local.clients = {}
        if port not in local.clients:
            local.clients[port] = local_openai_client(
                port,
                timeout=args.api_timeout,
            )
        client = local.clients[port]
        started = time.monotonic()
        response_text = ""
        error = ""
        media_error = ""
        frame_budget: dict[str, Any] = {}
        usage = None
        finish_reason = None
        try:
            messages, frame_budget = mvu_messages(
                row,
                args.mvu_root / "videos",
                frames_per_video=args.mvu_frames_per_video,
                question_frame_cap=args.mvu_question_frame_cap,
                max_side=args.mvu_max_side,
                decode_batch_frames=args.decode_batch_frames,
                cache_dir=args.media_cache_dir if args.media_cache else None,
            )
        except Exception as exc:  # noqa: BLE001 - persist media failures
            media_error = f"{type(exc).__name__}: {exc}"
            error = media_error
            messages = []

        for attempt in range(1, args.max_retries + 1):
            if media_error:
                break
            try:
                response = client.chat.completions.create(
                    model=args.model,
                    messages=messages,
                    max_tokens=args.mvu_max_tokens,
                    temperature=args.mvu_temperature,
                    top_p=args.mvu_top_p,
                    extra_body={
                        "chat_template_kwargs": {
                            "enable_thinking": args.mvu_enable_thinking,
                        }
                    },
                )
                response_text = response.choices[0].message.content or ""
                finish_reason = response.choices[0].finish_reason
                usage = response_usage(response)
                error = ""
                break
            except Exception as exc:  # noqa: BLE001 - persist actionable failure
                error = f"{type(exc).__name__}: {exc}"
                if attempt < args.max_retries:
                    time.sleep(min(2**attempt, 8))

        prediction, parse_method = extract_final_choice_with_method(
            response_text,
            row.get("options") or [],
        )
        legacy_prediction = response_text.strip().upper()[:1]
        answer = str(row["answer"]).strip().upper()
        return {
            "id": int(row["id"]),
            "task_type": str(row.get("task") or "Unknown"),
            "answer": answer,
            "prediction": prediction,
            "answer_parse_method": parse_method,
            "legacy_first_character_prediction": legacy_prediction,
            "model_output": response_text,
            "correct": prediction == answer,
            "legacy_first_character_correct": legacy_prediction == answer,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "endpoint": f"http://127.0.0.1:{port}/v1",
            "frame_budget": frame_budget,
            "usage": usage,
            "finish_reason": finish_reason,
            "generation": {
                "max_tokens": args.mvu_max_tokens,
                "temperature": args.mvu_temperature,
                "top_p": args.mvu_top_p,
                "enable_thinking": args.mvu_enable_thinking,
            },
            **({"error": error} if error else {}),
        }

    workers = len(ports) * args.mvu_workers_per_port
    print(
        f"MVU-Eval: {len(completed)} complete, {len(pending)} pending, "
        f"workers={workers}",
        flush=True,
    )
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(infer, row): row for row in pending}
        for number, future in enumerate(as_completed(futures), start=1):
            record = future.result()
            with lock, output.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            if number % 10 == 0 or record.get("error"):
                print(
                    f"MVU-Eval progress: {len(completed) + number}/{len(rows)}"
                    + (f" error={record['error']}" if record.get("error") else ""),
                    flush=True,
                )


def summarize_cv(args: argparse.Namespace) -> dict[str, Any]:
    source_rows = read_json(args.cvbench_root / "QAs.json")
    if args.limit is not None:
        source_rows = source_rows[: args.limit]
    selected_ids = {int(row["id"]) for row in source_rows}
    rows = load_jsonl(args.output / "raw/cvbench_predictions.jsonl")
    latest = {
        int(row["id"]): row
        for row in rows
        if int(row["id"]) in selected_ids
    }
    valid = [row for row in latest.values() if not row.get("error")]
    task_stats: dict[str, Counter[str]] = defaultdict(Counter)
    for row in valid:
        task_stats[row["task_type"]]["total"] += 1
        task_stats[row["task_type"]]["correct"] += int(row["correct"])
    return {
        "expected": len(source_rows),
        "completed": len(valid),
        "errors": sum(bool(row.get("error")) for row in latest.values()),
        "correct": sum(bool(row["correct"]) for row in valid),
        "accuracy": (
            sum(bool(row["correct"]) for row in valid) / len(valid) if valid else None
        ),
        "by_task": {
            task: {
                "correct": values["correct"],
                "total": values["total"],
                "accuracy": values["correct"] / values["total"],
            }
            for task, values in sorted(task_stats.items())
        },
    }


def summarize_mvu(args: argparse.Namespace) -> dict[str, Any]:
    source_rows = read_json(args.mvu_root / "QAs.json")
    if args.limit is not None:
        source_rows = source_rows[: args.limit]
    selected_ids = {int(row["id"]) for row in source_rows}
    records = load_jsonl(args.output / "raw/mvu_eval_predictions.jsonl")
    latest = {
        int(row["id"]): row
        for row in records
        if int(row["id"]) in selected_ids
    }
    valid = [row for row in latest.values() if not row.get("error")]
    task_stats: dict[str, Counter[str]] = defaultdict(Counter)
    for row in valid:
        task = str(row.get("task_type") or "Unknown")
        task_stats[task]["total"] += 1
        task_stats[task]["correct"] += int(row["correct"])
        task_stats[task]["legacy_correct"] += int(
            row["legacy_first_character_correct"]
        )
    correct = sum(bool(row["correct"]) for row in valid)
    legacy_correct = sum(
        bool(row["legacy_first_character_correct"]) for row in valid
    )
    return {
        "expected": len(source_rows),
        "completed": len(valid),
        "errors": sum(bool(row.get("error")) for row in latest.values()),
        "correct": correct,
        "accuracy": correct / len(valid) if valid else None,
        "legacy_first_character_correct": legacy_correct,
        "legacy_first_character_accuracy": (
            legacy_correct / len(valid) if valid else None
        ),
        "answer_parse_failures": sum(
            row.get("answer_parse_method") == "unparsed" for row in valid
        ),
        "answer_parser": "final-choice-v1",
        "by_task": {
            task: {
                "correct": values["correct"],
                "legacy_first_character_correct": values["legacy_correct"],
                "total": values["total"],
                "accuracy": values["correct"] / values["total"],
                "legacy_first_character_accuracy": (
                    values["legacy_correct"] / values["total"]
                ),
            }
            for task, values in sorted(task_stats.items())
        },
    }


def main() -> None:
    args = parse_args()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    runner_snapshot = snapshot_runner(args.output)
    cv_source, mvu_source = resolve_official_sources(args)
    mvu_ports = [int(value) for value in args.mvu_ports.split(",") if value.strip()]
    cv_ports = (
        [int(value) for value in args.cv_ports.split(",") if value.strip()]
        if args.cv_ports
        else [args.cv_port]
    )
    if not cv_ports:
        raise ValueError("CVBench requires at least one endpoint")
    if not mvu_ports:
        raise ValueError("MVU-Eval requires at least one endpoint")
    required_ports = (cv_ports if args.only in {"all", "cvbench"} else []) + (
        mvu_ports if args.only in {"all", "mvu-eval"} else []
    )
    require_servers(sorted(set(required_ports)), args.model)
    manifest = {
            "model": args.model,
            "scope": (
                "full CVBench and MVU-Eval"
                if args.limit is None
                else f"deterministic first {args.limit} rows per selected benchmark"
            ),
            "only": args.only,
            "limit": args.limit,
            "runner": {
                "path": "scripts/run_official_cvbench_mvu.py",
                "sha256": sha256(runner_snapshot),
                "snapshot_path": str(runner_snapshot),
                "description": (
                    "Local OpenAI-compatible compatibility adapter referencing the "
                    "Git-tracked reduced upstream sources; not an unmodified official-"
                    "repository execution."
                ),
            },
            "official_sources": {
                "cvbench": {
                    "url": "https://github.com/Hokhim2/CVBench",
                    "protocol_sha256": sha256(
                        cv_source / "lmms-eval/lmms_eval/tasks/mvr/mvr.yaml"
                    ),
                    "qwen_adapter_sha256": sha256(
                        cv_source / "lmms-eval/lmms_eval/models/qwen2_5_vl.py"
                    ),
                },
                "mvu_eval": {
                    "url": "https://github.com/NJU-LINK/MVU-Eval",
                    "inference_sha256": sha256(mvu_source / "inference/main.py"),
                    "scorer_sha256": sha256(mvu_source / "inference/analyze.py"),
                },
            },
            "cvbench": {
                "endpoints": [f"http://127.0.0.1:{port}/v1" for port in cv_ports],
                "workers": args.cv_workers,
                "decode_batch_frames": args.decode_batch_frames,
                "media_cache": args.media_cache,
                "media_cache_dir": str(args.media_cache_dir),
                "frames_per_video_cap": args.cv_frames_per_video,
                "frames_per_question_cap": args.cv_question_frame_cap,
                "max_side_pixels": args.cv_max_side,
                "max_tokens": 16,
                "temperature": 0,
                "top_p": 1.0,
            },
            "mvu_eval": {
                "endpoints": [f"http://127.0.0.1:{port}/v1" for port in mvu_ports],
                "workers_per_endpoint": args.mvu_workers_per_port,
                "decode_batch_frames": args.decode_batch_frames,
                "media_cache": args.media_cache,
                "media_cache_dir": str(args.media_cache_dir),
                "frames_per_video_cap": args.mvu_frames_per_video,
                "frames_per_question_cap": args.mvu_question_frame_cap,
                "max_side_pixels": args.mvu_max_side,
                "max_tokens": args.mvu_max_tokens,
                "temperature": args.mvu_temperature,
                "top_p": args.mvu_top_p,
                "enable_thinking": args.mvu_enable_thinking,
                "answer_parser": "final-choice-v1",
                "legacy_score": "first upper-cased output character",
            },
            "transport": {
                "api_timeout_seconds": args.api_timeout,
                "max_retries": args.max_retries,
            },
        }
    manifest_path = args.output / "run_manifest.json"
    if manifest_path.exists() and read_json(manifest_path) != manifest:
        raise RuntimeError(
            f"Run manifest does not match existing output: {manifest_path}. "
            "Use a new output directory for changed protocol settings or code."
        )
    write_json(manifest_path, manifest)
    started = time.monotonic()
    failures: list[BaseException] = []
    jobs = []
    with ThreadPoolExecutor(max_workers=2) as executor:
        if args.only in {"all", "cvbench"}:
            jobs.append(executor.submit(run_cvbench, args, cv_source))
        if args.only in {"all", "mvu-eval"}:
            jobs.append(executor.submit(run_mvu, args, mvu_source))
        for job in as_completed(jobs):
            try:
                job.result()
            except BaseException as exc:  # noqa: BLE001 - finish sibling benchmark
                failures.append(exc)
                print(f"Benchmark failed: {type(exc).__name__}: {exc}", flush=True)
    cv_summary = summarize_cv(args) if args.only in {"all", "cvbench"} else None
    mvu_summary = summarize_mvu(args) if args.only in {"all", "mvu-eval"} else None
    for name, item in (("CVBench", cv_summary), ("MVU-Eval", mvu_summary)):
        if item is None:
            continue
        if item["completed"] != item["expected"] or item.get("errors"):
            failures.append(
                RuntimeError(
                    f"{name} incomplete: completed={item['completed']} "
                    f"expected={item['expected']} errors={item.get('errors', 0)}"
                )
            )
    summary = {
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "cvbench": cv_summary,
        "mvu_eval": mvu_summary,
        "failures": [f"{type(exc).__name__}: {exc}" for exc in failures],
    }
    write_json(args.output / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
