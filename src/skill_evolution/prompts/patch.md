# Decision strategy patch

## System architecture
{{target_architecture}}

## Current SkillSet
The target role is fixed as `{{target_role}}`. Only its current Decision strategy is
shown and only this strategy may be modified.

### Target Decision strategy
{{target_skill}}

## Previous optimizer memory
These are compact lessons relevant to the fixed target role, not trajectory evidence or
attempted edit text. Use them to avoid repeating rejected or regressive directions.
Temporary feedback from this candidate's immediately preceding retry may also appear
here. Do not infer unseen sample facts from these entries.

{{optimizer_memory}}

## Trajectories
These are the selected target-role failed and successful trajectories. Each
trajectory contains only state visible to the target Planner at Runtime, followed by its
own decisions and results. Other roles' private state, complete downstream execution,
ground truth, case IDs, source groups, paths, numeric scores, and internal signatures are
not shown.

{{cases}}

## Patch rules
The diagnosis below is frozen. It was produced from complete train episodes before the
evidence was projected onto the target role.

### Frozen diagnosis
{{diagnosis}}

- {{mode_instructions}}
- Do not re-diagnose the episodes, change the target role, or return a role field. The
  only task in this stage is to decide whether the frozen diagnosis can be expressed as
  at most one safe, general edit to the shown target strategy.
- Write a rule only when its trigger can be recognized from the target Planner's
  Runtime-visible state. The rule must connect that trigger to one existing action,
  parameter choice, sequence, refinement, or stopping decision and include the
  successful-trajectory boundary that prevents unnecessary behavior changes.
- If the diagnosis is unsupported by the target-visible trajectories, duplicates the
  current strategy, cannot be expressed without hidden information, or would require a
  generic fallback, return an empty `edits` array.
- Add only the missing conditional decision rule. Do not restate the architecture,
  action schemas, fixed Rules, evidence boundaries, generic goals, or the diagnosis.
  Do not add or alter actions, parameters, schemas, validation, action-internal prompts,
  evidence flow, or Runtime control flow.
- Do not compensate for Observer, joint-watch, summarizer, finalizer, media, model, or
  execution failures by inventing a Planner rule. Do not use `watch_videos` as a generic
  fallback for weak, vague, uncertain, conflicting, incomplete, or insufficient reports;
  use it only when the frozen trigger establishes an unresolved answer-changing relation
  that inherently requires joint viewing.
- Do not copy answers, option labels, question entities or activities, numbers,
  timestamps, parameter values, benchmark/task labels, identifiers, or other train-
  specific content into `edits.content`. Do not invent numeric duration or FPS thresholds;
  use observable relative conditions unless a number is an immutable action constraint
  in the architecture above.
- Avoid open-ended verification loops. Every follow-up rule needs an observable evidence
  change or stop condition. The resulting strategy must remain concise and must not
  exceed {{max_chars}} characters.
{{changed_chars_rule}}
- For an empty strategy, use `append` with an empty target and content beginning with one
  `###` heading followed by one concise policy paragraph. For a non-empty strategy, use
  one exact `append`, `insert_after`, `replace`, or `delete`. A `replace`, `delete`, or
  `insert_after` target must copy text from the current target strategy exactly. For
  `delete`, return an empty content string.
- Before returning, inspect only `edits.content` and remove every train-specific answer,
  option, entity, label, identifier, and value. If the rule cannot be stated without
  them, return no edit.

## Output contract
Return one JSON object and no surrounding prose. `edits` must contain zero or one item.
The target role is injected by the optimization framework and must not appear in the
output.

```json
{
  "edits": [
    {
      "op": "append | insert_after | replace | delete",
      "target": "<exact current target text, or empty only for append>",
      "content": "<one concise general Markdown policy; empty only for delete>"
    }
  ]
}
```
