# Runtime Skills

For Global card scope, field-writing rules, multi-video action guidance, and complete
examples, see the [GlobalAgent Skill Specification](../../skill_evolution/infra/global_skill_specification.md).
This authoring reference does not change the runtime contract.

A dynamic bank is an immutable, hash-pinned JSON snapshot with `schema_version: 3`
and a `skills` array. Each authored Skill is one JSON file with exactly five fields:

```json
{
  "meta": {"id": "event-boundary", "role": "video", "stages": ["evidence"]},
  "when_to_use": "An event is located but a required boundary is uncertain. Exclude unlocated events.",
  "strategy": "1. Observe around known anchors, including surrounding context.\n2. Report source-video seconds; a crop edge is not necessarily an event boundary."
}
```

`meta.id` is unique, lowercase-hyphenated, at most64 characters. `role` is global
or video; `stages` is a nonempty unique subset of initial/evidence. Text fields must
be nonempty. when_to_use have no independent hard length limits. All three text
fields combined and the rendered execution body each fit1200 words. Evolution
defaults to the same1200-word `max_card_words` budget for the sum of the two text fields.
Old dynamic-bank formats are rejected. Historical snapshots retain their frozen
source; current code neither converts nor resumes them. Static Markdown policy
references remain a separate existing mode, unrelated to dynamic JSON authoring.

## Module boundaries

| File or directory | Responsibility |
| --- | --- |
| `__init__.py` | Public `SkillBank` and `load_skill` exports; no implementation. |
| `bank.py` | Immutable card/bank data, validation, hashes, path resolution and static/dynamic loading. Card/body limits are enforced here. |
| `prompts.py` | Selector System templates and User input, plus pure Markdown heading rendering for injected Skill text. No file I/O or model calls. |
| `selection.py` | Metadata retrieval, LLM selection, output validation, task-scoped reuse and telemetry. |
| `authored/` | Editable individual Skill JSON cards, grouped by library. |
| `skill_sets/` | Hash-addressed frozen bank snapshots referenced by configuration. |
| `PROVENANCE.json` | Historical selector provenance, not runtime configuration. |

Dependencies: `selection → bank/prompts`; `bank → prompts` for pure text rendering.
Import rendering helpers from `mvagent.skills.prompts`, and data/loading helpers from
`mvagent.skills.bank`. Offline authoring and evolution remain outside this package.

## Selection and execution

1. Filter by role and usable-evidence stage.
2. At most8 eligible cards: expose all in ID order, without retrieval/model embedding.
3. More than8: retrieve top8 by SQLite FTS5 BM25 and top8 by embedding cosine,
   using **only when_to_use**. Fuse by reciprocal rank, summing
   `1 / (60 + rank)` per list, and keep8 (ID breaks ties). BM25 indexes applicability; unmatched lexical entries are excluded. Embedding supplies
   semantic candidates even when lexical matching is empty.
4. Selector sees a readable task, available video IDs/durations, and candidates with **id,
   when_to_use only**. Its supplied JSON Schema permits one candidate ID or none,
   with exactly selected_skill_ids (one string reference or an empty array);
   no reason, boolean or null. Invalid output propagates; abstention is not overridden.
5. Actor receives **Strategy only**, under H3 headings inside
   `## Decision strategy`; headings within each field are rebased to H4 or deeper.
   Metadata and when_to_use are not injected. Put any operational
   prerequisites, exclusions and pitfalls needed for execution into strategy.
   Unclosed code fences are rejected. Observer and finalizers receive no Skill.

`retrieval_top_k` is fixed at8; other values and removed `max_selected` are rejected.
Large eligible banks require `skill.embedding`; failures never silently fall back
or load the whole bank. Embedding uses the existing local `/v1/embeddings` interface,
normalized vectors and immutable process-local indexes. Queries use the first3000
characters of task plus last3000 of visible history. No video pixels or GT are added.

The shared selector template is `SYSTEM_TEMPLATE` in `prompts.py`, identical for
Global and Video. It contains no role BACKGROUND or action signatures. Global
selects for the whole question; Video selects for the current instruction. Rules
require clear main-task applicability before comparing candidates, distinguish
necessary prerequisites from observation goals, and prefer none for unresolved
necessary conditions. New references are sequential numeric strings such as "1";
the JSON output contains only `selected_skill_ids` (strings, empty for none).
The prompt adapts AutoSkill's conservative one-or-none approach but is **not** the
upstream verbatim prompt. User input is readable text under Input (Question for Global or Instruction for Video, plus optional Videos)
and Candidate skills headings, with each candidate headed `## Skill ID: <id>`, not JSON. Global supplies the full question/options
and video IDs/durations; Video supplies the current instruction. Neither sends a
history or max_selected field. Agent execution Memory remains intact; the existing
retrieval query and role/stage filtering described above remain independent of this
LLM input. Candidate text and task text are not truncated by the User renderer.
System sections separate the selection task, target Agent (available information, available actions,
required result), input, selection rules and output contract. No full tool Schema,
sibling private traces or complete Skill strategy enter the selector input.
By default it uses the role Planner model; `skill.selector` can name another model.
Structured generation, bounded repair, pool admission and usage telemetry are shared.

