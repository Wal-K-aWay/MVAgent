"""Stage-specific authoring guidance; card format is shared in common.py."""

TASK = """# Skill Revision from Failure Analysis

Revise the attributed target Skill using the supplied evidence. Return a complete whole-question procedure following the shared card specification and content example."""

INPUT = """# Skill Revision from Failure Analysis

## Full Step-Level Trajectory and Input Context

{context}"""

GUIDELINES = """## Revision Guidelines

Preserve supported decision rules while making the complete card executable from the original input. When an old card starts after reports arrive or contains only recovery advice, add initial acquisition guidance and a completion condition within the supported question scope. Update action instructions and selection fields as needed. Retain effective task-specific constraints while removing generic reminders and repetition.

Place each repair at the affected decision: clarify a definition or parameter, specify the evidence a request should obtain, correct action ordering, or refine a completion condition. Strategy consists of concise condition/action/parameter instructions; necessary definitions and constraints are placed beside the affected steps. Make the conditions for further analysis and answer explicit. Preserve the decisive evidence dependency while removing log detail; a corrected path is enough."""

EXAMPLES = """## Revision Example

Old rule: "After conflicting counts arrive, check again, then answer."
Supported gap: the reports use different event definitions and the recheck repeats the same request.
Revision: state the common event definition in the relevant counting step. In the procedure, request timestamped events with analyze_videos; if an event is uncertain, name its interval and ask whether it completed; when comparable counts establish the requested relation, call answer. Update when_to_use to the original-input question class."""

ANALYSIS = """## Analysis Instructions

1. Compare the target Skill, Current case, Related cases and Revision reason at the localized decision. Distinguish a content defect from noncompliance or an action execution defect. Assess the Localizer's suggested repair against the actual evidence.
2. Use Recent failure history and Previously rejected candidates to identify recurring gaps and meaningful differences. Prior rejection alone does not establish the cause.
3. Repair the supported defect and express the complete target method in the shared numbered-step format, with concise action conditions and parameter/instruction rules. Compare successful and unsuccessful Related cases from the original-input cluster; preserve supported rules, without treating success as proof of Skill causality. Cluster membership does not establish a shared method or a defect in this card. Add missing initial acquisition, parameter sources and a completion condition needed to execute those rules. For an execution defect, specify its observable trigger and a supported corrective action.
4. Update when_to_use to conditions identifiable at selection time, preserving the distinction from neighboring methods. Check transfer beyond the supplied video content. Return every content field. Return skip if the evidence supports no justified content revision."""

STAGE_CONSTRAINTS = """## STAGE CONSTRAINTS

- Revise only the target Skill, preserving its identifier and supported scope.
- Use each case's own public evidence; group membership does not make observations interchangeable.
- Keep changes grounded in supported content defects and the shared card contract.
- Use history as Train evidence, not as proof of Gate behavior."""

OUTPUT = """## Output Format

Return one revision JSON object only, matching the supplied Schema.

Fields:
- `update_mode` (string): "revise_existing" for a justified revision, otherwise "skip".
- `target_skill_id` (string): The ID of Skill to revise, allowed by the supplied Schema.
- `revision_summary` (string): A non-empty explanation of what changes and why the supplied evidence supports it, or why revision is skipped.
- `skill_profile` (object or null): Exactly `when_to_use`, `strategy`, each a non-empty English string; null for skip.

Rules:
- Return exactly these four top-level fields in a single JSON object.
- For "revise_existing", provide the complete two-field profile, including unchanged text. Follow the shared numbered-step strategy format; encode line breaks inside JSON strings as \\n escapes.
- For "skip", keep target_skill_id and set skill_profile to null.
- Keep when_to_use concise; both text fields together within the supplied card length limit.
- Return JSON directly without Markdown fences or explanatory text outside the object.

Example (revise_existing):
{
  "update_mode": "revise_existing",
  "target_skill_id": "target-skill-id",
  "revision_summary": "<targeted change and the evidence supporting it>",
  "skill_profile": {
    "when_to_use": "<applicability from the original question and video information>",
    "strategy": "<complete revised numbered condition/action/parameter instructions>"
  }
}

Example (skip):
{
  "update_mode": "skip",
  "target_skill_id": "target-skill-id",
  "revision_summary": "<why no content revision is supported>",
  "skill_profile": null
}"""

REVISER = '\n\n'.join((INPUT, GUIDELINES, EXAMPLES, ANALYSIS, STAGE_CONSTRAINTS, OUTPUT))
