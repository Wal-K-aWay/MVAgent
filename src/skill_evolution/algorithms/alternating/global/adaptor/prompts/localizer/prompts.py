"""Localize action selection, parameter and execution faults in public trajectories."""

TASK = """# Fault Localization Analysis

Identify supported action-level faults in a recorded multi-video question-solving trajectory. Locate each fault at the step where it occurs, classify it, and propose a feasible, reusable correction.

## Inputs and their roles

The trajectory input contains the following sections, named exactly as shown:
- **Input**: The original question, options and video IDs and durations. The question defines the task, including its quantifiers, comparison criteria and required answer format. Video metadata supports checks of video references and time ranges.
- **selected skill**: The Skill the selector judged most suitable among the available candidates for this question, or None when no suitable Skill was selected or available. Selection expresses an applicability judgment, not a guarantee of correctness. Use this section to understand the guidance supplied; assess its assumptions and rules against Input and the public evidence. An explicit notice of unavailable selection records represents missing information.
- **steps**: The actual sequence of actions, parameters and returned results produced while solving Input under the selected Skill's guidance. With no selected Skill, the Agent determines the solution procedure itself from Input and accumulated evidence. Guidance can be followed, adapted or mishandled; the recorded actions establish what actually happened. For each step, assess the decision using information available before its action and assess execution using the request and returned result.
- **output**: The final answer produced by the recorded run. Check its content and format against Input and the evidence in steps.
- **ground truth**: The reference answer supplied for offline analysis. Compare it with output to establish the outcome discrepancy. It was unavailable during solving; identifying the cause of a discrepancy requires evidence from steps.

## Analysis objective

Establish the task requirements from Input first, then inspect steps for a specific action, parameter or result defect. Explain each finding through those requirements and the evidence available at the relevant step.

The selected skill helps explain how an action may have arisen. Following a Skill rule may still produce a faulty action; departing from it may be justified by the question and evidence. Evaluate action correctness independently of Skill compliance. Skill examples supply hypothetical illustrations rather than facts about this case.

Return supported action-level findings. Assessment of whether to revise the Skill or create a new one belongs to later stages. When the public evidence cannot support an actionable localization, return skip and explain the uncertainty."""

INPUT = """# Full Step-Level Trajectory

Read the input, question-level Skill guidance, all steps, final answer and ground truth together. For Step k, separate:
- Decision basis: the question, video metadata, fixed Skill guidance and results from Steps before k.
- Action: the action and parameters recorded at Step k.
- Result: the observation or answer returned at Step k, available to subsequent decisions.

Locate selection or parameter faults at the step making that decision, judged against its decision basis. Locate execution faults at the step producing the defective result, judged against its request and available evidence. When a later step mishandles that result, assess the later action separately. Reports from one analyze_videos call share one step; watch_videos returns one joint observation. The ordinary answer action has no parameters and generates its result from the supplied question and History.

{trajectory}"""

