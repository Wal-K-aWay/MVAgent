from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Protocol

from models.utils import ProviderRegistry, resolve_api_key, retry_transient
from models.llm.base import LLMClient


class ApiLLMError(RuntimeError):
    """Raised when an API LLM request cannot be completed."""

    def __init__(
        self,
        message: str,
        *,
        transient: bool = False,
        status_code: Optional[int] = None,
    ) -> None:
        super().__init__(message)
        self.transient = transient
        self.status_code = status_code


@dataclass(frozen=True)
class ApiLLMRequest:
    cfg: Any
    messages: List[Dict[str, Any]]
    api_key: str
    temperature: Optional[float]
    top_p: Optional[float]
    max_tokens: int
    json_schema: Optional[Dict[str, Any]] = None
    schema_name: Optional[str] = None


class ApiLLMProvider(Protocol):
    def __init__(self, cfg: Any) -> None:
        ...

    def chat(self, request: ApiLLMRequest) -> str:
        ...


_ProviderFactory = Callable[[Any], ApiLLMProvider]
_LLM_PROVIDERS = ProviderRegistry[ApiLLMProvider](
    label="API LLM",
    error_class=ApiLLMError,
)


def register_api_llm_provider(name: str, provider: _ProviderFactory) -> None:
    _LLM_PROVIDERS.register(name, provider)


def available_api_llm_providers() -> List[str]:
    return _LLM_PROVIDERS.available()


class ApiLLMClient(LLMClient):
    """Pure-text client backed by one registered API provider."""

    def __init__(self, cfg: Any) -> None:
        super().__init__(
            name=cfg.model_name or cfg.model_type,
            backend_type="api",
        )
        self.cfg = cfg
        self.api_key = resolve_api_key(
            cfg.api_key,
            error_class=ApiLLMError,
            label="API LLM clients",
        )
        provider_name = str(cfg.provider or "").strip()
        self.provider = _LLM_PROVIDERS.get(provider_name)(cfg)

    def chat(
        self,
        messages: List[Dict[str, Any]],
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        max_tokens: Optional[int] = None,
        stop_token_ids: Optional[List[int]] = None,
        json_schema: Optional[Dict[str, Any]] = None,
        schema_name: Optional[str] = None,
    ) -> str:
        del stop_token_ids
        for index, message in enumerate(messages):
            content = message.get("content", "")
            if not isinstance(content, str):
                raise ApiLLMError(
                    "API LLM messages must contain text only; message "
                    f"{index} has non-text content."
                )
        omit_sampling = (
            str(self.cfg.provider or "") == "deepseek"
            and bool(self.cfg.enable_thinking)
        )
        resolved_temperature = (
            self.cfg.temperature if temperature is None else temperature
        )
        resolved_top_p = self.cfg.top_p if top_p is None else top_p
        request = ApiLLMRequest(
            cfg=self.cfg,
            messages=messages,
            api_key=self.api_key,
            temperature=None if omit_sampling else resolved_temperature,
            top_p=None if omit_sampling else resolved_top_p,
            max_tokens=(
                self.cfg.max_tokens
                if max_tokens is None
                else max_tokens
            ),
            json_schema=json_schema,
            schema_name=schema_name,
        )

        return retry_transient(
            lambda: self.provider.chat(request),
            attempts=self.cfg.max_retries,
            error_class=ApiLLMError,
            label="API LLM",
        )


from .providers.anthropic_compatible import (
    AnthropicCompatibleLLMProvider,
    MiniMaxAnthropicLLMProvider,
)
from .providers.deepseek import DeepSeekProvider


register_api_llm_provider(
    "anthropic_compatible",
    AnthropicCompatibleLLMProvider,
)
register_api_llm_provider("deepseek", DeepSeekProvider)
register_api_llm_provider("minimax_anthropic", MiniMaxAnthropicLLMProvider)


__all__ = [
    "ApiLLMClient",
    "ApiLLMError",
    "ApiLLMProvider",
    "ApiLLMRequest",
    "available_api_llm_providers",
    "register_api_llm_provider",
]
