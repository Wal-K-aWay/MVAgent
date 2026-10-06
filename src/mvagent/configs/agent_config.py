from __future__ import annotations

import math

from dataclasses import dataclass, field
from typing import Any, Dict, Optional
from models.embeddings import EmbeddingConfig


@dataclass(frozen=True)
class Skill_Config:
    """Hash-pinned static Markdown or dynamic Skill bank reference."""

    enabled: bool
    path: str = ""
    sha256: str = ""
    mode: str = "static"
    selection_scope: str = "decision"
    retrieval_top_k: int = 8
    selector: Agent_Model_Config | None = None
    embedding: EmbeddingConfig | None = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any], *, field_name: str) -> "Skill_Config":
        if not isinstance(data, dict):
            raise ValueError(f"{field_name} must be a mapping")
        enabled = data.get("enabled")
        if not isinstance(enabled, bool):
            raise ValueError(f"{field_name}.enabled must be true or false")
        mode = data.get("mode", "static")
        if mode not in ("static", "dynamic"):
            raise ValueError(f"{field_name}.mode must be static or dynamic")
        scope = data.get("selection_scope", "decision")
        if scope not in ("decision", "task"):
            raise ValueError(f"{field_name}.selection_scope must be decision or task")
        if 'max_selected' in data:
            raise ValueError(f"{field_name}.max_selected is removed; select one Skill or none")
        top_k = data.get("retrieval_top_k", 8)
        if type(top_k) is not int or top_k != 8:
            raise ValueError(f"{field_name} requires retrieval_top_k = 8")
        if mode != "dynamic" and any(k in data for k in ("retrieval_top_k", "selector", "embedding", "selection_scope")):
            raise ValueError(f"{field_name} retrieval settings require dynamic mode")
        selector = None
        if "selector" in data:
            raw = data["selector"]
            if (not isinstance(raw, dict) or set(raw) - {"model_type", "temperature", "max_tokens"}
                    or not isinstance(raw.get("model_type"), str) or not raw["model_type"].strip()):
                raise ValueError(f"{field_name}.selector requires model_type and optional temperature/max_tokens")
            temperature = raw.get("temperature")
            if temperature is not None:
                if type(temperature) not in (int, float) or not math.isfinite(temperature) or temperature < 0:
                    raise ValueError(f"{field_name}.selector.temperature must be finite and nonnegative")
            selector = Agent_Model_Config()
            selector.load_from_dict({**raw, "model_type": raw["model_type"].strip()})
        path = str(data.get("path") or "").strip()
        sha256 = str(data.get("sha256") or "").strip().lower()
        if enabled:
            if not path:
                raise ValueError(
                    f"{field_name}.path must be non-empty when enabled"
                )
            if len(sha256) != 64 or any(
                character not in "0123456789abcdef" for character in sha256
            ):
                raise ValueError(
                    f"{field_name}.sha256 must be a SHA256 hex digest when enabled"
                )
        return cls(enabled=enabled, path=path, sha256=sha256, mode=mode, selection_scope=scope,
                   retrieval_top_k=top_k, selector=selector,
                   embedding=EmbeddingConfig.from_dict(data['embedding']) if 'embedding' in data else None)

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"enabled": self.enabled}
        if self.mode != "static":
            payload["mode"] = self.mode
            payload["retrieval_top_k"] = self.retrieval_top_k
        if self.selection_scope != "decision":
            payload["selection_scope"] = self.selection_scope
        if self.path:
            payload["path"] = self.path
        if self.sha256:
            payload["sha256"] = self.sha256
        if self.selector is not None:
            payload["selector"] = self.selector.to_dict()
        if self.embedding is not None:
            payload['embedding'] = self.embedding.to_dict()
        return payload


@dataclass
class Agent_Model_Config:
    """Reference to one API-backed model instance."""

    model_type: str = "qwen_api"
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None

    def load_from_dict(self, data: Dict[str, Any]) -> None:
        if not isinstance(data, dict):
            return
        for field_name in ("model_type", "temperature", "max_tokens"):
            if field_name in data:
                setattr(self, field_name, data[field_name])
        if self.max_tokens is not None and (
            isinstance(self.max_tokens, bool)
            or not isinstance(self.max_tokens, int)
            or self.max_tokens <= 0
        ):
            raise ValueError("Agent model max_tokens must be a positive integer")

    def to_dict(self, mask_api_key: bool = True) -> Dict[str, Any]:
        del mask_api_key
        payload: Dict[str, Any] = {"model_type": self.model_type}
        if self.temperature is not None:
            payload["temperature"] = self.temperature
        if self.max_tokens is not None:
            payload["max_tokens"] = self.max_tokens
        return payload


