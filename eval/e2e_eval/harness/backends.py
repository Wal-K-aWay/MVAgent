"""Model backends with one call shape: complete(messages, max_tokens, temperature, top_p) -> (text, request).

`VLLMBackend` is the standard path: OpenAI-compatible vLLM replicas, the same servers MVAgent uses.
`APIBackend` wraps the official provider profiles in `../api/` for closed models.
"""

from __future__ import annotations

import queue
import sys
import threading
import time
from typing import Any

import httpx
from openai import OpenAI

from .common import E2E_ROOT


def _usage(response: Any) -> dict[str, Any] | None:
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    return usage.model_dump(exclude_none=True) if hasattr(usage, "model_dump") else dict(usage)


class VLLMBackend:
    """A pool of vLLM endpoints serving one model, one request in flight per endpoint.

    One request at a time per replica keeps every batch identical across runs, so greedy outputs are
    bit-for-bit reproducible (verified on H200); concurrent requests would change batch composition.
    """

    def __init__(
        self,
        endpoints: list[str],
        *,
        model: str | None,
        timeout: float,
        retries: int,
        enable_thinking: bool,
    ) -> None:
        self.endpoints = [endpoint.rstrip("/") for endpoint in endpoints]
        self.timeout = timeout
        self.retries = retries
        self.enable_thinking = enable_thinking
        self._local = threading.local()
        served = {endpoint: self._served_models(endpoint) for endpoint in self.endpoints}
        names = {name for models in served.values() for name in models}
        self.model = model or (names.pop() if len(names) == 1 else "")
        if not self.model:
            raise RuntimeError(f"endpoints serve several models {sorted(names)}; pass --model")
        missing = [endpoint for endpoint, models in served.items() if self.model not in models]
        if missing:
            raise RuntimeError(f"model {self.model!r} is not served by {missing}")
        cards = {endpoint: served[endpoint][self.model] for endpoint in self.endpoints}
        if len({(card.get("root"), card.get("max_model_len")) for card in cards.values()}) != 1:
            raise RuntimeError(f"endpoints serve different weights or context lengths: {cards}")
        self.card = next(iter(cards.values()))
        self._slots: queue.Queue[str] = queue.Queue()
        for endpoint in self.endpoints:
            self._slots.put(endpoint)

    @property
    def slots(self) -> int:
        return len(self.endpoints)

    def _served_models(self, endpoint: str) -> dict[str, dict[str, Any]]:
        response = httpx.get(f"{endpoint}/models", timeout=15, trust_env=False)
        response.raise_for_status()
        return {item["id"]: item for item in response.json()["data"]}

    def _client(self, endpoint: str) -> OpenAI:
        clients = self._local.__dict__.setdefault("clients", {})
        if endpoint not in clients:
            clients[endpoint] = OpenAI(
                api_key="unused",
                base_url=endpoint,
                timeout=self.timeout,
                max_retries=0,
                http_client=httpx.Client(trust_env=False, timeout=self.timeout),
            )
        return clients[endpoint]

    def identity(self) -> dict[str, Any]:
        return {
            "type": "vllm",
            "model": self.model,
            "weights": self.card.get("root"),
            "max_model_len": self.card.get("max_model_len"),
            "endpoints": self.endpoints,
            "enable_thinking": self.enable_thinking,
        }

    def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int | None,
        temperature: float,
        top_p: float,
        extra_body: dict[str, Any] | None = None,
    ) -> tuple[str, dict[str, Any]]:
        body = {"chat_template_kwargs": {"enable_thinking": self.enable_thinking}, **(extra_body or {})}
        last_error: Exception | None = None
        for attempt in range(1, self.retries + 1):
            endpoint = self._slots.get()
            started = time.monotonic()
            try:
                response = self._client(endpoint).chat.completions.create(
                    model=self.model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    top_p=top_p,
                    extra_body=body,
                )
            except Exception as exc:  # noqa: BLE001 - retried, then re-raised with the last cause
                last_error = exc
                self._slots.put(endpoint)
                time.sleep(min(2**attempt, 8))
                continue
            self._slots.put(endpoint)
            choice = response.choices[0]
            return choice.message.content or "", {
                "endpoint": endpoint,
                "attempts": attempt,
                "seconds": round(time.monotonic() - started, 3),
                "finish_reason": choice.finish_reason,
                "usage": _usage(response),
                "generation": {"max_tokens": max_tokens, "temperature": temperature, "top_p": top_p, **body},
            }
        raise RuntimeError(f"vLLM request failed after {self.retries} attempts: {last_error}") from last_error


class APIBackend:
    """Official closed-model APIs; the provider profile owns thinking control and frame transport."""

    def __init__(self, model: str, *, base_url: str | None, api_key_env: str | None, timeout: float, retries: int) -> None:
        import os

        api_root = str(E2E_ROOT / "api")
        if api_root not in sys.path:
            sys.path.insert(0, api_root)
        from client import APIChat, profile_for  # noqa: PLC0415 - provider package lives in ../api

        self.api_key_env = api_key_env or profile_for(model).api_key_env
        key = os.environ.get(self.api_key_env, "")
        if not key:
            raise RuntimeError(f"set {self.api_key_env}; credentials are only read from the environment")
        self.chat = APIChat(api_key=key, model=model, base_url=base_url, timeout=timeout)
        self.model = model
        self.retries = retries
        self.slots = 1

    def identity(self) -> dict[str, Any]:
        return {"type": "api", **self.chat.public_config(), "api_key_env": self.api_key_env}

    def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int | None,
        temperature: float,
        top_p: float,
        extra_body: dict[str, Any] | None = None,  # vLLM-only options; providers set their own
    ) -> tuple[str, dict[str, Any]]:
        last_error: Exception | None = None
        for attempt in range(1, self.retries + 1):
            try:
                text, metadata = self.chat.complete(
                    messages, max_output_tokens=max_tokens or 8192, temperature=temperature, top_p=top_p
                )
            except Exception as exc:  # noqa: BLE001 - retried, then re-raised with the last cause
                last_error = exc
                time.sleep(min(2**attempt, 8))
                continue
            return text, {"attempts": attempt, **metadata}
        raise RuntimeError(f"API request failed after {self.retries} attempts: {last_error}") from last_error
