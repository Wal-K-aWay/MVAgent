from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
import os
from pathlib import Path
from typing import Any, Mapping
import urllib.parse

import yaml
from models.utils import is_loopback_host

from ..evaluation.gate import GatePolicy
from ..orchestration.coordinator import SearchConfig
from ..strategy.contracts import Role
from .model_config import EvolutionModelConfig


PROJECT_ROOT = Path(
    os.environ.get("MVAGENT_PROJECT_ROOT")
    or Path(__file__).resolve().parents[3]
).expanduser().resolve()


def _mapping(data: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(data, Mapping):
        raise ValueError(f"{field_name} must be a mapping.")
    return data


def _dataclass_kwargs(
    data: Mapping[str, Any],
    config_type: type,
    *,
    field_name: str,
) -> dict[str, Any]:
    known = {item.name for item in fields(config_type) if item.init}
    unknown = set(data) - known
    if unknown:
        raise ValueError(
            f"{field_name} contains unknown fields: "
            + ", ".join(sorted(str(item) for item in unknown))
        )
    return {key: value for key, value in data.items() if key in known}


def _project_path(value: Any, *, field_name: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError(f"{field_name} must be non-empty.")
    path = Path(raw).expanduser()
    return str((path if path.is_absolute() else PROJECT_ROOT / path).resolve())


@dataclass(frozen=True)
class RolloutReplicaConfig:
    """One single-GPU endpoint used by one offline MVAgent rollout worker."""

    endpoint: str
    gpus: tuple[int, ...]

    def __post_init__(self) -> None:
        endpoint = str(self.endpoint or "").strip()
        parsed = urllib.parse.urlparse(endpoint)
        if (
            parsed.scheme != "http"
            or not is_loopback_host(parsed.hostname)
            or parsed.path != "/v1"
            or any((parsed.params, parsed.query, parsed.fragment))
        ):
            raise ValueError(
                "runtime.rollout_replicas endpoints must use loopback HTTP "
                "and end exactly with /v1."
            )
        try:
            port = parsed.port
        except ValueError as exc:
            raise ValueError(
                "runtime.rollout_replicas endpoint has an invalid port."
            ) from exc
        if port is None:
            raise ValueError(
                "runtime.rollout_replicas endpoint must include a port."
            )
        raw_gpus = self.gpus
        if not isinstance(raw_gpus, (list, tuple)):
            raise ValueError(
                "runtime.rollout_replicas.gpus must be a one-item list."
            )
        gpus = tuple(raw_gpus)
        if (
            len(gpus) != 1
            or isinstance(gpus[0], bool)
            or not isinstance(gpus[0], int)
            or gpus[0] < 0
        ):
            raise ValueError(
                "Each runtime.rollout_replicas entry must select exactly one "
                "non-negative GPU index."
            )
        object.__setattr__(self, "endpoint", endpoint)
        object.__setattr__(self, "gpus", gpus)

    def to_dict(self) -> dict[str, Any]:
        return {"endpoint": self.endpoint, "gpus": list(self.gpus)}


@dataclass(frozen=True)
class EvolutionRuntimeConfig:
    """Offline paths; MVAgent's own Runtime config remains unchanged."""

    mvagent_config: str
    output_dir: str = "outputs/skill_evolution"
    cache_dir: str = ".cache/skill_evolution"
    rollout_replicas: tuple[RolloutReplicaConfig, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "mvagent_config",
            _project_path(self.mvagent_config, field_name="runtime.mvagent_config"),
        )
        object.__setattr__(
            self,
            "output_dir",
            _project_path(self.output_dir, field_name="runtime.output_dir"),
        )
        object.__setattr__(
            self,
            "cache_dir",
            _project_path(self.cache_dir, field_name="runtime.cache_dir"),
        )
        raw_replicas = self.rollout_replicas
        if not isinstance(raw_replicas, (list, tuple)):
            raise ValueError("runtime.rollout_replicas must be a list.")
        replicas: list[RolloutReplicaConfig] = []
        for index, item in enumerate(raw_replicas):
            if isinstance(item, RolloutReplicaConfig):
                replica = item
            else:
                replica_data = _mapping(
                    item,
                    f"runtime.rollout_replicas[{index}]",
                )
                replica = RolloutReplicaConfig(
                    **_dataclass_kwargs(
                        replica_data,
                        RolloutReplicaConfig,
                        field_name=f"runtime.rollout_replicas[{index}]",
                    )
                )
            replicas.append(replica)
        endpoints = [item.endpoint for item in replicas]
        if len(endpoints) != len(set(endpoints)):
            raise ValueError("runtime.rollout_replicas endpoints must be unique.")
        gpus = [item.gpus[0] for item in replicas]
        if len(gpus) != len(set(gpus)):
            raise ValueError("runtime.rollout_replicas GPU indexes must be unique.")
        object.__setattr__(self, "rollout_replicas", tuple(replicas))
        if not Path(self.mvagent_config).is_file():
            raise FileNotFoundError(
                f"MVAgent config not found: {self.mvagent_config}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "mvagent_config": self.mvagent_config,
            "output_dir": self.output_dir,
            "cache_dir": self.cache_dir,
            "rollout_replicas": [
                replica.to_dict() for replica in self.rollout_replicas
            ],
        }


@dataclass(frozen=True)
class PatcherConfig:
    model: EvolutionModelConfig
    workflow: str = "single_stage"
    prompt_path: str = ""
    diagnosis_prompt_path: str = ""
    patch_prompt_path: str = ""

    def __post_init__(self) -> None:
        workflow = str(self.workflow or "").strip().lower()
        if workflow not in {"single_stage", "diagnose_then_patch"}:
            raise ValueError(
                "patcher.workflow must be single_stage or diagnose_then_patch."
            )
        object.__setattr__(self, "workflow", workflow)
        if workflow == "single_stage" and (
            self.diagnosis_prompt_path or self.patch_prompt_path
        ):
            raise ValueError(
                "diagnosis_prompt_path and patch_prompt_path require "
                "patcher.workflow=diagnose_then_patch."
            )
        if workflow == "diagnose_then_patch" and self.prompt_path:
            raise ValueError(
                "prompt_path is only valid for patcher.workflow=single_stage."
            )


@dataclass(frozen=True)
class ReviewerConfig:
    enabled: bool = True
    prompt_path: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise ValueError("reviewer.enabled must be true or false.")


@dataclass(frozen=True)
class PairwiseConfig:
    enabled: bool = False
    model: EvolutionModelConfig | None = None
    prompt_path: str = ""
    max_parse_retries: int = 2
    max_cases: int = 10
    seed: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise ValueError("pairwise.enabled must be true or false.")
        if self.enabled and self.model is None:
            raise ValueError("pairwise.model is required when pairwise is enabled.")
        if (
            isinstance(self.max_parse_retries, bool)
            or not isinstance(self.max_parse_retries, int)
            or self.max_parse_retries < 0
        ):
            raise ValueError("pairwise.max_parse_retries must be non-negative.")
        if (
            isinstance(self.max_cases, bool)
            or not isinstance(self.max_cases, int)
            or self.max_cases < 1
        ):
            raise ValueError("pairwise.max_cases must be a positive integer.")
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise ValueError("pairwise.seed must be an integer.")


@dataclass(frozen=True)
class OpenQAJudgeConfig:
    """One frozen, cached OpenQA scorer used only by benchmark evaluation."""

    enabled: bool = False
    model: EvolutionModelConfig | None = None
    prompt_path: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise ValueError("open_qa_judge.enabled must be true or false.")
        if self.enabled and self.model is None:
            raise ValueError(
                "open_qa_judge.model is required when OpenQA judging is enabled."
            )
        prompt_path = str(self.prompt_path or "").strip()
        if prompt_path:
            prompt_path = _project_path(
                prompt_path,
                field_name="open_qa_judge.prompt_path",
            )
            if not Path(prompt_path).is_file():
                raise FileNotFoundError(
                    f"OpenQA judge prompt not found: {prompt_path}"
                )
        object.__setattr__(self, "prompt_path", prompt_path)


@dataclass(frozen=True)
class PlannerReplayConfig:
    enabled: bool = False
    min_support_change_ratio: float = 0.5
    max_contrast_action_change_ratio: float = 0.0
    max_states_per_case: int = 2

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise ValueError("planner_replay.enabled must be true or false.")
        ratio = float(self.min_support_change_ratio)
        if not 0.0 < ratio <= 1.0:
            raise ValueError(
                "planner_replay.min_support_change_ratio must be in (0, 1]."
            )
        object.__setattr__(self, "min_support_change_ratio", ratio)
        contrast_ratio = float(self.max_contrast_action_change_ratio)
        if not 0.0 <= contrast_ratio <= 1.0:
            raise ValueError(
                "planner_replay.max_contrast_action_change_ratio must be in [0, 1]."
            )
        object.__setattr__(
            self,
            "max_contrast_action_change_ratio",
            contrast_ratio,
        )
        if (
            isinstance(self.max_states_per_case, bool)
            or not isinstance(self.max_states_per_case, int)
            or self.max_states_per_case < 1
        ):
            raise ValueError(
                "planner_replay.max_states_per_case must be a positive integer."
            )


@dataclass(frozen=True)
class UpdaterConfig:
    max_edits: int = 1
    max_chars: int = 6_000
    initial_max_chars: int = 1_200
    max_net_growth: int = 1_000
    min_edit_evidence: int = 2
    adaptive_edit_budget: bool = False
    adaptive_min_changed_chars: int = 240
    adaptive_chars_per_support_group: int = 160
    adaptive_generation_decay: float = 0.5

    def __post_init__(self) -> None:
        if not isinstance(self.adaptive_edit_budget, bool):
            raise ValueError("updater.adaptive_edit_budget must be true or false.")
        if self.max_edits != 1:
            raise ValueError("updater.max_edits must be 1.")
        integer_names = (
            "max_edits",
            "max_chars",
            "initial_max_chars",
            "max_net_growth",
            "min_edit_evidence",
            "adaptive_min_changed_chars",
            "adaptive_chars_per_support_group",
        )
        values = tuple(getattr(self, name) for name in integer_names)
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 1
            for value in values
        ):
            raise ValueError(
                "All updater character/count limits must be positive integers."
            )
        decay = float(self.adaptive_generation_decay)
        if decay < 0.0:
            raise ValueError(
                "updater.adaptive_generation_decay must be non-negative."
            )
        object.__setattr__(self, "adaptive_generation_decay", decay)

    def to_kwargs(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MinibatchConfig:
    """Deterministic role-local failure/success trajectory batch sizes."""

    failure_size: int = 6
    success_size: int = 2

    def __post_init__(self) -> None:
        for name in ("failure_size", "success_size"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"minibatch.{name} must be a positive integer.")


@dataclass(frozen=True)
class SkillEvolutionConfig:
    """Validated configuration for one offline Skill-evolution run."""

    runtime: EvolutionRuntimeConfig
    patcher: PatcherConfig
    reviewer: ReviewerConfig = field(default_factory=ReviewerConfig)
    pairwise: PairwiseConfig = field(default_factory=PairwiseConfig)
    open_qa_judge: OpenQAJudgeConfig = field(
        default_factory=OpenQAJudgeConfig
    )
    planner_replay: PlannerReplayConfig = field(
        default_factory=PlannerReplayConfig
    )
    minibatch: MinibatchConfig = field(default_factory=MinibatchConfig)
    search: SearchConfig = field(default_factory=SearchConfig)
    updater: UpdaterConfig = field(default_factory=UpdaterConfig)
    gate: GatePolicy = field(default_factory=GatePolicy)

    @classmethod
    def from_yaml(cls, path: str | Path) -> "SkillEvolutionConfig":
        config_path = Path(path).expanduser().resolve()
        if not config_path.is_file():
            raise FileNotFoundError(
                f"Skill evolution config not found: {config_path}"
            )
        data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        return cls.from_dict(_mapping(data, "skill_evolution"))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SkillEvolutionConfig":
        data = _mapping(data, "skill_evolution")
        unknown = set(data) - {
            "runtime",
            "patcher",
            "reviewer",
            "pairwise",
            "open_qa_judge",
            "planner_replay",
            "minibatch",
            "search",
            "updater",
            "gate",
        }
        if unknown:
            raise ValueError(
                "skill_evolution contains unknown fields: "
                + ", ".join(sorted(str(item) for item in unknown))
            )

        runtime_data = _mapping(data.get("runtime"), "runtime")
        runtime = EvolutionRuntimeConfig(
            **_dataclass_kwargs(
                runtime_data,
                EvolutionRuntimeConfig,
                field_name="runtime",
            )
        )

        patcher_data = _mapping(data.get("patcher"), "patcher")
        patcher_unknown = set(patcher_data) - {
            "model",
            "workflow",
            "prompt_path",
            "diagnosis_prompt_path",
            "patch_prompt_path",
        }
        if patcher_unknown:
            raise ValueError(
                "patcher contains unknown fields: "
                + ", ".join(sorted(str(item) for item in patcher_unknown))
            )
        patcher = PatcherConfig(
            model=EvolutionModelConfig.from_dict(
                _mapping(patcher_data.get("model"), "patcher.model"),
                field_name="patcher.model",
            ),
            workflow=str(
                patcher_data.get("workflow") or "single_stage"
            ).strip(),
            prompt_path=str(patcher_data.get("prompt_path") or "").strip(),
            diagnosis_prompt_path=str(
                patcher_data.get("diagnosis_prompt_path") or ""
            ).strip(),
            patch_prompt_path=str(
                patcher_data.get("patch_prompt_path") or ""
            ).strip(),
        )

        reviewer_data = _mapping(data.get("reviewer", {}), "reviewer")
        reviewer = ReviewerConfig(
            **_dataclass_kwargs(
                reviewer_data,
                ReviewerConfig,
                field_name="reviewer",
            )
        )

        pairwise_data = _mapping(data.get("pairwise", {}), "pairwise")
        pairwise_unknown = set(pairwise_data) - {
            "enabled",
            "model",
            "prompt_path",
            "max_parse_retries",
            "max_cases",
            "seed",
        }
        if pairwise_unknown:
            raise ValueError(
                "pairwise contains unknown fields: "
                + ", ".join(sorted(str(item) for item in pairwise_unknown))
            )
        pairwise_model_data = pairwise_data.get("model")
        pairwise = PairwiseConfig(
            enabled=pairwise_data.get("enabled", False),
            model=(
                EvolutionModelConfig.from_dict(
                    _mapping(pairwise_model_data, "pairwise.model"),
                    field_name="pairwise.model",
                )
                if pairwise_model_data is not None
                else None
            ),
            prompt_path=str(pairwise_data.get("prompt_path") or "").strip(),
            max_parse_retries=pairwise_data.get("max_parse_retries", 2),
            max_cases=pairwise_data.get("max_cases", 10),
            seed=pairwise_data.get("seed", 0),
        )

        open_qa_judge_data = _mapping(
            data.get("open_qa_judge", {}),
            "open_qa_judge",
        )
        open_qa_judge_unknown = set(open_qa_judge_data) - {
            "enabled",
            "model",
            "prompt_path",
        }
        if open_qa_judge_unknown:
            raise ValueError(
                "open_qa_judge contains unknown fields: "
                + ", ".join(
                    sorted(str(item) for item in open_qa_judge_unknown)
                )
            )
        open_qa_model_data = open_qa_judge_data.get("model")
        open_qa_judge = OpenQAJudgeConfig(
            enabled=open_qa_judge_data.get("enabled", False),
            model=(
                EvolutionModelConfig.from_dict(
                    _mapping(open_qa_model_data, "open_qa_judge.model"),
                    field_name="open_qa_judge.model",
                )
                if open_qa_model_data is not None
                else None
            ),
            prompt_path=str(
                open_qa_judge_data.get("prompt_path") or ""
            ).strip(),
        )

        planner_replay_data = _mapping(
            data.get("planner_replay", {}),
            "planner_replay",
        )
        planner_replay = PlannerReplayConfig(
            **_dataclass_kwargs(
                planner_replay_data,
                PlannerReplayConfig,
                field_name="planner_replay",
            )
        )

        minibatch_data = _mapping(data.get("minibatch", {}), "minibatch")
        minibatch = MinibatchConfig(
            **_dataclass_kwargs(
                minibatch_data,
                MinibatchConfig,
                field_name="minibatch",
            )
        )

        search_data = dict(_mapping(data.get("search", {}), "search"))
        if "role_order" in search_data:
            role_order = search_data["role_order"]
            if not isinstance(role_order, (list, tuple)):
                raise ValueError("search.role_order must be a list.")
            search_data["role_order"] = tuple(Role(str(item)) for item in role_order)
        search = SearchConfig(
            **_dataclass_kwargs(search_data, SearchConfig, field_name="search")
        )

        updater_data = _mapping(data.get("updater", {}), "updater")
        updater = UpdaterConfig(
            **_dataclass_kwargs(
                updater_data,
                UpdaterConfig,
                field_name="updater",
            )
        )

        gate_data = _mapping(data.get("gate", {}), "gate")
        gate = GatePolicy(
            **_dataclass_kwargs(gate_data, GatePolicy, field_name="gate")
        )
        return cls(
            runtime=runtime,
            patcher=patcher,
            reviewer=reviewer,
            pairwise=pairwise,
            open_qa_judge=open_qa_judge,
            planner_replay=planner_replay,
            minibatch=minibatch,
            search=search,
            updater=updater,
            gate=gate,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "runtime": self.runtime.to_dict(),
            "patcher": {
                "model": self.patcher.model.to_dict(),
                "workflow": self.patcher.workflow,
                "prompt_path": self.patcher.prompt_path,
                "diagnosis_prompt_path": self.patcher.diagnosis_prompt_path,
                "patch_prompt_path": self.patcher.patch_prompt_path,
            },
            "reviewer": asdict(self.reviewer),
            "pairwise": {
                "enabled": self.pairwise.enabled,
                "model": (
                    self.pairwise.model.to_dict()
                    if self.pairwise.model is not None
                    else None
                ),
                "prompt_path": self.pairwise.prompt_path,
                "max_parse_retries": self.pairwise.max_parse_retries,
                "max_cases": self.pairwise.max_cases,
                "seed": self.pairwise.seed,
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
            "planner_replay": asdict(self.planner_replay),
            "minibatch": asdict(self.minibatch),
            "search": {
                **asdict(self.search),
                "role_order": [role.value for role in self.search.role_order],
            },
            "updater": asdict(self.updater),
            "gate": asdict(self.gate),
        }


__all__ = [
    "EvolutionRuntimeConfig",
    "MinibatchConfig",
    "OpenQAJudgeConfig",
    "PairwiseConfig",
    "PlannerReplayConfig",
    "PatcherConfig",
    "ReviewerConfig",
    "RolloutReplicaConfig",
    "SkillEvolutionConfig",
    "UpdaterConfig",
]