FAULT_TYPES = """# Fault Type Definitions

Choose one type for each fault_chain entry. Different steps in one trajectory may have different types.

**action_selection_error**: The chosen action is unsuitable for the evidence need at that point.
- Characteristics: An adequate next move requires a different action; changing only the existing action's parameters does not address the gap.
- Improvement: Identify the evidence need and an appropriate alternative action.
- Example: The decisive property is unresolved in all reports, yet the Agent calls answer instead of gathering evidence.

**action_parameter_error**: The action is appropriate, but its parameters make the request inadequate for the question.
- Characteristics: Keeping the action and changing its video IDs, clips or instruction would form a reasonable request. These parameters belong to analyze_videos and watch_videos; answer has none.
- Improvement: Specify the parameter change and its source in the input or earlier evidence.
- Example: A joint comparison excludes the candidate event because its clips end before the reported event time.

**action_execution_error**: An appropriate action with adequate parameters returns a demonstrably defective result.
- Characteristics: Identify the adequate request, a verifiable defect in its result, and the evidence requirement affected by that defect. Supported defects include an explicit request requirement left unanswered, an internally invalid result, an explicit execution failure or incorrect handling of already sufficient evidence. An ordinary answer can fall in this category when answering is justified but its returned answer contradicts clear History.
- Improvement: Identify a feasible public evidence-verification or answer-consistency rule. Describe the execution defect without inventing a defect in an adequate request or proposing changes to hidden action internals. If no supported improvement is available through the Agent's actions or evidence handling, use skip and explain the execution problem in reason.
- Example: History unambiguously identifies video_2, mapped to option B, but answer returns A.

## Classification Boundaries

Judge a request against the evidence-acquisition purpose it serves at that stage. An initial overview may reasonably request approximate times or gather reference and target descriptions concurrently. Assess whether later decisions refine the decisive details before answering. Retaining the action with better parameters supports action_parameter_error; an alternative action also being available does not establish action_selection_error.

For answer, first check whether History supports an answer meeting the question's requirements. Unresolved competing candidates in a single-choice task, counts matching no option, or undetermined ordering relations require assessment of a concrete follow-up opportunity. Calling answer while such an actionable decisive gap remains is action_selection_error. When evidence is sufficient but the returned answer misuses it or violates the required format, assess action_execution_error. Agreement with one report is insufficient when other relevant evidence remains unresolved. An ordinary answer has no parameters.

For an execution fault, identify the request requirement, the direct result defect and evidence assigning that defect to this step. A later report can correct an earlier report. Disagreement between reports establishes a need for reconciliation, not which report failed. Cross-view contradictions require established object identity, time span and comparison criteria. Event timestamps or suspicious counts are verification cues; they do not reveal hidden observation mistakes or establish observation coverage.

The question determines the evidential standard. A prediction task may require plausible inference from beginning/end clips rather than direct observation of the absent middle. Honest uncertainty is compatible with valid execution. Shared people or settings provide continuity clues, not proof of immediate adjacency.

## Evidence threshold: verification need versus proven defect

Use the same threshold in reason, evidence_reason and improvement_principle. Distinguish a directly supported defect from a concrete verification need and from an unexplained outcome discrepancy; do not turn a verification suggestion into an assertion that the hidden observation was wrong.

- **Direct defect**: Identify the exact request or task requirement and the public wording, invalid output, explicit failure or sufficient conflicting History that violates it. For action_execution_error, uncertainty, omission or a task-premise conflict alone is insufficient. Missing a result item is a demonstrated execution defect only when the request explicitly requires that item or an exhaustive/complete result; an initial general description is allowed to be selective. A report that says it examined 0-end and lists events at 10-25 seconds is not evidence that it examined only 10-25 seconds.
- **Verification need**: State which decision-critical distinction is unresolved, why existing evidence cannot settle it, and a feasible action that could obtain the missing evidence. A report limited to an explicit subinterval leaves other intervals unsupported in public History; it does not establish which frames the hidden model actually saw. An endpoint description that does not establish complete exit justifies clarifying full absence; it does not prove the object was still partly visible or that the true exit was later. A likely or unmentioned detail may justify checking a live candidate without branding the report false. If the Agent answers despite this supported, actionable gap, locate action_selection_error at that later answer step; the preceding uncertain report need not be a fault.
- **Outcome discrepancy only**: If no direct defect or concrete decision-time verification need is supported, return skip. Do not use ground truth to assert where a hidden event occurred, which report omitted it, or what a repeated observation would reveal. A correct final answer does not erase a visible defect either.

For every decision fault, cite only Input and results returned before that step. Its own returned result can establish an execution issue or a later verification need, not retroactively prove the action was wrongly selected. A hypothetical better request does not by itself make a reasonable overview defective. Compare the actual changes in repeated instructions, including broadened criteria or requests for alternative descriptions; repeated action names or the availability of watch_videos do not prove that an action switch was required. Keep proposed improvement conditional on its missing evidence and do not promise a correct result. When choosing a fault type, follow the stated sufficiency and parameter-repair tests; use reason to preserve unresolved uncertainty rather than inventing an earlier root cause.

## Task-derived checks before skip

Apply these checks from Input, requests and public results, even when output matches ground truth. A GT mismatch is not required for a supported fault. Do not skip a visible task-contract violation merely because the answer follows a report.

- **Output contract and evidence sufficiency**: Check allowed options, answer count, format, quantifiers and required conditions. An answer outside the offered options is a visible output violation. Counts matching no option, a tied candidate set or an unverified conjunct leave an evidence gap; eliminating other candidates does not prove the remaining candidate satisfies every required condition. When a concrete follow-up is feasible, locate premature answer selection; when answering is already justified but its returned content or format is defective, locate answer execution. A format defect can coexist with insufficient evidence; explain both and classify the entry by the decision-time sufficiency test. The question's premise flags a conflict to resolve, not proof that a particular video report is false.
- **Report scope and coverage**: Compare the request's intended scope with what the result explicitly says it examined. A report explicitly limited to a final subinterval does not establish coverage of the full requested video. Check whether omitted ranges could contain evidence needed for this question and whether a targeted request can cover them. A request deliberately excluding an already needed range supports a parameter fault; an adequate request whose result explicitly leaves a required range or criterion unanswered can support an execution fault. If the scope is ambiguous, seek clarification rather than asserting unseen frames were omitted. A few event timestamps or a terse report do not alone prove incomplete coverage. Do not require full-duration viewing when a sufficient targeted interval serves the task.
- **Event and comparison definitions**: Preserve the question's subject, object, event endpoint, functional criterion and synchronized time. 'No longer fully inside the frame' does not mean 'completely outside the frame'; vehicles passing the target are not the target itself passing; the same function need not use the same technique. Identify a literal mismatch in the request or result and its affected requirement, without inventing the true event time or object identity. Different views can have different visibility intervals. An ID prefix locates its identification label, not every view in which the underlying object can be tracked; transfer identity cues when needed. Do not add counts from two views of the same scene without deduplicating events.
- **Verifiable candidates**: Separate explicit absence, unmentioned evidence and uncertain identification. A relevant 'likely' identity, approximate decisive boundary, unresolved object correspondence or ordering relation can warrant a targeted check; uncertainty alone does not prove execution failed. State the specific unresolved distinction, available video/range or prerequisite, and how analyze_videos refinement or direct watch_videos comparison could address it within the remaining opportunities. Do not promise the check will succeed. For a missing-middle prediction, compare plausible candidates using the supplied clips; neither demand direct observation of the absent middle nor recheck every hypothetical event merely because GT disagrees. When the existing result already compares candidates plausibly and no concrete unresolved check is supported, skip remains appropriate.

Skill presence or absence does not determine fault type. When the answer follows adequate reports and only ground truth disagrees, with no supported public defect or actionable decision gap, return skip. Ground truth establishes the discrepancy; it cannot identify a faulty report by itself.""" 

