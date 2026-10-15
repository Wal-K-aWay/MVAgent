from __future__ import annotations

from models.llm.api.client import ApiLLMError
from .anthropic import (
    MINIMAX_ANTHROPIC_API_BASE,
    AnthropicCompatibleProvider,
)


class AnthropicCompatibleLLMProvider(AnthropicCompatibleProvider):
    """Anthropic Messages-compatible provider for pure-text API models."""

    error_class = ApiLLMError
    provider_kind_label = "API LLM"


class MiniMaxAnthropicLLMProvider(AnthropicCompatibleLLMProvider):
    """MiniMax Anthropic-compatible text provider."""

    default_api_base = MINIMAX_ANTHROPIC_API_BASE


__all__ = [
    "AnthropicCompatibleLLMProvider",
    "MiniMaxAnthropicLLMProvider",
]
