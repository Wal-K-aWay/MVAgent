"""Shared helpers for model clients and providers."""

from __future__ import annotations

import json
import ipaddress
import os
import re
import time
from pathlib import Path
from typing import Any, Callable, Generic, Iterable, TypeVar

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError


T = TypeVar("T")


def extract_json(text: Any) -> Any:
    """Extract and parse the first JSON object or array in text."""
    if isinstance(text, (dict, list)):
        return text
    original = str(text or "")
    raw = original.strip()
    if not raw:
        raise ValueError("Empty text; cannot extract JSON.")
    fenced = re.search(
        r"```(?:json)?\s*(.*?)\s*```",
        raw,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if fenced:
        raw = fenced.group(1).strip()
    try:
        return json.loads(raw)
    except Exception:
        match = re.search(r"(\{.*\}|\[.*\])", raw, flags=re.DOTALL)
        if not match:
            raise ValueError(
                "No JSON object or array found in response "
                f"({len(original)} characters): "
                f"{sanitize_error_excerpt(original)}"
            )
        try:
            return json.loads(match.group(1))
        except Exception as exc:
            raise ValueError(
                f"Failed to parse JSON response ({len(original)} characters): "
                f"{sanitize_error_excerpt(original)}"
            ) from exc


def validate_json_schema(
    value: Any,
    schema: dict[str, Any] | None,
    *,
    path: str = "$",
) -> None:
    if not schema:
        return
    try:
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(value)
    except ValidationError as exc:
        raise ValueError(_schema_error(exc, path=path)) from exc
    except SchemaError as exc:
        raise ValueError(f"Invalid JSON schema: {exc.message}") from exc


def _schema_error(exc: ValidationError, *, path: str) -> str:
    location = ".".join(str(item) for item in exc.absolute_path)
    error_path = f"{path}.{location}" if location else path
    message = f"{error_path}: {exc.message}"
    if exc.context:
        details = "; ".join(
            _schema_error(item, path=path) for item in exc.context[:3]
        )
        message = f"{message} ({details})"
    return message


def resolve_local_path(path: str | Path) -> str:
    return str(Path(path).expanduser().resolve())


_ENV_VAR_NAME_RE = re.compile(r"^[A-Z_][A-Z0-9_]*$")
_CREDENTIAL_ENV_VAR_HINTS = ("KEY", "TOKEN", "SECRET", "CREDENTIAL")


def looks_like_env_var_name(value: str) -> bool:
    """Return whether one API-key literal looks like a credential env var name."""
    return bool(_ENV_VAR_NAME_RE.fullmatch(str(value or ""))) and any(
        hint in str(value or "") for hint in _CREDENTIAL_ENV_VAR_HINTS
    )


def is_loopback_host(host: str | None) -> bool:
    """Return whether one hostname is the local loopback."""
    if not host:
        return False
    if str(host).lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def validate_gpu_list(
    value: Any,
    *,
    label: str,
    error_class: type[Exception] = ValueError,
) -> None:
    """Validate one non-empty, duplicate-free list of GPU indexes."""
    if not isinstance(value, list) or not value:
        raise error_class(f"{label} gpus must be a non-empty list.")
    if any(
        not (type(gpu) is int and gpu >= 0 or isinstance(gpu, str) and gpu.startswith("GPU-"))
        for gpu in value
    ):
        raise error_class(
            f"{label} gpus must contain non-negative indexes or GPU UUIDs."
        )
    if len(set(value)) != len(value):
        raise error_class(f"{label} gpus must not contain duplicates.")


def build_chat_messages(
    system_prompt: str | None,
    user_prompt: str,
) -> list[dict[str, str]]:
    """Return the canonical system-plus-user message list."""
    messages: list[dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": user_prompt})
    return messages


def resolve_api_key(
    api_key: str | None,
    *,
    error_class: type[Exception],
    label: str,
) -> str:
    """Resolve one API key literal or environment-variable name to its value."""
    raw_api_key = str(api_key or "").strip()
    if not raw_api_key:
        raise error_class(f"API key is required for {label}; set api_key.")
    env_value = os.environ.get(raw_api_key)
    if env_value is not None and env_value.strip():
        return env_value.strip()
    if looks_like_env_var_name(raw_api_key):
        raise error_class(
            f"API key environment variable '{raw_api_key}' is not set "
            "or is empty."
        )
    return raw_api_key


class ProviderRegistry(Generic[T]):
    """Registry mapping provider names to factories with one error contract."""

    def __init__(
        self,
        *,
        label: str,
        error_class: type[Exception],
    ) -> None:
        self._label = str(label)
        self._error_class = error_class
        self._factories: dict[str, Callable[..., T]] = {}

    def register(self, name: str, factory: Callable[..., T]) -> None:
        normalized_name = str(name or "").strip()
        if not normalized_name:
            raise self._error_class(
                f"{self._label} provider name cannot be empty."
            )
        self._factories[normalized_name] = factory

    def get(self, name: str) -> Callable[..., T]:
        provider_name = str(name or "").strip()
        factory = self._factories.get(provider_name)
        if factory is None:
            available = ", ".join(sorted(self._factories)) or "none"
            raise self._error_class(
                f"Unknown {self._label} provider '{provider_name}'. "
                f"Available providers: {available}."
            )
        return factory

    def available(self) -> list[str]:
        return sorted(self._factories)


def sanitize_error_excerpt(body: str, *, max_chars: int = 400) -> str:
    """Collapse and redact credential-like values from one HTTP error body."""
    excerpt = " ".join(str(body or "").split())
    excerpt = re.sub(
        r"(?i)(x-api-key\s*[:=]\s*[\"']?)[^\"'\s,}]+",
        r"\1[REDACTED]",
        excerpt,
    )
    excerpt = re.sub(
        r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+",
        r"\1[REDACTED]",
        excerpt,
    )
    excerpt = re.sub(
        r"(?i)((?:api[_\s-]?key|access[_-]?token|auth[_-]?token|token)"
        r"\s*[:=]\s*[\"']?)[^\"'\s,}]+",
        r"\1[REDACTED]",
        excerpt,
    )
    excerpt = re.sub(
        r"(?i)((?:api[_\s-]?key|access[_-]?token|auth[_-]?token|token)"
        r"[\"']?\s*:\s*[\"'])[^\"']+([\"'])",
        r"\1[REDACTED]\2",
        excerpt,
    )
    if len(excerpt) > max_chars:
        excerpt = excerpt[:max_chars].rstrip() + "..."
    return excerpt


_SYSTEM_ROLES = frozenset({"system", "developer"})


def content_text(content: Any) -> str:
    """Render one message content value as plain text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                if item.get("type") == "text" or "text" in item:
                    parts.append(str(item.get("text", "")))
        return "\n".join(part for part in parts if part)
    return str(content or "")


def messages_with_schema_prompt(
    messages: Iterable[dict[str, Any]],
    *,
    json_schema: dict[str, Any],
    schema_name: str | None,
) -> list[dict[str, Any]]:
    """Prepend one JSON-Schema instruction when the backend has no native support."""
    instruction = (
        "Return exactly one JSON object matching the following JSON Schema. "
        "Do not add Markdown fences or explanatory text.\n\n"
        f"Schema name: {schema_name or 'mvagent_response'}\n"
        "JSON Schema:\n"
        f"{json.dumps(json_schema, ensure_ascii=False)}"
    )
    normalized = [dict(message) for message in messages]
    if normalized and str(normalized[0].get("role", "")).lower() in _SYSTEM_ROLES:
        normalized[0]["content"] = (
            f"{content_text(normalized[0].get('content', ''))}\n\n{instruction}"
        )
    else:
        normalized.insert(0, {"role": "system", "content": instruction})
    return normalized


def retry_transient(
    call: Callable[[], T],
    *,
    attempts: int,
    error_class: type[Exception],
    label: str,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Call ``call`` with bounded backoff retries for transient API errors."""
    last_error: Exception | None = None
    total_attempts = max(0, int(attempts or 0)) + 1
    for attempt in range(total_attempts):
        try:
            return call()
        except error_class as exc:
            last_error = exc
            if not getattr(exc, "transient", False) or attempt >= total_attempts - 1:
                raise
            from models.execution import emit_event, remaining_timeout
            emit_event("model_retry", attempt=attempt + 1, error=str(exc))
            sleep(remaining_timeout(min(1.0, 0.25 * float(attempt + 1))))
    if last_error is not None:
        raise last_error
    raise error_class(f"{label} request failed without an error.")


__all__ = [
    "ProviderRegistry",
    "build_chat_messages",
    "content_text",
    "extract_json",
    "is_loopback_host",
    "looks_like_env_var_name",
    "messages_with_schema_prompt",
    "resolve_local_path",
    "resolve_api_key",
    "retry_transient",
    "sanitize_error_excerpt",
    "validate_gpu_list",
    "validate_json_schema",
]
