from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

import yaml

from ..configs.model_config import EvolutionModelConfig
from ..configs.system_config import (
    EvolutionRuntimeConfig,
    OpenQAJudgeConfig,
)
from ..evaluation.gate import GatePolicy
from ..strategy.contracts import Role


_SKILLOPT_SECTIONS = frozenset(
    {"model", "train", "gradient", "optimizer", "evaluation", "env"}
)


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be a mapping.")
    return value


def _kwargs(value: Mapping[str, Any], cls: type, name: str) -> dict[str, Any]:
    known = {item.name for item in fields(cls) if item.init}
    unknown = set(value) - known
    if unknown:
        raise ValueError(
            f"{name} contains unknown fields: "
            + ", ".join(sorted(str(item) for item in unknown))
        )
    return dict(value)


def _positive_int(value: object, name: str, *, minimum: int = 1) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}.")
    return value


@dataclass(frozen=True)
class SkillOptRecipe:
    """One immutable, structured configuration passed to stock SkillOpt.

    MVAgent validates the few settings that define the requested algorithmic
    contract.  SkillOpt remains the authority that flattens and consumes the
    complete configuration.
    """

    sections: Mapping[str, Mapping[str, Any]]

    def __post_init__(self) -> None:
        raw = _mapping(self.sections, "skillopt")
        unknown = set(raw) - _SKILLOPT_SECTIONS
        if unknown:
            raise ValueError(
                "skillopt contains unknown sections: "
                + ", ".join(sorted(str(item) for item in unknown))
            )
        missing = _SKILLOPT_SECTIONS - set(raw)
        if missing:
            raise ValueError(
                "skillopt is missing sections: "
                + ", ".join(sorted(missing))
            )
        normalized = {
            section: MappingProxyType(dict(_mapping(raw[section], f"skillopt.{section}")))
            for section in sorted(_SKILLOPT_SECTIONS)
        }
        train = normalized["train"]
        gradient = normalized["gradient"]
        optimizer = normalized["optimizer"]
        evaluation = normalized["evaluation"]

        _positive_int(train.get("num_epochs"), "skillopt.train.num_epochs", minimum=2)
        train_size = train.get("train_size", 0)
        if isinstance(train_size, bool) or not isinstance(train_size, int) or train_size != 0:
            raise ValueError(
                "skillopt.train.train_size must be 0 so the stock Trainer "
                "derives each role's eligible Train pool."
            )
        _positive_int(train.get("batch_size"), "skillopt.train.batch_size")
        _positive_int(train.get("accumulation", 1), "skillopt.train.accumulation")
        _positive_int(gradient.get("minibatch_size"), "skillopt.gradient.minibatch_size")
        _positive_int(
            gradient.get("merge_batch_size"),
            "skillopt.gradient.merge_batch_size",
            minimum=2,
        )
        _positive_int(gradient.get("analyst_workers"), "skillopt.gradient.analyst_workers")
        if gradient.get("failure_only") is not False:
            raise ValueError(
                "skillopt.gradient.failure_only must be false so the stock "
                "failure and success reflection/merge paths both remain active."
            )
        learning_rate = _positive_int(
            optimizer.get("learning_rate"),
            "skillopt.optimizer.learning_rate",
        )
        minimum_rate = _positive_int(
            optimizer.get("min_learning_rate"),
            "skillopt.optimizer.min_learning_rate",
        )
        if minimum_rate > learning_rate:
            raise ValueError(
                "skillopt.optimizer.min_learning_rate cannot exceed learning_rate."
            )
        if str(optimizer.get("skill_update_mode") or "").strip() != "patch":
            raise ValueError(
                "skillopt.optimizer.skill_update_mode must be patch so ranking "
                "and top-L update remain active."
            )
        if str(optimizer.get("lr_control_mode") or "").strip() != "fixed":
            raise ValueError(
                "skillopt.optimizer.lr_control_mode must be fixed; the stock "
                "scheduler controls top-L."
            )
        if str(optimizer.get("lr_scheduler") or "").strip() not in {
            "constant",
            "linear",
            "cosine",
        }:
            raise ValueError(
                "skillopt.optimizer.lr_scheduler must be constant, linear, or cosine."
            )
        if optimizer.get("use_slow_update") is not True:
            raise ValueError(
                "skillopt.optimizer.use_slow_update must be true for the canonical run."
            )
        _positive_int(
            optimizer.get("slow_update_samples"),
            "skillopt.optimizer.slow_update_samples",
        )
        if optimizer.get("slow_update_gate_with_selection") is not True:
            raise ValueError(
                "skillopt.optimizer.slow_update_gate_with_selection must be true."
            )
        if str(optimizer.get("longitudinal_pair_policy") or "").strip() != "mixed":
            raise ValueError(
                "skillopt.optimizer.longitudinal_pair_policy must be mixed so "
                "all four longitudinal outcome categories remain available."
            )
        if evaluation.get("use_gate") is not True:
            raise ValueError("skillopt.evaluation.use_gate must be true.")
        if evaluation.get("eval_test") is not False:
            raise ValueError(
                "skillopt.evaluation.eval_test must be false; MVAgent owns a "
                "Train/Eval-only boundary and no Test split is exposed to SkillOpt."
            )
        _positive_int(
            evaluation.get("sel_env_num"),
            "skillopt.evaluation.sel_env_num",
        )
        object.__setattr__(self, "sections", MappingProxyType(normalized))

    def to_dict(self) -> dict[str, dict[str, Any]]:
        return {name: dict(values) for name, values in self.sections.items()}


