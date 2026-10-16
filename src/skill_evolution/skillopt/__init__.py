"""Public MVAgent-to-SkillOpt adapter boundary."""

from .adapter import (
    CoordinateRunResult,
    FixedIdDataLoader,
    MVAgentRoleEnvAdapter,
    RoleRolloutBackend,
    RoleRolloutRequest,
    RoleRolloutResult,
    SkillOptCoordinateRunner,
    TrainerFactory,
)
from .backend import MVAgentRoleRolloutBackend, RoleSampleMetadata
from .config import RoleSessionConfig, SkillOptEvolutionConfig, SkillOptRecipe
from .coordinator import (
    CompleteSystemAcceptance,
    CoordinateRunner,
    RoleSessionCandidate,
    RoleSessionCoordinator,
    RoleSessionEvolutionResult,
    RoleSessionRecord,
)
from .engine import (
    SkillOptEvolutionEngine,
    SkillOptEvolutionOutcome,
    SkillOptEvolutionRunResult,
)


__all__ = [
    "CompleteSystemAcceptance",
    "CoordinateRunResult",
    "CoordinateRunner",
    "FixedIdDataLoader",
    "MVAgentRoleEnvAdapter",
    "MVAgentRoleRolloutBackend",
    "RoleRolloutBackend",
    "RoleRolloutRequest",
    "RoleRolloutResult",
    "RoleSampleMetadata",
    "RoleSessionConfig",
    "RoleSessionCandidate",
    "RoleSessionCoordinator",
    "RoleSessionEvolutionResult",
    "RoleSessionRecord",
    "SkillOptCoordinateRunner",
    "SkillOptEvolutionConfig",
    "SkillOptEvolutionEngine",
    "SkillOptEvolutionOutcome",
    "SkillOptEvolutionRunResult",
    "SkillOptRecipe",
    "TrainerFactory",
]
