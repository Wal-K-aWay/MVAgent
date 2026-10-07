"""Frame sampling, video packaging, the shared preprocessing cache and the per-request media audit.

Only CVBench needs harness-side video handling: its official adapter feeds video files to
`qwen_vl_utils`, which an OpenAI-compatible request cannot do. MVU-Eval and CrossVid frames are
produced by their own official code; this module only caches and audits them.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import threading
from fractions import Fraction
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


def _jpeg(frame: np.ndarray) -> bytes:
    from PIL import Image

    output = BytesIO()
    Image.fromarray(frame).save(output, format="JPEG", quality=JPEG_QUALITY)
    return output.getvalue()


def _sampled_batches(path: Path, *, count: int, max_side: int):
    """Uniform `count` frames with qwen_vl_utils indexing (linspace(...).round()), resized by decord.

    Returns metadata and a generator of RGB frame batches.
    """
    from decord import VideoReader, cpu

    reader = VideoReader(str(path), ctx=cpu(0), num_threads=4)
    total = len(reader)
    if total < 1:
        raise ValueError(f"no decodable frames: {path}")
    source_fps = float(reader.get_avg_fps() or 0.0)
    height, width = reader[0].asnumpy().shape[:2]
    size = resized_dims(width, height, max_side)
    if size != (width, height):
        reader = VideoReader(str(path), ctx=cpu(0), num_threads=4, width=size[0], height=size[1])
        total = len(reader)
    count = min(count, total)
    indices = np.linspace(0, total - 1, count).round().astype(int).tolist()
    meta = {
        "source_frames": total,
        "source_fps": source_fps,
        "original_size": [width, height],
        "size": list(size),
        "frames": len(indices),
        "indices": indices,
    }

    def batches():
        for offset in range(0, len(indices), DECODE_BATCH):
            yield reader.get_batch(indices[offset : offset + DECODE_BATCH]).asnumpy()

    return meta, batches()


def _mjpeg_avi(jpegs: list[bytes], *, size: list[int], fps: float) -> bytes:
    """Mux already-encoded JPEGs into an MJPEG AVI unchanged, at an exact (fractional) frame rate."""
    import av

    rate = Fraction(fps).limit_denominator(1_000_000)
    buffer = BytesIO()
    with av.open(buffer, mode="w", format="avi") as container:
        stream = container.add_stream("mjpeg", rate=rate)
        stream.width, stream.height = size
        stream.pix_fmt = "yuvj420p"
        for index, data in enumerate(jpegs):
            packet = av.Packet(data)
            packet.stream = stream
            packet.pts = packet.dts = index
            packet.time_base = 1 / rate
            container.mux(packet)
    return buffer.getvalue()


def video_part(path: Path, *, count: int, max_side: int, native_video: bool) -> tuple[dict[str, Any], dict[str, Any]]:
    """One video as a single `video_url` part.

    native_video (vLLM): an MJPEG AVI whose frame rate makes `frame_index / fps` equal the source
    timestamp of each sampled frame, so Qwen3.5's per-frame time labels are real seconds.
    Otherwise (API providers): an inline JPEG sequence that the provider expands to ordered images.
    """
    transport = "mjpeg_avi" if native_video else "jpeg_sequence"

    def compute() -> dict[str, Any]:
        meta, batches = _sampled_batches(path, count=count, max_side=max_side)
        jpegs = [_jpeg(frame) for batch in batches for frame in batch]
        if transport == "jpeg_sequence":
            frames = ",".join(base64.b64encode(data).decode("ascii") for data in jpegs)
            return {"url": f"data:video/jpeg;base64,{frames}", "meta": meta}
        span = meta["indices"][-1] - meta["indices"][0]
        fps = (meta["frames"] - 1) * meta["source_fps"] / span if span > 0 and meta["source_fps"] > 0 else 1.0
        meta["container_fps"] = fps
        payload = base64.b64encode(_mjpeg_avi(jpegs, size=meta["size"], fps=fps)).decode("ascii")
        return {"url": f"data:video/x-msvideo;base64,{payload}", "meta": meta}

    identity = {
        "version": 1,
        "source": source_identity(path),
        "count": count,
        "max_side": max_side,
        "transport": transport,
        "quality": JPEG_QUALITY,
        "indexing": "linspace-round",
    }
    value = cached("cvbench_video", identity, compute)
    meta = {key: item for key, item in value["meta"].items() if key != "indices"}
    return {"type": "video_url", "video_url": {"url": value["url"]}}, meta


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
