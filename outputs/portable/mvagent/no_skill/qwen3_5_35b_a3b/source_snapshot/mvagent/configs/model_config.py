from __future__ import annotations

import os
import urllib.parse
from dataclasses import dataclass, field, fields
from typing import Any, ClassVar, Optional, Sequence

from mvagent.utils.tools import is_loopback_host, looks_like_env_var_name, validate_gpu_list

from .agent_config import Agent_Model_Config


_MINIMAX_ANTHROPIC_MODELS = {
    "MiniMax-M3",
    "MiniMax-M2.7",
    "MiniMax-M2.7-highspeed",
    "MiniMax-M2.5",
    "MiniMax-M2.5-highspeed",
    "MiniMax-M2.1",
    "MiniMax-M2.1-highspeed",
    "MiniMax-M2",
}
_MINIMAX_ANTHROPIC_VLM_MODELS = {"MiniMax-M3"}


def _pick(value: Any, default: Any) -> Any:
    return default if value is None else value


def _validate_api_key(value: Any, name: str) -> None:
    key = str(value or "").strip()
    if not key:
        raise ValueError(f"{name} must set api_key.")
    env_value = os.environ.get(key)
    if env_value is not None and not env_value.strip():
        raise ValueError(
            f"{name} api_key references empty environment variable '{key}'."
        )
    if env_value is None and looks_like_env_var_name(key):
        raise ValueError(
            f"{name} api_key references unset environment variable '{key}'."
        )


@dataclass
class ApiLLMConfig:
    """Resolved settings consumed by :class:`ApiLLMClient`."""

    model_type: str = "api_llm"
    provider: str = "deepseek"
    model_name: str = ""
    api_base: Optional[str] = None
    api_key: Optional[str] = None
    enable_thinking: bool = False
    reasoning_effort: Optional[str] = None
    temperature: float = 0.2
    top_p: float = 0.8
    max_tokens: int = 1024
    stop_token_ids: list[int] = field(default_factory=list)
    timeout_sec: int = 120
    max_retries: int = 2


@dataclass
class ApiVLMConfig:
    """Resolved settings consumed by :class:`ApiVLMClient`."""

    model_type: str = "api_vlm"
    provider: str = "openai_compatible"
    model_name: str = ""
    api_base: Optional[str] = None
    api_key: Optional[str] = None
    reasoning_effort: Optional[str] = None
    temperature: float = 0.2
    top_p: float = 0.8
    max_tokens: int = 1024
    stop_token_ids: list[int] = field(default_factory=list)
    max_videos_per_request: int = 1
    max_video_frames_per_request: int = 512
    video_mode: str = "video_url"
    video_fps: Optional[float] = None
    video_fps_transport: str = "content"
    video_min_pixels: int = 28 * 28
    video_max_pixels: int = 360 * 420
    timeout_sec: int = 120
    max_retries: int = 2


@dataclass
class LocalVLLMConfig:
    """Resolved settings consumed by the local vLLM client and service."""

    model_type: str = "local_vllm"
    model_name: str = ""
    served_model_name: str = ""
    gpus: list[int | str] = field(default_factory=list)
    endpoint: str = ""
    api_key: str = "EMPTY"
    startup_timeout_sec: float = 1800.0
    dtype: str = "bfloat16"
    gpu_memory_utilization: float = 0.85
    max_model_len: int = 16384
    reasoning_parser: Optional[str] = None
    enable_thinking: bool = False
    temperature: float = 0.2
    top_p: float = 0.8
    max_tokens: int = 1024
    stop_token_ids: list[int] = field(default_factory=list)
    max_videos_per_request: int = 1
    max_video_frames_per_request: int = 512
    video_mode: str = "video_url"
    video_fps: Optional[float] = None
    video_min_pixels: int = 28 * 28
    video_max_pixels: int = 360 * 420
    timeout_sec: int = 120
    max_retries: int = 2


