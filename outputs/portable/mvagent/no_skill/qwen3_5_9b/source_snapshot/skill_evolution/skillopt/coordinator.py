"""Block-coordinate orchestration around complete upstream SkillOpt sessions.

The upstream trainer optimizes one Skill string at a time.  This module supplies
the small multi-Agent boundary around it: freeze the other role for a complete
trainer session, optionally accept the resulting full SkillSet, checkpoint that
role boundary atomically, and then move to the next coordinate.

No SkillOpt implementation helper is imported here.  A coordinate is delegated
through the public MVAgent adapter contract in :mod:`.adapter`.
"""

from __future__ import annotations

import copy
import json
import math
import os
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from ..strategy.contracts import (
    Role,
    SkillSet,
    hash_json,
    normalize_skill_text,
    sha256_text,
)
from .adapter import CoordinateRunResult, SkillOptCoordinateRunner


_COORDINATOR_CONTRACT = "mvagent-skillopt-role-coordinator-v2"
_CHECKPOINT_VERSION = 1


class CoordinateRunner(Protocol):
    """Public adapter operation needed by the outer coordinator."""

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
    ) -> CoordinateRunResult: ...


@dataclass(frozen=True, slots=True)
class RoleSessionCandidate:
    """Complete-system candidate emitted by one finished role session."""

    session_index: int
    round_index: int
    role_position: int
    role: Role
    session_identity: str
    parent_skill_set: SkillSet
    candidate_skill_set: SkillSet
    coordinate_result: CoordinateRunResult

    @property
    def changed(self) -> bool:
        return self.parent_skill_set != self.candidate_skill_set


CompleteSystemAcceptance = Callable[[RoleSessionCandidate], bool]


