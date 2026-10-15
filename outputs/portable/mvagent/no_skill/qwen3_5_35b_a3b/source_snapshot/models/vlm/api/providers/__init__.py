"""Built-in visual-model providers."""

from __future__ import annotations

from .anthropic_compatible import (
    AnthropicCompatibleVLMProvider,
    MiniMaxAnthropicVLMProvider,
)
from .dashscope import DashScopeProvider
from .openai_compatible import OpenAICompatibleProvider


__all__ = [
    "AnthropicCompatibleVLMProvider",
    "DashScopeProvider",
    "MiniMaxAnthropicVLMProvider",
    "OpenAICompatibleProvider",
]
