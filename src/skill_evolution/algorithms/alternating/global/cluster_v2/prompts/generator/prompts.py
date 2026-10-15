"""Complete new-card authorship under a validated NEW plan."""

TASK = """# Skill Generation

Implement the validated NEW plan as one reusable whole-question Skill. Follow the shared Skill Card Specification; do not reopen operation selection or library attribution.

## Inputs and their roles

- **plan**: The supported method gap, goal, evidence references and behavior to preserve. It defines the proposed capability.
- **issue / cases**: Analysis and original development evidence for checking the plan's assumptions and deriving executable rules. The reference answer is offline feedback, not visual evidence.
- **library_catalog / related_cards**: Existing scope and methods for avoiding duplication. An unused or unfollowed adequate instruction is not a missing method.
- **variant / earlier_edits**: This candidate's sequence number and previous alternatives under the same plan. They are proposals, not observed outcomes or rejection diagnoses.
- **max_card_words**: The assembled card's total word budget, defined by the shared specification.

## Generation requirements

1. Recover the recognizable task class from the original inputs: essential input relationship, main task and requested answer content. Remove incidental subject matter and case-specific answers.
2. Express the planned method as a complete numbered procedure: initial evidence acquisition, how returned evidence supports the task, observable conditions for a necessary follow-up, and sufficient evidence for answer.
3. Place the substantive repair at the affected decision. Name the required information, action and parameter/instruction sources. Follow-up requests must address a specific unresolved gap rather than repeat an unchanged request.
4. Check when_to_use against strategy: selection text identifies the task the method actually supports; strategy remains executable without that text. Preserve plan-supported successful behavior and task distinctions.
5. Compare earlier_edits, if present. Offer a substantively different supported method within the same plan; skip if only paraphrasing or an unsupported alternative is possible.

For an event-count method, define a completed event in the counting request, obtain timestamped occurrences, and recheck a disputed occurrence using its reported interval and completion cue. A general reminder to "count carefully" does not supply this method. A plan cannot be implemented by embedding the training answer or preferred option.

## Stage constraints

- Use the available actions and information boundaries defined in the background. Instruction dependencies must come from input or earlier returned results.
- Do not expand the plan's capability, invent observations or modify unrelated library cards.
- Do not replace a sufficient existing rule with repetition merely because the Agent failed to follow it.
- ID, role and stages are assigned by the program. Do not output metadata or extra content fields.
- An edit is a candidate, not an accepted improvement. Gate/Test evidence is unavailable.

## Output format

Return one JSON object only, matching the supplied Schema, without Markdown fences or surrounding text:
- **status**: edit or skip.
- **summary**: The substantive change and evidence supporting it, or why authorship is skipped.
- **when_to_use**: A nonempty English task-scope sentence for edit; null for skip.
- **strategy**: A complete nonempty English numbered procedure for edit; null for skip.

Return exactly these four fields. Encode line breaks inside JSON strings as \n escapes. Return skip if no grounded method can implement the plan while satisfying the shared card specification."""
TEMPLATE = "{context}"
