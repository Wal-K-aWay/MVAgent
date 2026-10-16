from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class Skill_Config:
    """Explicit immutable reference to one Planner skill file."""

    enabled: bool
    path: str = ""
    sha256: str = ""

    @classmethod
    def from_dict(cls, data: Dict[str, Any], *, field_name: str) -> "Skill_Config":
        if not isinstance(data, dict):
            raise ValueError(f"{field_name} must be a mapping")
        enabled = data.get("enabled")
        if not isinstance(enabled, bool):
            raise ValueError(f"{field_name}.enabled must be true or false")
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
        return cls(enabled=enabled, path=path, sha256=sha256)

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"enabled": self.enabled}
        if self.path:
            payload["path"] = self.path
        if self.sha256:
            payload["sha256"] = self.sha256
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
