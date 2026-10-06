"""Grounded single-card planning from analysis, routing and actual guidance."""

TASK = """# Skill Edit Planning

Determine whether the supplied issue supports one coherent edit to the current parent library. Return a justified NEW, WHEN or STRATEGY plan, or skip. A failure finding does not by itself establish a Skill defect.

## Inputs and their roles

- **issue**: Analyzer findings, references, hypotheses and uncertainties. Verify them against cases; the analysis is not new observation evidence.
- **cases**: Original inputs, public steps, final answers and offline feedback, with actual routing and exposure records. Assess decisions using evidence available before each action.
- **library_catalog**: Global card IDs and when_to_use text. It describes selection scope, not the full methods.
- **related_cards**: Supplied complete cards for method comparison. Evaluate only text actually provided; a catalog entry alone does not establish strategy coverage.
- **used_skill / routing / injected**: Recorded selection and verified exposure. Distinguish eligible, recalled, selected and actually injected. Missing verification remains unknown.
- **omitted_case_ids**: Unavailable cases; do not cite their unseen details.

## Planning requirements

1. Verify the task, failure and editable decision against the original cases. Separate retrieval omission, selector rejection or false selection, ignored guidance, strategy content defects and insufficient observation.
2. Compare the required method with related card content. Coverage requires support for the input relationships, decisive evidence dependencies and requested answer content; shared words or generic analysis actions are insufficient.
3. Identify a specific content change and explain how it could affect the recorded selection or an available Global decision. A wrong answer, an empty candidate list or a generic reminder alone is not an edit rationale. An answer-result defect does not establish a missing strategy rule when the input or existing guidance already supplies that rule.
4. Select the operation below, preserving supported successful behavior and meaningful task distinctions. If the evidence cannot support such an edit, return skip; do not force attribution or generation.

## Operation criteria

- **WHEN**: An identifiable defect in when_to_use contributed to selection or non-selection, while the existing strategy already supports the intended task. Revise only when_to_use; freeze strategy. Expanding wording cannot create a missing method. A candidate omitted by retrieval is distinct from a candidate shown and rejected by the selector.
- **STRATEGY**: A concrete strategy defect is connected to an editable decision that verifiably received this exact target strategy. Revise only strategy; freeze when_to_use. A clear existing instruction left unfollowed is not missing content; unknown exposure cannot establish this operation.
- **NEW**: A supported method is needed that the supplied related cards cannot reasonably provide. Check every supplied complete related card and state the substantive method gap. Different subject matter or cluster membership alone does not require another card.

For example, a whole-video counting method selected for a snapshot-count question may have an overbroad when_to_use. An injected method that explicitly restricts whole-video totals to opening clips has a strategy defect. A library of counting methods does not cover chronological segment ordering merely because both use video reports.

## Stage constraints

- when_to_use is the only card content visible during selection; strategy is the only content injected after selection. Keep selection and execution defects separate.
- Applicability must be recognizable from the original input. References and feedback are offline evidence, never facts the solving Agent observed. Use the case sample_id as case_id.
- Check each case's actual card/exposure relationship. Success does not prove Skill causality; previous rejection does not reveal its cause.
- Gate/Test details are unavailable. Acceptance is decided by later evaluation, not by this plan.

## Output format

Return one JSON object only, matching the supplied Schema, without Markdown fences or surrounding text. Return every field:
- **status**: ready or skip.
- **reason**: Evidence supporting the operation, or why an edit is unsupported. Distinguish observed facts from the expected effect of the proposal.
- **operation**: WHEN, STRATEGY or NEW for ready; null for skip.
- **target_skill_id**: The supplied target ID for WHEN/STRATEGY; null for NEW or skip.
- **evidence_refs**: case_id and actual step or null. ready must include non-perfect evidence. STRATEGY requires verified target injection at a referenced editable step; routing edits may use step=null.
- **checked_skill_ids**: IDs of supplied complete related cards actually assessed; NEW includes every supplied related card.
- **goal**: The concrete change the author should implement.
- **expected_benefit**: The supported improvement hypothesis, not a guaranteed gain.
- **preserved_behavior**: Effective rules and task distinctions the edit must retain.
- **frozen_fields**: ["strategy"] for WHEN, ["when_to_use"] for STRATEGY, [] for NEW or skip.

For skip, explain the evidence limitation in reason and use empty text/arrays where inapplicable. Do not specify an edit or target."""
TEMPLATE = "{context}"
