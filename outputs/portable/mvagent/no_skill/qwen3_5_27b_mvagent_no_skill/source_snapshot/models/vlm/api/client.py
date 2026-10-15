from __future__ import annotations

from models.pool import media_preparation_slot
import base64
import mimetypes
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Protocol

from models.utils import (
    ProviderRegistry,
    resolve_api_key,
    resolve_local_path,
    retry_transient,
)
from models.vlm.base import VLMClient
from models.execution import emit_event


class ApiVLMError(RuntimeError):
    """Raised when an API VLM request cannot be completed."""

    def __init__(self, message: str, *, transient: bool = False, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.transient = transient
        self.status_code = status_code


@dataclass(frozen=True)
class ApiVLMRequest:
    cfg: Any
    messages: List[Dict[str, Any]]
    api_key: str
    temperature: float
    top_p: float
    max_tokens: int
    json_schema: Optional[Dict[str, Any]] = None
    schema_name: Optional[str] = None
    extra_body: Dict[str, Any] = field(default_factory=dict)


class ApiVLMProvider(Protocol):
    supported_video_modes: set[str]

    def __init__(self, cfg: Any) -> None:
        ...

    def chat(self, request: ApiVLMRequest) -> str:
        ...


_ProviderFactory = Callable[[Any], ApiVLMProvider]
_VLM_PROVIDERS = ProviderRegistry[ApiVLMProvider](
    label="API VLM",
    error_class=ApiVLMError,
)


def register_api_vlm_provider(name: str, provider: _ProviderFactory) -> None:
    _VLM_PROVIDERS.register(name, provider)


def available_api_vlm_providers() -> List[str]:
    return _VLM_PROVIDERS.available()


def _video_url_for_request(video_path: str) -> str:
    raw_path = str(video_path)
    if raw_path.startswith(("http://", "https://", "data:")):
        return raw_path

    started_at = time.time()
    started = time.monotonic()
    resolved_path = Path(resolve_local_path(raw_path))
    mime_type = mimetypes.guess_type(str(resolved_path))[0] or "video/mp4"
    if not mime_type.startswith("video/"):
        mime_type = "video/mp4"
    data = resolved_path.read_bytes()
    read_seconds = time.monotonic() - started
    encoding = time.monotonic()
    encoded = base64.b64encode(data).decode("ascii")
    emit_event("media_payload", started_at=started_at, seconds=time.monotonic() - started,
               read_seconds=read_seconds, base64_seconds=time.monotonic() - encoding,
               source_bytes=len(data))
    return f"data:{mime_type};base64,{encoded}"


class ApiVLMClient(VLMClient):
    """VLM client backed by a remote OpenAI-compatible multimodal chat API."""

    def __init__(self, cfg: Any) -> None:
        super().__init__(
            name=cfg.model_name or cfg.model_type,
            backend_type="api",
            max_videos_per_request=cfg.max_videos_per_request,
            max_video_frames_per_request=(
                cfg.max_video_frames_per_request
            ),
        )
        self.cfg = cfg
        self.api_key = resolve_api_key(
            cfg.api_key,
            error_class=ApiVLMError,
            label="API VLM clients",
        )

        provider_name = str(cfg.provider or "").strip()
        self.provider = _VLM_PROVIDERS.get(provider_name)(cfg)

    def chat(
        self,
        messages: List[Dict[str, Any]],
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        max_tokens: Optional[int] = None,
        stop_token_ids: Optional[List[int]] = None,
        json_schema: Optional[Dict[str, Any]] = None,
        schema_name: Optional[str] = None,
        extra_body: Optional[Dict[str, Any]] = None,
    ) -> str:
        del stop_token_ids
        request = ApiVLMRequest(
            cfg=self.cfg,
            messages=messages,
            api_key=self.api_key,
            temperature=self.cfg.temperature if temperature is None else temperature,
            top_p=self.cfg.top_p if top_p is None else top_p,
            max_tokens=self.cfg.max_tokens if max_tokens is None else max_tokens,
            json_schema=json_schema,
            schema_name=schema_name,
            extra_body=dict(extra_body or {}),
        )

        return retry_transient(
            lambda: self.provider.chat(request),
            attempts=self.cfg.max_retries,
            error_class=ApiVLMError,
            label="API VLM",
        )

    def chat_on_images(
        self,
        image_paths: Iterable[str],
        text_prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        max_tokens: Optional[int] = None,
        stop_token_ids: Optional[List[int]] = None,
        json_schema: Optional[Dict[str, Any]] = None,
        schema_name: Optional[str] = None,
    ) -> str:
        content: List[Dict[str, Any]] = [{"type": "image", "image": str(image_path)} for image_path in image_paths]
        content.append({"type": "text", "text": text_prompt})

        messages: List[Dict[str, Any]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": content})

        return self.chat(
            messages=messages,
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            stop_token_ids=stop_token_ids,
            json_schema=json_schema,
            schema_name=schema_name,
        )

    def chat_on_videos(
        self,
        video_paths: Mapping[str, str],
        text_prompt: str,
        fps: Optional[float] = None,
        min_pixels: Optional[int] = None,
        max_pixels: Optional[int] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        max_tokens: Optional[int] = None,
        stop_token_ids: Optional[List[int]] = None,
        json_schema: Optional[Dict[str, Any]] = None,
        schema_name: Optional[str] = None,
    ) -> str:
        del min_pixels, max_pixels
        video_mode = str(self.cfg.video_mode or "").strip()
        if video_mode != "video_url":
            raise ApiVLMError(f"Unsupported API VLM video_mode '{video_mode}'; only 'video_url' is supported")
        if video_mode not in self.provider.supported_video_modes:
            raise ApiVLMError(f"Provider '{self.cfg.provider}' does not support video_mode '{video_mode}'")

        inputs: list[tuple[str, str]] = []
        for raw_video_id, raw_path in video_paths.items():
            video_id = str(raw_video_id).strip()
            if not video_id:
                raise ApiVLMError("Video IDs must be non-empty")
            if not isinstance(raw_path, str):
                raise ApiVLMError(
                    f"Video '{video_id}' clip path must be a string"
                )
            path = raw_path.strip()
            if not path:
                raise ApiVLMError(
                    f"Video '{video_id}' requires one non-empty clip path"
                )
            inputs.append((video_id, path))
        if not inputs:
            raise ApiVLMError("A video request requires at least one video")
        if len(inputs) > self.max_videos_per_request:
            raise ApiVLMError(
                f"Video request contains {len(inputs)} inputs; model limit is "
                f"{self.max_videos_per_request}"
            )
        with media_preparation_slot():
            prepare_video_url = getattr(self.provider, "prepare_video_url", None)
            video_items: list[tuple[str, Dict[str, Any]]] = []
            for video_id, video_path in inputs:
                video_url = (
                    prepare_video_url(video_path)
                    if callable(prepare_video_url)
                    else _video_url_for_request(video_path)
                )
                video_items.append(
                    (
                        video_id,
                        {
                            "type": "video_url",
                            "video_url": {"url": video_url},
                        },
                    )
                )
            resolved_fps = self.cfg.video_fps if fps is None else fps
            extra_body: Dict[str, Any] = {}
            if resolved_fps is not None:
                if self.cfg.video_fps_transport == "content":
                    for _, video_item in video_items:
                        video_item["fps"] = resolved_fps
                elif self.cfg.video_fps_transport == "media_io_kwargs":
                    extra_body = {
                        "media_io_kwargs": {
                            "video": {"fps": resolved_fps},
                        }
                    }
                else:
                    raise ApiVLMError(
                        f"Unsupported video FPS transport: {self.cfg.video_fps_transport}"
                    )
            content: List[Dict[str, Any]] = []
            for video_id, video_item in video_items:
                content.append(
                    {"type": "text", "text": f"This is {video_id}"}
                )
                content.append(video_item)
            content.append({"type": "text", "text": text_prompt})
            messages = [
                {
                    "role": "user",
                    "content": content,
                }
            ]
            return self.chat(
                messages=messages,
                temperature=temperature,
                top_p=top_p,
                max_tokens=max_tokens,
                stop_token_ids=stop_token_ids,
                json_schema=json_schema,
                schema_name=schema_name,
                extra_body=extra_body,
            )



from .providers.dashscope import DashScopeProvider
from .providers.anthropic_compatible import (
    AnthropicCompatibleVLMProvider,
    MiniMaxAnthropicVLMProvider,
)
from .providers.openai_compatible import OpenAICompatibleProvider
from .providers.bigmodel import BigModelProvider


register_api_vlm_provider(
    "anthropic_compatible",
    AnthropicCompatibleVLMProvider,
)
register_api_vlm_provider("dashscope", DashScopeProvider)
register_api_vlm_provider("minimax_anthropic", MiniMaxAnthropicVLMProvider)
register_api_vlm_provider("openai_compatible", OpenAICompatibleProvider)
register_api_vlm_provider("bigmodel", BigModelProvider)


__all__ = [
    "ApiVLMClient",
    "ApiVLMError",
    "ApiVLMProvider",
    "ApiVLMRequest",
    "available_api_vlm_providers",
    "register_api_vlm_provider",
]
