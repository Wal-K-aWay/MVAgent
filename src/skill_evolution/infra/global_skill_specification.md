**MVAgent GlobalAgent Skill Specification**

Version: 1.1 · Reviewed: 2026-10-05 · Language: English

This document defines how to write and review GlobalAgent Skills for multi-video question answering. It applies to both human-authored and automatically generated skills using MVAgent's three-field JSON format. A skill provides reusable guidance for acquiring, comparing, and combining evidence across videos to answer the current question.

**MUST** identifies a required authoring or runtime constraint. **SHOULD** identifies a recommended practice whose exceptions need a concrete justification. Only requirements explicitly described as parser or runtime checks are automatically enforced; semantic requirements need review and behavioral evaluation. This specification does not change the runtime or prescribe an evolution algorithm.

**1. Basis and adaptation**

OpenAI recommends focused skills, precise discovery descriptions, explicit inputs and outputs, and testing whether requests trigger the intended workflow. Its skill system loads discovery metadata before the full instructions. MVAgent adopts these principles through separate routing and execution fields. [OpenAI: Build skills](https://learn.chatgpt.com/docs/build-skills)

Claude's guidance emphasizes concise instructions, informative descriptions, appropriate procedural specificity, examples, and conditional workflows. These inform the authoring recommendations below. Its filesystem-based progressive loading also distinguishes discovery metadata from instructions and optional resources. [Claude: Authoring best practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices), [Claude: Agent Skills overview](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview)

OpenAI additionally cautions that overly broad descriptions attract unrelated work and elaborate fixed recipes can overconstrain capable models. Here, necessary evidence dependencies are explicit while video-specific choices remain conditional. Effectiveness must be checked with MVAgent's actual models. [OpenAI: Rethinking skills and prompts](https://developers.openai.com/blog/rethinking-skills-and-prompts-for-gpt-6-astra)

The three-field JSON schema, single-skill selection, word limits, actions, and evidence boundaries below are **MVAgent-specific contracts**, not OpenAI or Claude format requirements. This JSON is not a drop-in `SKILL.md` package. MVAgent does not load supporting scripts, linked files, or another skill on an injected skill's request.

**2. Runtime context and visibility**

GlobalAgent receives the complete question, options when present, input video IDs and durations, and public History. Its visual evidence consists of successful VideoAgent reports and completed `watch_videos` results. The Global planner does not directly inspect video pixels.

Each VideoAgent receives its own instruction and retains its own previous trajectory and Memory. It cannot see the complete Global context, other videos, or sibling agents' private information. GlobalAgent cannot inspect a VideoAgent's private observation sequence. Repeated calls may reuse that VideoAgent's retained evidence; a new call does not necessarily imply a new observation.

| Component | Skill information available |
|---|---|
| Runtime eligibility filter | `meta.role` and `meta.stages` |
| BM25 and embedding retrieval | `description` and `when_to_use` |
| Actor | `strategy` only |
| LLM selector | Candidate `id`, `description`, and `when_to_use`, plus the selection input |
| VideoAgent and visual Observer | No automatic inheritance of the Global skill; necessary instructions must be passed through action parameters |
| Terminal finalizer | No injected skill; it follows its existing finalization contract |

Eligible catalogs of eight or fewer skills are shown in full. Larger catalogs use BM25 and embedding recall, fused into eight candidates. The selector chooses at most one skill or none. A skill MUST NOT depend on an unselected companion skill.

The current Global task-scoped profile selects once per question and retains that selection, including none. Author skills as workflows that remain useful throughout a question. Stage eligibility is checked at activation; `stages` does not schedule a future switch or force another selection. An evidence-only skill cannot be assumed to activate later in a question that began without evidence. The generic decision-scoped option is a separate experimental setting.

Runtime details: [Skills README](../../mvagent/skills/README.md), [bank validation](../../mvagent/skills/bank.py), [Global prompts](../../mvagent/agents/global_agent/prompts.py).

**3. JSON structure and enforced limits**


| Element | Parser-enforced contract |
|---|---|
| `meta` | Exactly `id`, `role`, and `stages` |
| `meta.id` | Unique within the bank; program-assigned sequential number for new cards; path-safe reference matching `[A-Za-z0-9_-]+` |
| `meta.role` | MUST be `"global"` for a skill governed by this specification; the shared parser also supports Video skills |
| `meta.stages` | Nonempty array with no duplicates, drawn from `"initial"` and `"evidence"` |
| `when_to_use` | Nonempty text; concise text |
| `strategy` | Nonempty execution guidance |
| Combined text | Sum of the two normalized text-field lengths at most 1200 words |
| Rendered execution body | At most 1200 words, including added headings |
| Fenced content | Unclosed code fences are rejected during rendering |

These are word counts, not token counts, byte counts, or serialized JSON lengths. The current Global evolution recipe limits the two text fields together to `max_card_words: 1200`. Authors targeting that recipe MUST satisfy this budget; the runtime also enforces the rendered-body limit. Upper bounds are not writing targets.

Do not add vendor fields such as `name`, `tags`, `tools`, or `scripts`, or experiment fields such as scores and evidence references. Keep provenance, parent hashes, support cases, and evaluation status in offline artifacts. No additional semantic policy is enforced merely because it appears in `meta`.

**4. Skill scope and granularity**

A skill SHOULD own one distinguishable evidence workflow: a recurring problem structure, a useful method, and a clear completion condition. It MUST preserve the question's requested task rather than substitute a preferred task or output.

Suitable scopes include checking a shared predicate before applying a cross-video quantifier; ordering clips through observed state transitions; transferring a reference-event description to a target video; or comparing a particular visual feature through localized joint observation. These are possible scopes, not a mandatory taxonomy or prescribed number of skills.

A skill MUST NOT route by benchmark names, task codes, sample IDs, answer keys, or memorized media identities. Conditions SHOULD describe observable input structure and evidence needs. Removing a dataset name is insufficient if the procedure still assumes that dataset's options, domain conventions, or video naming pattern.

A skill SHOULD specify the default method and only the alternatives needed by its scope. Do not list every available action as equally appropriate. Do not require every question to follow the same action sequence, inspect every video again, or consume a fixed number of rounds.

**5. Field-writing requirements**

**`meta`: identity and activation eligibility.** The program assigns the reference number. Role and stages define activation eligibility; stages do not schedule future card switches.

**`when_to_use`: task, core method, applicability and nearby boundaries.** Briefly describe the requested result and distinctive evidence procedure before its necessary prerequisites and exclusions. Explain the conditions under which the method fits, the prerequisites known at selection time, and likely confusions with neighboring skills. Distinguish the main requested result from supporting details: asking for timestamps as evidence does not necessarily make temporal localization the main task.

Initial Global selection normally has no visual observations. Applicability MUST NOT depend on hidden visual facts, private Video Memory, unknown future contradictions, or knowing the correct answer. If the choice depends on a later observation, make it a conditional branch inside `strategy`.

Use a few specific exclusions where they prevent plausible mistakes. For example, distinguish counting the number of qualifying videos from counting repeated events inside a video. Avoid long keyword inventories: lexical retrieval does not reliably interpret negation, and shared exclusion words may increase irrelevant recall. Applicability SHOULD allow the selector to decline the card when its prerequisites are absent.


**`strategy`: executable decision guidance.** Write direct steps or short conditional instructions. As relevant to the skill's job, make the following clear:

| Decision | What useful guidance specifies |
|---|---|
| Evidence target | The visible entities, attributes, event conditions, temporal relations, or quantifiers that matter |
| Action choice | When separate local analysis is sufficient and when joint observation is necessary |
| Parameters | Which videos to select, what each instruction must preserve, and how clip bounds follow from available anchors |
| Returned evidence | The local fact, state, interval, identity cue, or limitation needed for Global synthesis |
| Follow-up | Which unresolved distinction could change the answer and which action can resolve it |
| Completion | When evidence is sufficient for the requested answer, subject to runtime limits |

These are review questions, not mandatory headings or a fixed six-step sequence. Include only the instructions that materially change this workflow. Generic advice such as “think carefully” does not replace a concrete operation. Preserve valid alternative approaches when the evidence supports them. Do not invent universal FPS, time-window sizes, iteration counts, or confidence thresholds.

The strategy MUST preserve existing action and answer contracts. It MUST NOT request a new memory object, additional output fields, a long reasoning transcript, an unavailable tool, or hidden file access. An evidence matrix or event ledger may describe how to organize available information; it does not create a new runtime store or mandatory report schema.


Short illustrative examples are optional within strategy. Label invented observations as hypothetical. Use synthetic video IDs and times only inside an explicitly defined example; the Actor MUST substitute the current input's IDs and valid durations. Do not copy training answers or present example observations as facts about the current videos. Examples MUST agree with the applicability, procedure, and output contract. They SHOULD demonstrate a meaningful conditional branch when the workflow depends on one. Placeholders are explanatory text, not runtime template variables.

**6. Multi-video action and evidence rules**

These rules constrain authored procedures. A card only needs to restate the ones necessary for its particular workflow.

| Global action | Required parameter shape | Authoring implications |
|---|---|---|
| `analyze_videos` | `parameters.videoagent_request`: objects containing `video_id` and `instruction` | Each instruction must be independently answerable using that video and its retained local evidence |
| `watch_videos` | `parameters.instruction` and `parameters.videos`: objects containing `video_id` and one `clip: [start_sec, end_sec]` | Jointly observe at least two distinct videos when their visual relationship matters; no `fps` field |
| `answer` | `parameters.answer`: a nonblank string | Use the answer representation requested by the complete question; do not hardcode one option letter, one selected video, or a report format |

Normal Global decisions contain `reason`, `action`, and `parameters`. The current available-action list and Schema are authoritative, including instruction budgets, watch capacity, and per-video duration bounds. A skill cannot make an unavailable action available. Video actions such as `observe` and `finish` are not Global actions.

For separate analysis, pass the exact local criterion and necessary context in each instruction. A VideoAgent does not receive the Global question automatically. Preserve answer-critical qualifiers, object descriptions, and temporal conditions rather than replacing them with “summarize this video.” Do not copy irrelevant options or ask the local agent to decide a cross-video comparison.

Calls within one `analyze_videos` action are independent. If a target request depends on a description extracted from a reference video, obtain that report first and place the relevant description into a later target instruction. Do not ask a VideoAgent to use a sibling report that has not yet been returned. On a repeated call, state the remaining gap; do not demand a new observation merely because the agent was called again.

For joint observation, the `instruction` is the visual model's sole task text. Name the selected video IDs and the precise relationship to inspect. Request visible evidence, not a final option choice. All clips must use their own source-video seconds, be inside the corresponding duration, and have a start before the end. Select each video only once in an action, with one clip. If relevant moments are unknown, the procedure must explain how to locate them or why broader coverage is appropriate; it must not invent anchors.

A shared event time and a video's local timestamp are different concepts. Matching seconds across different videos is not evidence of synchronization. Comparison of equivalent events can legitimately use different source times. Broad coverage can help find events, but sparse sampling may miss brief details; localizing an event does not itself prove its exact boundary.

Cross-video synthesis MUST retain source identities and the original question's semantics. A single-choice option may describe several videos. “All videos” differs from “all events.” Repeated appearances differ from distinct objects. Matching appearance does not by itself establish identity across views.

Use only successful public reports and completed joint-watch results as visual evidence. Failed actions and selection telemetry are not visual observations. An omitted detail is unknown; absence requires coverage adequate for the claim. Distinguish observed facts from an inference supported by them. The skill, its example, and a suggested answer are never evidence.

Follow-up requests SHOULD target a remaining distinction that can change the answer and should not lead the observer toward a preferred verdict. When the evidence is sufficient, allow `answer`; when the runtime reaches its limit, respect the existing bounded finalization and nonempty-answer contracts. Do not prescribe endless verification or require the finalizer to read the skill.

**7. Formatting and content economy**

Write the two text fields in English, retaining exact action names and JSON keys. Plain prose, short numbered steps, and compact Markdown are allowed inside strings. Escape quotes and newlines correctly in JSON.

Runtime adds `### Strategy` and nests headings inside each field at H4 or deeper. Authors SHOULD omit redundant outer titles. Keep code fences balanced. Do not embed a second system prompt or competing Task, Rules, or Output Contract section.

Prefer operational detail over generic reassurance. Keep necessary conditions close to the step they govern. Do not add long API manuals, benchmark commentary, optimization history, or links that the Actor would have to open. Unlike filesystem-based vendor skills, this runtime injects only the strategy string and exposes no skill-resource loading action.

**8. Complete examples**

The following cards illustrate this specification. They are documentation examples, not deployed skills, accepted evolution results, or evidence of accuracy gains. Their observations are fictional. Both fit the current 1200-word evolution budget.

Example A demonstrates consistent local criteria and cross-video quantifiers:

```json
{
  "meta": {
    "id": "global-quantified-presence",
    "role": "global",
    "stages": ["initial"]
  },
  "when_to_use": "The question compares whether a named condition holds in each video, and each local judgment is independently observable. Exclude counts of repeated events within one video and visual identity matching that requires joint comparison.",
  "strategy": "1. Identify the exact visible condition and its qualifiers. Use this procedure when that condition is independently checkable in each video; preserve whether the requested result concerns videos or option combinations.\n2. Use analyze_videos with one videoagent_request per relevant video_id. Each instruction states the same local criterion and asks for decisive visible evidence, necessary temporal anchors, and uncertainty. Keep every request answerable from that video alone.\n3. Compare the returned reports using that criterion. Separate supported presence, supported absence, and unknown. Omission is unknown; a negative needs coverage adequate for the claim.\n4. If an uncertain or conflicting finding could change the required quantifier, ask that VideoAgent to check the specific gap, using public anchors when available. Do not suggest the desired finding.\n5. Apply the question's quantifier to the supported findings and answer in its requested format when the combination is resolved. At the runtime limit, follow the existing finalization contract without inventing evidence."
}
```

Example B demonstrates localized joint comparison and explicit parameter guidance:

```json
{
  "meta": {
    "id": "global-localized-feature-comparison",
    "role": "global",
    "stages": ["initial"]
  },
  "when_to_use": "The question requires a shared or distinguishing visual feature to be compared across videos at consistent detail. Relevant moments may need localization first. Exclude event counting, exact boundary localization, and ordering whose answer follows from already established state transitions.",
  "strategy": "1. Identify the visible discriminants required by the question. Use this workflow for a cross-video feature comparison; do not infer shared identity merely from a matching color or shape.\n2. Reuse adequate public reports. If the relevant moments are unknown, use analyze_videos to request where the specified object and features are visible in each needed video. Each request names the local target and asks for source-time anchors and visibility limits.\n3. If joint evidence is still needed and watch_videos is available, select at least two relevant video IDs and one bounded clip per video around the reported moments. Set parameters.videos to video_id/clip objects and parameters.instruction to the exact feature comparison naming those IDs. Keep enough context to identify the object. Do not include fps or assume equal seconds mean synchronized events.\n4. Compare the returned visible details. If an unresolved feature could change the answer, obtain evidence for that gap; do not repeat the entire workflow automatically. Answer when the comparison is supported, preserving the question's output format and runtime limits."
}
```

For Example B, a complete hypothetical action using the existing Global contract is:

```json
{
  "reason": "The public reports locate both bags, but the closure mechanisms still need a joint visual comparison.",
  "action": "watch_videos",
  "parameters": {
    "instruction": "Compare the visible fasteners on the bags in video_1 and video_2; describe each mechanism and any obscured detail.",
    "videos": [
      {"video_id": "video_1", "clip": [8, 12]},
      {"video_id": "video_2", "clip": [25, 29]}
    ]
  }
}
```

The source times differ because the question compares corresponding objects, not a synchronized instant. Actual decisions must use the current question's IDs, durations, evidence, available actions, and limits.

**9. Review and validation**

Separate mechanical validity, appropriate selection, actual execution, and answer quality. OpenAI's evaluation guidance recommends checking both outcomes and recorded behavior, including negative trigger cases. MVAgent applies that distinction to selected IDs, injected bodies, action parameters, returned evidence, and official question scores. [OpenAI: Testing Agent Skills Systematically with Evals](https://developers.openai.com/blog/eval-skills)

Review each candidate against the following criteria:

| Check | Required review |
|---|---|
| Structure | Exactly five fields; valid meta; nonblank strings; applicable size limits; valid rendering |
| Scope | One identifiable workflow; capability rather than dataset identity; no unsupported expansion of the task |
| Discovery | Description and applicability distinguish likely neighbors using information available at activation |
| Consistency | Routing promises, execution prerequisites, procedure, and example agree |
| Self-containment | Strategy remains usable without when_to_use, external files, or another skill |
| Action fidelity | Existing actions and fields; valid IDs and time coordinates; explicit evidence-bearing instructions |
| Evidence discipline | No hidden traces, answer leakage, fabricated observations, or example facts treated as current evidence |
| Behavioral value | A specific decision or parameter choice improves beyond generic advice and can be inspected in a trace |

Behavioral evaluation SHOULD cover a clear positive case, a close negative case, and a case where required evidence is missing or ambiguous. Add cases that reflect the skill's actual branches and known failure modes. Applicability labels may allow several reasonable skills or none; they are not ground truth for usefulness.

Observe whether the correct body was injected and whether its applicable instructions changed behavior as intended. Compare final answers under matching model, runtime, question, budget, and scoring conditions. A syntactically valid skill, high selection frequency, or better adherence alone does not establish accuracy improvement. Evaluate the whole bank under ordinary selection before accepting a claimed system improvement. This specification does not replace the experiment's acceptance protocol or make token/call counts an optimization objective.

In the current Global evolution workflow, routing revisions preserve strategy, and procedural revisions preserve when_to_use. Record provenance and results outside the card. Update only what the evidence supports rather than accumulating a new universal rule for every failure.

**10. Maintenance**

This document is an authoring reference; it is not loaded into a model prompt. Its illustrative cards are not installed. Changes to actual authored cards or model-visible prompts must follow the repository's existing Chinese prompt-mirror maintenance rule.

Keep this specification aligned with [SkillCard validation](../../mvagent/skills/bank.py), [Global action Schema](../../mvagent/agents/global_agent/schema.py), [Global prompts](../../mvagent/agents/global_agent/prompts.py), and the active selection profile. Runtime source is authoritative for enforced behavior. The separate [Global evolution design](../../../analysis/skill_evolution/global_skill_evolution_design_20260927.md) covers candidate search and experimental planning.

当前 Skill 长度规则：两个文本字段合计最多 **1200 words**，when_to_use无独立硬上限；渲染正文（含标题）最多1200 words。统一由 `count_words` 统计字母/数字/下划线组成的词，词内撇号和连字符不拆分，独立标点不计数；cat、analyze_videos、segment_1 各计1 word，1->2 计2 words。这是英文词计数，不是 tokenizer 或中文分词。Prompt 要求简洁英文，通常900–1100 words或更少，上限不是写作目标。配置改为 max_card_words/max_skill_words；旧字符配置不再支持。JSON Schema 仅保留非空和结构检查，单词上限由程序统一校验。冻结实验仍保留原字符口径，不能混用新源码恢复。


Current content fields are when_to_use and strategy. when_to_use combines the task summary, distinctive evidence method, necessary prerequisites and applicability boundaries; strategy is the standalone execution procedure. Examples and normative field details are maintained in the shared CARD_CONTRACT in each Global author prompt.