ANALYSIS = """# Analysis Instructions

1. **Establish task requirements**: Read Input to determine the answer form (single choice, multiple choices, interval or ordering), quantifiers, comparison entities and time scope. Establish whether the task asks for observed facts or inference from the supplied evidence. Preserve explicit answer-count instructions even when the question uses singular wording. Then compare output with ground truth.
2. **Reconstruct each step**: Separate its prior decision basis, action and parameters, and returned result. Requests within one analyze_videos call share pre-call evidence; a request depending on a new report belongs in a later call. Judge each request by its role in the solution, allowing an overview followed by targeted refinement.
3. **Check answer sufficiency**: Determine whether the accumulated evidence supports an answer satisfying the task requirements. Identify any decisive conflict, missing condition or unresolved relation and a feasible action that could address it. Separate premature answer selection from incorrect execution of an answer already supported by sufficient evidence. For prediction tasks, assess candidate discrimination using available clues rather than demand observation of the missing event.
4. **Locate and classify faults**: Select 1-3 distinct editable steps with a supported defect and feasible correction, earliest supported root cause first. Selection and parameter faults belong to the decision step; execution faults belong to the step producing a directly demonstrable defect. For execution, state the request requirement, result defect and why it belongs to this step. Preserve uncertainty about which report is wrong when only a conflict is visible. Compare actual parameter changes before treating repeated requests as ineffective.
5. **Formulate improvement**: Give one concise, reusable principle containing the triggering condition, action or parameter correction, and specific evidence or consistency check needed. Explain what a proposed action change would resolve. Derive parameters from information available at the proposed call; explain how missing prerequisites can be obtained. Keep case details in evidence_reason and exclude ground-truth-only answers, identities or times from runtime parameter rules. A correction must be feasible at the relevant decision, including its remaining action opportunities.
6. **Verify findings and scope**: Look up every step number and ensure its action/result, evidence_reason and improvement_principle refer to the same defect. Reconcile reason with fault_chain. Return skip when no supported actionable localization remains, including inaccessible execution failures, non-editable finalizers or unexplained answer-reference mismatches. Keep Skill editing decisions for later stages; describe insufficient public support without claiming an answer was correct merely by luck."""

