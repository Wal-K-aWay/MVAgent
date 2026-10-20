"""Model backends with one call shape: complete(messages, max_tokens, temperature, top_p) -> (text, request).

`VLLMBackend` uses the serial in-process replicas started by `../serve.py`.
`APIBackend` wraps the official provider profiles in `../api/` for closed models.
"""

from __future__ import annotations

import queue
import hashlib
import sys
import threading
import time
from typing import Any

import httpx
from .common import E2E_ROOT, sha256_file
from models.vlm.local.sync_server import digest, token_audit, validate_card


class VLLMBackend:
    """One request per endpoint; require the frozen execution profile and retain full token audits."""

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
        if enable_thinking:
            raise ValueError('The validated local profile requires thinking disabled')
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
        for card in cards.values():
            validate_card(card)
        if len({digest({key: card[key] for key in ['root', 'max_model_len', 'weights_manifest', 'execution']})
                for card in cards.values()}) != 1:
            raise RuntimeError('Endpoints have different weights, context lengths or execution settings')
        self.card = next(iter(cards.values()))
        self.replicas = {endpoint: card['worker'] for endpoint, card in cards.items()}
        if len({worker['gpu_uuid'] for worker in self.replicas.values()}) != len(self.replicas):
            raise RuntimeError('Each endpoint must own a different physical GPU')
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

    def _client(self, endpoint: str) -> httpx.Client:
        clients = self._local.__dict__.setdefault("clients", {})
        if endpoint not in clients:
            clients[endpoint] = httpx.Client(base_url=endpoint+'/', trust_env=False, timeout=self.timeout)
        return clients[endpoint]

    def identity(self) -> dict[str, Any]:
        return {
            "type": "vllm",
            "model": self.model,
            "weights": self.card.get("root"),
            "max_model_len": self.card.get("max_model_len"),
            "endpoints": self.endpoints,
            "enable_thinking": self.enable_thinking,
            "execution": self.card['execution'],
            "weights_manifest": self.card['weights_manifest'],
            "replicas": self.replicas,
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
        body = dict(model=self.model, messages=messages, max_tokens=max_tokens,
                    temperature=temperature, top_p=top_p, seed=0, return_token_ids=True,
                    chat_template_kwargs={'enable_thinking': False})
        if set(extra_body or {}).intersection(body):
            raise ValueError('extra_body cannot override the frozen request fields')
        body.update(extra_body or {})
        last_error: Exception | None = None
        for attempt in range(1, self.retries + 1):
            endpoint = self._slots.get()
            started = time.monotonic()
            try:
                response = self._client(endpoint).post('chat/completions', json=body)
                response.raise_for_status()
            except Exception as exc:  # noqa: BLE001 - retried, then re-raised with the last cause
                last_error = exc
                if attempt < self.retries:
                    time.sleep(min(2**attempt, 8))
                continue
            finally:
                self._slots.put(endpoint)
            data = response.json()
            audit = token_audit(data, response.request.content)
            if data['model'] != self.model or any(audit['worker'].get(k) != v for k, v in self.replicas[endpoint].items()):
                raise ValueError('The response came from a different worker than the admitted endpoint')
            if audit['input_sha256'] != digest(dict(messages=messages,
                generation=dict(temperature=temperature, top_p=top_p, max_tokens=max_tokens, seed=0),
                chat_template_kwargs={'enable_thinking': False})):
                raise ValueError('The endpoint used different messages or generation parameters')
            choice = data['choices'][0]
            # With thinking off this should stay empty; kept so an output the reasoning parser moved out of
            # `content` is never lost from the raw record.
            reasoning = choice['message'].get('reasoning_content') or choice['message'].get('reasoning')
            return choice['message'].get('content') or "", {
                "endpoint": endpoint,
                "attempts": attempt,
                "seconds": round(time.monotonic() - started, 3),
                "finish_reason": choice['finish_reason'],
                "usage": data['usage'],
                "generation": {k: v for k, v in body.items() if k not in {'model', 'messages'}},
                **audit,
                **({"reasoning_content": reasoning} if reasoning else {}),
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
