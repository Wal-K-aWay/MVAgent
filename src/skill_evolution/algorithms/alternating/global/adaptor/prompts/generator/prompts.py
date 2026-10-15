"""Stage-specific authoring guidance; card format is shared in common.py."""

TASK = """# Skill Generation from Failure Analysis

Create one reusable whole-question Skill from the supplied failure evidence, following the shared card specification and content example."""

INPUT = """# Skill Generation from Failure Analysis

## Full Step-Level Trajectory and Input Context

{context}"""

GUIDELINES = """## Generation Guidelines

Turn the localized gap into a complete method for a recognizable question class. Use the supplied cases to determine meaningful action conditions and parameter/instruction rules."""

EXAMPLES = """## Generation Example

For an event-count comparison, state the completion definition in the relevant counting step. In the procedure, request timestamped events with analyze_videos; if a reported event is uncertain, request its completion cue in that video and interval; when comparable counts establish the requested relation, call answer."""

ANALYSIS = """## Analysis Instructions

1. Read the original question, localized step, prior evidence, parameters and results. Use ground truth to understand the failure; derive deployed decisions from evidence the Agent can obtain.
2. Identify the reusable gap and compare it with Previously rejected candidates. Separate a missing procedure from an adequate procedure that was not followed. Use Related cases from the original-input cluster to compare successful and unsuccessful procedures and define shared scope and relevant differences. Success does not prove Skill causality; cluster membership does not require one shared Skill. Identify the evidence or parameter rule that adds value beyond the Agent background; different subject matter alone does not justify a new method.
3. Express the method in concise numbered steps, placing necessary requirements beside the relevant steps. Specify initial acquisition, observable follow-up conditions, action parameters and instruction content, and the evidence condition for answer. For action_execution_error, use a publicly observable result defect as the trigger and specify a corrective request available to the Agent.
4. Preserve the decisive evidence dependency, not the full source log.
5. Check that the action guidance covers the question, uses valid parameters with available sources, and states sufficient evidence for completion. Test the applicability wording against a similar question requiring a different method. Return the full card within the supplied limit."""

STAGE_CONSTRAINTS = """## STAGE CONSTRAINTS

- Propose one method grounded in the supplied failure; novelty comes from a substantive decision rule.
- Preserve the question's evidence relationships, timing conventions and output requirements.
- Keep each per-video request within that video's information boundary.
- Treat rejected proposals as prior attempts, not as proof of a particular defect or future improvement."""

OUTPUT = """## Output Format

Return one Skill proposal JSON object only, matching the supplied Schema.

Fields:
The reference number is assigned by the program and is not an output field.
- `when_to_use`, `strategy` (strings): Non-empty English text following the Skill Card Design and Writing Specification.

Rules:

- Return a complete new card. Follow the shared numbered-step strategy format; encode line breaks inside JSON strings as \\n escapes.

- Keep when_to_use concise; the two text fields together within the supplied card length limit.
- Return JSON directly without Markdown fences or explanatory text outside the object.

Example:
{
  "when_to_use": "<applicability from the original question and video information>",
  "strategy": "<concise numbered condition/action/parameter instructions>"
}"""

GENERATOR = '\n\n'.join((INPUT, GUIDELINES, EXAMPLES, ANALYSIS, STAGE_CONSTRAINTS, OUTPUT))