EXAMPLES = """# Examples

Hypothetical illustrations only. Each example has its own step numbers and question-level Skill; these facts are not evidence for the supplied case.

<example type="action_selection_error">
Input: Which video adds vinegar to the batter?
Videos: video_1 (20 seconds); video_2 (20 seconds).
Selected skill: None.
Trajectory:
Step 1: action=analyze_videos {"videoagent_request":[{"video_id":"video_1","instruction":"Identify liquids added to the batter."},{"video_id":"video_2","instruction":"Identify liquids added to the batter."}]}
  obs[video_1]: A clear liquid is poured; its identity is uncertain.
  obs[video_2]: A vinegar bottle is present; its use is uncertain.
Step 2: action=answer | output=video_1
Final answer: video_1.
Ground truth: video_2.
Analysis: Both prior reports leave the decisive fact unresolved. Answer has no parameters to repair; the next move should gather evidence.
Output:
{"status":"located","reason":"The answer was issued while vinegar use remained unresolved.","fault_chain":[{"step":2,"fault_type":"action_selection_error","evidence_reason":"Neither earlier report establishes which video adds vinegar, yet the Agent calls answer.","improvement_principle":"Use targeted analyze_videos instructions to verify the unresolved pours before answering."}]}
</example>

<example type="overview_then_verification">
Input: Return the interval in video_2 serving the same function as video_1 at 5-10 seconds.
Videos: video_1 (20 seconds); video_2 (90 seconds).
Selected skill: None.
Trajectory:
Step 1: action=analyze_videos {"videoagent_request":[{"video_id":"video_1","instruction":"Describe the action and its purpose at 5-10 seconds."},{"video_id":"video_2","instruction":"List preparation steps, purposes and approximate intervals."}]}
  obs[video_1]: Mix a dressing before serving.
  obs[video_2]: Mixing at roughly 20-30 seconds; purpose uncertain. Another dressing-like preparation occurs around 50-60 seconds.
Step 2: action=answer | output=20,30
Final answer: 20,30.
Ground truth: 51,62.
Analysis: Concurrent overview requests and approximate initial times are reasonable. The candidate function and boundaries remain unresolved when Step 2 answers.
Output:
{"status":"located","reason":"The overview was reasonable, but the Agent answered before distinguishing the candidates.","fault_chain":[{"step":2,"fault_type":"action_selection_error","evidence_reason":"Two candidates remain, one with uncertain purpose, and neither has verified boundaries; answer selects the first without resolving these gaps.","improvement_principle":"When an overview leaves multiple functional candidates, use analyze_videos to verify their purposes and the matching candidate's start/end boundaries before answering."}]}
</example>

<example type="answer_execution_error">
Input: Which video shows a red car? A means video_1; B means video_2.
Videos: video_1 (10 seconds); video_2 (10 seconds).
Selected skill: preserve-identities, used throughout; preserve video IDs when comparing reports.
Trajectory:
Step 1: action=analyze_videos {"videoagent_request":[{"video_id":"video_1","instruction":"Identify the car color."},{"video_id":"video_2","instruction":"Identify the car color."}]}
  obs[video_1]: A blue car; no red car.
  obs[video_2]: A red car; no blue car.
Step 2: action=watch_videos {"instruction":"Confirm which video shows the red car.","videos":[{"video_id":"video_1","clip":[0,10]},{"video_id":"video_2","clip":[0,10]}]} | obs=video_1 shows a blue car; video_2 shows a red car.
Step 3: action=answer | output=A
Final answer: A.
Ground truth: B.
Analysis: Step 2 supplies consistent evidence. Step 3 returns the wrong option, so the execution fault belongs to Step 3. Answering is justified by clear evidence. The answer result contradicts the video-to-option mapping; answer has no parameters.
Output:
{"status":"located","reason":"The evidence resolves the question, but the answer maps the supported video to the wrong option.","fault_chain":[{"step":3,"fault_type":"action_execution_error","evidence_reason":"History identifies video_2 as red and the input maps video_2 to B, but answer returns A.","improvement_principle":"Verify the evidence-supported video ID against the question's option mapping when producing the final answer."}]}
</example>

<example type="explicit_label_confusion">
Input: Where is the vehicle marked B2 relative to the vehicle marked B3 at 8 seconds? A: left; B: right. Boxes mark vehicle identity only.
Videos: view_A (20 seconds); view_B (20 seconds).
Selected skill: None.
Trajectory:
Step 1: action=analyze_videos {"videoagent_request":[{"video_id":"view_B","instruction":"Use labels to identify the vehicles B2 and B3, then report their relative position at 8 seconds."}]}
  obs[view_B]: I compared the printed text labels, not the vehicles. Text B2 is left of text B3.
Step 2: action=answer | output=A
Final answer: A.
Ground truth: B.
Analysis: The report explicitly describes evaluating text instead of the requested vehicles. This directly establishes a result defect, independently of GT. The later answer uses unresolved vehicle evidence.
Output:
{"status":"located","reason":"The report explicitly substitutes text positions for vehicle positions, then the Agent answers without correcting it.","fault_chain":[{"step":1,"fault_type":"action_execution_error","evidence_reason":"The adequate request asks for vehicles at 8 seconds, but the result explicitly states it compares printed labels instead.","improvement_principle":"When a report substitutes labels for their referents, request tracking of the underlying objects from their identity markers to the required time."},{"step":2,"fault_type":"action_selection_error","evidence_reason":"The preceding result supplies no vehicle-position comparison, yet answer selects A.","improvement_principle":"Obtain the requested object-position evidence before answering when the available report describes only labels."}]}
</example>

<example type="unexplained_mismatch">
Input: Which video has more jumps? A means video_1; B means video_2.
Videos: video_1 (20 seconds); video_2 (20 seconds).
Selected skill: None.
Trajectory:
Step 1: action=analyze_videos {"videoagent_request":[{"video_id":"video_1","instruction":"Count completed jumps across the full duration."},{"video_id":"video_2","instruction":"Count completed jumps across the full duration."}]}
  obs[video_1]: Five completed jumps.
  obs[video_2]: Three completed jumps.
Step 2: action=answer | output=A
Final answer: A.
Ground truth: B.
Analysis: The final answer agrees with the available reports. GT disagreement does not establish which report is wrong or a specific correctable decision.
Output:
{"status":"skip","reason":"The public trajectory supports the reported comparison and exposes no specific request or result defect; GT disagreement alone does not localize the cause.","fault_chain":[]}
</example>


<example type="concurrent_reference_dependency">
Input: Find the interval in video_2 that serves the same purpose as the action in video_1.
Videos: video_1 (15 seconds); video_2 (120 seconds).
Selected skill: None.
Trajectory:
Step 1: action=analyze_videos {"videoagent_request":[{"video_id":"video_1","instruction":"Describe the action, object and purpose."},{"video_id":"video_2","instruction":"Locate stirring in a pan as the matching action."}]}
  obs[video_1]: Flour coats meat to create an outer layer before cooking.
  obs[video_2]: Stirring in a pan occurs at 70-85 seconds.
Step 2: action=answer | output=70,85
Final answer: 70,85.
Ground truth: 20,35.
Analysis: The question supplies no pan-stirring criterion. That unsupported restriction is visible before Step 1. The coating report arrives after both instructions were fixed; a coating-specific target query therefore belongs in a later call.
Output:
{"status":"located","reason":"The target request presupposes a visual action before establishing the reference function.","fault_chain":[{"step":1,"fault_type":"action_parameter_error","evidence_reason":"The video_2 instruction assumes pan stirring although the input specifies only a functional match and no earlier report establishes the reference action.","improvement_principle":"When the reference function is unknown, first request its action, object and purpose through analyze_videos, then use that report to formulate the target-video instruction in a subsequent call."}]}
</example>

<example type="suspicious_timestamp_is_not_proof">
Input: When A1 leaves view_A, where is B1 in view_B? A: left; B: right. Identity boxes appear during each object's first visible second.
Videos: view_A (30 seconds); view_B (30 seconds).
Selected skill: None.
Trajectory:
Step 1: action=watch_videos {"instruction":"Track the objects after identification. At A1's exit, locate B1.","videos":[{"video_id":"view_A","clip":[0,30]},{"video_id":"view_B","clip":[0,30]}]} | obs=A1 exits at 1 second; B1 is on the left.
Step 2: action=answer | output=A
Final answer: A.
Ground truth: B.
Analysis: The timestamp coincides with possible label disappearance, but the result does not establish label confusion. The answer follows the report; GT alone cannot assign a defect.
Output:
{"status":"skip","reason":"The public trace contains no direct evidence that label disappearance was mistaken for object departure; the timestamp and GT mismatch alone do not establish an actionable fault.","fault_chain":[]}
</example>

<example type="prediction_with_uncertainty">
Input: Infer the missing middle from beginning and ending clips. A: the passenger misses the train; B: the passenger boards it.
Videos: beginning (20 seconds); ending (20 seconds).
Selected skill: None.
Trajectory:
Step 1: action=watch_videos {"instruction":"Compare the passenger's location and train state in the beginning and ending to assess missing-middle alternatives A and B.","videos":[{"video_id":"beginning","clip":[0,20]},{"video_id":"ending","clip":[0,20]}]} | obs=The passenger runs toward a departing train, then stands on an empty platform. Missing the train is more plausible; boarding and later returning cannot be excluded.
Step 2: action=answer | output=A
Final answer: A.
Ground truth: B.
Analysis: The task asks for inference from supplied clips. The result compares alternatives and preserves uncertainty; the middle is absent by design. No specific overlooked clue or request defect is established.
Output:
{"status":"skip","reason":"The answer follows a plausible evidence-based comparison; uncertainty about an unobserved middle event is not an execution defect, and GT alone does not localize the discrepancy.","fault_chain":[]}
</example>"""

