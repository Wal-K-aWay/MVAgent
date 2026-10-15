"""SkillOpt-derived stages adapted to MVAgent role evidence and editing contracts.

Provenance and licenses live beside the vendored prompt files. INTEGRATION describes deployment boundaries and serialization, not a new
reflection method. The offline trainer supplies the dynamic evidence and limits.
"""

from pathlib import Path


_ROOT = Path(__file__).resolve().parent
SKILLOPT = {
    name: (_ROOT / f"{name}.md").read_text(encoding="utf-8")
    for name in (
        "analyst_error", "analyst_success", "merge_failure", "merge_success",
        "merge_final", "ranking", "slow_update", "meta_skill",
    )
}

INTEGRATION = (_ROOT / "integration.md").read_text(encoding="utf-8")

ROLES = {role: (_ROOT / f"role_{role}.md").read_text(encoding="utf-8") for role in ("global", "video")}