@dataclass
class Global_Agent_Config:
    """Bounded question-level control-loop configuration."""

    model: Agent_Model_Config = field(default_factory=Agent_Model_Config)
    max_steps: int = 8
    max_videos_per_watch: int = 4
    skill: Skill_Config | None = None

    def load_from_dict(self, data: Dict[str, Any]) -> None:
        if not isinstance(data, dict):
            return
        if "enabled" in data:
            raise ValueError(
                "agents.global_agent.enabled is no longer supported; "
                "GlobalAgent is required"
            )
        if isinstance(data.get("model"), dict):
            self.model.load_from_dict(data["model"])
        if data.get("skill") is not None:
            self.skill = Skill_Config.from_dict(
                data["skill"],
                field_name="agents.global_agent.skill",
            )
        for field_name in (
            "max_steps",
            "max_videos_per_watch",
        ):
            if field_name in data:
                setattr(self, field_name, data[field_name])
        for field_name in (
            "max_steps",
            "max_videos_per_watch",
        ):
            value = getattr(self, field_name)
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value <= 0
            ):
                raise ValueError(
                    f"agents.global_agent.{field_name} must be a positive integer"
                )

    def to_dict(self, mask_api_key: bool = True) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "model": self.model.to_dict(mask_api_key=mask_api_key),
            "max_steps": self.max_steps,
            "max_videos_per_watch": self.max_videos_per_watch,
        }
        if self.skill is not None:
            payload["skill"] = self.skill.to_dict()
        return payload


@dataclass
class Video_Agent_Config:
    """Adaptive local-loop settings shared by all per-video agents."""

    planner: Agent_Model_Config = field(default_factory=Agent_Model_Config)
    observer: Agent_Model_Config = field(default_factory=Agent_Model_Config)
    max_steps: int = 6
    max_ranges_per_action: int = 8
    skill: Skill_Config | None = None

    def load_from_dict(self, data: Dict[str, Any]) -> None:
        if not isinstance(data, dict):
            return
        if "model" in data:
            raise ValueError(
                "agents.video_agent.model is no longer supported; "
                "configure planner and observer"
            )
        if "reflector" in data:
            raise ValueError(
                "agents.video_agent.reflector is no longer supported; "
                "Planner now decides whether to continue or finish"
            )
        if "enabled" in data:
            raise ValueError(
                "agents.video_agent.enabled is no longer supported; "
                "VideoAgent is required"
            )
        for role in ("planner", "observer"):
            role_data = data.get(role)
            if (
                not isinstance(role_data, dict)
                or not str(role_data.get("model_type", "") or "").strip()
            ):
                raise ValueError(
                    f"agents.video_agent.{role} must be a mapping "
                    "containing model_type"
                )
            getattr(self, role).load_from_dict(role_data)
        if data.get("skill") is not None:
            self.skill = Skill_Config.from_dict(
                data["skill"],
                field_name="agents.video_agent.skill",
            )
        for field_name in (
            "max_steps",
            "max_ranges_per_action",
        ):
            if field_name in data:
                setattr(self, field_name, data[field_name])
        for field_name in (
            "max_steps",
            "max_ranges_per_action",
        ):
            value = getattr(self, field_name)
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value <= 0
            ):
                raise ValueError(
                    f"agents.video_agent.{field_name} must be a positive integer"
                )

    def to_dict(self, mask_api_key: bool = True) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "planner": self.planner.to_dict(mask_api_key=mask_api_key),
            "observer": self.observer.to_dict(mask_api_key=mask_api_key),
            "max_steps": self.max_steps,
            "max_ranges_per_action": self.max_ranges_per_action,
        }
        if self.skill is not None:
            payload["skill"] = self.skill.to_dict()
        return payload


__all__ = [
    "Agent_Model_Config",
    "Global_Agent_Config",
    "Skill_Config",
    "Video_Agent_Config",
]