OUTPUT = """# Output Format

Return one JSON object only, matching the supplied Schema.

Fields:
- `status` (string): `located` or `skip`.
- `reason` (non-empty string): Overall evidence-supported explanation, including uncertainty or why no actionable localization is possible.
- `fault_chain` (array): Each item contains `step` (integer), `fault_type` (`action_selection_error`, `action_parameter_error` or `action_execution_error`), `evidence_reason` and `improvement_principle` (non-empty strings).

Rules:
- Return exactly status, reason and fault_chain at the top level. Classify each chain item independently.
- located requires 1-3 distinct editable step numbers, earliest supported root cause first.
- skip requires an empty fault_chain; describe any supported execution defect or uncertainty in reason.
- Each entry contains exactly step, fault_type, evidence_reason and improvement_principle.
- answer has no parameters; action_parameter_error applies only to analyze_videos or watch_videos.
- Use only step numbers allowed by the Schema. Runtime finalizers are context, not fault targets.
- Return JSON directly without Markdown fences or text outside the object.

Example (located):
{"status":"located","reason":"An incomplete observation window led to an unsupported comparison.","fault_chain":[{"step":1,"fault_type":"action_parameter_error","evidence_reason":"The clip excludes a candidate already reported in History.","improvement_principle":"Include the reported candidate interval in the comparison clips."}]}

Example (skip):
{"status":"skip","reason":"The public evidence does not identify a feasible correction.","fault_chain":[]}"""

