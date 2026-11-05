from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from models.execution import emit_event, remaining_timeout
from models.llm.api.client import ApiLLMError, ApiLLMRequest
from models.utils import messages_with_schema_prompt, sanitize_error_excerpt


class OpenAIResponsesProvider:
    """Text-only Responses transport; Agent schemas remain locally validated."""

    def __init__(self, cfg: Any) -> None:
        self.cfg = cfg

    def build_payload(self, request: ApiLLMRequest) -> dict[str, Any]:
        messages = request.messages
        if request.json_schema:
            # Agent action schemas use constraints outside OpenAI's strict subset.
            messages = messages_with_schema_prompt(
                messages, json_schema=request.json_schema,
                schema_name=request.schema_name,
            )
        effort = self.cfg.reasoning_effort or "none"
        payload = {
            "model": self.cfg.model_name,
            "input": messages,
            "store": False,
            "stream": False,
            "max_output_tokens": request.max_tokens,
            "reasoning": {"effort": effort},
        }
        if effort == "none":
            if request.temperature is not None:
                payload["temperature"] = request.temperature
            if request.top_p is not None:
                payload["top_p"] = request.top_p
        if request.json_schema:
            payload["text"] = {"format": {"type": "json_object"}}
        return payload

    def chat(self, request: ApiLLMRequest) -> str:
        payload = self.build_payload(request)
        emit_event("model_request", payload=payload)
        api_base = str(self.cfg.api_base or "https://api.openai.com/v1").rstrip("/")
        http_request = urllib.request.Request(
            f"{api_base}/responses", data=json.dumps(payload).encode("utf-8"),
            headers={
                **self.cfg.http_headers,
                "Authorization": f"Bearer {request.api_key}",
                "Content-Type": "application/json", "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                http_request, timeout=remaining_timeout(self.cfg.timeout_sec),
            ) as response:
                data = json.load(response)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            body = body.replace(request.api_key, "[REDACTED]")
            raise ApiLLMError(
                f"Responses API HTTP {exc.code}: {sanitize_error_excerpt(body)}",
                transient=exc.code == 429 or 500 <= exc.code <= 599,
                status_code=exc.code,
            ) from exc
        except (urllib.error.URLError, OSError) as exc:
            raise ApiLLMError("Responses API transport failed.", transient=True) from exc
        except (ValueError, UnicodeError) as exc:
            raise ApiLLMError("Malformed Responses API JSON.") from exc

        try:
            status = data["status"]
            parts = [part for item in data.get("output", [])
                     if item["type"] == "message"
                     for part in item["content"]]
            text = "".join(part["text"] for part in parts
                           if part["type"] == "output_text")
            refused = any(part["type"] == "refusal" for part in parts)
            usage = dict(data.get("usage") or {})
            for source, target in (("input_tokens", "prompt_tokens"),
                                   ("output_tokens", "completion_tokens"),
                                   ("input_tokens_details", "prompt_tokens_details")):
                if source in usage:
                    usage[target] = usage[source]
        except (KeyError, TypeError, AttributeError, ValueError) as exc:
            raise ApiLLMError("Malformed Responses API output.") from exc
        emit_event(
            "model_response", schema=request.schema_name,
            model=data.get("model"), request_id=data.get("id"),
            finish_reason="stop" if status == "completed" else status,
            usage=usage, text=text,
        )
        if status != "completed" or refused or not text.strip():
            raise ApiLLMError(
                f"Responses API returned no complete usable text (status={status}, refusal={refused})."
            )
        return text


__all__ = ["OpenAIResponsesProvider"]
