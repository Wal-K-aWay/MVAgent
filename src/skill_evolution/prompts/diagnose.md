# Decision strategy diagnosis

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
separated into failed and successful trajectories. They show question-level input, chronological nested execution,
final output, train ground truth, normalized outcome, and concise scorer feedback when
format or partial credit matters. Ground truth is supervision for diagnosing the
completed episode; it was not Runtime evidence. Case IDs, source groups, paths, numeric
scores, intermediate Planner reasons, and internal selection metadata are intentionally
absent.

{{cases}}

## Diagnosis rules
- Diagnose one recurring causal decision pattern across the trajectories, or conclude
  that no safe Planner attribution is supported. Do not propose an edit or write Skill
  content in this stage.
- First locate the failure source: `global`, `video`, `action_internal`, `joint`, or
  `unattributed`. A wrong final answer alone does not establish a Planner defect.
- Treat a confidently wrong public observation, joint-watch result, or summary as
  `action_internal` when neither Planner saw a contradiction, uncertainty, or missing-
  evidence signal that it could act on. Ground truth can reveal the failure but cannot
  make a hidden visual mistake recoverable by a decision rule.
- Select `global` only when the complete Question and public History exposed a condition
  from which a different existing action, parameter choice, sequence, or answer timing
  could plausibly change the downstream result. Select `video` only when the local
  Instruction and private Memory exposed such a condition for Observe or Finish.
- Use `joint` only when more than one layer contributed. Even then, choose one target
  role only when the trajectories establish one first Planner-controllable change;
  otherwise choose `none`.
- Set `target_role` to `none` for `action_internal` or `unattributed` failures, for mixed
  or insufficient evidence, or whenever the trigger would require hidden pixels, ground
  truth, another role's private state, or information unavailable at decision time.
{{target_role_rule}}
- In `causal_evidence`, state the counterfactual chain from Runtime-visible state through
  one controllable decision variable to its downstream effect. In `regression_risk`,
  state the successful-trajectory condition that must remain unchanged. In
  `expected_behavior_change`, name an observable action, parameter, sequence, or stopping
  change rather than a generic goal.
- Abstract every output field across trajectories. Do not include case IDs, source
  groups, answers, option labels, copied question entities or activities, timestamps,
  parameter values, benchmark/task labels, or other train-specific identifiers or facts.
- Candidate {{candidate_number}} of {{candidate_count}}; diversity token {{seed}}.
  Candidate 1 should test the most conservative supported hypothesis. A later candidate
  may test a materially different causal hypothesis, but must return `none` rather than
  force an unsupported distinction.

## Output contract
Return one JSON object and no surrounding prose. Return exactly these six fields; do not
return edits, case IDs, evidence lists, confidence scores, or additional classifications.

```json
{
  "failure_source": "global | video | action_internal | joint | unattributed",
  "target_role": "global | video | none",
  "pattern": "<one recurring decision pattern, or why attribution is unsafe>",
  "causal_evidence": "<Runtime-visible trigger, controllable decision, and downstream effect>",
  "regression_risk": "<successful-trajectory condition that must be preserved>",
  "expected_behavior_change": "<observable action, parameter, sequence, or stopping change>"
}
```
