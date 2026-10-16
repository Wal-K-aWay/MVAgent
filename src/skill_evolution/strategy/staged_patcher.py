"""Two-stage diagnosis and role-local Skill patch generation."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from models.llm import LLMClient

from .contracts import (
    EditOp,
    Role,
    SkillDiagnosis,
    SkillEdit,
    SkillUpdateProposal,
    SkillUpdateRequest,
    hash_json,
)
from .optimizer_calls import OptimizerCallCache, optimizer_call_hash
from .patcher import (
    PROMPT_ROOT,
    ROLE_CONTRACTS,
    build_role_architectures,
    build_system_architecture,
    render_evidence_episodes,
    render_trace_case,
)


DIAGNOSIS_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "failure_source",
        "target_role",
        "pattern",
        "causal_evidence",
        "regression_risk",
        "expected_behavior_change",
    ],
    "properties": {
        "failure_source": {
            "type": "string",
            "enum": [
                "global",
                "video",
                "action_internal",
                "joint",
                "unattributed",
            ],
        },
        "target_role": {
            "type": "string",
            "enum": ["global", "video", "none"],
        },
        "pattern": {"type": "string"},
        "causal_evidence": {"type": "string"},
        "regression_risk": {"type": "string"},
        "expected_behavior_change": {"type": "string"},
    },
}


PATCH_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["edits"],
    "properties": {
        "edits": {
            "type": "array",
            "maxItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["op", "target", "content"],
                "properties": {
                    "op": {
                        "type": "string",
                        "enum": [op.value for op in EditOp],
                    },
                    "target": {"type": "string"},
                    "content": {"type": "string"},
                },
            },
        },
    },
}


_DIAGNOSIS_FIELDS = frozenset(DIAGNOSIS_OUTPUT_SCHEMA["required"])
_SOURCE_TARGETS: dict[str, frozenset[Role | None]] = {
    "global": frozenset({Role.GLOBAL, None}),
    "video": frozenset({Role.VIDEO, None}),
    "action_internal": frozenset({None}),
    "joint": frozenset({Role.GLOBAL, Role.VIDEO, None}),
    "unattributed": frozenset({None}),
}


def _render_template(
    template: str,
    replacements: Mapping[str, str],
    *,
    label: str,
) -> str:
    markers = set(re.findall(r"\{\{[a-z_]+\}\}", template))
    unknown = markers - set(replacements)
    if unknown:
        raise ValueError(
            f"Unknown placeholder in {label}: " + ", ".join(sorted(unknown))
        )
    missing = set(replacements) & markers
    pattern = re.compile("|".join(re.escape(item) for item in missing))
    return pattern.sub(lambda match: replacements[match.group(0)], template)


def _render_optimizer_memory(request: SkillUpdateRequest, role: Role | None) -> str:
    items = request.optimizer_memory
    if role is not None:
        target_prefix = f"[{role.value}]"
        role_prefixes = tuple(f"[{item.value}]" for item in Role)
        items = tuple(
            item
            for item in items
            if item.startswith(target_prefix)
            or not item.startswith(role_prefixes)
        )
    return "\n".join(f"- {item}" for item in items) or "None"


def _request_identity(request: SkillUpdateRequest) -> dict[str, Any]:
    assert request.parent_skill_set is not None
    return {
        "role": request.role.value,
        "parent_skill_set": request.parent_skill_set.to_dict(),
        "evidence": {
            "role": request.evidence.role.value,
            "signature": request.evidence.signature,
            "support_ids": list(request.evidence.support_ids),
            "contrast_ids": list(request.evidence.contrast_ids),
            "cases": [
                {**case.to_dict(), "source_group": case.source_group}
                for case in request.cases
            ],
        },
        "cycle": request.cycle,
        "candidate_number": request.candidate_number,
        "candidate_count": request.candidate_count,
        "seed": request.seed,
        "max_chars": request.max_chars,
        "max_changed_chars": request.max_changed_chars,
        "changed_char_budgets": {
            role.value: budget
            for role, budget in request.changed_char_budgets.items()
        },
        "generation": request.generation,
        "target_role_lock": (
            request.target_role_lock.value
            if request.target_role_lock is not None
            else None
        ),
        "optimizer_memory": list(request.optimizer_memory),
        "mode": request.mode,
        "min_support_cases": request.min_support_cases,
        "min_support_groups": request.min_support_groups,
    }


class PromptStagedSkillPatcher:
    """Freeze causal attribution before generating one target-role edit."""

    workflow = "diagnose_then_patch"

    def __init__(
        self,
        *,
        model: LLMClient,
        diagnosis_prompt_path: str | Path | None = None,
        patch_prompt_path: str | Path | None = None,
        system_architecture: str | None = None,
        role_architectures: Mapping[Role, str] | None = None,
        call_cache: OptimizerCallCache | None = None,
    ) -> None:
        self.model = model
        diagnosis_path = (
            Path(diagnosis_prompt_path)
            if diagnosis_prompt_path
            else PROMPT_ROOT / "diagnose.md"
        )
        patch_path = (
            Path(patch_prompt_path)
            if patch_prompt_path
            else PROMPT_ROOT / "patch.md"
        )
        self.diagnosis_template = diagnosis_path.read_text(
            encoding="utf-8"
        ).strip()
        self.patch_template = patch_path.read_text(encoding="utf-8").strip()
        self.system_architecture = str(
            system_architecture or build_system_architecture()
        ).strip()
        supplied_roles = role_architectures or build_role_architectures()
        self.role_architectures = {
            role: str(supplied_roles.get(role, ROLE_CONTRACTS[role])).strip()
            for role in Role
        }
        if not self.system_architecture or any(
            not value for value in self.role_architectures.values()
        ):
            raise ValueError("Optimizer architecture text must be non-empty.")
        self.call_cache = call_cache or OptimizerCallCache()

    @property
    def identity(self) -> Mapping[str, Any]:
        return {
            "workflow": self.workflow,
            "diagnosis_template": self.diagnosis_template,
            "diagnosis_output_schema": DIAGNOSIS_OUTPUT_SCHEMA,
            "patch_template": self.patch_template,
            "patch_output_schema": PATCH_OUTPUT_SCHEMA,
            "system_architecture": self.system_architecture,
            "role_architectures": {
                role.value: text
                for role, text in self.role_architectures.items()
            },
            "model": dict(getattr(self.model, "identity", {})),
        }

    def diagnose(
        self,
        request: SkillUpdateRequest,
        *,
        audit_context: Mapping[str, Any] | None = None,
    ) -> SkillDiagnosis | None:
        prompt = self.render_diagnosis_prompt(request)
        result, call_hash = self._call(
            stage="diagnosis",
            schema_name="skill_diagnosis",
            prompt=prompt,
            schema=DIAGNOSIS_OUTPUT_SCHEMA,
            request=request,
            audit_context=audit_context,
        )
        if result.get("status") != "ok":
            self._emit_parse_event(
                stage="diagnosis",
                call_hash=call_hash,
                audit_context=audit_context,
                status="invalid",
                error=str(result.get("error") or "structured model output was invalid"),
            )
            return None
        try:
            diagnosis = self._parse_diagnosis(result.get("value"), request)
        except (TypeError, ValueError) as exc:
            self._emit_parse_event(
                stage="diagnosis",
                call_hash=call_hash,
                audit_context=audit_context,
                status="invalid",
                error=str(exc),
            )
            return None
        self._emit_parse_event(
            stage="diagnosis",
            call_hash=call_hash,
            audit_context=audit_context,
            status="ok",
            diagnosis=diagnosis,
        )
        return diagnosis

    def patch(
        self,
        request: SkillUpdateRequest,
        diagnosis: SkillDiagnosis,
        *,
        audit_context: Mapping[str, Any] | None = None,
    ) -> Sequence[SkillUpdateProposal]:
        if diagnosis.target_role is not request.role:
            raise ValueError("Frozen diagnosis target does not match the Patch role.")
        if diagnosis.support_ids != request.evidence.support_ids or (
            diagnosis.contrast_ids != request.evidence.contrast_ids
        ):
            raise ValueError("Frozen diagnosis does not match the target evidence.")
        prompt = self.render_patch_prompt(request, diagnosis)
        result, call_hash = self._call(
            stage="patch",
            schema_name="skill_patch",
            prompt=prompt,
            schema=PATCH_OUTPUT_SCHEMA,
            request=request,
            diagnosis=diagnosis,
            audit_context=audit_context,
        )
        if result.get("status") != "ok":
            self._emit_parse_event(
                stage="patch",
                call_hash=call_hash,
                audit_context=audit_context,
                status="invalid",
                error=str(result.get("error") or "structured model output was invalid"),
            )
            return ()
        try:
            proposal = self._parse_patch(result.get("value"), request, diagnosis)
        except (TypeError, ValueError) as exc:
            self._emit_parse_event(
                stage="patch",
                call_hash=call_hash,
                audit_context=audit_context,
                status="invalid",
                error=str(exc),
            )
            return ()
        self._emit_parse_event(
            stage="patch",
            call_hash=call_hash,
            audit_context=audit_context,
            status="ok",
            diagnosis=diagnosis,
            edit_count=len(proposal.edits),
        )
        return (proposal,)

    def render_diagnosis_prompt(self, request: SkillUpdateRequest) -> str:
        rendered = render_evidence_episodes(request)
        assert request.parent_skill_set is not None
        return _render_template(
            self.diagnosis_template,
            {
                "{{system_architecture}}": self.system_architecture,
                "{{global_skill}}": request.parent_skill_set.global_skill or "None",
                "{{video_skill}}": request.parent_skill_set.video_skill or "None",
                "{{optimizer_memory}}": _render_optimizer_memory(request, None),
                "{{cases}}": rendered,
                "{{candidate_number}}": str(request.candidate_number),
                "{{candidate_count}}": str(request.candidate_count),
                "{{seed}}": str(request.seed),
                "{{target_role_rule}}": (
                    "- This candidate slot is locked to the `"
                    f"{request.target_role_lock.value}` Planner. Select only that "
                    "`target_role` when its Runtime-visible state establishes the "
                    "defect; otherwise select `none`. Do not select the other Planner."
                    if request.target_role_lock is not None
                    else ""
                ),
            },
            label="Skill diagnosis Prompt",
        )

    def render_patch_prompt(
        self,
        request: SkillUpdateRequest,
        diagnosis: SkillDiagnosis,
    ) -> str:
        by_id = {case.case_id: case for case in request.cases}
        rendered_sections: list[str] = []
        trajectory_number = 0
        for label, case_ids in (
            ("Failed trajectories", request.evidence.support_ids),
            ("Successful trajectories", request.evidence.contrast_ids),
        ):
            rendered: list[str] = []
            for case_id in case_ids:
                trajectory_number += 1
                rendered.append(
                    render_trace_case(
                        by_id[case_id],
                        heading=f"#### Trajectory {trajectory_number}",
                        include_failure_reason=False,
                    )
                )
            rendered_sections.append(
                f"### {label}\n\n" + ("\n\n".join(rendered) or "None")
            )
        diagnosis_text = "\n".join(
            (
                f"- Failure source: {diagnosis.failure_source}",
                f"- Target role: {request.role.value}",
                f"- Pattern: {diagnosis.pattern}",
                f"- Causal evidence: {diagnosis.causal_evidence}",
                f"- Regression risk: {diagnosis.regression_risk}",
                "- Expected behavior change: "
                f"{diagnosis.expected_behavior_change}",
            )
        )
        mode_instructions = (
            "Add or refine one missing conditional rule for the fixed target role."
            if request.mode == "discover"
            else "Repair the fixed target strategy using exactly one `replace` whose "
            "target is the complete current strategy and whose content is the complete "
            "repaired strategy. Preserve the recorded gain while removing the paired "
            "train regression."
        )
        return _render_template(
            self.patch_template,
            {
                "{{target_architecture}}": self.role_architectures[request.role],
                "{{target_role}}": request.role.value,
                "{{target_skill}}": request.parent_skill or "None",
                "{{optimizer_memory}}": _render_optimizer_memory(
                    request, request.role
                ),
                "{{cases}}": "\n\n".join(rendered_sections),
                "{{diagnosis}}": diagnosis_text,
                "{{mode_instructions}}": mode_instructions,
                "{{max_chars}}": str(request.max_chars),
                "{{changed_chars_rule}}": (
                    "- Keep the textual difference from the current target strategy "
                    f"within {request.max_changed_chars} changed characters. This "
                    "evidence-scaled budget limits insertions, deletions, and "
                    "replacements, not only net length growth."
                    if request.max_changed_chars is not None
                    else ""
                ),
            },
            label="Skill Patch Prompt",
        )

    def _call(
        self,
        *,
        stage: str,
        schema_name: str,
        prompt: str,
        schema: Mapping[str, Any],
        request: SkillUpdateRequest,
        diagnosis: SkillDiagnosis | None = None,
        audit_context: Mapping[str, Any] | None = None,
    ) -> tuple[dict[str, Any], str]:
        identity = {
            "contract_version": 1,
            "workflow": self.workflow,
            "stage": stage,
            "schema_name": schema_name,
            "prompt": prompt,
            "json_schema": dict(schema),
            "model": dict(getattr(self.model, "identity", {})),
            "request": _request_identity(request),
            "diagnosis": diagnosis.to_dict() if diagnosis is not None else None,
            "audit_context": dict(audit_context or {}),
        }
        call_hash = optimizer_call_hash(identity)
        context = {
            "stage": stage,
            "cycle": request.cycle,
            "source_role": request.evidence.role.value,
            "target_role": request.role.value if stage == "patch" else "pending",
            "candidate_number": request.candidate_number,
            "seed": request.seed,
            "mode": request.mode,
            "evidence_signature": request.evidence.signature,
            **dict(audit_context or {}),
        }
        result = self.call_cache.call(
            call_hash=call_hash,
            invoke=lambda: self.model.json_prompt(
                prompt,
                json_schema=dict(schema),
                schema_name=schema_name,
            ),
            audit_context=context,
        )
        return result, call_hash

    @staticmethod
    def _parse_diagnosis(
        raw: object,
        request: SkillUpdateRequest,
    ) -> SkillDiagnosis:
        if not isinstance(raw, Mapping) or set(raw) != _DIAGNOSIS_FIELDS:
            raise ValueError(
                "Diagnosis output fields do not match the six-field contract."
            )
        values = {
            key: str(raw[key] or "").strip()
            for key in _DIAGNOSIS_FIELDS
        }
        if any(not value for value in values.values()):
            raise ValueError("Every diagnosis output field must be non-empty.")
        target_text = values["target_role"].lower()
        target_role = None if target_text == "none" else Role(target_text)
        if (
            request.target_role_lock is not None
            and target_role is not None
            and target_role is not request.target_role_lock
        ):
            raise ValueError("Diagnosis target_role violates the candidate slot's role lock.")
        source = values["failure_source"].lower()
        if source not in _SOURCE_TARGETS or target_role not in _SOURCE_TARGETS[source]:
            raise ValueError(
                "failure_source and target_role violate the attribution boundary."
            )
        return SkillDiagnosis(
            pattern=values["pattern"],
            support_ids=request.evidence.support_ids,
            contrast_ids=request.evidence.contrast_ids,
            regression_risk=values["regression_risk"],
            expected_behavior_change=values["expected_behavior_change"],
            failure_source=source,
            target_role=target_role,
            causal_evidence=values["causal_evidence"],
        )

    @staticmethod
    def _parse_patch(
        raw: object,
        request: SkillUpdateRequest,
        diagnosis: SkillDiagnosis,
    ) -> SkillUpdateProposal:
        if not isinstance(raw, Mapping) or set(raw) != {"edits"}:
            raise ValueError("Patch output must contain exactly the edits field.")
        raw_edits = raw["edits"]
        if not isinstance(raw_edits, list):
            raise ValueError("Patch edits must be an array.")
        if len(raw_edits) > 1:
            raise ValueError("Patch output exceeds the one-edit budget.")
        edits: list[SkillEdit] = []
        for item in raw_edits:
            if not isinstance(item, Mapping) or set(item) != {
                "op",
                "target",
                "content",
            }:
                raise ValueError(
                    "Each Patch edit must contain exactly op, target, and content."
                )
            edits.append(
                SkillEdit(
                    op=EditOp(str(item["op"])),
                    target=str(item["target"]),
                    content=str(item["content"]),
                )
            )
        return SkillUpdateProposal(
            role=request.role,
            parent_sha256=request.parent_sha256,
            diagnosis=diagnosis,
            case_assessments=request.evidence.case_assessments,
            edits=tuple(edits),
        )

    def _emit_parse_event(
        self,
        *,
        stage: str,
        call_hash: str,
        audit_context: Mapping[str, Any] | None,
        status: str,
        error: str = "",
        diagnosis: SkillDiagnosis | None = None,
        edit_count: int | None = None,
    ) -> None:
        audit = self.call_cache.audit
        if audit is None:
            return
        event: dict[str, Any] = {
            "event": "parse_complete" if status == "ok" else "parse_invalid",
            "call_hash": call_hash,
            "source": "parser",
            "result_status": status,
            "audit_context": {
                "stage": stage,
                **dict(audit_context or {}),
            },
        }
        if error:
            event["error"] = error[:1_000]
        if diagnosis is not None:
            event["failure_source"] = diagnosis.failure_source
            event["target_role"] = (
                diagnosis.target_role.value
                if diagnosis.target_role is not None
                else "none"
            )
            event["diagnosis_hash"] = hash_json(diagnosis.to_dict())
        if edit_count is not None:
            event["edit_count"] = int(edit_count)
        audit(event)


__all__ = [
    "DIAGNOSIS_OUTPUT_SCHEMA",
    "PATCH_OUTPUT_SCHEMA",
    "PromptStagedSkillPatcher",
]