@dataclass(frozen=True)
class RoleSessionConfig:
    """Only the multi-Agent scheduling that SkillOpt itself does not own."""

    rounds: int = 1
    role_order: tuple[Role, ...] = (Role.GLOBAL, Role.VIDEO)

    def __post_init__(self) -> None:
        _positive_int(self.rounds, "coordination.rounds")
        order = tuple(Role(item) for item in self.role_order)
        if not order or len(order) != len(set(order)):
            raise ValueError("coordination.role_order must contain unique roles.")
        if set(order) != {Role.GLOBAL, Role.VIDEO}:
            raise ValueError(
                "coordination.role_order must contain global and video exactly once."
            )
        object.__setattr__(self, "role_order", order)


@dataclass(frozen=True)
class SkillOptEvolutionConfig:
    """Canonical MVAgent evolution config backed by stock SkillOpt."""

    runtime: EvolutionRuntimeConfig
    skillopt: SkillOptRecipe
    coordination: RoleSessionConfig = field(default_factory=RoleSessionConfig)
    open_qa_judge: OpenQAJudgeConfig = field(default_factory=OpenQAJudgeConfig)
    gate: GatePolicy = field(default_factory=GatePolicy)

    def __post_init__(self) -> None:
        if self.gate.required_references != {"eval": ("parent",)}:
            raise ValueError(
                "The canonical SkillOpt engine exposes one complete-system "
                "Eval stage against parent; gate.required_references must be "
                "exactly {eval: [parent]}."
            )

    @classmethod
    def from_yaml(cls, path: str | Path) -> "SkillOptEvolutionConfig":
        config_path = Path(path).expanduser().resolve()
        if not config_path.is_file():
            raise FileNotFoundError(f"Skill evolution config not found: {config_path}")
        data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        return cls.from_dict(_mapping(data, "skill_evolution"))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SkillOptEvolutionConfig":
        unknown = set(data) - {
            "runtime",
            "skillopt",
            "coordination",
            "open_qa_judge",
            "gate",
        }
        if unknown:
            raise ValueError(
                "skill_evolution contains obsolete or unknown fields: "
                + ", ".join(sorted(str(item) for item in unknown))
            )
        runtime_data = _mapping(data.get("runtime"), "runtime")
        runtime = EvolutionRuntimeConfig(
            **_kwargs(runtime_data, EvolutionRuntimeConfig, "runtime")
        )
        coordination_data = dict(
            _mapping(data.get("coordination", {}), "coordination")
        )
        if "role_order" in coordination_data:
            raw_order = coordination_data["role_order"]
            if not isinstance(raw_order, (list, tuple)):
                raise ValueError("coordination.role_order must be a list.")
            coordination_data["role_order"] = tuple(Role(str(item)) for item in raw_order)
        coordination = RoleSessionConfig(
            **_kwargs(coordination_data, RoleSessionConfig, "coordination")
        )

        judge_data = _mapping(data.get("open_qa_judge", {}), "open_qa_judge")
        judge_unknown = set(judge_data) - {"enabled", "model", "prompt_path"}
        if judge_unknown:
            raise ValueError(
                "open_qa_judge contains unknown fields: "
                + ", ".join(sorted(str(item) for item in judge_unknown))
            )
        raw_model = judge_data.get("model")
        judge = OpenQAJudgeConfig(
            enabled=judge_data.get("enabled", False),
            model=(
                EvolutionModelConfig.from_dict(
                    _mapping(raw_model, "open_qa_judge.model"),
                    field_name="open_qa_judge.model",
                )
                if raw_model is not None
                else None
            ),
            prompt_path=str(judge_data.get("prompt_path") or "").strip(),
        )
        gate_data = _mapping(data.get("gate", {}), "gate")
        gate = GatePolicy(**_kwargs(gate_data, GatePolicy, "gate"))
        return cls(
            runtime=runtime,
            skillopt=SkillOptRecipe(_mapping(data.get("skillopt"), "skillopt")),
            coordination=coordination,
            open_qa_judge=judge,
            gate=gate,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "runtime": self.runtime.to_dict(),
            "skillopt": self.skillopt.to_dict(),
            "coordination": {
                "rounds": self.coordination.rounds,
                "role_order": [role.value for role in self.coordination.role_order],
            },
            "open_qa_judge": {
                "enabled": self.open_qa_judge.enabled,
                "model": (
                    self.open_qa_judge.model.to_dict()
                    if self.open_qa_judge.model is not None
                    else None
                ),
                "prompt_path": self.open_qa_judge.prompt_path,
            },
            "gate": asdict(self.gate),
        }


__all__ = [
    "RoleSessionConfig",
    "SkillOptEvolutionConfig",
    "SkillOptRecipe",
]
