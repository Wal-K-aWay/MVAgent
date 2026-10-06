from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Union

import yaml

from .agent_config import (
    Agent_Model_Config,
    Global_Agent_Config,
    Video_Agent_Config,
)
from .model_config import ModelInstanceConfig, parse_model_instance_config


_AGENT_MODEL_ROLES = (
    ("global_agent", ("model",)),
    ("video_agent", ("planner", "observer")),
)

_ROLE_CAPABILITY_REQUIREMENTS: dict[tuple[str, str], frozenset[str]] = {
    ("global_agent", "skill.selector"): frozenset({"text", "structured_output"}),
    ("video_agent", "skill.selector"): frozenset({"text", "structured_output"}),
    ("global_agent", "model"): frozenset(
        {"text", "structured_output"}
    ),
    ("video_agent", "planner"): frozenset(
        {"text", "structured_output"}
    ),
    ("video_agent", "observer"): frozenset(
        {"text", "video", "structured_output"}
    ),
}


@dataclass
class Runtime_Config:
    """Runtime output and cache paths."""

    output_dir: str = "outputs"
    cache_dir: str = ".cache/mvagent"
    video_concurrency: int = 1

    def load_from_dict(self, data: Dict[str, Any]) -> None:
        if not isinstance(data, dict):
            return
        for field_name in ("output_dir", "cache_dir", "video_concurrency"):
            if field_name in data:
                setattr(self, field_name, data[field_name])

    def to_dict(self) -> Dict[str, Any]:
        return {
            "output_dir": self.output_dir,
            "cache_dir": self.cache_dir,
            "video_concurrency": self.video_concurrency,
        }


@dataclass
class MVAgentConfig:
    """Top-level model, Agent, and runtime configuration."""

    models: Dict[str, ModelInstanceConfig] = field(default_factory=dict)
    runtime: Runtime_Config = field(default_factory=Runtime_Config)
    global_agent: Global_Agent_Config = field(default_factory=Global_Agent_Config)
    video_agent: Video_Agent_Config = field(default_factory=Video_Agent_Config)

    def model_roles(self) -> list[tuple[str, str, Agent_Model_Config]]:
        """Return all required model-bearing roles in stable runtime order."""
        roles: list[tuple[str, str, Agent_Model_Config]] = []
        for agent_name, role_names in _AGENT_MODEL_ROLES:
            agent = getattr(self, agent_name)
            for role_name in role_names:
                roles.append((agent_name, role_name, getattr(agent, role_name)))
            skill = agent.skill
            if skill is not None and skill.enabled and skill.mode == "dynamic" and skill.selector is not None:
                roles.append((agent_name, "skill.selector", skill.selector))
        return roles

    @classmethod
    def from_yaml(cls, config_path: Union[str, Path]) -> "MVAgentConfig":
        config_path = Path(config_path)
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")
        with config_path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MVAgentConfig":
        cfg = cls()
        cfg._load_from_dict(data)
        cfg.validate()
        return cfg

    def _load_from_dict(self, data: Dict[str, Any]) -> None:
        models_data = data.get("models")
        if isinstance(models_data, dict):
            for model_type, section in models_data.items():
                self.models[model_type] = parse_model_instance_config(
                    model_type,
                    section,
                )

        if isinstance(data.get("runtime"), dict):
            self.runtime.load_from_dict(data["runtime"])

        agents = data.get("agents")
        if not isinstance(agents, dict):
            raise ValueError("agents must be a mapping")
        global_agent = agents.get("global_agent")
        if not isinstance(global_agent, dict):
            raise ValueError("agents.global_agent must be a mapping")
        self.global_agent.load_from_dict(global_agent)
        video_agent = agents.get("video_agent")
        if not isinstance(video_agent, dict):
            raise ValueError("agents.video_agent must be a mapping")
        self.video_agent.load_from_dict(video_agent)

    def validate(self) -> None:
        if type(self.runtime.video_concurrency) is not int or self.runtime.video_concurrency < 1:
            raise ValueError("runtime.video_concurrency must be a positive integer")
        """Validate every required GlobalAgent and VideoAgent model role."""
        from models.llm.api.client import available_api_llm_providers
        from models.vlm.api.client import available_api_vlm_providers

        known_llm_providers = available_api_llm_providers()
        known_vlm_providers = available_api_vlm_providers()
        validated_instances: set[str] = set()
        for agent_name, role_name, model_ref in self.model_roles():
            model_name = str(model_ref.model_type or "").strip()
            model_cfg = self.models.get(model_name)
            if model_cfg is None:
                raise ValueError(
                    f"{agent_name}.{role_name} references unknown model "
                    f"instance: {model_name}"
                )
            if model_name not in validated_instances:
                model_cfg.validate_limits(model_name)
                model_cfg.validate(
                    model_name,
                    known_api_providers=known_vlm_providers,
                    known_api_llm_providers=known_llm_providers,
                )
                validated_instances.add(model_name)

            required = _ROLE_CAPABILITY_REQUIREMENTS.get(
                (agent_name, role_name),
                frozenset(),
            )
            available = frozenset(model_cfg.capabilities)
            missing = sorted(required - available)
            if missing:
                raise ValueError(
                    f"agents.{agent_name}.{role_name} requires model "
                    f"capabilities {sorted(required)}, but '{model_name}' "
                    f"(type={model_cfg.type}) provides {sorted(available)}; "
                    f"missing {missing}."
                )
            if (
                model_cfg.type == "api_llm"
                and getattr(model_cfg, "provider", None) == "deepseek"
                and bool(getattr(model_cfg, "enable_thinking", False))
                and model_ref.temperature is not None
            ):
                raise ValueError(
                    f"agents.{agent_name}.{role_name}.temperature must not "
                    f"be set because '{model_name}' has DeepSeek thinking "
                    "mode enabled and the API ignores temperature."
                )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "models": {
                model_type: cfg.to_dict()
                for model_type, cfg in self.models.items()
            },
            "runtime": self.runtime.to_dict(),
            "agents": {
                "global_agent": self.global_agent.to_dict(),
                "video_agent": self.video_agent.to_dict(),
            },
        }


__all__ = [
    "MVAgentConfig",
    "Runtime_Config",
]