@dataclass
class ModelInstanceConfig:
    """Common user-facing settings for one named model instance."""

    type: str = field(init=False, default="")
    model_name: Optional[str] = None
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    max_tokens: Optional[int] = None
    stop_token_ids: Optional[list[int]] = None
    max_videos_per_request: Optional[int] = None
    max_video_frames_per_request: Optional[int] = None
    video_mode: Optional[str] = None
    video_fps: Optional[float] = None
    video_min_pixels: Optional[int] = None
    video_max_pixels: Optional[int] = None
    timeout_sec: Optional[int] = None
    max_retries: Optional[int] = None
    capabilities: ClassVar[frozenset[str]] = frozenset(
        {"text", "structured_output"}
    )

    def validate_limits(self, name: str) -> None:
        """Validate provider-independent output and visual-input limits."""
        if self.max_tokens is not None and (
            isinstance(self.max_tokens, bool)
            or not isinstance(self.max_tokens, int)
            or self.max_tokens <= 0
        ):
            raise ValueError(f"{name} max_tokens must be a positive integer.")
        if self.video_fps is not None and (
            isinstance(self.video_fps, bool)
            or not isinstance(self.video_fps, (int, float))
            or float(self.video_fps) <= 0.0
        ):
            raise ValueError(f"{name} video_fps must be positive.")
        if self.max_videos_per_request is not None and (
            isinstance(self.max_videos_per_request, bool)
            or not isinstance(self.max_videos_per_request, int)
            or self.max_videos_per_request <= 0
        ):
            raise ValueError(
                f"{name} max_videos_per_request must be a positive integer."
            )
        if self.max_video_frames_per_request is not None and (
            isinstance(self.max_video_frames_per_request, bool)
            or not isinstance(self.max_video_frames_per_request, int)
            or self.max_video_frames_per_request <= 0
        ):
            raise ValueError(
                f"{name} max_video_frames_per_request must be a positive integer."
            )
        for field_name in ("video_min_pixels", "video_max_pixels"):
            value = getattr(self, field_name)
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value <= 0
            ):
                raise ValueError(
                    f"{name} {field_name} must be a positive integer."
                )
        if (
            self.video_min_pixels is not None
            and self.video_max_pixels is not None
            and self.video_min_pixels > self.video_max_pixels
        ):
            raise ValueError(
                f"{name} video_min_pixels must not exceed video_max_pixels."
            )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ModelInstanceConfig:
        kwargs = {
            item.name: data[item.name]
            for item in fields(cls)
            if item.init and item.name in data
        }
        return cls(**kwargs)

    def to_dict(self) -> dict[str, Any]:
        return {
            item.name: value
            for item in fields(self)
            if (value := getattr(self, item.name)) is not None
        }

    def _text_runtime(
        self,
        agent: Agent_Model_Config,
    ) -> dict[str, Any]:
        return {
            "temperature": float(
                _pick(agent.temperature, _pick(self.temperature, 0.2))
            ),
            "top_p": float(_pick(self.top_p, 0.8)),
            "max_tokens": int(
                _pick(_pick(agent.max_tokens, self.max_tokens), 1024)
            ),
            "stop_token_ids": list(self.stop_token_ids or []),
            "timeout_sec": int(_pick(self.timeout_sec, 120)),
            "max_retries": int(_pick(self.max_retries, 2)),
        }

    def _visual_runtime(
        self,
        agent: Agent_Model_Config,
    ) -> dict[str, Any]:
        return {
            **self._text_runtime(agent),
            "max_videos_per_request": int(
                _pick(self.max_videos_per_request, 1)
            ),
            "max_video_frames_per_request": int(
                _pick(self.max_video_frames_per_request, 512)
            ),
            "video_mode": str(self.video_mode or "video_url"),
            "video_fps": self.video_fps,
            "video_min_pixels": int(_pick(self.video_min_pixels, 28 * 28)),
            "video_max_pixels": int(
                _pick(self.video_max_pixels, 360 * 420)
            ),
        }

    def validate(
        self,
        name: str,
        *,
        known_api_providers: Sequence[str] = (),
        known_api_llm_providers: Sequence[str] = (),
    ) -> None:
        raise NotImplementedError

    def to_runtime_config(
        self,
        name: str,
        agent: Agent_Model_Config,
    ) -> ApiLLMConfig | ApiVLMConfig | LocalVLLMConfig:
        raise NotImplementedError


