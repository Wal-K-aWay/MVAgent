"""DeepSeek invocation."""

import base64
import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor

from .common import ModelProfile, base_request
from .common import expand_video_sequences


PROFILE = ModelProfile(
    model="deepseek-flash",
    base_url="https://api.deepseek.com",
    api_key_env="DEEPSEEK_API_KEY",
    description="DeepSeek official API; image input only.",
)

TRANSPORT = "inline images below 24 MiB; one-hour Files API references above that"
# The documented request limit is 48 MiB, but multipart file references and JSON
# encoding still leave enough gateway overhead to reject a 45 MiB inline payload.
INLINE_LIMIT_BYTES = 24 * 1024 * 1024
_FILE_CACHE: dict[str, str] = {}
_CACHE_LOCK = threading.Lock()


def prepare_messages(messages, *, client, api_key=None):
    messages = expand_video_sequences(messages)
    candidates = []
    total_bytes = 0
    for message_index, message in enumerate(messages):
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for part_index, part in enumerate(content):
            url = part.get("image_url", {}).get("url", "")
            if url.startswith("data:image/jpeg;base64,"):
                size = len(url)
                total_bytes += size
                candidates.append((size, message_index, part_index, url.split("base64,", 1)[1]))
    if total_bytes <= INLINE_LIMIT_BYTES:
        return messages

    selected = []
    remaining = total_bytes
    for candidate in sorted(candidates, reverse=True):
        selected.append(candidate)
        remaining -= candidate[0]
        if remaining <= INLINE_LIMIT_BYTES:
            break

    def upload(candidate):
        _, message_index, part_index, encoded = candidate
        digest = hashlib.sha256(encoded.encode("ascii")).hexdigest()
        with _CACHE_LOCK:
            file_id = _FILE_CACHE.get(digest)
        if file_id is None:
            file_id = client.files.create(
                file=(f"{digest}.jpg", base64.b64decode(encoded), "image/jpeg"),
                purpose="user_data",
                expires_after={"anchor": "created_at", "seconds": 3600},
            ).id
            with _CACHE_LOCK:
                _FILE_CACHE[digest] = file_id
        return message_index, part_index, file_id

    with ThreadPoolExecutor(max_workers=16) as executor:
        uploaded = list(executor.map(upload, selected))
    prepared = [
        {**message, "content": list(message["content"])}
        if isinstance(message.get("content"), list)
        else dict(message)
        for message in messages
    ]
    for message_index, part_index, file_id in uploaded:
        prepared[message_index]["content"][part_index] = {"type": "file", "file_id": file_id}
    return prepared


def request_kwargs(messages, **generation):
    request = base_request(PROFILE, messages, **generation)
    request["extra_body"] = {"thinking": {"type": "disabled"}}
    return request
