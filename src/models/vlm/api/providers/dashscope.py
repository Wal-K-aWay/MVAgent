from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from models.vlm.api.client import ApiVLMError, ApiVLMRequest
from models.utils import resolve_local_path


class DashScopeProvider:
    """DashScope SDK-backed VLM provider."""

    supported_video_modes = {"video_url"}

    def __init__(self, cfg: Any) -> None:
        self.cfg = cfg

    def prepare_video_url(self, video_path: str) -> str:
        raw_path = str(video_path)
        if raw_path.startswith(("http://", "https://", "data:", "file://")):
            return raw_path
        return f"file://{Path(resolve_local_path(raw_path)).resolve()}"

    def chat(self, request: ApiVLMRequest) -> str:
        return self._chat_with_sdk(request)

    def _chat_with_sdk(self, request: ApiVLMRequest) -> str:
        try:
            import dashscope
            from dashscope import MultiModalConversation
        except ModuleNotFoundError as exc:
            raise ApiVLMError(
                "DashScope SDK is required for local video file input; install the optional dependency 'dashscope'."
            ) from exc

        api_base = str(getattr(self.cfg, "api_base", "") or "").strip()
        if api_base:
            dashscope.base_http_api_url = api_base.rstrip("/")

        try:
            kwargs: Dict[str, Any] = {}
            if request.json_schema:
                kwargs["response_format"] = {"type": "json_object"}
            response = MultiModalConversation.call(
                api_key=request.api_key,
                model=self.cfg.model_name,
                messages=[self._sdk_message(message) for message in request.messages],
                temperature=request.temperature,
                top_p=request.top_p,
                max_tokens=request.max_tokens,
                **kwargs,
            )
        except Exception as exc:
            raise ApiVLMError(
                f"DashScope SDK request failed for model {self.cfg.model_name}: {exc}",
                transient=True,
            ) from exc
        return self._extract_sdk_text(response)

    def _sdk_message(self, message: Dict[str, Any]) -> Dict[str, Any]:
        content = message.get("content", "")
        if isinstance(content, list):
            content = [self._sdk_content_item(item) for item in content]
        elif isinstance(content, str):
            content = [{"text": content}]
        return {
            "role": str(message.get("role", "user")),
            "content": content,
        }

    @staticmethod
    def _sdk_content_item(item: Dict[str, Any]) -> Dict[str, Any]:
        item_type = item.get("type")
        if item_type == "text":
            return {"text": str(item.get("text", ""))}
        if item_type == "video_url":
            video_url = item.get("video_url")
            if isinstance(video_url, dict):
                video_url = video_url.get("url")
            if not video_url:
                raise ApiVLMError("DashScope video content item is missing a video URL")
            content_item: Dict[str, Any] = {"video": str(video_url)}
            if item.get("fps") is not None:
                content_item["fps"] = item.get("fps")
            return content_item
        if item_type == "image_url":
            image_url = item.get("image_url")
            if isinstance(image_url, dict):
                image_url = image_url.get("url")
            if not image_url:
                raise ApiVLMError("DashScope image content item is missing an image URL")
            return {"image": str(image_url)}
        if item_type == "image":
            image = item.get("image")
            if image is None:
                raise ApiVLMError("DashScope image content item is missing an image path")
            return {"image": str(image)}
        if "text" in item:
            return {"text": str(item.get("text", ""))}
        if "video" in item:
            return dict(item)
        if "image" in item:
            return dict(item)
        raise ApiVLMError(f"Unsupported DashScope content item type: {item_type}")

    @classmethod
    def _extract_sdk_text(cls, response: Any) -> str:
        output = cls._get(response, "output")
        choices = cls._get(output, "choices") if output is not None else None
        if not choices:
            raise ApiVLMError("Malformed DashScope SDK response: missing output.choices")
        message = cls._get(choices[0], "message")
        content = cls._get(message, "content") if message is not None else None
        if isinstance(content, list):
            text_parts = []
            for item in content:
                if isinstance(item, dict) and "text" in item:
                    text_parts.append(str(item.get("text", "")))
                elif isinstance(item, str):
                    text_parts.append(item)
            return "".join(text_parts).strip()
        if content is not None:
            return str(content).strip()
        text = cls._get(message, "content") or cls._get(message, "text")
        return str(text or "").strip()

    @staticmethod
    def _get(value: Any, key: str) -> Any:
        if isinstance(value, dict):
            return value.get(key)
        return getattr(value, key, None)


__all__ = [
    "DashScopeProvider",
]
