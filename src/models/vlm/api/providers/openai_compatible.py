from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List

from models.utils import is_loopback_host, sanitize_error_excerpt
from models.vlm.api.client import ApiVLMError, ApiVLMRequest
from models.vlm.api.providers.media import image_to_data_url


def _is_loopback_endpoint(url: str) -> bool:
    return is_loopback_host(urllib.parse.urlparse(url).hostname)


class OpenAICompatibleProvider:
    default_api_base: str | None = None
    supported_video_modes = {"video_url"}

    def __init__(self, cfg: Any) -> None:
        self.cfg = cfg

    def _content_item(self, item: Dict[str, Any]) -> Dict[str, Any]:
        item_type = item.get("type")
        if item_type == "text":
            return {"type": "text", "text": str(item.get("text", ""))}
        if item_type == "image":
            image = item.get("image")
            if image is None:
                raise ApiVLMError("Image content item is missing an image path")
            return {
                "type": "image_url",
                "image_url": {
                    "url": image_to_data_url(
                        str(image),
                        min_pixels=self.cfg.video_min_pixels,
                        max_pixels=self.cfg.video_max_pixels,
                        provider=self.cfg.provider,
                        model=self.cfg.model_name,
                    )
                },
            }
        if item_type == "image_url":
            return dict(item)
        if item_type == "video_url":
            video_url = item.get("video_url")
            if isinstance(video_url, str):
                video_url = {"url": video_url}
            if not isinstance(video_url, dict) or not video_url.get("url"):
                raise ApiVLMError("Video content item is missing a video_url.url value")
            content_item: Dict[str, Any] = {
                "type": "video_url",
                "video_url": {"url": str(video_url.get("url"))},
            }
            if item.get("fps") is not None:
                content_item["fps"] = item.get("fps")
            return content_item
        raise ApiVLMError(f"Unsupported OpenAI-compatible content item type: {item_type}")

    def _message(self, message: Dict[str, Any]) -> Dict[str, Any]:
        content = message.get("content", "")
        if isinstance(content, list):
            content = [self._content_item(item) for item in content]
        return {
            "role": str(message.get("role", "user")),
            "content": content,
        }

    def build_payload(
        self,
        *,
        messages: List[Dict[str, Any]],
        temperature: float,
        top_p: float,
        max_tokens: int,
        json_schema: Dict[str, Any] | None = None,
        schema_name: str | None = None,
        extra_body: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "model": self.cfg.model_name,
            "messages": [self._message(message) for message in messages],
            "temperature": temperature,
            "top_p": top_p,
            "max_tokens": max_tokens,
        }
        if json_schema:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": str(schema_name or "mvagent_response"),
                    "schema": json_schema,
                    "strict": True,
                },
            }
        extra_body = dict(extra_body or {})
        reserved = set(payload).intersection(extra_body)
        if reserved:
            raise ApiVLMError(
                "OpenAI-compatible extra_body cannot replace core fields: "
                + ", ".join(sorted(reserved))
            )
        payload.update(extra_body)
        return payload

    def _endpoint(self) -> str:
        api_base = str(self.cfg.api_base or self.default_api_base or "").strip()
        if not api_base:
            raise ApiVLMError("api_base is required for OpenAI-compatible API VLM providers")
        return f"{api_base.rstrip('/')}/chat/completions"

    def chat(self, request: ApiVLMRequest) -> str:
        payload = self.build_payload(
            messages=request.messages,
            temperature=request.temperature,
            top_p=request.top_p,
            max_tokens=request.max_tokens,
            json_schema=request.json_schema,
            schema_name=request.schema_name,
            extra_body=request.extra_body,
        )
        body = json.dumps(payload).encode("utf-8")
        endpoint = self._endpoint()
        http_request = urllib.request.Request(
            endpoint,
            data=body,
            headers={
                "Authorization": f"Bearer {request.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )

        try:
            if _is_loopback_endpoint(endpoint):
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                response_handle = opener.open(http_request, timeout=self.cfg.timeout_sec)
            else:
                response_handle = urllib.request.urlopen(http_request, timeout=self.cfg.timeout_sec)
            with response_handle as response:
                response_body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            transient = exc.code == 429 or 500 <= exc.code <= 599
            excerpt = sanitize_error_excerpt(error_body)
            raise ApiVLMError(
                (
                    f"API VLM request failed with HTTP {exc.code} "
                    f"from provider {self.cfg.provider} model {self.cfg.model_name}: {excerpt}"
                ),
                transient=transient,
                status_code=exc.code,
            ) from exc
        except (urllib.error.URLError, OSError) as exc:
            raise ApiVLMError(
                f"API VLM transport failed for provider {self.cfg.provider} model {self.cfg.model_name}: {exc}",
                transient=True,
            ) from exc

        try:
            data = json.loads(response_body)
            content = data["choices"][0]["message"]["content"]
        except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
            raise ApiVLMError(
                f"Malformed API VLM response from provider {self.cfg.provider} model {self.cfg.model_name}"
            ) from exc

        if isinstance(content, list):
            text_parts: List[str] = []
            for item in content:
                if isinstance(item, dict):
                    if item.get("type") == "text" or "text" in item:
                        text_parts.append(str(item.get("text", "")))
                elif isinstance(item, str):
                    text_parts.append(item)
            return "".join(text_parts)
        return str(content)


__all__ = [
    "OpenAICompatibleProvider",
]
