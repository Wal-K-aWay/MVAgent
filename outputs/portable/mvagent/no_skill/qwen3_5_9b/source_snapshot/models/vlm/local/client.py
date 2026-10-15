from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, Iterable, List, Mapping, Optional

from models.vlm.api.client import ApiVLMClient
from models.vlm.base import VLMClient

from .service import VLLMServiceManager, VLLMServiceStatus


def _vllm_generation_schema(
    json_schema: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Copy a schema while omitting constraints unsupported by vLLM 0.18.0."""
    if json_schema is None:
        return None

    def normalize(value: Any, *, root: bool = False) -> Any:
        if isinstance(value, dict):
            return {
                key: normalize(item)
                for key, item in value.items()
                if key != "uniqueItems" and not (root and key == "oneOf")
            }
        if isinstance(value, list):
            return [normalize(item) for item in value]
        return value

    return normalize(json_schema, root=True)


class LocalVLLMClient(VLMClient):
    """VLM client that reaches a reusable local vLLM OpenAI-compatible server."""

    def __init__(self, cfg: Any, *, cache_dir: str) -> None:
        super().__init__(
            name=cfg.served_model_name,
            backend_type="local_vllm",
            max_videos_per_request=cfg.max_videos_per_request,
            max_video_frames_per_request=(
                cfg.max_video_frames_per_request
            ),
        )
        self.cfg = cfg
        self.service_manager = VLLMServiceManager(cfg, cache_dir=cache_dir)
        self.service_status: VLLMServiceStatus = self.service_manager.ensure_running()
        self.api_client = ApiVLMClient(
            SimpleNamespace(
                model_type="api_vlm",
                provider="openai_compatible",
                model_name=cfg.served_model_name,
                api_base=cfg.endpoint,
                api_key="EMPTY",
                temperature=cfg.temperature,
                top_p=cfg.top_p,
                max_tokens=cfg.max_tokens,
                stop_token_ids=list(cfg.stop_token_ids),
                max_videos_per_request=cfg.max_videos_per_request,
                max_video_frames_per_request=(
                    cfg.max_video_frames_per_request
                ),
                video_mode=cfg.video_mode,
                video_fps=cfg.video_fps,
                video_fps_transport="media_io_kwargs",
                video_min_pixels=cfg.video_min_pixels,
                video_max_pixels=cfg.video_max_pixels,
                timeout_sec=cfg.timeout_sec,
                max_retries=cfg.max_retries,
            )
        )

    def runtime_status(self) -> dict[str, str]:
        if hasattr(self.service_status, "to_dict"):
            return self.service_status.to_dict()
        return {
            "status": str(self.service_status.state),
            "endpoint": str(self.service_status.endpoint),
            "model": str(self.service_status.served_model_name),
        }

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
        return self.api_client.chat(
            messages=messages,
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            stop_token_ids=stop_token_ids,
            json_schema=_vllm_generation_schema(json_schema),
            schema_name=schema_name,
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
        return self.api_client.chat_on_images(
            image_paths=image_paths,
            text_prompt=text_prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            stop_token_ids=stop_token_ids,
            json_schema=_vllm_generation_schema(json_schema),
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
        return self.api_client.chat_on_videos(
            video_paths=video_paths,
            text_prompt=text_prompt,
            fps=fps,
            min_pixels=min_pixels,
            max_pixels=max_pixels,
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            stop_token_ids=stop_token_ids,
            json_schema=_vllm_generation_schema(json_schema),
            schema_name=schema_name,
        )

    def close(self) -> None:
        self.api_client.close()
        self.service_manager.close()


__all__ = ["LocalVLLMClient"]
