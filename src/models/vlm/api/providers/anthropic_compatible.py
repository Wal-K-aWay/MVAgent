from __future__ import annotations

from typing import Any, Dict

from models.llm.api.providers.anthropic import (
    MINIMAX_ANTHROPIC_API_BASE,
    AnthropicCompatibleProvider,
)
from models.vlm.api.client import ApiVLMError
from models.vlm.api.providers.media import (
    image_to_data_url,
    local_media_to_data_url,
    parse_data_url,
)


def _source_from_value(
    value: str,
    *,
    default_mime: str,
) -> dict[str, str]:
    source = str(value or "").strip()
    if not source:
        raise ApiVLMError("Anthropic-compatible media item is empty.")
    if source.startswith(("http://", "https://", "mm_file://")):
        return {"type": "url", "url": source}
    if source.startswith("data:"):
        parsed = parse_data_url(source)
    else:
        parsed = parse_data_url(
            local_media_to_data_url(source, default_mime=default_mime)
        )
    if parsed is None:
        raise ApiVLMError("Anthropic-compatible media item cannot be encoded.")
    media_type, encoded = parsed
    return {
        "type": "base64",
        "media_type": media_type,
        "data": encoded,
    }


class AnthropicCompatibleVLMProvider(AnthropicCompatibleProvider):
    """Anthropic Messages-compatible provider for text, image, and video input."""

    error_class = ApiVLMError
    provider_kind_label = "API VLM"
    supported_video_modes = {"video_url"}

    def prepare_video_url(self, video_path: str) -> str:
        raw_path = str(video_path)
        if raw_path.startswith(("http://", "https://", "data:", "mm_file://")):
            return raw_path
        return raw_path

    def _content_item(self, item: Dict[str, Any]) -> Dict[str, Any]:
        item_type = item.get("type")
        if item_type == "text" or "text" in item:
            return {"type": "text", "text": str(item.get("text", ""))}
        if item_type in {"image", "video"} and isinstance(item.get("source"), dict):
            return dict(item)
        if item_type == "image":
            image = item.get("image")
            if image is None:
                raise ApiVLMError("Anthropic-compatible image item is missing a path.")
            data_url = image_to_data_url(
                str(image),
                min_pixels=self.cfg.video_min_pixels,
                max_pixels=self.cfg.video_max_pixels,
                provider=self.cfg.provider,
                model=self.cfg.model_name,
            )
            return {
                "type": "image",
                "source": _source_from_value(
                    data_url,
                    default_mime="image/png",
                ),
            }
        if item_type == "image_url":
            image_url = item.get("image_url")
            if isinstance(image_url, dict):
                image_url = image_url.get("url")
            if not image_url:
                raise ApiVLMError("Anthropic-compatible image_url item is missing a URL.")
            return {
                "type": "image",
                "source": _source_from_value(
                    str(image_url),
                    default_mime="image/png",
                ),
            }
        if item_type == "video_url":
            video_url = item.get("video_url")
            if isinstance(video_url, dict):
                video_url = video_url.get("url")
            if not video_url:
                raise ApiVLMError("Anthropic-compatible video item is missing a URL.")
            return {
                "type": "video",
                "source": _source_from_value(
                    str(video_url),
                    default_mime="video/mp4",
                ),
            }
        raise ApiVLMError(
            f"Unsupported Anthropic-compatible content item type: {item_type}"
        )


class MiniMaxAnthropicVLMProvider(AnthropicCompatibleVLMProvider):
    """MiniMax Anthropic-compatible VLM provider."""

    default_api_base = MINIMAX_ANTHROPIC_API_BASE


__all__ = [
    "AnthropicCompatibleVLMProvider",
    "MiniMaxAnthropicVLMProvider",
]
