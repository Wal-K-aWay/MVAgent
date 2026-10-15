from __future__ import annotations

import json
from typing import Any, Callable

from models.utils import build_chat_messages
from mvagent.utils.tools import extract_json, validate_json_schema


class BaseAgent:
    """Shared text-model decision contract for both Agent layers."""

    def __init__(
        self,
        name: str,
        model: Any,
        system_prompt: str | None = None,
        logger: Callable[[str], None] | None = None,
    ) -> None:
        if model is None:
            raise ValueError(f"{name} requires a language model client.")
        self.name = name
        self.model = model
        self.system_prompt = system_prompt
        self._logger = logger or (lambda message: print(message, flush=True))

    def build_messages(
        self,
        user_prompt: str,
        *,
        system_prompt: str | None = None,
    ) -> list[dict[str, Any]]:
        """Build one request, optionally with a block-specific role."""
        return build_chat_messages(
            self.system_prompt if system_prompt is None else system_prompt,
            user_prompt,
        )

    def decide_json(
        self,
        user_prompt: str,
        *,
        json_schema: dict[str, Any] | None = None,
        schema_name: str | None = None,
        system_prompt: str | None = None,
        model: Any | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Return one ``ok`` or ``invalid`` structured-result dict."""
        raw_response = ""
        decision_model = self.model if model is None else model
        json_chat = getattr(decision_model, "json_chat", None)
        if callable(json_chat):
            result = json_chat(
                messages=self.build_messages(
                    user_prompt,
                    system_prompt=system_prompt,
                ),
                json_schema=json_schema,
                schema_name=schema_name,
                **kwargs,
            )
            if not isinstance(result, dict):
                raise TypeError("json_chat(...) must return a result object.")
            if result.get("status") not in {"ok", "invalid"}:
                raise ValueError(
                    "json_chat(...) result requires status=ok or invalid."
                )
            if result.get("status") == "ok":
                value = result.get("value")
                try:
                    validate_json_schema(value, json_schema)
                    if not isinstance(value, dict):
                        raise ValueError(
                            f"{self.name} structured text response must be "
                            "a JSON object."
                        )
                except (TypeError, ValueError) as exc:
                    return {
                        "status": "invalid",
                        "value": None,
                        "error": (
                            f"{self.name} returned invalid structured "
                            f"output: {exc}"
                        ),
                        "raw_response": (
                            str(result.get("raw_response") or "")
                            or json.dumps(value, ensure_ascii=False, default=str)
                        ),
                    }
            return result
        else:
            chat = getattr(decision_model, "chat", None)
            if not callable(chat):
                raise TypeError(
                    f"{self.name} model client does not implement "
                    "json_chat(...) or chat(...)."
                )
            raw = chat(
                messages=self.build_messages(
                    user_prompt,
                    system_prompt=system_prompt,
                ),
                **kwargs,
            )
            raw_response = str(raw or "")
            try:
                parsed = extract_json(raw)
            except ValueError as exc:
                return {
                    "status": "invalid",
                    "value": None,
                    "error": (
                        f"{self.name} returned invalid structured output: {exc}"
                    ),
                    "raw_response": raw_response,
                }
        try:
            validate_json_schema(parsed, json_schema)
            if not isinstance(parsed, dict):
                raise ValueError(
                    f"{self.name} structured text response must be a JSON object."
                )
        except (TypeError, ValueError) as exc:
            return {
                "status": "invalid",
                "value": None,
                "error": (
                    f"{self.name} returned invalid structured output: {exc}"
                ),
                "raw_response": raw_response,
            }
        return {
            "status": "ok",
            "value": parsed,
            "error": "",
            "raw_response": "",
        }

    def _log(self, message: str) -> None:
        """Write one trace message through the configured logger."""
        self._logger(message)


__all__ = ["BaseAgent"]
