"""Alibaba Cloud Model Studio Qwen invocation."""

import base64
import hashlib
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from dashscope.utils.oss_utils import OssUtils

from .common import ModelProfile, base_request


PROFILE = ModelProfile(
    model="qwen3.8-flash",
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    api_key_env="DASHSCOPE_API_KEY",
    description="Alibaba Cloud Model Studio official API.",
)

DEFAULT_HEADERS = {"X-DashScope-OssResourceResolve": "enable"}
TRANSPORT = "inline images up to 250 data URIs; temporary OSS video-frame lists above that"
_URL_CACHE: dict[str, str] = {}
_CACHE_LOCK = threading.Lock()


def _upload_frames(frames: list[str], api_key: str) -> list[str]:
    digests = [hashlib.sha256(frame.encode("ascii")).hexdigest() for frame in frames]
    with _CACHE_LOCK:
        missing = {digest: frame for digest, frame in zip(digests, frames) if digest not in _URL_CACHE}
    if missing:
        with tempfile.TemporaryDirectory(prefix="mvagent-qwen-frames-") as directory:
            paths: dict[str, Path] = {}
            for digest, frame in missing.items():
                path = Path(directory) / f"{digest}.jpg"
                path.write_bytes(base64.b64decode(frame))
                paths[digest] = path
            first_digest, first_path = next(iter(paths.items()))
            first_url, certificate = OssUtils.upload(
                model=PROFILE.model, file_path=str(first_path), api_key=api_key
            )
            uploaded = {first_digest: first_url}

            def upload(item):
                digest, path = item
                url, _ = OssUtils.upload(
                    model=PROFILE.model,
                    file_path=str(path),
                    api_key=api_key,
                    upload_certificate=certificate,
                )
                return digest, url

            rest = [(digest, path) for digest, path in paths.items() if digest != first_digest]
            with ThreadPoolExecutor(max_workers=16) as executor:
                uploaded.update(executor.map(upload, rest))
            with _CACHE_LOCK:
                _URL_CACHE.update(uploaded)
    with _CACHE_LOCK:
        return [_URL_CACHE[digest] for digest in digests]


def prepare_messages(messages, *, api_key, client=None):
    prefix = "data:video/jpeg;base64,"
    inline_count = sum(
        1
        for message in messages
        if isinstance(message.get("content"), list)
        for part in message["content"]
        if (
            part.get("video_url", {}).get("url", "").startswith(prefix)
            or part.get("image_url", {}).get("url", "").startswith("data:")
        )
    )
    video_frame_count = sum(
        len(part["video_url"]["url"][len(prefix) :].split(","))
        for message in messages
        if isinstance(message.get("content"), list)
        for part in message["content"]
        if part.get("video_url", {}).get("url", "").startswith(prefix)
    )
    if inline_count + video_frame_count <= 250:
        return messages

    prepared = []
    for message in messages:
        content = message.get("content")
        if not isinstance(content, list):
            prepared.append(dict(message))
            continue
        parts = []
        image_run: list[tuple[dict, str]] = []

        def flush_images():
            if image_run:
                if len(image_run) < 4:
                    parts.extend(part for part, _ in image_run)
                else:
                    parts.append(
                        {
                            "type": "video",
                            "video": _upload_frames(
                                [encoded for _, encoded in image_run], api_key
                            ),
                        }
                    )
                image_run.clear()

        for part in content:
            video_url = part.get("video_url", {}).get("url", "")
            image_url = part.get("image_url", {}).get("url", "")
            if video_url.startswith(prefix):
                flush_images()
                frames = [frame for frame in video_url[len(prefix) :].split(",") if frame]
                parts.append({"type": "video", "video": _upload_frames(frames, api_key)})
            elif image_url.startswith("data:image/jpeg;base64,"):
                image_run.append((part, image_url.split("base64,", 1)[1]))
            else:
                flush_images()
                parts.append(part)
        flush_images()
        prepared.append({**message, "content": parts})
    return prepared


def request_kwargs(messages, **generation):
    request = base_request(PROFILE, messages, **generation)
    request["extra_body"] = {"enable_thinking": False}
    return request
