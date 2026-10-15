"""Unchanged upstream optimizer prompts plus MVAgent's task interface.

Provenance and licenses live beside the vendored prompt files. INTEGRATION and
JOINT_FORMAT describe deployment boundaries and serialization, not a new
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
GEPA = (_ROOT / "instruction_proposal.txt").read_text(encoding="utf-8")

INTEGRATION = (_ROOT / "integration.md").read_text(encoding="utf-8")
JOINT_FORMAT = (_ROOT / "joint_format.md").read_text(encoding="utf-8")