Current `dynamic_35b_embedding.yaml` uses `selection_scope: task`: Global selects
once per QA; Video once per invocation, retaining that selection through its observe
steps and selecting again on a new invocation. Empty selections persist too. Invalid
selections do not. Generic `decision` scope is retained for explicit experiments.

`skill_retrieval` records candidates, fused scores and retrieval identity;
`skill_selection`/`skill_reuse` record full-card hashes and rendered-body hashes.
Changing routing metadata changes card identity even when execution text is unchanged.
Actual Actor requests are audited against the rendered strategy body. Telemetry
is never evidence. Runtime never edits Skills or imports the optimizer.

## Offline management

Use `PYTHONPATH=src /home/kww/miniconda3/envs/MVAgent/bin/python`:

```bash
python scripts/manage_skills.py add --bank outputs/my-skills/author.json --file my-skill.json
python scripts/manage_skills.py update --bank outputs/my-skills/author.json --id event-boundary --file my-skill.json --expected-sha256 CURRENT_BANK_SHA256
python scripts/manage_skills.py remove --bank outputs/my-skills/author.json --id event-boundary --expected-sha256 CURRENT_BANK_SHA256
python scripts/manage_skills.py list --bank outputs/my-skills/author.json
python scripts/manage_skills.py validate --bank outputs/my-skills/author.json
python scripts/manage_skills.py freeze --bank outputs/my-skills/author.json --output outputs/my-skills/snapshots
python scripts/manage_skills.py search --bank outputs/my-skills/author.json --role video --stage evidence --query 'uncertain event start' --embedding-config embedding.json
```

`embedding.json` contains `endpoint`, `model`, optional `timeout_sec`, for example
`{"endpoint":"http://127.0.0.1:8110/v1","model":"qwen3_embedding_8b"}`.
`search` previews the same candidate retrieval as Runtime; it calls embedding only
for large catalogs and does not call the selector. Edits are locked, atomic and
validate the whole bank. Freeze publishes a new `<sha256>.json`, never overwriting
old snapshots. Configure enabled/mode/path/sha256, task scope and embedding on each
role's Skill reference. Neither this code nor these commands deploy model services.

Current cards live under `authored/*/*.json`; experiment bank exports are in
`configs/skill_evolution/skills/`. Original Common Pitfalls were moved into strategy
as constraints; existing guidance was retained. The current 11-card Global acquisition
bank exercises hybrid retrieval; the7-card Video bank bypasses it. No new accuracy
claim follows from the format change. Frozen experimental artifacts are unchanged.

Role backgrounds describe available information, action inputs/results and the required
deliverable directly, without relying on MVAgent/GlobalAgent/VideoAgent names.
Agent execution capabilities remain distinct from the Selector input boundary.

Selector input descriptions are integrated into each Target Agent Available information
section; there is no separate Selector input section. Candidate metadata is described
once in the shared selection task.
Global receives Question, available Videos and candidates; Video receives Instruction
and candidates, without a separate video catalog or retained Memory. These Selector
inputs are distinct from the target Agent's execution-time information and final result.
The shared template only defines selection task/rules and the selection output contract.

Current selection rules evaluate whole-task fit using the requested result and main
evidence need; auxiliary-only matches lead to abstention. Background input/result
sections state received information and deliverables concisely. Existing-evidence
prerequisites require explicit support, while visual facts to acquire are method goals.

当前 Skill 长度规则：两个文本字段合计最多 **1200 words**，when_to_use无独立硬上限；渲染正文（含标题）最多1200 words。统一由 `count_words` 统计字母/数字/下划线组成的词，词内撇号和连字符不拆分，独立标点不计数；cat、analyze_videos、segment_1 各计1 word，1->2 计2 words。这是英文词计数，不是 tokenizer 或中文分词。Prompt 要求简洁英文，通常900–1100 words或更少，上限不是写作目标。配置改为 max_card_words/max_skill_words；旧字符配置不再支持。JSON Schema 仅保留非空和结构检查，单词上限由程序统一校验。冻结实验仍保留原字符口径，不能混用新源码恢复。

2026-10-05 当前规范：新卡引用编号由程序分配顺序数字字符串，Generator只返回四个内容字段，不生成命名ID；修订保持已有引用。引用字段仍用于选卡、归因和版本关联，不承载语义。CARD_CONTRACT使用客观字段规范，Design requirements说明各字段作用、内容细节和样例；无独立字段上限提示。整卡及渲染正文总预算保留。历史冻结源与卡库不改写。
