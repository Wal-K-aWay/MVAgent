# Decision strategy update

## System architecture
{{system_architecture}}

## Current SkillSet

### Global Decision strategy
{{global_skill}}

### Video Decision strategy
{{video_skill}}

## Previous optimizer memory
These are compact, role-labelled lessons from earlier semantic checks and rollouts, not
trajectory evidence or attempted edit text. A recorded eval regression rules out merely
paraphrasing the same hypothesis; other lessons may require a narrower trigger or a
different causal direction. Temporary format and duplicate errors are shown only during
the current candidate retry. Do not infer unseen sample facts from these entries.

{{optimizer_memory}}

## Trajectories
These are one deterministic role-local minibatch of complete train episodes, explicitly
separated into failed and successful trajectories. They show the question-level input, chronological nested
execution, final output, train ground truth, normalized outcome, and concise scorer
feedback when format or partial credit matters. Ground truth is supervision for
diagnosing the completed episode, not visual evidence that was available during
execution. Case IDs, source groups, paths, numeric scores, intermediate Planner reasons,
and internal selection metadata are intentionally absent.

{{cases}}

## Update rules
- {{mode_instructions}}
- First locate the failure source: `global`, `video`, `action_internal`, `joint`, or
  `unattributed`. A wrong answer alone does not prove that either Planner strategy was
  wrong. If the trajectories do not establish one recurring, causal, Planner-controllable
  defect, set `target_role` to `none` and return no edit.
- Treat a confidently wrong public observation, joint-watch result, or summary as
  `action_internal` unless the target Planner's visible state contained a contradiction,
  uncertainty, or missing-evidence signal that it could have acted on. Ground truth may
  reveal that the episode failed, but it does not make the hidden visual mistake
  recoverable by a new decision rule.
- If a Planner-controllable defect is established, select exactly one `target_role`:
  `global` or `video`. Return at most one edit and modify only that role's current
  Decision strategy. The complete episode may be used for offline attribution, but the
  new rule may depend only on state visible to that target Planner at Runtime.
- For Global, inspect instruction assignment, evidence-request order, selected videos,
  `analyze_videos` versus `watch_videos`, reactions to public History, repeated requests,
  and answer timing. Select Global only when Question and public History expose a
  recoverable decision error. For Video, inspect Observe WHAT/ranges/FPS, reactions to
  private Memory, repeated equivalent observations, refinement, and Finish timing;
  select Video only when Instruction and Memory expose the controllable mistake.
- Do not optimize fixed action-internal Observer, watch, summarizer, or finalizer prompts;
  do not compensate for a capability failure by inventing a Planner rule. Do not add or
  alter actions, parameters, schemas, validation, evidence boundaries, or Runtime flow.
- Abstract across trajectories. Never copy a ground-truth answer, option label, question
  entity, activity, number, timestamp, parameter value, benchmark/task label, or other
  train-specific content into the Skill. Never infer unseen video content from ground
  truth. Do not invent numeric duration or FPS thresholds; use observable relative
  conditions unless a number is an immutable action constraint above.
- Add only the missing conditional decision rule; do not restate the architecture,
  action schemas, fixed Rules, evidence boundaries, or generic goals. Avoid open-ended
  confidence loops: every follow-up needs an observable change or stop condition.
- State why the proposed trigger applies to the failed trajectories but not to the
  successful trajectories. If that boundary cannot be expressed using Runtime-visible state, return no
  edit instead of creating a generic verification policy.
- Do not use `watch_videos` as a generic fallback after weak, vague, uncertain,
  conflicting, incomplete, or insufficient independent reports. Use it only when the
  unresolved answer-changing relation inherently requires joint viewing.
- Candidate {{candidate_number}} of {{candidate_count}}; diversity token {{seed}}.
  Candidate 1 should be conservative; later candidates must test a materially different
  causal hypothesis rather than paraphrase it. Return at most one edit.
- The resulting target strategy must not exceed {{max_chars}} characters. For an empty
  strategy, use `append` with an empty target and content beginning with one `###`
  heading followed by one concise policy paragraph. For a non-empty strategy, use one
  exact `append`, `insert_after`, `replace`, or `delete`. In repair mode, use exactly one
  `replace` whose target is the complete current target strategy and whose content is the
  complete repaired strategy.
{{changed_chars_rule}}
- Before returning, inspect only `edits.content` and remove every train-specific answer,
  option, entity, label, identifier, and value. If the rule cannot be stated without
  them, return no edit.

## Output contract
Return one JSON object and no surrounding prose. `edits` is empty exactly when
`target_role` is `none`; otherwise it contains one edit whose `role` equals
`target_role`.

```json
{
  "diagnosis": {
    "failure_source": "global | video | action_internal | joint | unattributed",
    "target_role": "global | video | none",
    "pattern": "<one recurring decision pattern, or why attribution is unsafe>",
    "causal_evidence": "<trajectory-grounded link to one target-Planner decision variable>",
    "regression_risk": "<successful behavior that the edit must preserve>",
    "expected_behavior_change": "<observable action, parameter, sequence, or stopping change>"
  },
  "edits": [
    {
      "role": "global | video",
      "op": "append | insert_after | replace | delete",
      "target": "<exact current target text, or empty only for append>",
      "content": "<one concise general Markdown policy; empty only for delete>"
    }
  ]
}
```
