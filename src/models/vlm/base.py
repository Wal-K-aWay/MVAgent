from __future__ import annotations

from abc import abstractmethod
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional

from models.llm.base import LLMClient
from models.utils import extract_json, validate_json_schema


class VLMClient(LLMClient):
    """Text-model interface extended with image and video input."""

    def __init__(
        self,
        name: str,
        backend_type: str,
        *,
        max_videos_per_request: int = 1,
        max_video_frames_per_request: int = 512,
    ) -> None:
        super().__init__(name=name, backend_type=backend_type)
        self.model_type = "vlm"
        self.max_videos_per_request = int(max_videos_per_request)
        if self.max_videos_per_request <= 0:
            raise ValueError("max_videos_per_request must be positive.")
        self.max_video_frames_per_request = int(
            max_video_frames_per_request
        )
        if self.max_video_frames_per_request <= 0:
            raise ValueError(
                "max_video_frames_per_request must be positive."
            )

    @abstractmethod
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
        """Run one prompt against one or more images."""

    @abstractmethod
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
        """Run one prompt against one clip per video at one shared FPS."""

    def chat_on_video(
        self,
        video_path: str,
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
        video_id: Optional[str] = None,
    ) -> str:
        """Run one prompt against one video."""
        return self.chat_on_videos(
            video_paths={str(video_id or "video"): video_path},
            text_prompt=text_prompt,
            fps=fps,
            min_pixels=min_pixels,
            max_pixels=max_pixels,
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            stop_token_ids=stop_token_ids,
            json_schema=json_schema,
            schema_name=schema_name,
        )

    def json_on_images(
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
    ) -> Dict[str, Any]:
        """Return an ``ok`` or ``invalid`` structured image result."""
        raw = self._multimodal_maybe_structured(
            self.chat_on_images,
            request={
                "image_paths": list(image_paths),
                "text_prompt": text_prompt,
                "system_prompt": system_prompt,
                "temperature": temperature,
                "top_p": top_p,
                "max_tokens": max_tokens,
                "stop_token_ids": stop_token_ids,
            },
            json_schema=json_schema,
            schema_name=schema_name,
        )
        return self._parse_multimodal_json(
            raw=raw,
            response_label="image",
            schema_name=schema_name,
            json_schema=json_schema,
        )

    def json_on_video(
        self,
        video_path: str,
        text_prompt: str,
        system_prompt: Optional[str] = None,
        fps: Optional[float] = None,
        min_pixels: Optional[int] = None,
        max_pixels: Optional[int] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        max_tokens: Optional[int] = None,
        stop_token_ids: Optional[List[int]] = None,
        json_schema: Optional[Dict[str, Any]] = None,
        schema_name: Optional[str] = None,
        video_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Return an ``ok`` or ``invalid`` structured video result."""
        return self.json_on_videos(
            video_paths={str(video_id or "video_1"): video_path},
            text_prompt=text_prompt,
            system_prompt=system_prompt,
            fps=fps,
            min_pixels=min_pixels,
            max_pixels=max_pixels,
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            stop_token_ids=stop_token_ids,
            json_schema=json_schema,
            schema_name=schema_name,
        )

    def json_on_videos(
        self,
        video_paths: Mapping[str, str],
        text_prompt: str,
        system_prompt: Optional[str] = None,
        fps: Optional[float] = None,
        min_pixels: Optional[int] = None,
        max_pixels: Optional[int] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        max_tokens: Optional[int] = None,
        stop_token_ids: Optional[List[int]] = None,
        json_schema: Optional[Dict[str, Any]] = None,
        schema_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Return a structured result for one clip per video."""
        raw = self._multimodal_maybe_structured(
            self.chat_on_videos,
            request={
                "video_paths": {
                    str(video_id): path
                    for video_id, path in video_paths.items()
                },
                "text_prompt": self._with_system_prompt(
                    system_prompt,
                    text_prompt,
                ),
                "fps": fps,
                "min_pixels": min_pixels,
                "max_pixels": max_pixels,
                "temperature": temperature,
                "top_p": top_p,
                "max_tokens": max_tokens,
                "stop_token_ids": stop_token_ids,
            },
            json_schema=json_schema,
            schema_name=schema_name,
        )
        return self._parse_multimodal_json(
            raw=raw,
            response_label="video",
            schema_name=schema_name,
            json_schema=json_schema,
        )

    @classmethod
    def _parse_multimodal_json(
        cls,
        *,
        raw: str,
        response_label: str,
        schema_name: str | None,
        json_schema: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Parse one multimodal response without a hidden retry."""
        try:
            parsed = cls._parse_visual_json_object(
                raw,
                json_schema=json_schema,
                response_label=response_label,
            )
        except ValueError as error:
            from models.execution import emit_event
            emit_event("structured_invalid", schema=schema_name, modality=response_label,
                       attempt="initial", error=str(error))
            return {
                "status": "invalid",
                "value": None,
                "error": f"Invalid structured {response_label} response: {error}",
                "raw_response": raw,
            }
        return {
            "status": "ok",
            "value": parsed,
            "error": "",
            "raw_response": "",
        }

    @staticmethod
    def _multimodal_maybe_structured(
        call: Callable[..., Any],
        *,
        request: Dict[str, Any],
        json_schema: Optional[Dict[str, Any]],
        schema_name: Optional[str],
    ) -> str:
        try:
            value = call(
                **request,
                json_schema=json_schema,
                schema_name=schema_name,
            )
        except (RuntimeError, TypeError) as exc:
            if not json_schema or "unexpected keyword" not in str(exc):
                raise
            value = call(**request)
        return LLMClient._coerce_text(value)

    @staticmethod
    def _parse_visual_json_object(
        raw: str,
        *,
        json_schema: Optional[Dict[str, Any]],
        response_label: str,
    ) -> Dict[str, Any]:
        parsed = extract_json(raw)
        validate_json_schema(parsed, json_schema)
        if not isinstance(parsed, dict):
            raise ValueError(
                f"Structured {response_label} response must be a JSON object."
            )
        return parsed

    @staticmethod
    def _with_system_prompt(
        system_prompt: Optional[str],
        user_prompt: str,
    ) -> str:
        if not system_prompt:
            return user_prompt
        return (
            f"System instructions:\n{system_prompt}\n\n"
            f"User request:\n{user_prompt}"
        )

__all__ = [
    "VLMClient",
]
