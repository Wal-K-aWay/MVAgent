# p03_reviser.md

调用：`Reviser._build_revision_prompt`，一条 `user` 消息，temperature `0.2`。

```text
# Skill Revision - Minimal Targeted Changes
You are repairing an **existing** skill (skill_wrong path). Read the full step-level trace; do not invent new scenarios.
{optional contrastive failure block}

## Task: Minimal Skill Revision
Revise an existing skill to prevent a similar future failure. Make **targeted, minimal changes** rather than complete rewrites.
### Revision Strategy
1. Add Preconditions  2. Add Negative Example  3. Clarify Ambiguity  4. Add Validation Step
### Constraints (CRITICAL)
- Preserve working parts; ONLY modify directly related content; prefer additive changes.
- Prefer add_precondition/add_negative_example/add_validation/clarify_procedure.
- NEVER install packages/create virtual environments; repetitive failures get max-3-retry guard.
{benchmark constraints; rejected-proposal history}

## Skill to Revise
ID/title/version/created_from/description/current body: {skill fields}
## Failure Context
task, step, observation[:250], wrong action, attribution weight/reason, history: {fault/attribution/history}
## Few-Shot Examples
{three examples: add_precondition, add_negative_example, unknown custom type}

## Output Schema (JSON) — prefer skill_profile (paper-aligned full replace)
```json
{"update_mode":"revise_existing", "target_skill_id":"{skill.id}", "revision_summary":"...",
 "skill_profile":{"title":"{skill.title}","principle":"Core rule (max 2 sentences)","when_to_apply":"Trigger patterns only — no task ids","procedure":["Step 1","Step 2","Step 3"],"qualification_criteria":"...","negative_example":{"what_not_to_do":"...","why_it_fails":"..."}}}
```
Legacy patch mode: revision_type, revision_summary, original_assessment, targeted_changes(section_modified,before,after,rationale), impact_assessment(severity_prevention,generalization_risk).
Types: add_precondition, add_negative_example, clarify_procedure, add_validation, reorder_workflow, remove_outdated, consolidate, generalize, specialize, none; unknown type appends a named section.
{active adapter reviser supplement}
{PromptProfile.model_specific_block('reviser')}
```

