"""Card-independent analysis of public development trajectories."""

TASK = """# Batch Issue Analysis

Identify one supported, reusable failure pattern in the supplied development cases. Establish what went wrong before considering Skill edits; library attribution and edit planning belong to planner.

## Inputs and their roles

- **cases**: Original input, public steps, final answer and offline feedback for each case. Cases may be successful or unsuccessful and may require different methods despite their grouping.
- **input**: The question, options and video IDs/durations define the input relationships, task criteria and required result.
- **steps**: Each recorded decision and its returned result. Assess the decision from the input and earlier results; assess execution from the request and its result. A result becomes available only after that action.
- **final_answer**: The final answer produced by the run. Check its content and format against input and steps.
- **offline_feedback**: Reference answer and scoring feedback establish an outcome discrepancy. They do not reveal unseen video content or the cause of failure.
- **omitted_case_ids**: Cases excluded from this input. Make no claims about their trajectories.

Skill text, selection records and private VideoAgent traces are unavailable at this stage.

## Analysis requirements

1. Establish the main task and decisive evidence requirement from each input. Preserve qualifiers, time coordinates, comparison criteria and answer content.
2. Locate a concrete defect in a public action, parameter, result or subsequent use of that result. Separate an inadequate request, an inadequate returned result and a later decision that mishandles the result. Check whether later steps already corrected the problem.
3. Explain the failure pattern using actual case and step references. Distinguish recorded facts from hypotheses about their cause; do not turn a plausible remedy into proof of the cause.
4. Compare related successful behavior and relevant task differences. Retain useful behavior without claiming that success proves causality or that every case shares the same defect.
5. Return issue only when a non-perfect case supports a specific defect that later planning can assess. If the evidence shows only a wrong answer, honest uncertainty or an unobservable perception error with no supported decision-level remedy, return no_issue.

For example, a request restricted to an opening interval is inadequate for a whole-video total. A timestamped event absent from a compressed report is not thereby absent from the video. Conflicting reports justify assessing reconciliation; they do not identify which report is wrong.

## Stage constraints

- Use each case's own public evidence; observations cannot be transferred between cases.
- Cite actual trajectory steps, not numbered strategy instructions. Use the case sample_id as case_id. Use step=null for an input-level requirement; action findings identify the relevant recorded step.
- Do not infer observation coverage from reported event intervals or invent private observations.
- Do not select an edit operation, target card or library policy. Gate/Test evidence is unavailable.

## Output format

Return one JSON object only, matching the supplied Schema, without Markdown fences or surrounding text. Return every field:
- **status**: issue or no_issue.
- **task_requirement**: The reusable task and evidence requirement.
- **failure**: The observed defect, its affected decision and its connection to the task. Keep causal uncertainty in hypotheses or uncertainties.
- **evidence_refs**: Objects containing case_id and step. For issue, provide supported references including a non-perfect case. For no_issue, use [].
- **preserved_behavior**: Supported successful behavior worth retaining, with case/step references where applicable.
- **hypotheses**: Possible explanations, explicitly distinguished from established facts.
- **uncertainties**: Missing evidence or alternative explanations that limit the finding.

For no_issue, use failure to explain why actionable analysis is unsupported; use empty strings or arrays for other inapplicable fields."""
TEMPLATE = "{context}"
