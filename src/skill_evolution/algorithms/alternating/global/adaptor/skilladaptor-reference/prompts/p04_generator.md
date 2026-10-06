# p04_generator.md

调用：`Generator._build_generation_prompt`，一条 `user` 消息，temperature `0.3`。

```text
# Skill Generation from Failure Analysis
You are an expert agent debugger for SkillAdaptor. Distill a **compact**, **reusable** skill — one actionable patch per localized fault, transferable within the task category.
**Use Generator when:** skill_missing, cold-start empty bank, or reasoning_wrong soft patch. If Linker named a misleading skill, revision is preferred.

{contrastive failure block}
**Improvement direction:** {improvement_principle[:400]}
{optional targets/wrong artifact/rubric gap}
**Category workflow (primary / fallback / verify):** {workflow_anchor}
## Task category: {category}
## Rubric shapes for verification (NO answers)
{extracted rubric or generic shape}

## FORBIDDEN (meta-skill anti-patterns — instant reject)
- Logging/capturing/documenting transcripts/session_status as main procedure
- Monitoring the agent instead of solving task
- Task IDs or benchmark names in when_to_apply
- Numeric answers, expected scores, golden rubric values

## Required structure
1. Primary path using tools; 2. named fallback; 3. rubric-shape verify; 4. trajectory-grounded negative; 5. transferable observation-pattern scope.
## Hard Limits
- principle max 2 sentences; procedure 3-5 steps
- may name files in prompt; otherwise generic deliverable
- copy prompt branch/count/format constraints; never invent alternate scenario
- narrow in category, not one task id

## Input Context
Task ID/brief={task_id,task_brief}; Fault Step/Type={step,type}; trajectory window={trace}; Fault={observation,wrong action,principle}; existing skills={up to 5}; rejected proposals={optional}; adapter supplement={optional}.
## Output Schema
```json
{"title":"Concise skill name (5-8 words, domain-specific)","principle":"Core rule (1-2 sentences) — MUST include fallback + verify","when_to_apply":"Observation patterns when this skill applies","procedure":["Step 1: Primary...","Step 2: Fallback...","Step 3: Verification...","Step 4: Optional refine loop"],"validation_criteria":"Rubric-shape checks only (no leaked answers)","qualification_criteria":"Preconditions before applying","negative_example":{"what_not_to_do":"failure pattern","why_it_fails":"why score stays 0"}}
```
{PromptProfile.model_specific_block('generator')}
```

随后 Python 会做 shell/artifact enrichment、meta/trivial 拒绝和 1600-char 压缩，见主文第 5.4 节。

