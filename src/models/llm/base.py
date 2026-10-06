from __future__ import annotations

from abc import ABC, abstractmethod
import json
from typing import Any, Dict, List, Mapping, Optional

from models.utils import build_chat_messages, extract_json, validate_json_schema


class LLMClient(ABC):
    """Base interface for text generation backends."""

    def __init__(self, name: str, backend_type: str) -> None:
        self.name = name
        self.model_type = "llm"
        self.backend_type = backend_type

    @property
    def identity(self) -> Mapping[str, Any]:
        """Return a stable, credential-free identity for offline experiments."""
        identity: dict[str, Any] = {
            "client": type(self).__qualname__,
            "name": self.name,
            "backend_type": self.backend_type,
        }
        cfg = getattr(self, "cfg", None)
        for field_name in (
            "model_type",
            "provider",
            "model_name",
            "served_model_name",
            "api_base",
            "endpoint",
            "enable_thinking",
            "reasoning_effort",
            "temperature",
            "top_p",
            "max_tokens",
            "stop_token_ids",
            "timeout_sec",
            "max_retries",
        ):
            value = getattr(cfg, field_name, None)
            if value is not None:
                identity[field_name] = list(value) if isinstance(value, list) else value
        return identity

    @abstractmethod
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
        """Run one text chat request."""

    def json_chat(
        self,
        messages: List[Dict[str, Any]],
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        max_tokens: Optional[int] = None,
        stop_token_ids: Optional[List[int]] = None,
        json_schema: Optional[Dict[str, Any]] = None,
        schema_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Return a structured result dict after at most one repair."""
        from models.execution import emit_event
        emit_event("structured_request", schema=schema_name, messages=messages, json_schema=json_schema)
        raw = self._chat_maybe_structured(
            messages=messages,
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            stop_token_ids=stop_token_ids,
            json_schema=json_schema,
            schema_name=schema_name,
        )
        try:
            parsed = self._parse_json_object(raw, json_schema=json_schema)
        except ValueError as exc:
            validation_error = str(exc)
            emit_event("structured_invalid", schema=schema_name, modality="text",
                       attempt="initial", error=validation_error)
        else:
            return {
                "status": "ok",
                "value": parsed,
                "error": "",
                "raw_response": "",
            }

        emit_event("structured_repair", schema=schema_name, error=validation_error, raw=raw)
        repaired = self._chat_maybe_structured(
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Repair the previous response so it satisfies the original "
                        "request and the required JSON Schema. Preserve identifiers "
                        "and constraints from the original request. Return the "
                        "smallest complete object: condense free-text fields instead "
                        "of continuing or repeating the previous analysis. Return "
                        "JSON only.\n\n"
                        "Original request:\n"
                        f"{json.dumps(messages, ensure_ascii=False, default=str)}\n\n"
                        "Required JSON Schema:\n"
                        f"{json.dumps(json_schema or {}, ensure_ascii=False)}\n\n"
                        "Validation error:\n"
                        f"{validation_error}\n\n"
                        "Previous response:\n"
                        f"{raw}"
                    ),
                }
            ],
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            stop_token_ids=stop_token_ids,
            json_schema=json_schema,
            schema_name=schema_name,
        )
        try:
            parsed = self._parse_json_object(
                repaired,
                json_schema=json_schema,
            )
        except ValueError as exc:
            emit_event("structured_invalid", schema=schema_name, modality="text",
                       attempt="repair", error=str(exc))
            label = str(schema_name or "structured_response")
            return {
                "status": "invalid",
                "value": None,
                "error": (
                    f"Model '{self.name}' returned invalid structured output "
                    f"for schema '{label}' after one repair: {exc}"
                ),
                "raw_response": repaired,
            }
        emit_event("structured_repair_succeeded", schema=schema_name)
        return {
            "status": "ok",
            "value": parsed,
            "error": "",
            "raw_response": "",
        }

    def json_prompt(
        self,
        prompt: str,
        *,
        json_schema: Optional[Dict[str, Any]] = None,
        schema_name: Optional[str] = None,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        max_tokens: Optional[int] = None,
        stop_token_ids: Optional[List[int]] = None,
    ) -> Dict[str, Any]:
        """Run one plain Prompt through the shared structured-text interface."""
        return self.json_chat(
            messages=self._build_messages(system_prompt, str(prompt)),
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            stop_token_ids=stop_token_ids,
            json_schema=json_schema,
            schema_name=schema_name,
        )

    def _chat_maybe_structured(
        self,
        *,
        messages: List[Dict[str, Any]],
        temperature: Optional[float],
        top_p: Optional[float],
        max_tokens: Optional[int],
        stop_token_ids: Optional[List[int]],
        json_schema: Optional[Dict[str, Any]],
        schema_name: Optional[str],
    ) -> str:
        try:
            return self.chat(
                messages=messages,
                temperature=temperature,
                top_p=top_p,
                max_tokens=max_tokens,
                stop_token_ids=stop_token_ids,
                json_schema=json_schema,
                schema_name=schema_name,
            )
        except (RuntimeError, TypeError) as exc:
            if not json_schema or "unexpected keyword" not in str(exc):
                raise
            return self.chat(
                messages=messages,
                temperature=temperature,
                top_p=top_p,
                max_tokens=max_tokens,
                stop_token_ids=stop_token_ids,
            )

    @staticmethod
    def _parse_json_object(
        raw: str,
        *,
        json_schema: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        parsed = extract_json(raw)
        validate_json_schema(parsed, json_schema)
        if not isinstance(parsed, dict):
            raise ValueError("Structured response must be a JSON object.")
        from models.execution import emit_event
        emit_event("structured_parsed", value=parsed)
        return parsed

    @staticmethod
    def _build_messages(
        system_prompt: Optional[str],
        user_prompt: str,
    ) -> List[Dict[str, Any]]:
        return build_chat_messages(system_prompt, user_prompt)

    @staticmethod
    def _coerce_text(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        return str(value).strip()

    @staticmethod
    def resolve_generation_params(
        *,
        temperature: float,
        top_p: float,
        max_tokens: int,
        stop_token_ids: Optional[List[int]],
    ) -> Dict[str, Any]:
        return {
            "temperature": temperature,
            "top_p": top_p,
            "max_tokens": max_tokens,
            "stop_token_ids": (
                list(stop_token_ids)
                if stop_token_ids is not None
                else None
            ),
        }

    def close(self) -> None:
        """Release backend resources when supported."""

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}(name={self.name}, "
            f"type={self.model_type}, backend={self.backend_type})"
        )

    def __str__(self) -> str:
        return self.__repr__()


__all__ = [
    "LLMClient",
]
