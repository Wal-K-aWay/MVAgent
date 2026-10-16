"""Thin MVAgent adapter for the fixed upstream SkillOpt trainer.

This is the only project module allowed to import :mod:`skillopt`.  It adapts
frozen MVAgent question IDs and role-local Skill text to SkillOpt's public
``BaseDataLoader`` / ``EnvAdapter`` / ``ReflACTTrainer`` contracts.  All
reflection, aggregation, ranking, top-L application, selection gating,
checkpointing, and slow-update behavior stays inside the upstream trainer.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Any, Literal, Protocol

from skillopt.config import flatten_config
from skillopt.datasets.base import BaseDataLoader, BatchSpec, SplitDataLoader
from skillopt.engine.trainer import ReflACTTrainer
from skillopt.envs.base import EnvAdapter

from mvagent.skills.loader import MAX_SKILL_CHARS

from ..benchmarks.scoring import REFLECTION_SUCCESS_POLICY
from ..strategy.contracts import (
    Role,
    SkillSet,
    hash_json,
    normalize_skill_text,
    sha256_text,
)


_ADAPTER_CONTRACT = "mvagent-skillopt-role-adapter-v2"
_TRAIN_SPLIT = "train"
_SELECTION_SPLITS = frozenset({"valid_seen", "selection", "val"})
_UPSTREAM_VERSION = "0.2.0"
_UPSTREAM_TREE_SHA256 = "79f028703e02a9e0d7107f795c4ee5399291c902975d422abacdf1e616989f4f"
_UPSTREAM_FILE_HASHES = {
    "skillopt/engine/trainer.py": "ff71a1480ee7c7c21a2574bb429eeb7dc0c88da0ea018feb22da4fa00b663a7f",
    "skillopt/gradient/reflect.py": "537a72293ebdeec88da6d7055e8b9af6204a8766a9f02bc9cf131fbe61499a8e",
    "skillopt/gradient/aggregate.py": "08e5e17ff13fb03838cf9a136af974ce5d21424bbba8a93b62ae983afe896d3f",
    "skillopt/optimizer/clip.py": "0c1060799884eb32e131000299ae78af094ee375d9c81c3dd1e1e2c78bd3c728",
    "skillopt/optimizer/scheduler.py": "791b81b6d7e3de974d6a9d4a9e69636bf2a442019a19c039dc7e2e0ff26b894a",
    "skillopt/optimizer/slow_update.py": "90e71c6fd4ae5ca0506a2e0bee604a9c05f53b0d8d017618a0d44e65635efaed",
    "skillopt/prompts/analyst_error.md": "40eaf561c7fdbdfc1c7a1febd9f7c3540270ca6d5e7e0a8798c7c90b8d303200",
    "skillopt/prompts/analyst_success.md": "0ffc8f85e13af2b14e1b9f3307a44d30ecf60e9d803ccb9190fdd9785e43fabc",
    "skillopt/prompts/merge_failure.md": "071313895da226840164ccda6e7f01d5f849ea128037d3f337cddab66ae799db",
    "skillopt/prompts/merge_success.md": "6b816bcf5526d31164b779921f3c8c847541bf92fbe26c6a38b555eb3b753712",
    "skillopt/prompts/merge_final.md": "b2c7b452032fbbe3b223e877b766ea6202775d685c3b32e68956a402e775b84b",
    "skillopt/prompts/ranking.md": "8bf37725b7b328d8d54af7a8fb173179bdd0f02b57399ed2cc7a5b5d25edea8a",
    "skillopt/prompts/slow_update.md": "7f6f97d2283a370ad072a91ad61e152551f4f4eb4f519c9a1c5c60679b4782f2",
}


def verify_upstream_installation() -> None:
    """Fail closed if the installed optimization code differs from the pin."""

    distribution = importlib_metadata.distribution("skillopt")
    if distribution.version != _UPSTREAM_VERSION:
        raise RuntimeError(
            f"Expected skillopt=={_UPSTREAM_VERSION}, got {distribution.version}."
        )
    for relative_path, expected in _UPSTREAM_FILE_HASHES.items():
        path = Path(distribution.locate_file(relative_path))
        if not path.is_file():
            raise RuntimeError(f"Pinned SkillOpt file is missing: {relative_path}")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            raise RuntimeError(
                "Installed SkillOpt does not match the reviewed upstream pin: "
                f"{relative_path}."
            )
    package_root = Path(distribution.locate_file("skillopt"))
    reviewed_files = sorted(
        (
            path
            for path in package_root.rglob("*")
            if path.is_file() and path.suffix in {".py", ".md"}
        ),
        key=lambda path: path.relative_to(package_root).as_posix(),
    )
    package_digest = hashlib.sha256()
    for path in reviewed_files:
        relative = path.relative_to(package_root).as_posix().encode("utf-8")
        package_digest.update(relative)
        package_digest.update(b"\0")
        package_digest.update(path.read_bytes())
        package_digest.update(b"\0")
    if package_digest.hexdigest() != _UPSTREAM_TREE_SHA256:
        raise RuntimeError(
            "Installed SkillOpt package tree does not match the reviewed upstream pin."
        )


def _validate_sample_id(value: object) -> str:
    sample_id = str(value or "").strip()
    if (
        not sample_id
        or sample_id in {".", ".."}
        or "/" in sample_id
        or "\\" in sample_id
        or "\x00" in sample_id
    ):
        raise ValueError(
            "SkillOpt sample IDs must be non-empty, path-safe directory names."
        )
    return sample_id


def _jsonable(value: object) -> object:
    """Return a deterministic JSON-compatible identity value."""

    if isinstance(value, Mapping):
        return {
            str(key): _jsonable(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_jsonable(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _normalized_items(
    items: Sequence[Mapping[str, Any]],
    *,
    name: str,
) -> tuple[dict[str, Any], ...]:
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in items:
        item = dict(raw)
        sample_id = _validate_sample_id(item.get("id"))
        if sample_id in seen:
            raise ValueError(f"{name} contains duplicate sample ID {sample_id!r}.")
        seen.add(sample_id)
        item["id"] = sample_id
        normalized.append(item)
    if not normalized:
        raise ValueError(f"{name} must contain at least one item.")
    return tuple(normalized)


def _item_with_context(
    item: Mapping[str, Any],
    *,
    phase: Literal["train", "selection"],
    split: str,
) -> dict[str, Any]:
    contextual = dict(item)
    contextual["_phase"] = phase
    contextual["_split"] = split
    return contextual


@dataclass(frozen=True, slots=True)
class RoleRolloutResult:
    """One question-level role trajectory returned by the MVAgent backend."""

    sample_id: str
    hard: float
    soft: float
    trajectory_text: str
    task_description: str
    task_type: str
    n_turns: int
    fail_reason: str = ""
    reference_text: str = ""
    predicted_answer: str = ""
    invoked: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "sample_id", _validate_sample_id(self.sample_id))
        hard = float(self.hard)
        soft = float(self.soft)
        if not math.isfinite(hard) or hard not in {0.0, 1.0}:
            raise ValueError("RoleRolloutResult.hard must be exactly 0 or 1.")
        if not math.isfinite(soft) or not 0.0 <= soft <= 1.0:
            raise ValueError("RoleRolloutResult.soft must be finite and in [0, 1].")
        invoked = bool(self.invoked)
        trajectory_text = str(self.trajectory_text or "").strip()
        if invoked and not trajectory_text:
            raise ValueError("RoleRolloutResult.trajectory_text must be non-empty.")
        n_turns = int(self.n_turns)
        if n_turns < 0:
            raise ValueError("RoleRolloutResult.n_turns must be non-negative.")
        object.__setattr__(self, "hard", hard)
        object.__setattr__(self, "soft", soft)
        object.__setattr__(self, "trajectory_text", trajectory_text)
        object.__setattr__(self, "task_description", str(self.task_description or ""))
        object.__setattr__(self, "task_type", str(self.task_type or ""))
        object.__setattr__(self, "n_turns", n_turns)
        object.__setattr__(self, "fail_reason", str(self.fail_reason or ""))
        object.__setattr__(self, "reference_text", str(self.reference_text or ""))
        object.__setattr__(self, "predicted_answer", str(self.predicted_answer or ""))
        object.__setattr__(self, "invoked", invoked)


@dataclass(frozen=True, slots=True)
class RoleRolloutRequest:
    """Frozen inputs for one target-role MVAgent rollout batch."""

    role: Role
    candidate_skill_set: SkillSet
    anchor_skill_set: SkillSet
    sample_ids: tuple[str, ...]
    phase: Literal["train", "selection"]
    split: str
    label: str
    output_dir: Path
    use_eval_feedback: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "role", Role(self.role))
        sample_ids = tuple(_validate_sample_id(item) for item in self.sample_ids)
        if not sample_ids or len(sample_ids) != len(set(sample_ids)):
            raise ValueError("RoleRolloutRequest sample IDs must be non-empty and unique.")
        if self.phase not in {"train", "selection"}:
            raise ValueError("RoleRolloutRequest.phase must be train or selection.")
        object.__setattr__(self, "sample_ids", sample_ids)
        object.__setattr__(self, "split", str(self.split or "").strip())
        object.__setattr__(self, "label", str(self.label or "").strip())
        object.__setattr__(self, "output_dir", Path(self.output_dir))
        object.__setattr__(self, "use_eval_feedback", bool(self.use_eval_feedback))


class RoleRolloutBackend(Protocol):
    """Execute and score complete MVAgent questions for one frozen coordinate."""

    def rollout(
        self,
        request: RoleRolloutRequest,
    ) -> Sequence[RoleRolloutResult]: ...


class FixedIdDataLoader(BaseDataLoader):
    """Deterministic train/selection loader over an already-frozen ID schedule."""

    def __init__(
        self,
        *,
        train_items: Sequence[Mapping[str, Any]],
        selection_items: Sequence[Mapping[str, Any]],
    ) -> None:
        self.train_items = _normalized_items(train_items, name="train_items")
        self.selection_items = _normalized_items(
            selection_items,
            name="selection_items",
        )
        train_ids = {str(item["id"]) for item in self.train_items}
        selection_ids = {str(item["id"]) for item in self.selection_items}
        if overlap := sorted(train_ids & selection_ids):
            raise ValueError(
                "Train and selection IDs must be disjoint: " + ", ".join(overlap[:5])
            )
        self._cfg: dict[str, Any] = {}

    @property
    def identity(self) -> Mapping[str, object]:
        return {
            "contract": "fixed-id-loader-v1",
            "train": [str(item["id"]) for item in self.train_items],
            "selection": [str(item["id"]) for item in self.selection_items],
            "items_hash": hash_json(
                {
                    "train": _jsonable(self.train_items),
                    "selection": _jsonable(self.selection_items),
                }
            ),
        }

    def setup(self, cfg: dict) -> None:
        self._cfg = dict(cfg)
        configured_train = int(cfg.get("train_size", 0) or 0)
        if configured_train and configured_train != len(self.train_items):
            raise ValueError(
                f"Configured train_size={configured_train} does not match the "
                f"frozen update set ({len(self.train_items)})."
            )
        configured_selection = int(cfg.get("sel_env_num", 0) or 0)
        if configured_selection and configured_selection != len(self.selection_items):
            raise ValueError(
                f"Configured sel_env_num={configured_selection} does not match the "
                f"frozen selection set ({len(self.selection_items)})."
            )

    def get_train_size(self) -> int:
        return len(self.train_items)

    def plan_train_epoch(
        self,
        *,
        epoch: int,
        steps_per_epoch: int,
        accumulation: int,
        batch_size: int,
        seed: int,
        **kwargs: Any,
    ) -> list[BatchSpec]:
        # MVAgent is a split-backed dataset. Delegate epoch scheduling to the
        # upstream split loader so its shuffle/refill semantics stay exact;
        # only attach the phase metadata needed by this adapter.
        upstream_batches = SplitDataLoader.plan_train_epoch(
            self,
            epoch=epoch,
            steps_per_epoch=steps_per_epoch,
            accumulation=accumulation,
            batch_size=batch_size,
            seed=seed,
            **kwargs,
        )
        return [
            BatchSpec(
                phase=batch.phase,
                split=batch.split,
                seed=batch.seed,
                batch_size=batch.batch_size,
                payload=[
                    _item_with_context(
                        item,
                        phase="train",
                        split=_TRAIN_SPLIT,
                    )
                    for item in (batch.payload or [])
                ],
                metadata=dict(batch.metadata),
            )
            for batch in upstream_batches
        ]

    def build_train_batch(
        self,
        batch_size: int,
        seed: int,
        **kwargs: Any,
    ) -> BatchSpec:
        upstream = SplitDataLoader.build_train_batch(
            self,
            batch_size=batch_size,
            seed=seed,
            **kwargs,
        )
        return BatchSpec(
            phase=upstream.phase,
            split=upstream.split,
            seed=upstream.seed,
            batch_size=upstream.batch_size,
            payload=[
                _item_with_context(item, phase="train", split=_TRAIN_SPLIT)
                for item in (upstream.payload or [])
            ],
            metadata=dict(upstream.metadata),
        )

    def build_eval_batch(
        self,
        env_num: int,
        split: str,
        seed: int,
        **kwargs: Any,
    ) -> BatchSpec:
        del kwargs
        normalized_split = str(split or "").strip()
        if normalized_split not in _SELECTION_SPLITS:
            raise ValueError(
                "FixedIdDataLoader exposes only the frozen selection split; "
                f"got {split!r}. Set SkillOpt eval_test=false."
            )
        requested = int(env_num or 0)
        if requested and requested != len(self.selection_items):
            raise ValueError(
                f"Selection requested {requested} items, but the frozen set contains "
                f"{len(self.selection_items)}."
            )
        return BatchSpec(
            phase="eval",
            split=normalized_split,
            seed=int(seed),
            batch_size=len(self.selection_items),
            payload=[
                _item_with_context(
                    item,
                    phase="selection",
                    split=normalized_split,
                )
                for item in self.selection_items
            ],
        )


class MVAgentRoleEnvAdapter(EnvAdapter):
    """Adapt one frozen Global or Video coordinate to upstream SkillOpt."""

    def __init__(
        self,
        *,
        role: Role,
        parent_role_skill: str,
        fixed_partner_skill: str,
        dataloader: FixedIdDataLoader,
        backend: RoleRolloutBackend,
        session_identity: str,
        target_system_prompt: str = "",
    ) -> None:
        self.role = Role(role)
        self.parent_role_skill = normalize_skill_text(parent_role_skill)
        self.fixed_partner_skill = normalize_skill_text(fixed_partner_skill)
        self.dataloader = dataloader
        self.backend = backend
        self.session_identity = str(session_identity or "").strip()
        if not self.session_identity:
            raise ValueError("session_identity must be non-empty.")
        self.target_system_prompt = str(target_system_prompt or "").strip()
        self.analyst_workers = 16
        self.failure_only = False
        self.minibatch_size = 8
        self.edit_budget = 4

    def setup(self, cfg: dict) -> None:
        super().setup(cfg)
        self.analyst_workers = int(cfg.get("analyst_workers", 16))
        self.failure_only = bool(cfg.get("failure_only", False))
        self.minibatch_size = int(cfg.get("minibatch_size", 8))
        self.edit_budget = int(cfg.get("edit_budget", 4))
        if self.analyst_workers <= 0 or self.minibatch_size <= 0:
            raise ValueError("SkillOpt worker and minibatch counts must be positive.")
        if self.edit_budget <= 0:
            raise ValueError("SkillOpt edit_budget must be positive.")
        self.dataloader.setup(cfg)

    def get_dataloader(self) -> BaseDataLoader:
        return self.dataloader

    def build_env_from_batch(self, batch: BatchSpec, **kwargs: Any) -> list[dict]:
        del kwargs
        return [dict(item) for item in (batch.payload or [])]

    def build_train_env(
        self,
        batch_size: int,
        seed: int,
        **kwargs: Any,
    ) -> list[dict]:
        batch = self.dataloader.build_train_batch(
            batch_size=batch_size,
            seed=seed,
            **kwargs,
        )
        return self.build_env_from_batch(batch)

    def build_eval_env(
        self,
        env_num: int,
        split: str,
        seed: int,
        **kwargs: Any,
    ) -> list[dict]:
        batch = self.dataloader.build_eval_batch(
            env_num=env_num,
            split=split,
            seed=seed,
            **kwargs,
        )
        return self.build_env_from_batch(batch)

    def get_task_types(self) -> list[str]:
        return sorted(
            {
                str(item.get("task_type") or f"mvagent_{self.role.value}")
                for item in (*self.dataloader.train_items, *self.dataloader.selection_items)
            }
        )

    def _skill_set(self, role_skill: str) -> SkillSet:
        normalized = normalize_skill_text(role_skill)
        if self.role is Role.GLOBAL:
            return SkillSet(
                global_skill=normalized,
                video_skill=self.fixed_partner_skill,
            )
        return SkillSet(
            global_skill=self.fixed_partner_skill,
            video_skill=normalized,
        )

    @property
    def anchor_skill_set(self) -> SkillSet:
        return self._skill_set(self.parent_role_skill)

    def rollout(
        self,
        env_manager: Sequence[Mapping[str, Any]],
        skill_content: str,
        out_dir: str,
        **kwargs: Any,
    ) -> list[dict]:
        items = [dict(item) for item in env_manager]
        if not items:
            return []
        sample_ids = tuple(_validate_sample_id(item.get("id")) for item in items)
        if len(sample_ids) != len(set(sample_ids)):
            raise ValueError("One SkillOpt rollout batch cannot repeat a sample ID.")
        phases = {str(item.get("_phase") or "") for item in items}
        splits = {str(item.get("_split") or "") for item in items}
        if len(phases) != 1 or phases.pop() not in {"train", "selection"}:
            raise ValueError("A rollout batch must have one explicit train/selection phase.")
        phase = str(items[0]["_phase"])
        if len(splits) != 1:
            raise ValueError("A rollout batch must come from one split.")
        split = str(items[0]["_split"])
        output_dir = Path(out_dir)
        normalized_role_skill = normalize_skill_text(skill_content)
        if len(normalized_role_skill.strip()) > MAX_SKILL_CHARS:
            return self._runtime_rejection_rows(
                items=items,
                output_dir=output_dir,
                phase=phase,
                reason=(
                    "Candidate Skill exceeds the MVAgent Runtime limit of "
                    f"{MAX_SKILL_CHARS} characters."
                ),
            )
        candidate = self._skill_set(skill_content)
        request = RoleRolloutRequest(
            role=self.role,
            candidate_skill_set=candidate,
            anchor_skill_set=self.anchor_skill_set,
            sample_ids=sample_ids,
            phase=phase,  # type: ignore[arg-type]
            split=split,
            label=(
                f"skillopt-{self.session_identity[:12]}-{self.role.value}-{phase}-"
                f"{candidate.skill_sha256(self.role)[:12]}"
            ),
            output_dir=output_dir,
            use_eval_feedback=bool(kwargs.get("use_eval_feedback", False)),
        )
        generated = tuple(self.backend.rollout(request))
        by_id: dict[str, RoleRolloutResult] = {}
        for result in generated:
            if not isinstance(result, RoleRolloutResult):
                raise TypeError("RoleRolloutBackend must return RoleRolloutResult objects.")
            if result.sample_id in by_id:
                raise ValueError("RoleRolloutBackend returned duplicate sample IDs.")
            by_id[result.sample_id] = result
        if set(by_id) != set(sample_ids):
            raise ValueError(
                "RoleRolloutBackend returned missing or unexpected sample IDs."
            )

        item_by_id = {str(item["id"]): item for item in items}
        rows: list[dict[str, object]] = []
        for sample_id in sample_ids:
            result = by_id[sample_id]
            if result.invoked:
                prediction_dir = output_dir / "predictions" / sample_id
                prediction_dir.mkdir(parents=True, exist_ok=True)
                conversation_path = prediction_dir / "conversation.json"
                conversation = [
                    {
                        "role": "assistant",
                        "content": result.trajectory_text,
                    }
                ]
                temporary_path = conversation_path.with_suffix(".json.tmp")
                temporary_path.write_text(
                    json.dumps(conversation, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                temporary_path.replace(conversation_path)

            item = item_by_id[sample_id]
            reference_text = (
                result.reference_text or self.build_reference_text(item)
                if phase == "train" and self.role is Role.GLOBAL
                else ""
            )
            row: dict[str, object] = {
                "id": sample_id,
                "hard": result.hard,
                "soft": result.soft,
                "n_turns": result.n_turns,
                "fail_reason": result.fail_reason,
                "task_description": (
                    result.task_description
                    or str(item.get("task_description") or item.get("instruction") or "")
                ),
                "task_type": (
                    result.task_type
                    or str(item.get("task_type") or f"mvagent_{self.role.value}")
                ),
                "predicted_answer": result.predicted_answer,
                "reference_text": reference_text,
                "target_role_invoked": result.invoked,
            }
            if self.target_system_prompt:
                row["target_system_prompt"] = self.target_system_prompt
            rows.append(row)
        return rows

    def _runtime_rejection_rows(
        self,
        *,
        items: Sequence[Mapping[str, Any]],
        output_dir: Path,
        phase: str,
        reason: str,
    ) -> list[dict[str, object]]:
        """Represent an online Runtime contract rejection as failed episodes.

        SkillOpt still owns candidate selection: returning zero-valued episodes
        lets its stock selection Gate reject an unusable update without a
        process-level exception.  Train episodes retain a compact conversation
        so the upstream Reflect stage can diagnose the failure; Eval episodes
        never receive hidden references.
        """

        rows: list[dict[str, object]] = []
        for item in items:
            sample_id = _validate_sample_id(item.get("id"))
            if phase == "train":
                prediction_dir = output_dir / "predictions" / sample_id
                prediction_dir.mkdir(parents=True, exist_ok=True)
                conversation_path = prediction_dir / "conversation.json"
                temporary_path = conversation_path.with_suffix(".json.tmp")
                temporary_path.write_text(
                    json.dumps(
                        [{"role": "system", "content": reason}],
                        ensure_ascii=False,
                        indent=2,
                    )
                    + "\n",
                    encoding="utf-8",
                )
                temporary_path.replace(conversation_path)
            row: dict[str, object] = {
                "id": sample_id,
                "hard": 0.0,
                "soft": 0.0,
                "n_turns": 0,
                "fail_reason": reason,
                "task_description": str(
                    item.get("task_description") or item.get("instruction") or ""
                ),
                "task_type": str(
                    item.get("task_type") or f"mvagent_{self.role.value}"
                ),
                "predicted_answer": "",
                "reference_text": (
                    self.build_reference_text(dict(item))
                    if phase == "train" and self.role is Role.GLOBAL
                    else ""
                ),
                "target_role_invoked": False,
            }
            if self.target_system_prompt:
                row["target_system_prompt"] = self.target_system_prompt
            rows.append(row)
        return rows


@dataclass(frozen=True, slots=True)
class CoordinateRunResult:
    """Validated public artifacts from one complete upstream Trainer run."""

    child_skill: str | None
    best_score: float
    best_step: int
    artifact_root: Path
    session_identity: str
    parent_hash: str
    partner_hash: str
    child_hash: str | None


class _Trainer(Protocol):
    def train(self) -> Mapping[str, Any]: ...


TrainerFactory = Callable[[dict[str, Any], EnvAdapter], _Trainer]


class SkillOptCoordinateRunner:
    """Run the stock SkillOpt trainer for one role while freezing its partner."""

    def __init__(
        self,
        *,
        backend: RoleRolloutBackend,
        artifact_root: str | Path,
        target_system_prompt: str | Mapping[Role, str] = "",
        trainer_factory: TrainerFactory | None = None,
    ) -> None:
        verify_upstream_installation()
        self.backend = backend
        self.artifact_root = Path(artifact_root)
        if isinstance(target_system_prompt, Mapping):
            self.target_system_prompts = {
                Role(role): str(prompt or "").strip()
                for role, prompt in target_system_prompt.items()
            }
        else:
            shared = str(target_system_prompt or "").strip()
            self.target_system_prompts = {
                Role.GLOBAL: shared,
                Role.VIDEO: shared,
            }
        self.trainer_factory: TrainerFactory = trainer_factory or ReflACTTrainer

    @staticmethod
    def session_identity(
        *,
        structured_config: Mapping[str, Any],
        role: Role,
        parent_role_skill: str,
        fixed_partner_skill: str,
        update_items: Sequence[Mapping[str, Any]],
        selection_items: Sequence[Mapping[str, Any]],
        session_metadata: Mapping[str, Any] | None = None,
    ) -> str:
        loader = FixedIdDataLoader(
            train_items=update_items,
            selection_items=selection_items,
        )
        return hash_json(
            {
                "contract": _ADAPTER_CONTRACT,
                "config": _jsonable(structured_config),
                "role": Role(role).value,
                "parent_sha256": sha256_text(normalize_skill_text(parent_role_skill)),
                "partner_sha256": sha256_text(normalize_skill_text(fixed_partner_skill)),
                "reflection_success_policy": dict(REFLECTION_SUCCESS_POLICY),
                "loader": dict(loader.identity),
                "metadata": _jsonable(session_metadata or {}),
            }
        )

    def run(
        self,
        *,
        structured_config: Mapping[str, Any],
        role: Role,
        parent_role_skill: str,
        fixed_partner_skill: str,
        update_items: Sequence[Mapping[str, Any]],
        selection_items: Sequence[Mapping[str, Any]],
        session_metadata: Mapping[str, Any] | None = None,
    ) -> CoordinateRunResult:
        role = Role(role)
        parent_skill = normalize_skill_text(parent_role_skill)
        partner_skill = normalize_skill_text(fixed_partner_skill)
        for label, content in (
            ("parent role Skill", parent_skill),
            ("frozen partner Skill", partner_skill),
        ):
            if len(content.strip()) > MAX_SKILL_CHARS:
                raise ValueError(
                    f"{label} exceeds the MVAgent Runtime limit of "
                    f"{MAX_SKILL_CHARS} characters."
                )
        source_dataloader = FixedIdDataLoader(
            train_items=update_items,
            selection_items=selection_items,
        )
        identity = self.session_identity(
            structured_config=structured_config,
            role=role,
            parent_role_skill=parent_skill,
            fixed_partner_skill=partner_skill,
            update_items=update_items,
            selection_items=selection_items,
            session_metadata=session_metadata,
        )
        run_root = self.artifact_root / role.value / identity
        run_root.mkdir(parents=True, exist_ok=True)
        parent_path = run_root / "parent_skill.md"
        self._write_or_verify(parent_path, parent_skill)

        eligible_update_items = self._eligible_update_items(
            role=role,
            parent_role_skill=parent_skill,
            fixed_partner_skill=partner_skill,
            update_items=source_dataloader.train_items,
            run_root=run_root,
            session_identity=identity,
        )
        manifest = {
            "contract": _ADAPTER_CONTRACT,
            "session_identity": identity,
            "role": role.value,
            "parent_sha256": sha256_text(parent_skill),
            "partner_sha256": sha256_text(partner_skill),
            "reflection_success_policy": dict(REFLECTION_SUCCESS_POLICY),
            "source_update_ids": [
                str(item["id"]) for item in source_dataloader.train_items
            ],
            "eligible_update_ids": [
                str(item["id"]) for item in eligible_update_items
            ],
            "selection_ids": [
                str(item["id"]) for item in source_dataloader.selection_items
            ],
            "config_sha256": hash_json(_jsonable(structured_config)),
            "metadata_sha256": hash_json(_jsonable(session_metadata or {})),
        }
        manifest_path = run_root / "session.json"
        self._write_or_verify(
            manifest_path,
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )
        if not eligible_update_items:
            best_path = run_root / "best_skill.md"
            state_path = run_root / "runtime_state.json"
            self._write_or_verify(best_path, parent_skill)
            self._write_or_verify(
                state_path,
                json.dumps(
                    {"best_score": -1000.0, "best_step": 0},
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
            )
            self._write_or_verify(
                run_root / "skipped.json",
                json.dumps(
                    {
                        "reason": "target Planner was not invoked in the parent Train pool",
                        "role": role.value,
                    },
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
            )
            return CoordinateRunResult(
                child_skill=None,
                best_score=-1000.0,
                best_step=0,
                artifact_root=run_root,
                session_identity=identity,
                parent_hash=sha256_text(parent_skill),
                partner_hash=sha256_text(partner_skill),
                child_hash=None,
            )
        dataloader = FixedIdDataLoader(
            train_items=eligible_update_items,
            selection_items=source_dataloader.selection_items,
        )

        config_copy = copy.deepcopy(dict(structured_config))
        flat = dict(flatten_config(config_copy))
        self._require_or_set(flat, "train_size", len(dataloader.train_items))
        self._require_or_set(flat, "sel_env_num", len(dataloader.selection_items))
        if bool(flat.get("eval_test", False)):
            raise ValueError(
                "MVAgent coordinate optimization has no SkillOpt test split; "
                "set evaluation.eval_test=false."
            )
        flat["eval_test"] = False
        flat["skill_init"] = str(parent_path.resolve())
        flat["out_root"] = str(run_root.resolve())

        adapter = MVAgentRoleEnvAdapter(
            role=role,
            parent_role_skill=parent_skill,
            fixed_partner_skill=partner_skill,
            dataloader=dataloader,
            backend=self.backend,
            session_identity=identity,
            target_system_prompt=self.target_system_prompts.get(role, ""),
        )
        trainer = self.trainer_factory(flat, adapter)
        trainer.train()

        best_path = run_root / "best_skill.md"
        state_path = run_root / "runtime_state.json"
        if not best_path.is_file() or not state_path.is_file():
            raise RuntimeError(
                "SkillOpt trainer did not produce best_skill.md and runtime_state.json."
            )
        best_skill = normalize_skill_text(best_path.read_text(encoding="utf-8"))
        try:
            runtime_state = json.loads(state_path.read_text(encoding="utf-8"))
            best_score = float(runtime_state["best_score"])
            best_step = int(runtime_state["best_step"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError("SkillOpt runtime_state.json is invalid.") from exc
        if not math.isfinite(best_score) or best_step < 0:
            raise RuntimeError("SkillOpt best score or step is invalid.")

        changed = best_skill != parent_skill
        child_hash = sha256_text(best_skill) if changed else None
        return CoordinateRunResult(
            child_skill=best_skill if changed else None,
            best_score=best_score,
            best_step=best_step,
            artifact_root=run_root,
            session_identity=identity,
            parent_hash=sha256_text(parent_skill),
            partner_hash=sha256_text(partner_skill),
            child_hash=child_hash,
        )

    def _eligible_update_items(
        self,
        *,
        role: Role,
        parent_role_skill: str,
        fixed_partner_skill: str,
        update_items: Sequence[Mapping[str, Any]],
        run_root: Path,
        session_identity: str,
    ) -> tuple[dict[str, Any], ...]:
        if role is Role.GLOBAL:
            return tuple(dict(item) for item in update_items)
        anchor = SkillSet(
            global_skill=fixed_partner_skill,
            video_skill=parent_role_skill,
        )
        sample_ids = tuple(str(item["id"]) for item in update_items)
        request = RoleRolloutRequest(
            role=role,
            candidate_skill_set=anchor,
            anchor_skill_set=anchor,
            sample_ids=sample_ids,
            phase="train",
            split=_TRAIN_SPLIT,
            label=f"skillopt-{session_identity[:12]}-video-eligibility",
            output_dir=run_root / "eligibility",
            use_eval_feedback=True,
        )
        results = tuple(self.backend.rollout(request))
        by_id = {result.sample_id: result for result in results}
        if len(by_id) != len(results) or set(by_id) != set(sample_ids):
            raise ValueError(
                "RoleRolloutBackend returned invalid eligibility results."
            )
        return tuple(
            dict(item)
            for item in update_items
            if by_id[str(item["id"])].invoked
        )

    @staticmethod
    def _require_or_set(flat: dict[str, Any], key: str, expected: int) -> None:
        configured = int(flat.get(key, 0) or 0)
        if configured and configured != expected:
            raise ValueError(
                f"Configured {key}={configured} does not match the frozen set ({expected})."
            )
        flat[key] = expected

    @staticmethod
    def _write_or_verify(path: Path, content: str) -> None:
        if path.exists():
            if path.read_text(encoding="utf-8") != content:
                raise RuntimeError(f"Session artifact identity mismatch: {path}")
            return
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(path)


__all__ = [
    "CoordinateRunResult",
    "FixedIdDataLoader",
    "MVAgentRoleEnvAdapter",
    "RoleRolloutBackend",
    "RoleRolloutRequest",
    "RoleRolloutResult",
    "SkillOptCoordinateRunner",
    "TrainerFactory",
    "verify_upstream_installation",
]
