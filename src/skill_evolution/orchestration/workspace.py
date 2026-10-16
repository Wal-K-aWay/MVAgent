from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from ..strategy.contracts import Role, SkillSet, SkillUpdateProposal


_CANDIDATE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
PROJECT_ROOT = Path(
    os.environ.get("MVAGENT_PROJECT_ROOT")
    or Path(__file__).resolve().parents[3]
).expanduser().resolve()
RUNTIME_SOURCE_ROOT = PROJECT_ROOT / "src"


def _json_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _config_without_skills(config: dict[str, Any]) -> dict[str, Any]:
    context = copy.deepcopy(config)
    agents = context.get("agents")
    if isinstance(agents, dict):
        for agent_name in ("global_agent", "video_agent"):
            agent = agents.get(agent_name)
            if isinstance(agent, dict):
                agent.pop("skill", None)
    return context


@dataclass(frozen=True)
class MaterializedCandidate:
    candidate_id: str
    directory: Path
    config_path: Path
    manifest_path: Path
    skill_set_hash: str
    rollout_context_hash: str


class CandidateWorkspace:
    """Materialize immutable rollout inputs outside the online source tree."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        if self.root == RUNTIME_SOURCE_ROOT or RUNTIME_SOURCE_ROOT in self.root.parents:
            raise ValueError("Skill evolution workspace must be outside src/.")
        allowed_project_root = PROJECT_ROOT / "outputs" / "skill_evolution"
        if (
            self.root == PROJECT_ROOT
            or PROJECT_ROOT in self.root.parents
            and not (
                self.root == allowed_project_root
                or allowed_project_root in self.root.parents
            )
        ):
            raise ValueError(
                "Repository-local candidates must stay under "
                "outputs/skill_evolution/."
            )
        self.root.mkdir(parents=True, exist_ok=True)

    def load(
        self,
        *,
        candidate_id: str,
        expected_skill_set_hash: str,
    ) -> MaterializedCandidate:
        """Load one existing immutable candidate and verify its content identity."""
        candidate_id = str(candidate_id).strip()
        if not _CANDIDATE_ID_RE.fullmatch(candidate_id):
            raise ValueError(f"Invalid candidate_id: {candidate_id!r}")
        directory = self.root / candidate_id
        manifest_path = directory / "skill_set.json"
        config_path = directory / "config.yaml"
        if not manifest_path.is_file() or not config_path.is_file():
            raise FileNotFoundError(f"Incomplete candidate workspace: {directory}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        actual_hash = str(manifest.get("skill_set_hash") or "")
        if actual_hash != str(expected_skill_set_hash):
            raise ValueError(
                f"Candidate {candidate_id} has SkillSet hash {actual_hash}, "
                f"expected {expected_skill_set_hash}."
            )
        return MaterializedCandidate(
            candidate_id=candidate_id,
            directory=directory,
            config_path=config_path,
            manifest_path=manifest_path,
            skill_set_hash=actual_hash,
            rollout_context_hash=str(manifest.get("rollout_context_hash") or ""),
        )

    def materialize(
        self,
        *,
        candidate_id: str,
        skill_set: SkillSet,
        base_config_path: str | Path,
        runtime_snapshot_sha256: str,
        parent_skill_set_hash: str = "",
        proposal: SkillUpdateProposal | None = None,
        update_errors: tuple[str, ...] = (),
    ) -> MaterializedCandidate:
        candidate_id = str(candidate_id).strip()
        if not _CANDIDATE_ID_RE.fullmatch(candidate_id):
            raise ValueError(f"Invalid candidate_id: {candidate_id!r}")
        runtime_snapshot_sha256 = str(runtime_snapshot_sha256).strip().lower()
        if not _SHA256_RE.fullmatch(runtime_snapshot_sha256):
            raise ValueError("runtime_snapshot_sha256 must be a 64-character hex digest.")

        base_path = Path(base_config_path).expanduser().resolve()
        if not base_path.is_file():
            raise FileNotFoundError(f"Base MVAgent config not found: {base_path}")
        config = yaml.safe_load(base_path.read_text(encoding="utf-8")) or {}
        if not isinstance(config, dict):
            raise ValueError("Base MVAgent config must be a YAML mapping.")
        agents = config.get("agents")
        if not isinstance(agents, dict):
            raise ValueError("Base MVAgent config must contain agents.")
        for agent_name in ("global_agent", "video_agent"):
            if not isinstance(agents.get(agent_name), dict):
                raise ValueError(f"Base config is missing agents.{agent_name}.")

        final_dir = self.root / candidate_id
        if final_dir.exists():
            raise FileExistsError(f"Candidate workspace already exists: {final_dir}")

        effective_config_sha256 = _json_hash(_config_without_skills(config))
        skill_set_hash = skill_set.skill_set_hash()
        rollout_context_hash = _json_hash(
            {
                "runtime_snapshot_sha256": runtime_snapshot_sha256,
                "effective_config_sha256": effective_config_sha256,
            }
        )
        stage_dir = Path(
            tempfile.mkdtemp(prefix=f".{candidate_id}.", dir=str(self.root))
        )
        try:
            role_manifest: dict[str, dict[str, Any]] = {}
            for role, agent_name in (
                (Role.GLOBAL, "global_agent"),
                (Role.VIDEO, "video_agent"),
            ):
                skill = skill_set.get(role)
                skill_sha256 = skill_set.skill_sha256(role)
                skill_dir = stage_dir / "skills"
                skill_dir.mkdir(parents=True, exist_ok=True)
                staged_skill_path = skill_dir / f"{role.value}.md"
                staged_skill_path.write_text(skill, encoding="utf-8")
                final_skill_path = final_dir / "skills" / f"{role.value}.md"
                if not skill:
                    agents[agent_name]["skill"] = {"enabled": False}
                    role_manifest[role.value] = {
                        "enabled": False,
                        "path": str(final_skill_path),
                        "sha256": skill_sha256,
                    }
                    continue

                agents[agent_name]["skill"] = {
                    "enabled": True,
                    "path": str(final_skill_path),
                    "sha256": skill_sha256,
                }
                role_manifest[role.value] = {
                    "enabled": True,
                    "path": str(final_skill_path),
                    "sha256": skill_sha256,
                }

            config_path = stage_dir / "config.yaml"
            config_path.write_text(
                yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            manifest = {
                "candidate_id": candidate_id,
                "skill_set_hash": skill_set_hash,
                "rollout_context_hash": rollout_context_hash,
                "parent_skill_set_hash": str(parent_skill_set_hash),
                "promotable": skill_set.is_promotable,
                "base_config_path": str(base_path),
                "base_config_sha256": hashlib.sha256(base_path.read_bytes()).hexdigest(),
                "effective_config_sha256": effective_config_sha256,
                "runtime_snapshot_sha256": runtime_snapshot_sha256,
                "roles": role_manifest,
            }
            _write_json(stage_dir / "skill_set.json", manifest)
            if proposal is not None or update_errors:
                _write_json(
                    stage_dir / "update_report.json",
                    {
                        "accepted": not update_errors,
                        "proposal": proposal.to_dict() if proposal is not None else None,
                        "errors": list(update_errors),
                    },
                )
            os.replace(stage_dir, final_dir)
        except Exception:
            shutil.rmtree(stage_dir, ignore_errors=True)
            raise

        return MaterializedCandidate(
            candidate_id=candidate_id,
            directory=final_dir,
            config_path=final_dir / "config.yaml",
            manifest_path=final_dir / "skill_set.json",
            skill_set_hash=skill_set_hash,
            rollout_context_hash=rollout_context_hash,
        )


__all__ = ["CandidateWorkspace", "MaterializedCandidate"]
