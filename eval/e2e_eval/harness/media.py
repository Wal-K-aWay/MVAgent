"""CVBench frame sampling, the shared preprocessing cache and the per-request image audit.

Every benchmark sends frames as ordered JPEG images. MVU-Eval and CrossVid frames come from their
own official code (this module only caches and audits them). CVBench's official adapter hands
video files to `qwen_vl_utils`, which an OpenAI-compatible request cannot do, so the harness samples
the frames itself with the same indexing and sends them as images.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import threading
from io import BytesIO
from pathlib import Path
from typing import Any, Callable

import numpy as np

CACHE_ENV = "MVAGENT_E2E_MEDIA_CACHE_DIR"  # also read by the vendored CrossVid preprocess cache
JPEG_QUALITY = 95
DECODE_BATCH = 64

_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock(key: str) -> threading.Lock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.Lock())


def source_identity(path: Path) -> dict[str, Any]:
    stat = Path(path).stat()
    return {"path": str(Path(path).resolve()), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def cached(namespace: str, identity: dict[str, Any], compute: Callable[[], Any]) -> Any:
    """JSON disk cache under $MVAGENT_E2E_MEDIA_CACHE_DIR/<namespace>; disabled when the variable is unset."""
    root = os.environ.get(CACHE_ENV, "").strip()
    if not root:
        return compute()
    key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    path = Path(root) / namespace / key[:2] / f"{key}.json"
    with _lock(key):
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        value = compute()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        temporary.write_text(json.dumps(value), encoding="utf-8")
        temporary.replace(path)
        return value


def resized_dims(width: int, height: int, max_side: int) -> tuple[int, int]:
    """Aspect-preserving shrink so the longest side is at most `max_side` (MVU-Eval/CrossVid rule)."""
    if width > max_side or height > max_side:
        longest = max(width, height)
        return max(1, int(max_side * width / longest)), max(1, int(max_side * height / longest))
    return width, height


def _jpeg_b64(frame: np.ndarray) -> str:
    from PIL import Image

    output = BytesIO()
    Image.fromarray(frame).save(output, format="JPEG", quality=JPEG_QUALITY)
    return base64.b64encode(output.getvalue()).decode("ascii")


def sample_frames(path: Path, *, count: int, max_side: int) -> tuple[list[str], dict[str, Any]]:
    """`count` uniform frames (qwen_vl_utils indexing: linspace(0, n-1, count).round()) as base64 JPEGs.

    decord decodes directly at the aspect-preserving size whose longest side is at most `max_side`.
    """

    def compute() -> dict[str, Any]:
        from decord import VideoReader, cpu

        reader = VideoReader(str(path), ctx=cpu(0), num_threads=4)
        total = len(reader)
        if total < 1:
            raise ValueError(f"no decodable frames: {path}")
        height, width = reader[0].asnumpy().shape[:2]
        size = resized_dims(width, height, max_side)
        if size != (width, height):
            reader = VideoReader(str(path), ctx=cpu(0), num_threads=4, width=size[0], height=size[1])
            total = len(reader)
        indices = np.linspace(0, total - 1, min(count, total)).round().astype(int).tolist()
        frames = []
        for offset in range(0, len(indices), DECODE_BATCH):
            frames += [_jpeg_b64(frame) for frame in reader.get_batch(indices[offset : offset + DECODE_BATCH]).asnumpy()]
        meta = {
            "source_frames": total,
            "source_fps": float(reader.get_avg_fps() or 0.0),
            "original_size": [width, height],
            "size": list(size),
            "frames": len(frames),
        }
        return {"frames": frames, "meta": meta}

    identity = {
        "version": 2,
        "source": source_identity(path),
        "count": count,
        "max_side": max_side,
        "quality": JPEG_QUALITY,
        "indexing": "linspace-round",
    }
    value = cached("cvbench_frames", identity, compute)
    return value["frames"], value["meta"]


def image_sizes(messages: list[dict[str, Any]]) -> list[list[int]]:
    """[width, height] of every inline image part, read from the encoded headers."""
    from PIL import Image

    sizes = []
    for message in messages:
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if part.get("type") != "image_url":
                continue
            url = part["image_url"]["url"]
            if url.startswith("data:"):
                with Image.open(BytesIO(base64.b64decode(url.split(",", 1)[1]))) as image:
                    sizes.append(list(image.size))
    return sizes