STAGE_CONSTRAINTS = """# STAGE CONSTRAINTS

- Assess the three public action contracts. Treat their execution as a black box.
- Evaluate request quality separately from result quality. A defective result does not retroactively make an adequate request defective.
- Use prior evidence to assess selection and parameters, and the action result to assess execution. Ground truth establishes outcome discrepancy, not facts the Agent knew beforehand.
- Keep honest uncertainty distinct from a demonstrably defective result. Cross-video differences can be valid.
- Steps marked not editable provide context and are excluded from fault_chain.
- Classify a later decision using its own action and available evidence; do not copy an earlier execution-fault category onto it.
- Repeated actions need evidence of an unresolved gap and ineffective parameter choices to establish a fault; purposeful verification can repeat an action.
- State improvements through available actions or public evidence checks, leaving Skill content attribution and editing to later stages.
- The question uses one fixed Skill or none. Neither condition determines the fault type."""

LOCALIZER = '\n\n'.join((INPUT, FAULT_TYPES, EXAMPLES, ANALYSIS, STAGE_CONSTRAINTS, OUTPUT))


def build_localizer_prompt(trajectory):
    from mvagent.skills.prompts import render_skill_text
    return LOCALIZER.replace('{trajectory}', render_skill_text(trajectory, minimum_level=2))
