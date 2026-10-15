"""Small shared pieces for official API provider scripts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class ModelProfile:
    model: str
    base_url: str
    api_key_env: str
    temperature: float | None = 0.0
    top_p: float | None = 1.0
    completion_limit: str = "max_tokens"
    minimum_output_tokens: int = 1
    thinking_setting: str = "disabled"
    description: str = ""


def expand_video_sequences(messages: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert the local JPEG-sequence extension to ordered standard images."""

    normalized: list[dict[str, Any]] = []
    prefix = "data:video/jpeg;base64,"
    for message in messages:
        content = message.get("content")
        if not isinstance(content, list):
            normalized.append(dict(message))
            continue
        parts: list[dict[str, Any]] = []
        for part in content:
            if part.get("type") != "video_url":
                parts.append(part)
                continue
            url = part.get("video_url", {}).get("url", "")
            if not url.startswith(prefix):
                raise ValueError("API adapter accepts only inline JPEG video sequences")
            parts.extend(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{frame}"},
                }
                for frame in url[len(prefix) :].split(",")
                if frame
            )
        normalized.append({**message, "content": parts})
    return normalized


def base_request(
    profile: ModelProfile,
    messages: Iterable[dict[str, Any]],
    *,
    max_output_tokens: int,
    temperature: float | None,
    top_p: float | None,
) -> dict[str, Any]:
    if max_output_tokens <= 0:
        raise ValueError("max_output_tokens must be positive")
    request: dict[str, Any] = {
        "model": profile.model,
        "messages": expand_video_sequences(messages),
        "stream": False,
        profile.completion_limit: max(
            max_output_tokens, profile.minimum_output_tokens
        ),
    }
    temperature = profile.temperature if temperature is None else temperature
    top_p = profile.top_p if top_p is None else top_p
    if temperature is not None:
        request["temperature"] = temperature
    if top_p is not None:
        request["top_p"] = top_p
    return request
