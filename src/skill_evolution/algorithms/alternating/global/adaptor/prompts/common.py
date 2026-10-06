"""Shared Agent background, card contract and illustrative content."""

BACKGROUND = """# Target Agent

## Available information
The Agent receives the complete multi-video question, including any options and constraints, and available video IDs and durations.

## Available actions
The arguments below are fields of each action's parameters object.
- analyze_videos(videoagent_request=[{video_id, instruction}, ...]): request analysis of selected videos. Give each video a self-contained instruction answerable from that video alone. Each request returns a report about its assigned video. The Agent must combine the reports to reason across videos.
- watch_videos(instruction, videos=[{video_id, clip: [start, end]}, ...]): when available, request joint visual analysis of at least two distinct videos. Specify the comparison and one clip per video, using each video's source-time seconds. The result provides evidence from viewing the clips together.
- answer(): generate the final answer from the question and accumulated History supplied automatically. This action has no input parameters; its output is the final answer.

## Action information boundaries
analyze_videos returns a separate instruction-focused text report for each video. These reports can preserve explicitly requested events, counts, timing and attributes, but they compress the visual evidence. Fine appearance, pose, spatial relationships or brief transitions may be omitted or described too coarsely for a detailed comparison. An omitted feature is unknown; matching descriptions do not establish visual equivalence. Each single-video analysis can inspect only its assigned video, so cross-video correspondence remains the Agent's responsibility.
watch_videos presents the selected clips together to a visual model for the requested joint analysis, allowing comparison before evidence is reduced to independent per-video reports. It returns a textual joint observation for later decisions; it does not preserve all visual detail in History. Its evidence is limited by the chosen clips, frame sampling and model perception. Long clips may receive sparse sampling under the frame budget, and details outside the clips or between sampled frames remain unobserved. Joint viewing does not itself establish synchronization or object identity; the question and observed cues must support the required correspondence.

## Information flow
At each decision, the Agent has the question, video metadata, the fixed question-level Skill if selected, and History from completed earlier actions. Each Step records the chosen action and parameters, followed by the result returned by that action. That result becomes evidence for subsequent decisions.
All instructions in one analyze_videos call are fixed before any report from that call is available. Each video request receives its own instruction and may retain its earlier local observations; it has no access to other videos' reports or the Agent's History beyond information supplied in the instruction. A request depending on another video's new report belongs in a subsequent call.
The Agent sees public reports and joint observations; action-internal reasoning and observation traces remain private. Reported event intervals describe events, and establish observation coverage only when the result explicitly states that coverage.

## Evidence sources
The question and options define the task, including its quantifiers and comparison criteria. A Skill supplies procedural guidance; its examples are hypothetical. Action results supply reported evidence with their stated uncertainty. Ground truth supplied for offline analysis establishes the answer discrepancy and is unavailable during solving. Claims about which action failed require support in the public trajectory.

## Required result
A final answer to the complete multi-video question in the requested format."""

CARD_CONTRACT = """# Skill Card Specification

## Purpose
A Skill supplies a reusable evidence-based method for a complete multi-video question. It is procedural guidance, not task evidence.

## Card structure
Two nonempty English strings define the content:
- when_to_use: one short task sentence with any essential input relationship, used for retrieval and selection.
- strategy: the executable evidence-acquisition and decision procedure.

When choosing a suitable Skill from the available bank, retrieval and selection match the current question against only the card's when_to_use; strategy is not visible during selection. Once a Skill is selected, only its strategy is inserted into the Agent's system context as procedural guidance. The program assigns the reference number; revisions preserve it, role and stages.
The two fields describe one coherent method: when_to_use identifies the task supported by strategy, and its task scope and input relationships match actual procedure dependencies and capabilities. strategy remains executable without selection text.
The two fields together and the rendered body are subject to the supplied total word budget. This budget applies to decoded content rather than JSON syntax. A word consists of letters/digits/underscores, with internal apostrophes or hyphens; standalone punctuation is excluded.

## Design requirements
The following sections define each field's role, content requirements and examples.

### when_to_use
when_to_use is one short English sentence naming the task this Skill supports. It is a retrieval and selection cue matched to the original question, options and video IDs/durations available before observation.

The sentence states the requested result and only the input relationship needed to identify that task, such as shuffled segments from one video, earlier and later segments with a missing middle, or synchronized views at a named event time. These distinctions are part of the task: ordering supplied clips differs from comparing actions within a clip; cumulative event counts differ from a state at one moment; a corresponding interval differs from a fine visual comparison.

The scope matches the tasks actually supported by strategy. Incidental topics, objects, exact video counts, durations and option counts do not narrow a reusable task unless the method depends on them. Observations not yet obtained, returned reports and private memory are not selection inputs. Generic claims such as "video analysis" do not identify a task.

The field contains natural task wording, without execution steps, action names, parameter rules, keyword lists, repeated paraphrases or a separate list of exclusions. Necessary task distinctions fit within the sentence; strategy contains the method and its execution requirements.

examples:

- strong example: Order shuffled segments from one continuous video.
- weak example: Order five cooking clips according to the recipe.

- strong example: Infer the missing event between earlier and later video segments.
- weak example: Use analyze_videos to inspect both endpoints, compare their states, then test which event connects them.

- strong example: Count event occurrences over a video interval.
- weak example: Count objects or events across videos, either at one moment or over an interval.

### strategy
strategy is a numbered procedure for solving the task. It explains what information to obtain first, how to use that information, what to check if something important remains unclear, and when the evidence is sufficient to answer. Each step names the action, the relevant videos and the information its instruction requests. Necessary definitions, such as the counting unit, appear where they are used.

The procedure uses available Global actions and valid parameters. Video IDs and times come from the input or earlier results; a request cannot depend on a report that has not returned. Each analyze_videos request is answerable from its assigned video alone. watch_videos compares at least two different videos, with one valid clip per video and a clear comparison instruction. It is used when needed to resolve a visual difference, not automatically for every comparison.

A follow-up addresses a specific gap that could change the answer, with a changed instruction or range. Missing details remain unknown; they do not prove absence. Matching descriptions do not prove identical objects, and joint viewing is limited by its clips and sampling. Training answers, examples and preferred options are not observations. Once the required result is supported, the procedure calls answer(parameters={}); unresolved uncertainty remains in History. The procedure preserves the question's criteria and output requirements and can be followed without reading when_to_use.

strong examples:

- 1. Use analyze_videos with one videoagent_request per supplied segment; each instruction requests its start state, end state, actions and uncertainty from that video alone.
  2. Match reported end states to start states. If an adjacency is ambiguous, use watch_videos on the disputed videos with clips inside their supplied durations; instruction requests the distinguishing boundary cue.
  3. When the chain is supported, check that every segment occurs exactly once, then call answer with no parameters. If observation cannot resolve a boundary, preserve the uncertainty in History.

weak examples:

- Compare the returned counts. If they disagree, request another check and choose the best-supported option.
- Ask view_C to locate the anchor event; in the same analyze_videos call, ask view_D to count at 21 seconds before that anchor time has been established.
- Add a top-level clip parameter to analyze_videos to limit the request to the disputed interval.
- Counts from synchronized views must match. Recheck different counts until they agree.
- If the named event cannot be located, use a representative nearby moment to answer the event-time question.
- If the event is absent from the report, mark it absent from the video; if no option fully matches, choose the closest option.
- Order the segments from their reported states and answer, without checking that every supplied segment appears exactly once.
- To infer a missing middle event, watch the supplied beginning and ending clips until the middle event is directly observed.
- If joint observation contradicts the individual reports and a repeat does not reproduce it, fall back to the original reports.
"""
