from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from models.execution import emit_event, remaining_timeout
from models.llm.api.client import ApiLLMError, ApiLLMRequest
from models.utils import messages_with_schema_prompt, sanitize_error_excerpt, validate_json_schema


def _strict_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Adapt the existing action unions to the Responses strict subset."""
    schema = dict(schema)
    if "allOf" in schema:
        # Per-video uniqueness uses contains/maxContains; retain the full local check.
        clauses = schema.pop("allOf")
        if not clauses or not all(
            set(item) == {"contains", "minContains", "maxContains"}
            and item["minContains"] == 0 and item["maxContains"] == 1
            for item in clauses
        ):
            raise ApiLLMError("Unsupported allOf in Responses schema.")
    if "anyOf" in schema and schema.get("type") == "object":
        # Agent root properties repeat their complete, action-specific branches.
        fields = set(schema.get("properties", {}))
        if fields not in ({"action", "parameters"}, {"reason", "action", "parameters"}) or not all(
            branch.get("type") == "object"
            and set(branch.get("properties", {})) == fields
            and set(branch.get("required", [])) == fields
            for branch in schema["anyOf"]
        ):
            raise ApiLLMError("Unsupported object union in Responses schema.")
        schema = {"anyOf": schema["anyOf"]}
    if "const" in schema:
        schema["enum"] = [schema.pop("const")]
    if "enum" in schema and "type" not in schema:
        types = {type(v) for v in schema["enum"]}
        if len(types) != 1 or next(iter(types)) not in (str, int, float, bool):
            raise ApiLLMError("Responses schema requires a typed scalar enum.")
        schema["type"] = {str: "string", int: "integer", float: "number", bool: "boolean"}[types.pop()]
    if "properties" in schema:
        if set(schema.get("required", [])) != set(schema["properties"]):
            raise ApiLLMError("Responses strict schema requires every property to be required.")
        schema["additionalProperties"] = False
        schema["properties"] = {key: _strict_schema(value) for key, value in schema["properties"].items()}
    if "items" in schema:
        schema["items"] = _strict_schema(schema["items"])
    if "anyOf" in schema:
        schema["anyOf"] = [_strict_schema(value) for value in schema["anyOf"]]
    return schema


def response_schema(schema: dict[str, Any]) -> dict[str, Any]:
    # OpenAI disallows root anyOf; the wrapper preserves action/parameter coupling.
    return {"type": "object", "additionalProperties": False, "required": ["result"],
            "properties": {"result": _strict_schema(schema)}}


class OpenAIResponsesProvider:
    """Text-only Responses transport with strict schema-constrained output."""

    def __init__(self, cfg: Any) -> None:
        self.cfg = cfg

    def build_payload(self, request: ApiLLMRequest) -> dict[str, Any]:
        messages = request.messages
        if request.json_schema:
            messages = messages_with_schema_prompt(
                messages, json_schema=response_schema(request.json_schema),
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
            payload["text"] = {"format": {
                "type": "json_schema", "name": request.schema_name or "mvagent_response",
                "strict": True, "schema": response_schema(request.json_schema),
            }}
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
            usage=usage, text=text, response_format=(data.get("text") or {}).get("format"),
        )
        if status != "completed" or refused or not text.strip():
            raise ApiLLMError(
                f"Responses API returned no complete usable text (status={status}, refusal={refused})."
            )
        if request.json_schema:
            actual = (data.get("text") or {}).get("format") or {}
            expected = payload["text"]["format"]
            if any(actual.get(key) != expected[key] for key in ("type", "strict", "schema")):
                raise ApiLLMError("Responses API did not confirm the requested strict schema.")
            try:
                wrapped = json.loads(text)
                validate_json_schema(wrapped, payload["text"]["format"]["schema"])
            except ValueError as exc:
                raise ApiLLMError("Responses API violated its strict output schema.") from exc
            text = json.dumps(wrapped["result"], ensure_ascii=False)
        return text


__all__ = ["OpenAIResponsesProvider", "response_schema"]
