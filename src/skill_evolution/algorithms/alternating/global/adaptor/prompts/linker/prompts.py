"""Skill responsibility attribution with schema-constrained JSON output."""

TASK = """# Skill Revision Decision

You are an expert agent debugger analyzing whether the single Skill used throughout this question contributed to a localized failure. Decide whether to revise that Skill or generate a new method, and give the evidence for your decision. Selection happens once before the question is solved; repeated decision requests reuse the same guidance. Cases with no Skill go directly to generation without this attribution stage. The selector sees only the original question, options, video IDs and durations, and the card when_to_use."""

INPUT = """# Skill Revision Decision

{context}"""

GUIDELINES = """## Fault Type Context

- **action_selection_error**: The chosen action was unsuitable for the evidence need. Check whether this card directed it, omitted a necessary transition, or already supplied adequate guidance.
- **action_parameter_error**: The action was appropriate but its video IDs, clips or instruction were inadequate. Check the card's actual parameter rules and whether the Agent followed them.
- **action_execution_error**: An adequate action returned a demonstrably defective result, including an ordinary answer contradicting sufficient History. Distinguish a supported card defect from unreliable execution. A result defect alone does not establish a reason to revise the card.

Fault types describe individual trajectory steps, not Skill responsibility. Different steps in one trajectory may have different types.

## Attribution Guidelines

Assess the need for revision using:
1. **Direct Instruction Match**: Did guidance supplied to the Agent instruct the localized wrong action? Identify the actual rule and how the action followed it.
2. **Context Appropriateness**: Did a defect in the Skill's applicability conditions encourage its use in this situation? Applying a sound rule outside its stated conditions is an Agent selection or reasoning error.
3. **Omission**: Is a necessary check absent from the Skill's procedure within its stated scope? Identify the gap in the content. An existing check left unperformed is a failure to follow guidance; an adequate method left unused is a selection gap.
4. **Misleading Applicability**: Does the supplied evidence link misleading when_to_use text to an unsuitable selection? Explain that selection link separately from the guidance governing an action.

## Evidence Sources

- **Skill Used for This Question** contains the full text of the single card verified across this question's ordinary decisions. strategy provides decision guidance; when_to_use describes the task, method and initial selection conditions. Runtime finalization receives no direct Skill injection. Other library cards are outside this task.
- **Related Cases** states whether each case used this exact card version, another version, another card, or no card. Related cases are selected by original-input similarity and may be successful, unsuccessful or unlocalized. Success alone does not prove this Skill caused it, and an unlocalized case is not an identified fault. Only supported same-version failures can directly support a recurring defect in this card; other cases provide context. An earlier library version does not necessarily mean the card itself changed.
- **Localization** identifies the fault to assess and proposes an improvement principle. Check its claims against the trajectory and card text. The proposed improvement is a suggestion to evaluate, not an existing Skill instruction.
- **Trajectory** establishes what was requested, what evidence had arrived, and what was answered. A method that could have helped is a potential remedy. Attribute a content defect only when the evidence connects that defect to the localized decision.

## Decision Criteria

- **revise**: Identify a concrete content defect in the question Skill and evidence connecting it to the localized wrong action or unsuitable selection. The defect must be addressable by revising this card.
- **generate**: The evidence does not establish such a defect, for example adequate guidance was not followed, the missing method lies outside the card's scope, or a reasonable action returned defective evidence. This requests exploration of a reusable new method; it does not establish that a new card will improve results.

The Localizer's fault type is context, not the routing decision. No fault type forces revise without a supported content defect in the actual card."""

EXAMPLES = """## Examples

Hypothetical illustrations only; use the actual supplied input for decisions.

<example>
Fault: The question requires whole-video action counts. The Agent uses analyze_videos with instructions restricted to opening clips, then compares these partial counts.
Question Skill: opening-count guides the whole question and explicitly restricts counting to the opening.
Output:
{"status":"revise","reason":"The injected strategy explicitly restricts observation to opening clips despite the whole-video requirement."}
</example>

<example>
Fault type: action_execution_error.
Fault: A watch_videos request clearly specifies source-time coordinates. The report uses an inconsistent timestamp. The Agent accepts it and answers without resolving the inconsistency.
Question Skill: time-check was injected and explicitly requires reconciling time coordinates before answering.
Output:
{"status":"generate","reason":"The supplied guidance already requires the relevant check. The trace shows a defective report and failure to follow that guidance, rather than a supported defect in the Skill."}
</example>

<example>
Fault type: action_execution_error.
Fault: An adequately specified analyze_videos request returns an incorrect report. The public evidence reveals no inconsistency the Agent could identify before answering.
Question Skill: The supplied guidance contains no instruction contributing to the report defect.
Output:
{"status":"generate","reason":"The evidence establishes a report defect but no contributing defect in the question Skill; explore a reusable remedy."}
</example>
"""

ANALYSIS = """## Analysis Instructions

1. **Anchor the fault**: Use Step in Localization as the target. Identify that action, its parameters, and the evidence available before it. Its returned result can reveal what happened after execution; later decisions remain separate attribution targets.
2. **Check the question Skill**: Use the full card and its verified question-level usage. Identify which actual rule, missing check, or applicability defect could have contributed at the target step.
3. **Separate content from adherence**: Compare the proposed improvement with the actual card text. Determine whether it adds a necessary check, repeats an existing check, or introduces a method outside the card's scope. Evaluate the Agent's selection and execution of guidance separately from content defects.
4. **Use related cases as supporting evidence**: Related cases retain their own trajectories and card-version relationships. Assess the current fault first and state which related evidence supports an attribution.
5. **Choose the operation**: Return revise only with a supported content defect connected to the target step. Otherwise return generate. Explain the evidence and distinguish card defects from failures to follow adequate guidance."""

STAGE_CONSTRAINTS = """## STAGE CONSTRAINTS

- Analyze the Agent through its inputs, available actions and public results. Action implementation details are outside the attribution evidence.
- Assess each decision using the evidence available before that decision. Historical cases retain their original evidence boundaries.
- Assess only the single question Skill in used_skill. The program supplies the revision target.
- Fault type and group membership provide context; responsibility requires evidence from the actual guidance and trajectory.
- The output selects revision or generation. Candidate acceptance is decided later by Gate."""

OUTPUT = """## Output Format

Return one JSON object only, matching the supplied Schema.

Fields:
- `status` (string): `revise` or `generate`.
- `reason` (non-empty string): Evidence supporting the decision.

Rules:
- Return exactly status and reason, directly in the JSON object.
- For revise, identify the card defect and its connection to the localized failure.
- For generate, explain why revising this card is not supported by the evidence.
- Return JSON directly without Markdown fences or explanatory text outside the object.

Example (revision):
{"status":"revise","reason":"The strategy restricts counting to opening clips despite the question requiring full-video totals."}

Example (generation):
{"status":"generate","reason":"The card already requires the missing coverage check; the Agent did not follow it. No relevant content defect is established."}
"""

LINKER = '\n\n'.join((INPUT, GUIDELINES, EXAMPLES, ANALYSIS, STAGE_CONSTRAINTS, OUTPUT))
