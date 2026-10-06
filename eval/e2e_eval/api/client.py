"""Official OpenAI-compatible clients for the evaluated multimodal models."""

from __future__ import annotations

import threading
import time
from dataclasses import asdict
from typing import Any, Iterable

import httpx
from openai import OpenAI

from providers import MODEL_PROFILES, provider_for
from providers.common import ModelProfile, expand_video_sequences


def profile_for(model: str) -> ModelProfile:
    return provider_for(model).PROFILE


def _usage_dict(response: Any) -> dict[str, Any] | None:
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    if hasattr(usage, "model_dump"):
        return usage.model_dump(exclude_none=True)
    return {
        key: value
        for key in ("prompt_tokens", "completion_tokens", "total_tokens")
        if (value := getattr(usage, key, None)) is not None
    } or None


class APIChat:
    """Thread-local OpenAI-compatible client for one pinned official model."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str | None = None,
        timeout: float = 900.0,
    ) -> None:
        if not api_key:
            raise ValueError("API key is empty")
        self.profile = profile_for(model)
        self.provider = provider_for(model)
        self.base_url = (base_url or self.profile.base_url).rstrip("/")
        self.timeout = timeout
        self._api_key = api_key
        self._local = threading.local()

    def public_config(self) -> dict[str, Any]:
        return {
            **asdict(self.profile),
            "base_url": self.base_url,
            "timeout_seconds": self.timeout,
            "endpoint": "/chat/completions",
            "transport": getattr(self.provider, "TRANSPORT", "ordered image parts"),
        }

    def _client(self) -> OpenAI:
        client = getattr(self._local, "client", None)
        if client is None:
            client = OpenAI(
                api_key=self._api_key,
                base_url=self.base_url,
                timeout=self.timeout,
                max_retries=0,
                http_client=httpx.Client(timeout=self.timeout),
                default_headers=getattr(self.provider, "DEFAULT_HEADERS", None),
            )
            self._local.client = client
        return client

    def request_kwargs(
        self,
        messages: Iterable[dict[str, Any]],
        *,
        max_output_tokens: int,
        temperature: float | None = None,
        top_p: float | None = None,
    ) -> dict[str, Any]:
        return self.provider.request_kwargs(
            messages,
            max_output_tokens=max_output_tokens,
            temperature=temperature,
            top_p=top_p,
        )

    def complete(
        self,
        messages: Iterable[dict[str, Any]],
        *,
        max_output_tokens: int,
        temperature: float | None = None,
        top_p: float | None = None,
    ) -> tuple[str, dict[str, Any]]:
        build_started = time.monotonic()
        prepare = getattr(self.provider, "prepare_messages", None)
        if prepare is not None:
            messages = prepare(
                list(messages), client=self._client(), api_key=self._api_key
            )
        kwargs = self.request_kwargs(
            messages,
            max_output_tokens=max_output_tokens,
            temperature=temperature,
            top_p=top_p,
        )
        request_build_seconds = time.monotonic() - build_started
        image_urls = [
            part["image_url"]["url"]
            for message in kwargs["messages"]
            if isinstance(message.get("content"), list)
            for part in message["content"]
            if part.get("type") == "image_url"
        ]
        file_count = sum(
            part.get("type") == "file"
            for message in kwargs["messages"]
            if isinstance(message.get("content"), list)
            for part in message["content"]
        )
        video_frame_count = sum(
            len(part.get("video") or [])
            for message in kwargs["messages"]
            if isinstance(message.get("content"), list)
            for part in message["content"]
            if part.get("type") == "video"
        )
        api_started = time.monotonic()
        response = self._client().chat.completions.create(**kwargs)
        api_seconds = time.monotonic() - api_started
        text = response.choices[0].message.content or ""
        metadata = {
            "response_id": getattr(response, "id", None),
            "finish_reason": response.choices[0].finish_reason,
            "usage": _usage_dict(response),
            "transport": {
                "image_count": len(image_urls),
                "file_count": file_count,
                "video_frame_count": video_frame_count,
                "data_url_bytes": sum(len(url) for url in image_urls),
                "request_build_seconds": round(request_build_seconds, 3),
                "api_seconds": round(api_seconds, 3),
            },
        }
        self._local.last_metadata = metadata
        return text, metadata

    def text(self, messages: Iterable[dict[str, Any]], **kwargs: Any) -> str:
        text, _ = self.complete(messages, **kwargs)
        return text

    def last_metadata(self) -> dict[str, Any] | None:
        return getattr(self._local, "last_metadata", None)
