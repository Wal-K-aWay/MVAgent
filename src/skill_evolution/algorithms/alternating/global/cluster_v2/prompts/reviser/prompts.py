"""Single-field revision with program-owned frozen content."""

TASK = """# Skill Revision

Implement the validated WHEN or STRATEGY plan on the supplied target card. Repair the supported defect while preserving effective content. The program copies the frozen field and metadata unchanged.

## Inputs and their roles

- **plan**: The operation, target ID, supported defect, goal, evidence references and behavior to preserve.
- **target_skill**: The exact complete card to revise. Inspect both fields to maintain their consistency, but return only the editable field.
- **issue / cases**: Analysis and original development evidence, including verified exposure and selection relationships. Check proposed repairs against the actual card and trajectory.
- **library_catalog / related_cards**: Context for retaining meaningful task distinctions; they are not additional revision targets.
- **variant / earlier_edits**: Previous alternatives under this plan; propose a substantive alternative, not a paraphrase. They do not establish rejection causes.
- **max_card_words**: The total assembled-card budget, including the frozen field.

## Revision requirements

1. Identify the exact wording or missing decision rule implicated by the plan. Separate an absent or misleading rule from adequate guidance that was ignored, unused or followed by unreliable execution.
2. Apply the operation-specific requirements below. Keep the operation and target fixed; skip if the requested field alone cannot implement a justified repair.
3. Preserve supported successful rules, evidence dependencies and prerequisites. Do not add case-specific answers, incidental restrictions or unrelated requirements.
4. Check the assembled card against the shared specification, including agreement between applicability and actual method. With earlier_edits, provide a substantively different supported repair or skip.

## Operation-specific requirements

- **WHEN**: Return a complete replacement when_to_use only. Make the supported task recognizable from the original question, options and video metadata, distinguishing input relationship, main task and answer content where necessary. The unchanged strategy must already support this scope. For example, a snapshot-count method should describe a count at a specified moment rather than an event total over time. Do not place execution instructions or unavailable observation conditions in selection text.
- **STRATEGY**: Return a complete replacement strategy only. Keep the frozen when_to_use scope and prerequisites. Repair the relevant action, instruction, evidence-handling rule or completion condition while retaining the rest of the executable procedure. For example, replace an unchanged retry with a request targeting the disputed event interval and completion cue. Do not broaden applicability through the strategy or repeat an already explicit rule as though it were absent.

## Stage constraints

- Revise exactly one field of one card. Do not return or rewrite the frozen field, ID, role or stages.
- Use each case's own public evidence; reference answers establish discrepancies, not unseen visual facts.
- Use valid available actions and input/earlier-result parameter sources. Preserve the question's criteria and required result.
- Unknown exposure does not prove a strategy defect. Prior rejection or related-case success does not establish causality.
- An edit remains a candidate for later evaluation; Gate/Test details are unavailable.

## Output format

Return one JSON object only, matching the operation-specific Schema, without Markdown fences or surrounding text:
- **status**: edit or skip.
- **summary**: The field repair and supporting evidence, or why revision is skipped.
- **when_to_use** for WHEN, or **strategy** for STRATEGY: The complete nonempty English replacement text for edit; null for skip.

Return exactly these three fields. Encode line breaks inside JSON strings as \n escapes. Do not output the other content field or target metadata."""
TEMPLATE = "{context}"
