# Decision strategy candidate review

## Task
Review one proposed {{role}} Decision strategy before any expensive rollout. Return a
pass/reject judgment only. Do not rewrite the candidate.

## Immutable role contract
{{role_contract}}

## Parent strategy
{{parent_skill}}

## Candidate strategy
{{candidate_skill}}

## Reject when any condition holds
- The candidate repeats the immutable role contract, action schemas, Public Rules,
  evidence boundary, or a generic objective instead of adding a conditional decision
  rule.
- The candidate strategy contains benchmark/case-specific objects, activities, option wording, answers,
  illustrative train-case details, case IDs, task labels, opaque task codes, or copied
  parameter values not defined by the immutable role contract. Do not reject a general
  policy solely because it uses a phrase such as `for example`; judge whether the
  content actually specializes to train evidence.
- The candidate strategy invents fixed video-duration, time-window, frame-count, or FPS thresholds that are
  not in the immutable role contract.
- It tells the Planner to gather evidence or continue observing until vague confidence,
  certainty, completeness, or sufficiency without an observable stop/change condition.
- It mandates another evidence action merely because text is vague or confidence is low,
  without naming an answer-changing visible distinction and requiring a non-equivalent
  call that can plausibly resolve it.
- For Global, it treats `watch_videos` as a generic fallback for `analyze_videos`.
  `watch_videos` is valid only when an unresolved relation inherently requires joint
  viewing of more than one selected video; otherwise refine independent analysis.
- For Global, before History reveals content differences, it assigns different
  instructions merely because video IDs differ or claims each video has a unique visual
  feature that the text-only Planner cannot know. Different instructions are valid when
  the question already assigns distinct views/roles or public History establishes the
  distinction. A shared comparison checklist is also valid when the same answer-changing
  property must be checked fairly across videos.
- It combines multiple independent behavioral hypotheses, crosses the role boundary,
  changes actions or schemas, or attempts to modify Runtime/Observer/Summarizer behavior.

Do not reject merely because the candidate is short, changes only one role, or leaves
the other role empty. A relative condition explicitly tied to required temporal detail,
event duration, or the density of an existing observation is not a fixed threshold and
must not be rejected as one. Reject a bare adjective such as "long" or "complex" only
when it has no observable relation to the instruction, Memory/History, or sampling need.

## Output contract
Return one JSON object and no surrounding prose:

```json
{
  "decision": "pass | reject",
  "reasons": ["<concise reason>"]
}
```