@dataclass(frozen=True, slots=True)
class RoleSessionRecord:
    """Durable outcome of one complete, immutable-partner role session."""

    session_index: int
    round_index: int
    role_position: int
    role: Role
    session_identity: str
    session_dir: Path
    parent_skill_set_hash: str
    target_parent_hash: str
    partner_hash: str
    candidate_skill_set_hash: str
    committed_skill_set_hash: str
    child_hash: str | None
    best_score: float
    best_step: int
    accepted: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "session_index": self.session_index,
            "round_index": self.round_index,
            "role_position": self.role_position,
            "role": self.role.value,
            "session_identity": self.session_identity,
            "session_dir": str(self.session_dir),
            "parent_skill_set_hash": self.parent_skill_set_hash,
            "target_parent_hash": self.target_parent_hash,
            "partner_hash": self.partner_hash,
            "candidate_skill_set_hash": self.candidate_skill_set_hash,
            "committed_skill_set_hash": self.committed_skill_set_hash,
            "child_hash": self.child_hash,
            "best_score": self.best_score,
            "best_step": self.best_step,
            "accepted": self.accepted,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> RoleSessionRecord:
        try:
            return cls(
                session_index=int(value["session_index"]),
                round_index=int(value["round_index"]),
                role_position=int(value["role_position"]),
                role=Role(value["role"]),
                session_identity=str(value["session_identity"]),
                session_dir=Path(value["session_dir"]),
                parent_skill_set_hash=str(value["parent_skill_set_hash"]),
                target_parent_hash=str(value["target_parent_hash"]),
                partner_hash=str(value["partner_hash"]),
                candidate_skill_set_hash=str(value["candidate_skill_set_hash"]),
                committed_skill_set_hash=str(value["committed_skill_set_hash"]),
                child_hash=(
                    str(value["child_hash"])
                    if value.get("child_hash") is not None
                    else None
                ),
                best_score=float(value["best_score"]),
                best_step=int(value["best_step"]),
                accepted=bool(value["accepted"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                "Coordinator checkpoint contains an invalid session."
            ) from exc


@dataclass(frozen=True, slots=True)
class RoleSessionEvolutionResult:
    """Final SkillSet and all role-boundary decisions for one outer run."""

    skill_set: SkillSet
    sessions: tuple[RoleSessionRecord, ...]
    coordinator_identity: str
    checkpoint_path: Path


@dataclass(frozen=True, slots=True)
class _ResumeState:
    next_session_index: int
    skill_set: SkillSet
    sessions: tuple[RoleSessionRecord, ...]


class RoleSessionCoordinator:
    """Optimize Global and Video Skills in complete alternating sessions.

    ``role_rounds`` repeats ``role_order``.  The non-target role is frozen for
    every call to the injected adapter runner, including all upstream epochs and
    slow updates inside that call.  The optional acceptance callable sees the
    complete parent and candidate SkillSets only after the upstream session has
    finished.
    """

    def __init__(
        self,
        *,
        runner: CoordinateRunner,
        structured_config: Mapping[str, Any],
        update_items: Sequence[Mapping[str, Any]],
        selection_items: Sequence[Mapping[str, Any]],
        output_root: str | Path,
        role_rounds: int = 1,
        role_order: Sequence[Role] = (Role.GLOBAL, Role.VIDEO),
        accept_candidate: CompleteSystemAcceptance | None = None,
        identity: Mapping[str, Any] | None = None,
        session_metadata: Mapping[str, Any] | None = None,
    ) -> None:
        if (
            isinstance(role_rounds, bool)
            or not isinstance(role_rounds, int)
            or role_rounds < 1
        ):
            raise ValueError("role_rounds must be a positive integer.")
        normalized_order = tuple(Role(role) for role in role_order)
        if not normalized_order:
            raise ValueError("role_order must contain at least one role.")
        if len(normalized_order) != len(set(normalized_order)):
            raise ValueError("role_order cannot repeat a role within one round.")

        self.runner = runner
        self.structured_config = copy.deepcopy(dict(structured_config))
        self.update_items = tuple(copy.deepcopy(dict(item)) for item in update_items)
        self.selection_items = tuple(
            copy.deepcopy(dict(item)) for item in selection_items
        )
        if not self.update_items or not self.selection_items:
            raise ValueError("update_items and selection_items must both be non-empty.")
        self.output_root = Path(output_root).expanduser().resolve()
        self.checkpoint_path = self.output_root / "state" / "coordinator.json"
        self.role_rounds = role_rounds
        self.role_order = normalized_order
        self.accept_candidate = accept_candidate
        self.extra_identity = copy.deepcopy(dict(identity or {}))
        self.extra_session_metadata = copy.deepcopy(dict(session_metadata or {}))

    def run(
        self,
        *,
        initial_skill_set: SkillSet,
        resume: bool = False,
    ) -> RoleSessionEvolutionResult:
        """Run or resume from the last atomically completed role boundary."""

        coordinator_identity = self._coordinator_identity(initial_skill_set)
        if resume:
            restored = self._load_checkpoint(
                expected_identity=coordinator_identity,
                initial_skill_set=initial_skill_set,
            )
        else:
            if self.checkpoint_path.exists():
                raise FileExistsError(
                    f"Coordinator checkpoint already exists: {self.checkpoint_path}. "
                    "Pass resume=True to continue it."
                )
            restored = None

        current = restored.skill_set if restored is not None else initial_skill_set
        records = list(restored.sessions if restored is not None else ())
        next_index = restored.next_session_index if restored is not None else 0
        total_sessions = self.role_rounds * len(self.role_order)

        for session_index in range(next_index, total_sessions):
            round_index, role_position = divmod(
                session_index,
                len(self.role_order),
            )
            role = self.role_order[role_position]
            partner_role = _partner_role(role)
            parent = current
            parent_role_skill = parent.get(role)
            fixed_partner_skill = parent.get(partner_role)
            metadata = self._session_metadata(
                coordinator_identity=coordinator_identity,
                session_index=session_index,
                round_index=round_index,
                role_position=role_position,
            )
            expected_session_identity = SkillOptCoordinateRunner.session_identity(
                structured_config=self.structured_config,
                role=role,
                parent_role_skill=parent_role_skill,
                fixed_partner_skill=fixed_partner_skill,
                update_items=self.update_items,
                selection_items=self.selection_items,
                session_metadata=metadata,
            )

            coordinate_result = self.runner.run(
                structured_config=self.structured_config,
                role=role,
                parent_role_skill=parent_role_skill,
                fixed_partner_skill=fixed_partner_skill,
                update_items=self.update_items,
                selection_items=self.selection_items,
                session_metadata=metadata,
            )
            candidate = self._candidate_skill_set(
                role=role,
                parent=parent,
                result=coordinate_result,
                expected_session_identity=expected_session_identity,
            )
            session_candidate = RoleSessionCandidate(
                session_index=session_index,
                round_index=round_index,
                role_position=role_position,
                role=role,
                session_identity=expected_session_identity,
                parent_skill_set=parent,
                candidate_skill_set=candidate,
                coordinate_result=coordinate_result,
            )
            accepted = self._accept(session_candidate)
            current = candidate if accepted else parent

            record = RoleSessionRecord(
                session_index=session_index,
                round_index=round_index,
                role_position=role_position,
                role=role,
                session_identity=expected_session_identity,
                session_dir=Path(coordinate_result.artifact_root),
                parent_skill_set_hash=parent.skill_set_hash(),
                target_parent_hash=parent.skill_sha256(role),
                partner_hash=parent.skill_sha256(partner_role),
                candidate_skill_set_hash=candidate.skill_set_hash(),
                committed_skill_set_hash=current.skill_set_hash(),
                child_hash=coordinate_result.child_hash,
                best_score=float(coordinate_result.best_score),
                best_step=int(coordinate_result.best_step),
                accepted=accepted,
            )
            records.append(record)
            self._save_checkpoint(
                coordinator_identity=coordinator_identity,
                initial_skill_set=initial_skill_set,
                next_session_index=session_index + 1,
                skill_set=current,
                sessions=records,
            )

        return RoleSessionEvolutionResult(
            skill_set=current,
            sessions=tuple(records),
            coordinator_identity=coordinator_identity,
            checkpoint_path=self.checkpoint_path,
        )

    def _accept(self, candidate: RoleSessionCandidate) -> bool:
        if not candidate.changed:
            return False
        if self.accept_candidate is None:
            return True
        decision = self.accept_candidate(candidate)
        if not isinstance(decision, bool):
            raise TypeError("accept_candidate must return bool.")
        return decision

    def _candidate_skill_set(
        self,
        *,
        role: Role,
        parent: SkillSet,
        result: CoordinateRunResult,
        expected_session_identity: str,
    ) -> SkillSet:
        if not isinstance(result, CoordinateRunResult):
            raise TypeError("CoordinateRunner must return CoordinateRunResult.")
        expected_parent_hash = parent.skill_sha256(role)
        expected_partner_hash = parent.skill_sha256(_partner_role(role))
        if result.session_identity != expected_session_identity:
            raise RuntimeError("Coordinate result belongs to a different session.")
        if result.parent_hash != expected_parent_hash:
            raise RuntimeError(
                "Coordinate result parent hash does not match this role."
            )
        if result.partner_hash != expected_partner_hash:
            raise RuntimeError(
                "Coordinate result partner hash does not match the freeze."
            )
        if Path(result.artifact_root).name != expected_session_identity:
            raise RuntimeError(
                "Coordinate result directory does not match its identity."
            )
        if not math.isfinite(float(result.best_score)) or int(result.best_step) < 0:
            raise RuntimeError("Coordinate result best score or step is invalid.")

        if result.child_skill is None:
            if result.child_hash is not None:
                raise RuntimeError(
                    "Unchanged coordinate result cannot have child_hash."
                )
            return parent

        child_skill = normalize_skill_text(result.child_skill)
        if child_skill == parent.get(role):
            raise RuntimeError("Unchanged coordinate result must use child_skill=None.")
        expected_child_hash = sha256_text(child_skill)
        if result.child_hash != expected_child_hash:
            raise RuntimeError("Coordinate result child hash is invalid.")
        candidate = parent.replace(role, child_skill)
        if candidate.get(_partner_role(role)) != parent.get(_partner_role(role)):
            raise RuntimeError("A role session attempted to change its frozen partner.")
        return candidate

    def _coordinator_identity(self, initial_skill_set: SkillSet) -> str:
        acceptance_identity: object = None
        if self.accept_candidate is not None:
            acceptance_identity = getattr(self.accept_candidate, "identity", None)
            if callable(acceptance_identity):
                acceptance_identity = acceptance_identity()
            acceptance_identity = {
                "type": (
                    f"{type(self.accept_candidate).__module__}."
                    f"{type(self.accept_candidate).__qualname__}"
                ),
                "identity": _jsonable(acceptance_identity),
            }
        return hash_json(
            {
                "contract": _COORDINATOR_CONTRACT,
                "initial_skill_set_hash": initial_skill_set.skill_set_hash(),
                "structured_config": _jsonable(self.structured_config),
                "update_items": _jsonable(self.update_items),
                "selection_items": _jsonable(self.selection_items),
                "role_rounds": self.role_rounds,
                "role_order": [role.value for role in self.role_order],
                "runner_type": (
                    f"{type(self.runner).__module__}.{type(self.runner).__qualname__}"
                ),
                "acceptance": acceptance_identity,
                "extra": _jsonable(self.extra_identity),
                "session_metadata": _jsonable(self.extra_session_metadata),
            }
        )

    def _session_metadata(
        self,
        *,
        coordinator_identity: str,
        session_index: int,
        round_index: int,
        role_position: int,
    ) -> dict[str, object]:
        return {
            "contract": _COORDINATOR_CONTRACT,
            "coordinator_identity": coordinator_identity,
            "session_index": session_index,
            "round_index": round_index,
            "role_position": role_position,
            "extra": copy.deepcopy(self.extra_session_metadata),
        }

    def _save_checkpoint(
        self,
        *,
        coordinator_identity: str,
        initial_skill_set: SkillSet,
        next_session_index: int,
        skill_set: SkillSet,
        sessions: Sequence[RoleSessionRecord],
    ) -> None:
        payload = {
            "checkpoint_version": _CHECKPOINT_VERSION,
            "contract": _COORDINATOR_CONTRACT,
            "coordinator_identity": coordinator_identity,
            "initial_skill_set_hash": initial_skill_set.skill_set_hash(),
            "role_rounds": self.role_rounds,
            "role_order": [role.value for role in self.role_order],
            "next_session_index": next_session_index,
            "skill_set": skill_set.to_dict(),
            "sessions": [record.to_dict() for record in sessions],
        }
        self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(
            prefix=f".{self.checkpoint_path.name}.",
            suffix=".tmp",
            dir=str(self.checkpoint_path.parent),
        )
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.checkpoint_path)
            directory = os.open(self.checkpoint_path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        except Exception:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise

    def _load_checkpoint(
        self,
        *,
        expected_identity: str,
        initial_skill_set: SkillSet,
    ) -> _ResumeState | None:
        if not self.checkpoint_path.is_file():
            return None
        try:
            value = json.loads(self.checkpoint_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("Coordinator checkpoint is unreadable.") from exc
        if not isinstance(value, Mapping):
            raise ValueError("Coordinator checkpoint must contain one JSON object.")
        if value.get("checkpoint_version") != _CHECKPOINT_VERSION:
            raise ValueError("Unsupported coordinator checkpoint version.")
        if value.get("contract") != _COORDINATOR_CONTRACT:
            raise ValueError("Coordinator checkpoint contract does not match.")
        if value.get("coordinator_identity") != expected_identity:
            raise ValueError("Coordinator checkpoint identity does not match this run.")
        if value.get("initial_skill_set_hash") != initial_skill_set.skill_set_hash():
            raise ValueError("Coordinator checkpoint initial SkillSet does not match.")
        if value.get("role_rounds") != self.role_rounds or value.get(
            "role_order"
        ) != [role.value for role in self.role_order]:
            raise ValueError("Coordinator checkpoint role schedule does not match.")

        try:
            next_session_index = int(value["next_session_index"])
            skill_value = value["skill_set"]
            skill_set = SkillSet(
                global_skill=skill_value["global_skill"],
                video_skill=skill_value["video_skill"],
            )
            raw_sessions = value["sessions"]
            sessions = tuple(RoleSessionRecord.from_dict(item) for item in raw_sessions)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Coordinator checkpoint state is invalid.") from exc

        total_sessions = self.role_rounds * len(self.role_order)
        if not 0 <= next_session_index <= total_sessions:
            raise ValueError("Coordinator checkpoint cursor is outside the schedule.")
        if len(sessions) != next_session_index:
            raise ValueError("Coordinator checkpoint cursor and sessions disagree.")
        for session_index, record in enumerate(sessions):
            round_index, role_position = divmod(
                session_index,
                len(self.role_order),
            )
            if (
                record.session_index != session_index
                or record.round_index != round_index
                or record.role_position != role_position
                or record.role is not self.role_order[role_position]
            ):
                raise ValueError("Coordinator checkpoint session schedule is invalid.")
        if (
            sessions
            and sessions[-1].committed_skill_set_hash != skill_set.skill_set_hash()
        ):
            raise ValueError(
                "Coordinator checkpoint committed SkillSet is inconsistent."
            )
        if not sessions and skill_set != initial_skill_set:
            raise ValueError(
                "Empty coordinator checkpoint changed the initial SkillSet."
            )
        return _ResumeState(
            next_session_index=next_session_index,
            skill_set=skill_set,
            sessions=sessions,
        )


def _partner_role(role: Role) -> Role:
    return Role.VIDEO if Role(role) is Role.GLOBAL else Role.GLOBAL


def _jsonable(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): _jsonable(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_jsonable(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Role):
        return value.value
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


__all__ = [
    "CompleteSystemAcceptance",
    "CoordinateRunner",
    "RoleSessionCandidate",
    "RoleSessionCoordinator",
    "RoleSessionEvolutionResult",
    "RoleSessionRecord",
]