@dataclass
class ApiLLMModelInstanceConfig(ModelInstanceConfig):
    """Parsed ``api_llm`` model instance."""

    type: str = field(init=False, default="api_llm")
    provider: Optional[str] = None
    api_base: Optional[str] = None
    api_key: Optional[str] = None
    enable_thinking: Optional[bool] = None
    reasoning_effort: Optional[str] = None
    capabilities: ClassVar[frozenset[str]] = frozenset(
        {"text", "structured_output"}
    )

    def validate(
        self,
        name: str,
        *,
        known_api_providers: Sequence[str] = (),
        known_api_llm_providers: Sequence[str] = (),
    ) -> None:
        del known_api_providers
        provider = str(self.provider or "").strip()
        if not provider:
            raise ValueError(f"{name} is missing provider.")
        if provider not in known_api_llm_providers:
            known = ", ".join(known_api_llm_providers) or "none"
            raise ValueError(
                f"{name} has unsupported API LLM provider '{provider}'. "
                f"Known providers: {known}."
            )
        model_name = str(self.model_name or "").strip()
        if not model_name:
            raise ValueError(f"{name} must set model_name.")
        if provider == "deepseek" and model_name not in {
            "deepseek-v4-flash",
            "deepseek-v4-pro",
        }:
            raise ValueError(
                f"{name} has unsupported DeepSeek model '{model_name}'. "
                "Use deepseek-v4-flash or deepseek-v4-pro."
            )
        if (
            provider == "minimax_anthropic"
            and model_name not in _MINIMAX_ANTHROPIC_MODELS
        ):
            raise ValueError(
                f"{name} has unsupported MiniMax Anthropic-compatible model "
                f"'{model_name}'."
            )
        if provider == "anthropic_compatible" and not str(
            self.api_base or ""
        ).strip():
            raise ValueError(
                f"{name} uses provider anthropic_compatible and must set api_base."
            )
        api_base = str(self.api_base or "").strip()
        if api_base:
            parsed_base = urllib.parse.urlparse(api_base)
            if parsed_base.scheme not in {"http", "https"} or not (
                parsed_base.hostname
            ):
                raise ValueError(
                    f"{name} api_base must be an HTTP(S) endpoint."
                )
        _validate_api_key(self.api_key, name)
        if self.enable_thinking is not None and not isinstance(
            self.enable_thinking,
            bool,
        ):
            raise ValueError(f"{name} enable_thinking must be a boolean.")
        effort = str(self.reasoning_effort or "").strip()
        if effort and provider != "deepseek":
            raise ValueError(
                f"{name} reasoning_effort is supported only for DeepSeek."
            )
        if effort and effort not in {"low", "high", "max"}:
            raise ValueError(
                f"{name} reasoning_effort must be low, high, or max."
            )
        if provider == "deepseek" and bool(self.enable_thinking) and (
            self.temperature is not None or self.top_p is not None
        ):
            raise ValueError(
                f"{name} must not set temperature or top_p while DeepSeek "
                "thinking mode is enabled because the API ignores them."
            )
        if self.stop_token_ids:
            raise ValueError(
                f"{name} uses provider {provider} and cannot set stop_token_ids."
            )
        visual_fields = {
            "max_videos_per_request": self.max_videos_per_request,
            "max_video_frames_per_request": (
                self.max_video_frames_per_request
            ),
            "video_mode": self.video_mode,
            "video_fps": self.video_fps,
            "video_min_pixels": self.video_min_pixels,
            "video_max_pixels": self.video_max_pixels,
        }
        configured_visual = [
            field_name
            for field_name, value in visual_fields.items()
            if value is not None
        ]
        if configured_visual:
            raise ValueError(
                f"{name} is type api_llm and cannot set visual parameters: "
                + ", ".join(configured_visual)
            )

    def to_runtime_config(
        self,
        name: str,
        agent: Agent_Model_Config,
    ) -> ApiLLMConfig:
        return ApiLLMConfig(
            provider=str(self.provider or "deepseek"),
            model_name=str(self.model_name or name),
            api_base=self.api_base,
            api_key=self.api_key,
            enable_thinking=bool(_pick(self.enable_thinking, False)),
            reasoning_effort=(
                str(self.reasoning_effort)
                if self.reasoning_effort
                else None
            ),
            **self._text_runtime(agent),
        )


@dataclass
class ApiModelInstanceConfig(ModelInstanceConfig):
    """Parsed ``api_vlm`` model instance."""

    type: str = field(init=False, default="api_vlm")
    provider: Optional[str] = None
    api_base: Optional[str] = None
    api_key: Optional[str] = None
    reasoning_effort: Optional[str] = None
    capabilities: ClassVar[frozenset[str]] = frozenset(
        {"text", "image", "video", "structured_output"}
    )

    def validate(
        self,
        name: str,
        *,
        known_api_providers: Sequence[str] = (),
        known_api_llm_providers: Sequence[str] = (),
    ) -> None:
        del known_api_llm_providers
        provider = str(self.provider or "").strip()
        if self.reasoning_effort is not None and (
            provider != "bigmodel" or self.reasoning_effort not in {"low", "high", "max"}
        ):
            raise ValueError(f"{name} api_vlm reasoning_effort requires bigmodel and low, high, or max.")
        if not provider:
            raise ValueError(f"{name} is missing provider.")
        if provider not in known_api_providers:
            known = ", ".join(known_api_providers) or "none"
            raise ValueError(
                f"{name} has unsupported provider '{provider}'. "
                f"Known providers: {known}."
            )
        if provider in {
            "openai_compatible",
            "anthropic_compatible",
        } and not str(self.api_base or "").strip():
            raise ValueError(
                f"{name} uses provider {provider} and must set api_base."
            )
        model_name = str(self.model_name or "").strip()
        if (
            provider == "minimax_anthropic"
            and model_name not in _MINIMAX_ANTHROPIC_VLM_MODELS
        ):
            raise ValueError(
                f"{name} has unsupported MiniMax Anthropic-compatible VLM "
                f"model '{model_name}'. Use MiniMax-M3 for image/video input."
            )
        mode = str(self.video_mode or "video_url").strip()
        if mode != "video_url":
            raise ValueError(
                f"{name} has unsupported video_mode '{mode}'. "
                "MVAgent_API supports only video_mode: video_url."
            )
        _validate_api_key(self.api_key, name)

    def to_runtime_config(
        self,
        name: str,
        agent: Agent_Model_Config,
    ) -> ApiVLMConfig:
        return ApiVLMConfig(
            provider=str(self.provider or "openai_compatible"),
            model_name=str(self.model_name or name),
            api_base=self.api_base,
            api_key=self.api_key,
            reasoning_effort=self.reasoning_effort,
            **self._visual_runtime(agent),
        )


