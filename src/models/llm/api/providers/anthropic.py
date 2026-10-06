"""Shared Anthropic Messages API provider base for text and VLM clients."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, Iterable, List, Tuple, TypeVar

from models.utils import (
    content_text,
    messages_with_schema_prompt,
    sanitize_error_excerpt,
)


ANTHROPIC_API_VERSION = "2023-06-01"
DEFAULT_ANTHROPIC_API_BASE = "https://api.anthropic.com"
MINIMAX_ANTHROPIC_API_BASE = "https://api.minimaxi.com/anthropic"

_SYSTEM_ROLES = {"system", "developer"}
_ErrorT = TypeVar("_ErrorT", bound=Exception)


def _default_content_mapper(item: dict[str, Any]) -> dict[str, Any]:
    item_type = item.get("type")
    if item_type == "text" or "text" in item:
        return {"type": "text", "text": str(item.get("text", ""))}
    raise ValueError(f"Unsupported Anthropic content item type: {item_type}")


def _normalize_messages(
    messages: Iterable[dict[str, Any]],
    *,
    content_mapper: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> Tuple[str | None, List[Dict[str, Any]]]:
    """Convert OpenAI-style chat messages to Anthropic Messages API shape."""
    mapper = content_mapper or _default_content_mapper
    system_parts: list[str] = []
    normalized: list[dict[str, Any]] = []
    for message in messages:
        role = str(message.get("role", "user") or "user").strip().lower()
        content = message.get("content", "")
        if role in _SYSTEM_ROLES:
            text = content_text(content).strip()
            if text:
                system_parts.append(text)
            continue
        if role not in {"user", "assistant"}:
            raise ValueError(f"Unsupported Anthropic message role: {role}")
        if isinstance(content, list):
            normalized_content = [mapper(dict(item)) for item in content]
        else:
            normalized_content = str(content or "")
        normalized.append({"role": role, "content": normalized_content})
    system = "\n\n".join(system_parts).strip() or None
    return system, normalized


def _messages_endpoint(api_base: str | None) -> str:
    base = str(api_base or DEFAULT_ANTHROPIC_API_BASE).strip().rstrip("/")
    if base.endswith("/v1"):
        return f"{base}/messages"
    return f"{base}/v1/messages"


def _post_messages(
    *,
    payload: dict[str, Any],
    api_base: str | None,
    api_key: str,
    timeout_sec: float,
    error_class: type[_ErrorT],
    provider_label: str,
    model_name: str,
) -> str:
    endpoint = _messages_endpoint(api_base)
    http_request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_API_VERSION,
            "content-type": "application/json",
            "accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(
            http_request,
            timeout=timeout_sec,
        ) as response:
            response_body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        transient = exc.code == 429 or 500 <= exc.code <= 599
        raise error_class(
            f"{provider_label} request failed with HTTP {exc.code} "
            f"for model {model_name}: {sanitize_error_excerpt(error_body)}",
            transient=transient,
            status_code=exc.code,
        ) from exc
    except (urllib.error.URLError, OSError) as exc:
        raise error_class(
            f"{provider_label} transport failed for model {model_name}: {exc}",
            transient=True,
        ) from exc

    try:
        data = json.loads(response_body)
        content = data["content"]
        text_parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text" or "text" in item:
                    text_parts.append(str(item.get("text", "")))
            elif isinstance(item, str):
                text_parts.append(item)
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise error_class(
            f"Malformed {provider_label} response for model {model_name}."
        ) from exc
    return "".join(text_parts).strip()


class AnthropicCompatibleProvider:
    """Anthropic Messages API provider shared by text and VLM clients.

    Concrete subclasses set ``error_class`` and ``provider_kind_label`` and may
    override ``_content_item`` to serialize image/video content blocks.
    """

    default_api_base: str | None = None
    error_class: type[Exception]
    provider_kind_label: str
    supported_video_modes: set[str] = set()

    def __init__(self, cfg: Any) -> None:
        self.cfg = cfg

    def _api_base(self) -> str:
        api_base = str(self.cfg.api_base or self.default_api_base or "").strip()
        if not api_base:
            raise self.error_class(
                f"api_base is required for Anthropic-compatible "
                f"{self.provider_kind_label} providers."
            )
        return api_base

    def _content_item(self, item: Dict[str, Any]) -> Dict[str, Any]:
        return _default_content_mapper(item)

    def _inject_thinking(self, extra_body: Dict[str, Any]) -> None:
        if str(self.cfg.provider or "") == "minimax_anthropic":
            extra_body.setdefault(
                "thinking",
                {
                    "type": (
                        "adaptive"
                        if bool(getattr(self.cfg, "enable_thinking", False))
                        else "disabled"
                    )
                },
            )

    def build_payload(self, request: Any) -> Dict[str, Any]:
        messages = request.messages
        if request.json_schema:
            messages = messages_with_schema_prompt(
                messages,
                json_schema=request.json_schema,
                schema_name=request.schema_name,
            )
        system, normalized_messages = _normalize_messages(
            messages,
            content_mapper=self._content_item,
        )
        payload: Dict[str, Any] = {
            "model": self.cfg.model_name,
            "max_tokens": int(request.max_tokens),
            "messages": normalized_messages,
            "stream": False,
        }
        if system:
            payload["system"] = system
        if request.temperature is not None:
            payload["temperature"] = float(request.temperature)
        if request.top_p is not None:
            payload["top_p"] = float(request.top_p)
        extra_body = dict(getattr(request, "extra_body", None) or {})
        self._inject_thinking(extra_body)
        reserved = set(payload).intersection(extra_body)
        if reserved:
            raise ValueError(
                "Anthropic extra_body cannot replace core fields: "
                + ", ".join(sorted(reserved))
            )
        payload.update(extra_body)
        return payload

    def chat(self, request: Any) -> str:
        return _post_messages(
            payload=self.build_payload(request),
            api_base=self._api_base(),
            api_key=request.api_key,
            timeout_sec=self.cfg.timeout_sec,
            error_class=self.error_class,
            provider_label=str(self.cfg.provider or "anthropic_compatible"),
            model_name=self.cfg.model_name,
        )


__all__ = [
    "ANTHROPIC_API_VERSION",
    "AnthropicCompatibleProvider",
    "DEFAULT_ANTHROPIC_API_BASE",
    "MINIMAX_ANTHROPIC_API_BASE",
]
