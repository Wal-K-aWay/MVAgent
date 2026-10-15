from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Dict

from models.execution import emit_event
from models.utils import messages_with_schema_prompt, sanitize_error_excerpt
from models.llm.api.client import ApiLLMError, ApiLLMRequest


_DEFAULT_API_BASE = "https://api.deepseek.com"


class DeepSeekProvider:
    """DeepSeek OpenAI ChatCompletions provider for pure-text models."""

    def __init__(self, cfg: Any) -> None:
        self.cfg = cfg

    def build_payload(self, request: ApiLLMRequest) -> Dict[str, Any]:
        messages = [dict(message) for message in request.messages]
        if request.json_schema:
            messages = messages_with_schema_prompt(
                messages,
                json_schema=request.json_schema,
                schema_name=request.schema_name,
            )
        payload: Dict[str, Any] = {
            "model": self.cfg.model_name,
            "messages": messages,
            "max_tokens": request.max_tokens,
            "stream": False,
            "thinking": {
                "type": (
                    "enabled"
                    if self.cfg.enable_thinking
                    else "disabled"
                )
            },
        }
        if self.cfg.enable_thinking:
            if self.cfg.reasoning_effort:
                payload["reasoning_effort"] = self.cfg.reasoning_effort
        else:
            if request.temperature is not None:
                payload["temperature"] = request.temperature
            if request.top_p is not None:
                payload["top_p"] = request.top_p
        if request.json_schema:
            payload["response_format"] = {"type": "json_object"}
        return payload

    def chat(self, request: ApiLLMRequest) -> str:
        payload = self.build_payload(request)
        api_base = str(self.cfg.api_base or _DEFAULT_API_BASE).rstrip("/")
        endpoint = f"{api_base}/chat/completions"
        http_request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {request.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                http_request,
                timeout=self.cfg.timeout_sec,
            ) as response:
                response_body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            transient = exc.code == 429 or 500 <= exc.code <= 599
            raise ApiLLMError(
                "DeepSeek API request failed with HTTP "
                f"{exc.code} for model {self.cfg.model_name}: "
                f"{sanitize_error_excerpt(error_body)}",
                transient=transient,
                status_code=exc.code,
            ) from exc
        except (urllib.error.URLError, OSError) as exc:
            raise ApiLLMError(
                "DeepSeek API transport failed for model "
                f"{self.cfg.model_name}: {exc}",
                transient=True,
            ) from exc

        try:
            data = json.loads(response_body)
            content = data["choices"][0]["message"]["content"]
        except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
            raise ApiLLMError(
                "Malformed DeepSeek API response for model "
                f"{self.cfg.model_name}."
            ) from exc
        emit_event("model_response", schema=request.schema_name,
                   model=data.get("model"), request_id=data.get("id"),
                   finish_reason=data["choices"][0].get("finish_reason"),
                   usage=data.get("usage"), text=content)
        return str(content or "")


__all__ = ["DeepSeekProvider"]
