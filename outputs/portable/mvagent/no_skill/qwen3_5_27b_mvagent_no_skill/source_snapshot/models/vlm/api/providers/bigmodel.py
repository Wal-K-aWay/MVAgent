"""BigModel JSON mode with the shared client's local schema validation."""
from __future__ import annotations

import json

from models.vlm.api.client import ApiVLMError
from models.vlm.api.providers.openai_compatible import OpenAICompatibleProvider


class BigModelProvider(OpenAICompatibleProvider):
    default_api_base = "https://open.bigmodel.cn/api/paas/v4"

    def build_payload(self, *, messages, json_schema=None, schema_name=None,
                      extra_body=None, **generation):
        reserved = {"thinking", "reasoning_effort", "response_format"}.intersection(extra_body or {})
        if reserved:
            raise ApiVLMError("BigModel extra_body cannot replace core fields: " + ", ".join(sorted(reserved)))
        effort = self.cfg.reasoning_effort
        if effort is not None and effort not in {"low", "high", "max"}:
            raise ApiVLMError("BigModel reasoning_effort must be low, high, or max.")
        messages = list(messages)
        if json_schema:
            # JSON mode guarantees JSON syntax, not schema adherence. Keep the
            # complete contract in the prompt and validate in LLMClient/VLMClient.
            instruction = "Return only a JSON object that satisfies this JSON Schema:\n" + json.dumps(json_schema, ensure_ascii=False)
            messages.insert(0, {"role": "system", "content": instruction})
        payload = super().build_payload(messages=messages, extra_body=extra_body, **generation)
        payload["thinking"] = {"type": "enabled"}
        if effort is not None:
            payload["reasoning_effort"] = effort
        if json_schema:
            payload["response_format"] = {"type": "json_object"}
        return payload