@dataclass
class LocalVLLMModelInstanceConfig(ModelInstanceConfig):
    """Parsed ``local_vllm`` model instance."""

    type: str = field(init=False, default="local_vllm")
    startup_timeout_sec: Optional[float] = None
    dtype: Optional[str] = None
    gpu_memory_utilization: Optional[float] = None
    max_model_len: Optional[int] = None
    reasoning_parser: Optional[str] = None
    enable_thinking: Optional[bool] = None
    capabilities: ClassVar[frozenset[str]] = frozenset(
        {"text", "image", "video", "structured_output"}
    )

    def validate(
        self,
        name: str,
        *,
        known_api_providers: Sequence[str] = (),
        known_api_llm_providers: Sequence[str] = (),
    ) -> None:
        del known_api_providers, known_api_llm_providers
        if not str(self.model_name or "").strip():
            raise ValueError(f"{name} must set model_name.")
        mode = str(self.video_mode or "video_url").strip()
        if mode != "video_url":
            raise ValueError(
                f"{name} has unsupported video_mode '{mode}'. "
                "MVAgent supports only video_mode: video_url."
            )
        if self.startup_timeout_sec is not None and float(
            self.startup_timeout_sec
        ) <= 0:
            raise ValueError(f"{name} startup_timeout_sec must be positive.")
        if self.gpu_memory_utilization is not None and not (
            0 < float(self.gpu_memory_utilization) <= 1
        ):
            raise ValueError(
                f"{name} gpu_memory_utilization must be in (0, 1]."
            )
        if self.max_model_len is not None and int(self.max_model_len) <= 0:
            raise ValueError(f"{name} max_model_len must be positive.")

    def to_runtime_config(
        self,
        name: str,
        agent: Agent_Model_Config,
    ) -> LocalVLLMConfig:
        return LocalVLLMConfig(
            model_name=str(self.model_name or name),
            served_model_name=name,
            startup_timeout_sec=float(
                _pick(self.startup_timeout_sec, 1800.0)
            ),
            dtype=str(self.dtype or "bfloat16"),
            gpu_memory_utilization=float(
                _pick(self.gpu_memory_utilization, 0.85)
            ),
            max_model_len=int(_pick(self.max_model_len, 16384)),
            reasoning_parser=(
                str(self.reasoning_parser)
                if self.reasoning_parser
                else None
            ),
            enable_thinking=bool(_pick(self.enable_thinking, False)),
            **self._visual_runtime(agent),
        )


def parse_model_instance_config(
    name: str,
    data: Any,
) -> ModelInstanceConfig:
    """Parse one model section into its backend-specific config class."""
    if not isinstance(data, dict):
        raise ValueError(f"Model instance '{name}' must be a mapping.")
    model_type = str(data.get("type") or "").strip()
    config_class = {
        "api_llm": ApiLLMModelInstanceConfig,
        "api_vlm": ApiModelInstanceConfig,
        "local_vllm": LocalVLLMModelInstanceConfig,
    }.get(model_type)
    if config_class is None:
        raise ValueError(
            f"Model instance '{name}' declares unsupported type "
            f"'{model_type or '<missing>'}'. Use type: api_llm, api_vlm, "
            "or local_vllm."
        )
    if config_class is ApiLLMModelInstanceConfig:
        allowed = {
            item.name
            for item in fields(config_class)
            if item.init
        } | {"type"}
        unknown = sorted(set(data) - allowed)
        if unknown:
            raise ValueError(
                f"Model instance '{name}' has unsupported api_llm fields: "
                + ", ".join(unknown)
            )
    if model_type == "local_vllm" and {"gpus", "endpoint"}.intersection(data):
        raise ValueError("Move local model gpus/endpoint to --execution-config model_pools")
    return config_class.from_dict(data)


__all__ = [
    "ApiLLMConfig",
    "ApiLLMModelInstanceConfig",
    "ApiModelInstanceConfig",
    "ApiVLMConfig",
    "LocalVLLMConfig",
    "LocalVLLMModelInstanceConfig",
    "ModelInstanceConfig",
    "parse_model_instance_config",
]
