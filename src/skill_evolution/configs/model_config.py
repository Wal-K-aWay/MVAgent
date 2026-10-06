from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class EvolutionModelConfig:
    """Reference one named shared model with optional generation overrides."""

    model_type: str
    temperature: float | None = None
    max_tokens: int | None = None

    def __post_init__(self) -> None:
        model_type = str(self.model_type or "").strip()
        if not model_type:
            raise ValueError("Skill evolution model_type must be non-empty.")
        object.__setattr__(self, "model_type", model_type)
        if self.temperature is not None and (
            isinstance(self.temperature, bool)
            or not isinstance(self.temperature, (int, float))
            or not math.isfinite(float(self.temperature))
            or float(self.temperature) < 0.0
        ):
            raise ValueError(
                "Skill evolution model temperature must be finite and non-negative."
            )
        if self.max_tokens is not None and (
            isinstance(self.max_tokens, bool)
            or not isinstance(self.max_tokens, int)
            or self.max_tokens <= 0
        ):
            raise ValueError("Skill evolution model max_tokens must be positive.")

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, Any],
        *,
        field_name: str,
    ) -> "EvolutionModelConfig":
        if not isinstance(data, Mapping):
            raise ValueError(f"{field_name} must be a mapping.")
        unknown = set(data) - {"model_type", "temperature", "max_tokens"}
        if unknown:
            raise ValueError(
                f"{field_name} contains unknown fields: "
                + ", ".join(sorted(str(item) for item in unknown))
            )
        return cls(
            model_type=str(data.get("model_type") or ""),
            temperature=data.get("temperature"),
            max_tokens=data.get("max_tokens"),
        )

    def to_dict(self, mask_api_key: bool = True) -> dict[str, Any]:
        del mask_api_key
        payload: dict[str, Any] = {"model_type": self.model_type}
        if self.temperature is not None:
            payload["temperature"] = self.temperature
        if self.max_tokens is not None:
            payload["max_tokens"] = self.max_tokens
        return payload


__all__ = ["EvolutionModelConfig"]
