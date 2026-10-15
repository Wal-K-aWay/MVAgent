"""Explicit offline Video evidence arms for the fixed-input development experiment."""
from copy import deepcopy

from skill_evolution.infra.trajectory import global_view


ATTRIBUTION_BOUNDARY = (
    "This appendix is offline diagnostic evidence, not information available to the Video Planner. "
    "A wrong system answer does not establish that this Video request failed. "
    "Separate instruction, observation, local planning/reporting, and downstream integration issues. "
    "Do not infer unobserved video facts from the reference answer. Propose no edit when the evidence "
    "does not support a Video-controllable improvement. Any deployed Video strategy must depend only "
    "on its local instruction, source duration, retained Memory and observations; never on references, "
    "sibling videos, Global History or future decisions. Do not copy question-specific answers into a Skill."
)


def video_evidence_arm(item, *, arm, artifact, task, reference, feedback, partner_skill):
    """Preserve the exact local trajectory and label; append only Train diagnostics.

    The caller must verify Train membership before supplying any reference.
    V2 uses the complete *public* Global view, not other videos' private steps.
    """
    if arm not in {"V0", "V1", "V2"}:
        raise ValueError(f"Unknown evidence arm: {arm}")
    result = deepcopy(item)
    if arm == "V0":
        return result
    result["offline_task_supervision"] = {
        "question": task, "reference": reference, "scorer_feedback": feedback,
        "scope": "Training-only task-level supervision; not a local Video ground-truth label.",
    }
    if arm == "V2":
        result["offline_system_context"] = global_view(artifact)
        result["frozen_global_skill"] = partner_skill
        result["attribution_boundary"] = ATTRIBUTION_BOUNDARY
    return result
