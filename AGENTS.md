# MVAgent_API Project Guide for Agents

Read this file before changing the repository. It is the primary guide for agents
working in `MVAgent_API`, the API-first fork of MVAgent with an optional local vLLM
backend.

## Required Maintenance Rule

When any change makes this document inaccurate, update `AGENTS.md` in the same work
item. This includes runtime flow, entry points, configuration fields, supported model
types, source paths, scripts, tests, dataset roots, output layout, or dependencies.

The human-readable Chinese Prompt mirror is
`analysis/current/prompt_chinese_reference.md`, except current Global evolution prompts:
their per-file mirrors live in
`src/skill_evolution/algorithms/alternating/global/{adaptor,cluster,cluster_v2}/chinese_prompts/`.
Update the corresponding mirror in that directory for changes to the matching global/{adaptor,cluster,cluster_v2}/prompts/;
the general document keeps an index only for this flow. Any change that affects a model-visible Prompt
string, role or evidence boundary, output contract, action block, Skill preamble,
Observer/finalizer wrapper, dynamic Memory/History rendering, or shipped authored Skill
content must update the corresponding Chinese mirror in the same work item. Keep action names, JSON fields,
and template variables unchanged in the Chinese mirror; it is documentation only and is
never loaded by Runtime.

## Git baseline and experiment workflow

The 2026-09-09 no-Skill runtime checkpoint is tagged `mvagent-base-20260909`.
Keep that tag fixed; use `skill-evolution/experiments` for subsequent optimizer work.
Baseline settings and validation references are recorded in
`analysis/current/runtime_baseline_20260909.json`. The closest completed 500-question
run predates deletion of the Video reason switch; its no-reason rendered Prompts match
the checkpoint. Do not describe that run as an exact post-deletion end-to-end rerun.
Record the commit, source snapshot, Skill hashes, split, model/Judge and inference
configuration for each experiment. Generated outputs and model weights stay ignored.
`scripts/attribution_probe.py` reads its credential from `DEEPSEEK_API_KEY`; never embed
an API credential in source or experiment manifests.

## Engineering Principles

- Do not keep backward compatibility. Remove obsolete things directly. Do not add compatibility layers, write migrations, or keep fallbacks.
- Choose the simplest implementation that satisfies current needs. Do not add preventive abstractions or unnecessary configuration layers.
- Keep the system layered but shallow. First get a minimal end-to-end version working, then add features on top. Never tear down a working system for the sake of unfinished complexity.
- Keep components modular and separate concerns.
- Prefer mature, well-maintained libraries. Do not rewrite them yourself without a clear reason.
- First check what existing dependencies in the project can do, then consider adding new packages or writing your own. Do not assume something is missing from the start.
- Make architectural decisions with a long-term perspective. Reject temporary solutions that are "good for now and will be replaced later."
- First see how mature products solve the same problem, and use proven patterns. Do not reinvent the wheel.

## Current task and experiment boundary

Skill evolution implementation and controlled tests are authorized on 2026-09-16. All three benchmarks with no Skills and the separately
authorized OpenQA API judging are complete. The user requested a clean restart:
the prior result root was deleted and all benchmark predictions were regenerated. Output:
`outputs/mvagent/no_skill/qwen3_5_35b_a3b_mvagent_no_skill/`. Control, frozen code/configs, current
launch/status/logs and restart provenance:
`outputs/analysis/20260915_no_skill_full_deferred/`. Do not edit its frozen files.
Check saved status rather than continuously polling; detach long experiments.

The full run has CrossVid9015, CVBench1000, MVU-Eval1824 questions (11839 total).
All 11839 predictions completed; on 2026-09-16 the user authorized separate DeepSeek
API scoring for all 872 CCQA answers. `eval/agent_eval/score_crossvid_ccqa.py` reads
DEEPSEEK_API_KEY from the environment, validates boolean counts against scoring points,
and caches response text, returned model and usage. Requested deepseek-v4-flash now
returns deepseek-flash; do not claim exact historical Judge model equivalence.
`eval/agent_eval/finalize_results.py` joins these scores by ID and exact prediction,
writing summary_scored.json and benchmark_results.md. Original deferred summary and
records remain unchanged; deferred score/correct stay null, never zero.
Closed-task scoring remains active. Independent24-question preflight repeats matched
actual input/output tokens; the postflight repeat also matched all24. This is sampled evidence,
not universal determinism. Old preflight records are not benchmark predictions.

Current Actor settings: Qwen3.5-35B-A3B, GPUs2–7, one admitted request per endpoint,
auto6 question workers, Video concurrency2, temperature0, top_p1, thinking disabled,
2048 output tokens,512 frames, Global/Video max_steps5. GPU0/1 are excluded.
Endpoints for GPU2/3/4/5/6/7:8105/8106/8101/8102/8100/8001. Verify actual service
identity before reuse; do not kill resident services or another user's jobs.

2026-09-19 current evaluation: the user authorized replacing all six GPU2–7 services
with Qwen3.5-27B and starting a no-Skill run at
`outputs/mvagent/no_skill/qwen3_5_27b_mvagent_no_skill/`. It uses full CVBench1000,
full MVU-Eval1824 and the frozen CrossVid Lite2500 development panel (5324 total),
selected with `--split-manifest`. All 5324 predictions completed with zero errors on
2026-09-20. The separately authorized official-protocol CCQA Judge completed all239
panel answers with zero failures; requested `deepseek-v4-flash` returned
`deepseek-flash`, so do not claim exact historical Judge identity. Final artifacts are
`summary_scored.json` and `benchmark_results.md`; raw inference records retain their
deferred state. Headline scores are CVBench68.80%, MVU-Eval54.50% micro and CrossVid
46.74% ten-task macro (CCQA31.11%).
That completed run's model config is `configs/inference/local_qwen35_27b_no_skill.yaml` and the
six-replica cap1 pool is
`configs/inference/execution/gpu2_7_qwen35_27b_single.yaml`. All six workers and exact
27B service identities were verified before launch. Do not describe CrossVid as the
full9015 benchmark or use the raw deferred summary as the final scored result.

2026-09-20 current diagnostic: the user authorized switching GPU2–7 back to
Qwen3.5-35B-A3B and testing handwritten watch strategies. All six services were
replaced after idle/identity checks, then verified through the existing pool path
(six workers, no unavailable endpoints). Frozen 96-question development panel:
CrossVid CC/PI, MVU Comparison, CVBench spatial navigation, 24 each. W0 is no Skill;
W1 requests first full-duration joint watch; W2 additionally preserves visual
discriminants in instruction. Prompt compliance must be measured, not assumed.
Control/source/Skills/protocol/status: `outputs/analysis/20260920_watch_diagnostic/`;
detached `controller.py` runs 8-question engineering smoke per arm then fresh96 per
arm, with no optimizer/API Judge. Inspect saved status, preserve active artifacts,
resume only the owning controller, and never rerun its one-off service replacement.
The panel is outcome-enriched development evidence, not Train or independent Test.
All arms and smoke runs completed: main W0/W1/W2 correct45/54/58 of96,
zero model errors/fatal/invalid. Random32 subset correct21/21/22; do not infer
benchmark-wide gains or deploy forced watch from enriched-panel results.
See section10 of the analysis plan for paired regressions and evidence limits.
Runtime/action contracts remain unchanged; branch search/state restore are plans.
Analysis and next implementation order:
`analysis/skill_evolution/contrastive_branch_plan_20260920.md`.
The retained historical35B no-Skill root was verified at
`outputs/mvagent/no_skill/qwen3_5_35b_a3b/`; older prose paths may no longer exist.

Current evolution state and restart guidance: `analysis/skill_evolution/handoff.md`.
Historical frozen130/70 training accepted Video step0 and Global steps3/7, then stopped
at next_step15 on pool timeouts; final confirmation is absent. Its500-question test
found empty/current55.989%/52.676%, with conditional interval crossing zero. Current
Skill is not a proven improved default. The subsequent Train130/Gate300 E0–E3 arms,
audit500 and E3 expanded evaluation are complete; see the dated results below.
The user authorizes GLM-5.3-Flash optimizer API use without per-run reconfirmation,
and completed evolution experiments invoked it. Future methodology must remain
optimizer-agnostic; no universal positive gain is guaranteed or demonstrated.
No cost/time/Observe-count objective or tie breaker in evolution.

## Architecture and contracts

- `src/models/` is shared model infrastructure; it imports neither Agent runtime nor
  skill evolution. Supported instance types: api_llm, api_vlm, local_vllm.
- `src/mvagent/` is online only. Engine owns question orchestration, shared models,
  trajectory and cleanup; one GlobalAgent coordinates one VideoAgent per video.
- Global owns the complete question and public History. Each Video has a text-only
  Planner, visual Observer, local instruction and private Memory. Global does not
  see absolute media paths or sibling private traces.
- Video actions are observe and finish only. Observe chooses what, ordered source
  ranges and FPS; Runtime validates and executes. No SAM3/object detection or
  temporal-localization backend remains. Do not restore them through old plans.
- Global decisions require reason/action/parameters; Video decisions require only
  action/parameters. Video reason and its switch are removed. Global may
  analyze_videos, watch_videos, or answer; answer parameters are empty and Runtime
  supplies question/History to the standalone answerer. Finalization is bounded and explicit.
- Finish requires at least one Runtime-owned usable observation. At the step limit,
  terminal text-only summarization uses retained evidence. Preserve required nonempty
  summary/answer contracts; failed calls are not usable observations.
- Observations retain actual ranges/effective FPS; visual calls are stateless.
  Global reason stays enabled; Video reason stays disabled. Schema validation,
  output length constraints and bounded repairs must remain observable.
- Each role can load one hash-pinned policy reference, validated once by Engine:
  static Markdown or schema_version3 dynamic JSON bank. Dynamic selections default to each decision; optional task scope persists the first
  valid selection for one Global QA or one Video request. Activations filter
  role/evidence stage, retrieve with metadata-only Qwen3 Embedding cosine AND SQLite FTS5
  BM25 using reciprocal-rank fusion (rank constant60, top8 each then fused top8), then use the configured selector (default role model) to choose one card or none.
  Small eligible catalogs are fully shown; embedding failures never silently fall back.
  retrieval_top_k is fixed at8; max_selected is removed and rejected.
  Selection sees only id/when_to_use; Actor receives only strategy.
  Cards contain meta={id,role,stages} plus when_to_use,strategy.
  Selection Schema and bank rendering enforce at most one1200-word body.
  Invalid selection propagates before action generation; errors never silently load all.
  Disabled references are not read; empty selections render None. Full selector/action
  requests and skill_retrieval/skill_selection telemetry remain separate from evidence.
  Fixed boundary preamble remains; Observer and terminal wrappers receive no Skill.
- Skills cannot override actions/Rules or supply evidence. Runtime never sees GT,
  imports an optimizer or edits Skills. Selection events are telemetry, not evidence.
- Keep Runtime independent of benchmark names/task codes. Keep ModelFactory stateless,
  RuntimeResources model-only, and action lists aligned with Prompt and Schema.

Detailed contracts: `analysis/current/system_architecture_and_flow.md`,
`prompt_design.md`, `memory_and_evidence_design.md`, `benchmark_contracts.md` and
`prompt_chinese_reference.md` in that same directory. Source is authoritative if
historical prose disagrees; update documentation with any behavior change.

## Offline evolution

Current Linker evidence criteria (2026-10-01): attribution targets the localized step,
separates missing content from unused or unfollowed guidance, and distinguishes card
text, actual exposure, and Localizer improvement suggestions. A revise decision requires
an identifiable content defect and a supported link to the action or its selection.
when_to_use informs selection; strategy supply decision
guidance, subject to explicitly provided historical injection evidence. The output is flat status (revise/generate) plus reason; there is no weight threshold or fault-type override.

Current algorithms also include global-cluster-v2 (2026-10-06, see cluster_v2 README): explicit Train/Cal/Gate, four optimizer stages and a complete-bank search pool. global-cluster-v1 (2026-10-03, see cluster README) runs
fixed-cluster batch reflection and one-card optimization; global-skilladaptor-v1 runs Global optimization under
algorithms/alternating/global/adaptor/. Video Skill is frozen; Video optimization and outer
alternating scheduling remain unimplemented. Fixed Train original-input embedding/Louvain groups
and a versioned cross-batch success/failure material pool precede Localizer failure triggering;
Linker attribution for the single question-level Skill, direct revise/generate routing, Reviser/Generator, programmatic validation and exact-duplicate checks, full Gate per candidate.
Acceptance is strictly positive overall official aggregate only; task/health changes
are logged, not extra gates. No two-source prerequisite or Train prescreen. Optimizer
gets Global public Train traces only; Gate details never enter model inputs. Prompts and stage Schemas
live in global/adaptor/prompts/<stage>/{prompts,schema}.py. runner imports the role module only for train; evaluate loads
no optimizer. Recipe configs/skill_evolution/global_skilladaptor_35b.yaml requires an
explicit frozen split; train never loads Test. Shared raw rollouts/scoring/bank storage
are reused. State global_evolution/state.json commits rounds atomically; persisted stage
responses and full-bank cache permit replay after interruption. Single process lock;
invalid output is recorded without stage-level correction; operational errors propagate. See Global
README for configuration/artifacts. Historical lifecycle descriptions below are archival.
Shared infrastructure:

- data: fixed Train/Eval/optionalTest identities, batching, media-group audits;
  training never loads Test. Do not relabel development data as independent Test.
- rollout/evaluation: persist raw results before scoring, independent scorer cache,
  official aggregation and per-question health. Judge failures raise, not score zero.
- trajectory: role-specific views, dependencies, actual Observe parameters; raw
  requests/repairs/usage are separately recorded and media represented by hashes.
- bank/store: immutable whole banks, parent hash/operation checks, transactional updates,
  source/media fingerprints, atomic artifacts and frozen source for resume.

Current lifecycle supports add/refine/merge/retire/keep; one operation per candidate,
at most2 candidates/round, one full Gate finalist selected using Train only. Merge is
atomic two-card same-role/same-stage consolidation. Candidate cards require two nonempty JSON text fields plus meta,
at most2400 chars, Train refs from at least2 source groups and operation-specific coverage.
Every candidate rollout starts the entire question with the whole bank, never reusing
inactive-role episodes from a different bank. Capability acceptance needs positive macro
delta, no protected-task decrease versus parent/seed, no new per-question fatal/invalid.
Default protection covers all task buckets. Zero-gain merge/retire maintenance additionally
requires no per-question Gate loss and a predeclared source-disjoint Eval confirmation
subset, with the same no-loss checks. Empty maintenance_ids disables maintenance acceptance.
Gate detail never enters optimizer prompts. No cost/count objective or slow/meta hierarchy.
Recipe: configs/skill_evolution/bank_lifecycle_27b.yaml; explicit --split-manifest required.
Runtime registry: configs/skill_evolution/runtime/dynamic_27b_embedding.yaml. Actor/Selector/
Observer27B, existing Embedding8110, GLM optimizer; service deployment is unchanged.
Artifacts: lifecycle/state.json (atomic cursor+bank+decisions), lifecycle/versions/,
rounds/, evaluations/, routing/, final_bank.json, summary.json. Input evidence preserves
whole role-local cases within100000 chars, omitted refs recorded. Actual body injection
is audited from Actor requests; missing requests remain unknown, not inferred injection.
Training owns a nonblocking process lock; resume reuses persisted optimizer proposals.
Full bank, routing/embedding, models, execution, media, Runtime/repeat enter cache identity.
Historical static SkillOpt and GEPA implementations have been removed; replay uses original frozen sources.

Historical 2026-09-16 algorithm: joint optimization was removed; SkillOpt-derived slow
edited runtime Skill and meta guided future optimizer calls. Its gate.py used
single-positive-health-v1. Historical three-repeat calibration retains its own reporting rule.
Fast edits carry validated evidence_refs through merge/rank; these never deploy. Allowed
references are enumerated in each proposal Schema and shown in trace headings; the
initial smoke that omitted a prefix is retained, revised E2/E3 sources use *_revision1. Slow/meta
inputs align video/call identities and mark instruction/partner changes and cache reuse.
Prompt templates are MVAgent adaptations, not byte-identical SkillOpt originals.
Controlled E0–E3 sources and status: outputs/mvagent/skill/20260916_evolution_redesign/.
E0 retains joint only in its frozen source; do not edit frozen arms. Runtime stays strict.
2026-09-17 API recovery: experiment descendants set NO_PROXY/no_proxy to include
open.bigmodel.cn after repeated SSL EOF through the inherited local proxy. Direct
replay of the failed request passed HTTP/Schema checks; this is not a balance error
response or proof that all future networking is stable. Frozen code/configs stay intact.
Transport evidence: outputs/analysis/20260917_glm_transport/.
Historical full experiment protocol: `analysis/skill_evolution/empty_stable_evolution_20260915.md`;
implementation: `src/skill_evolution/README.md`; redesign protocol and future work in `historical_next_steps_20260920.md`.
The 2026-09-19 rewrite of `analysis/skill_evolution/historical_next_steps_20260920.md` records the N0–N6
background protocol. The 2026-09-20 `contrastive_branch_plan_20260920.md` now owns
the next implementation order; new evolution mechanisms remain plans. Start with
diagnostics and focused evidence, keep Actor/Gate fixed, and enable candidate-count,
role-feedback or explicit batch scheduling changes only in their separate experiments.
Section16 adds a separate Runtime/Prompt diagnostic branch: audit watch context and
evidence transfer first; any future Runtime change needs its own no-Skill baseline
and matched evolution comparison. These recommendations are not deployed changes.
The completed CrossVid Lite2500 development panel is frozen at
`configs/skill_evolution/splits/crossvid_lite2500_eval_seed20260919.json` (eval only).
Build: `scripts/prepare_crossvid_representative_subset.py`; post-freeze validation:
`scripts/analysis/audit_crossvid_representative_subset.py`. No model/Judge calls were
made. Metadata stratification, known source isolation, inclusion probabilities and
historical-score checks are documented in `analysis/skill_evolution/crossvid_lite2500.md`;
preserve `outputs/analysis/20260919_crossvid_lite2500/` and its future-training source
guard. Whole-film/session isolation is not established. Future Train/Gate expansions
must exclude panel sources; no running recipe was switched. Preserve task macro.
The earlier E0–E3 implementation plan is archived via `historical_protocols.md`.
Resume through the owning frozen runner with identical algorithm/input/Skill/scoring
identities. repeat_id forces fresh inference; it does not promise deterministic tokens.

## Execution, models and media

`mvagent.batch.BatchExecutor` serves both evaluation and evolution: spawn workers,
dynamic question queue, deadlines/retries, partial-result persistence and resource
metrics. Workers own Engines but no weights; requests route to matching replicas.
`models/pool.py` provides process-shared endpoint capacity under /tmp/mvagent-model-pools,
explicit GPU/UUID service verification, orphan detection and endpoint quarantine.
An abandoned request is not considered cancelled by releasing a client lock; recover
only after bounded empty-queue and inference checks. Never reset locks to hide work.

ExecutionConfig controls question_workers, max_prepared_requests, question_timeout_sec,
question_retries, optional media_cache and named model_pools/replicas with endpoint,
gpus and max_inflight. Device placement belongs here, not model YAML. Auto worker
count uses healthy Actor capacity; Video concurrency remains a Runtime setting.
Media preparation limits precede endpoint admission. Keep result/barrier ordering.

Media cache uses content/processing identity and leases; never evict in-use media.
Clipping uses FFmpeg input seeking/stream copy; short clips may require last-frame
padding. Stream copy is not frame-identical to the old OpenCV path. The commented
historical OpenCV function remains at the user's request. Do not silently alter
sampling, pixels, timestamps or preprocessing under an efficiency-only change.

BigModel uses JSON mode plus local Schema validation and one bounded repair, not
strict provider Schema enforcement. GLM profile: thinking on, reasoning_effort high,
temperature1, top_p.95, max_tokens16384. Credentials: BIGMODEL_API_KEY; never persist
keys or reasoning_content. API changes require adapter tests; no claim of validated
GLM video handling from the text optimizer probe. Attribution uses DEEPSEEK_API_KEY.

## Configuration, data and entry points

All configs/ files live beneath inference/ or skill_evolution/:
- inference/: model/Agent settings; execution/: shared GPU pools.
- skill_evolution/: recipes and splits; redesign_train130_gate300_glm.yaml is the new recipe;
  runtime/strict_qwen35_glm53_deepseek.yaml fixes Actor/optimizer/Judge; other runtime/ files are model registries;
  execution/: dedicated local-optimizer pools. No legacy aliases or duplicated pools.
Shared GPU pools can serve both tasks. Historical recipe parameters are not silently
updated. See each subtree README. Current six-card profile is
`configs/inference/execution/gpu2_7_single.yaml`; no-Skill Actor profile is
`configs/inference/local_qwen35_35b_a3b_historical_no_skill.yaml`.
Some retained qwen35 filenames actually specify Qwen3.6 FP8: read model_name.

- `demo.py`: individual question/video or sample JSON inference.
- `scripts/manage_skills.py`: offline add/update/remove/list/validate/freeze for
  dynamic Skills; stale edits rejected, snapshots hash-addressed and immutable.
  Format/runtime selection: `src/mvagent/skills/README.md`.
- `eval/agent_eval/run.py`: resumable MVAgent evaluation for CrossVid, CVBench, MVU-Eval.
  --defer-open-qa-judge conflicts with --judge-model and is part of resume identity.
  --sample-ids-file selects an ordered JSON array across requested benchmarks;
  empty/duplicate/unknown IDs are rejected and selected IDs enter resume identity.
  It conflicts with --limit and --split-manifest; benchmark inputs remain unchanged.
- `eval/e2e_eval/`: tracked official-source tree and separate adapters; no nested Git
  repositories. Keep official scoring logic and record upstream provenance.
- `eval/e2e_eval/api/providers/`: one invocation script per official API platform;
  shared HTTP execution stays in `api/client.py` and benchmark orchestration in
  `api/run.py`. Manifests hash the selected provider script. API runs use the local
  E2E benchmark layout (`cvbench/raw`, `mvu_eval/raw`, `crossvid/raw`), the shared
  record fields plus additive provider metadata, and per-benchmark summaries.
- `scripts/run_official_cvbench_mvu.py`, `scripts/official_crossvid/`, and the
  `eval/e2e_eval/api/` adapter have distinct direct-inference protocols: use their
  documented interfaces, not MVAgent score claims for different inputs/budgets/Judges.
- `scripts/prepare_all_multivideo.py` is the one-command preparation entry point for
  a newly downloaded dataset root: it validates CrossVid/CVBench/MVU-Eval and
  integrates CrossVid media generation, resumable worker batches, `qa.jsonl`
  generation and final validation. `scripts/prepare_multivideo_benchmarks.py`,
  CrossVid preparation/visualization and split preparation scripts remain active
  utilities. frames_to_video is imported.
- `scripts/analysis/README.md` lists maintained audit categories; historical scripts
  operate on frozen records, not current inference. Probe scripts can spend API money.

Dataset paths are listed in `eval/benchmarks.txt` (moved from the repository root).
`eval/crossvid_2500.json` is a plain JSON array of all2500 unique full QA IDs
(`crossvid:<task>:<original_id>`); the split manifest remains the authority for
membership/grouping and `--split-manifest`. The completed sampling plan has been
removed from historical_next_steps_20260920.md; its report and provenance remain preserved.
Dataset default: /home/kww/datasets/Multi-Video/{CrossVid,CVBench,MVU-Eval}. Treat IDs,
bbox anchors, video order, reference/scorer identity and time coordinates as protocol.
Absolute model/data paths are machine-specific. Do not install/upgrade packages in
resident service environments to validate documentation. Root requirements.txt is the
single Python3.12/Linux dependency manifest, not a transitive lockfile. psutil>=7 and
imageio-ffmpeg>=0.6 provide service verification and bundled FFmpeg support.

## Outputs and documentation

`outputs/` and weights are ignored local artifacts. Never move/delete/compress a run
while a process writes it or another run reads its inputs. Preserve provenance,
checkpoints, Skill hashes, predictions and scorer details. Rollout caches are results,
not disposable media. Media caches can be rebuilt only after lease/process checks.
Resident service logs stay intact; one output-level source snapshot per run.

Authoritative retention rules: `analysis/current/outputs_retention_policy.md`.
Recent cleanup manifests under outputs/cleanup* record lost raw data and safety copies;
references to removed runs support only retained summary/case evidence, not resume.
The historical Observer2000/400 300/200 baseline and Video-reason counterpart
were deleted at the user’s explicit request on 2026-09-16. Their retained documentation
is summary-level evidence only; raw replay/resume is unavailable. Current full results remain separate. An absent retained_runs_index
must not be treated as proof that a directory is disposable.

`analysis/README.md` is the document entry. Current contracts belong in current/,
current experiment state in handoff.md, future changes in historical_next_steps_20260920.md, historical
results in experiment_summary_20260914.md and distinct reports. docs/, root demo command
catalogs, duplicate old plans and generators were removed. Do not recreate old report
paths from a historical script without an explicit task. Preserve unrelated dirty files.
No credentials in source, config snapshots, logs or manifests.

## Validation

Use /home/kww/miniconda3/envs/MVAgent/bin/python with PYTHONPATH=src in this workspace.
Tests cover current contracts even where names contain historical/experiment terms;
see tests/README.md. Prefer affected CPU-only tests, then broaden for real concerns.

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python -m compileall -q src tests demo.py scripts
```

Some modules contain pytest-style functions; unittest discovery does not execute
those functions. Do not report them as passed from a unittest run. Use the available
runner or explicitly call focused checks with suitable temporary fixtures; do not
install into resident service environments merely to run tests. No network/model
inference is required for ordinary unit checks. Always inspect failures and test count.


### Six-GPU recovery during current evaluation

The first batch after the clean restart admitted only GPU2/4/5 (3 workers), because
GPU3/6/7 remained quarantined from the stopped run. This was detected and recovered
through the existing ModelPool verification/probe path; workers were restarted with
resume and completed predictions retained. New batch_prepared confirms6 workers,
all6 endpoints and no unavailable service. See six_gpu_recovery.json in the control
root. Do not report the earlier phase as six-GPU throughput. Frozen runtime and cap1
remain unchanged; startup exclusion/automatic rejoin behavior is not patched yet.


2026-09-16：按用户要求，已完成结果目录更名为 `outputs/mvagent/no_skill/qwen3_5_35b_a3b_mvagent_no_skill/`。`_strict` 用于区分本轮包含 Schema 等严格约束的 Runtime；本次仅改目录名，不改变模型、约束或分数。冻结记录中的执行时旧路径保留，映射见结果目录 `directory_rename.json`。

2026-09-19: E0–E3, audit500 and E3 expanded CVBench/MVU-Eval evaluation completed. The latter used frozen E3_revision1 and GPU2–7 under `outputs/mvagent/skill/20260919_E3_full_cv_mvu/`; excluding Train130/Gate300 IDs left CVBench876 and MVU1696. CVBench579→584 correct (+0.5708pp); MVU900→900 correct (micro unchanged, task macro−0.0865pp). No optimizer/Judge API; historical strict baseline matched by ID. E3 fatal0, MVU invalid5/model_errors3/failed_video_requests17; do not assume these are new regressions without paired audit. Read report.md/summary/comparison; no subsequent evolution launched. The separately reported content-hash exclusion subset does not establish source-video isolation across different clips. Do not edit frozen sources.

2026-09-19 output layout: the three Qwen3.5 E2E roots now live under `outputs/e2e/`; no-Skill MVAgent roots under `outputs/mvagent/no_skill/`. Historical evolution collection plus E0–E3, stable500 and E3 expanded experiment units live under `outputs/mvagent/skill/`. Other analysis/control reports remain under `outputs/analysis/`. Exact moves: `outputs/maintenance/layout_20260919/moves.json`. Frozen execution-time paths are unchanged; consult the mapping before accessing or resuming old artifacts. Rescore the fixed CrossVid panel with `scripts/analysis/summarize_crossvid_2500.py`; results in `outputs/reports/crossvid_2500/`. Incomplete coverage has no full-panel macro score.

2026-09-19: 用户要求 35B-A3B 无 Skill 只保留 `_strict`，已删除 `_old`、`_recovery`、`_strict_preflight_20260916` 三个结果目录。删除前核查进程引用；简要 summary/manifest/config 和清单保留在 `outputs/maintenance/keep_35b_strict_20260919/`，原始轨迹和源码快照不再可用。9B、Skill 实验及 analysis 下其他诊断材料未清理。

2026-09-19: 按用户要求，当前 35B-A3B 无 Skill 目录已去掉 `_strict` 后缀，现为 `outputs/mvagent/no_skill/qwen3_5_35b_a3b_mvagent_no_skill/`。仅改名，仍是原 strict Runtime 的结果；冻结记录中的执行时路径不改。映射见 `outputs/maintenance/rename_35b_no_skill_20260919/manifest.json`。

2026-09-19: 用户明确要求删除 outputs 下 attribution_probe、maintenance、model_services、reports、services、vllm_persistent 六个目录，已核查进程引用后全部删除。历史清理备份、迁移映射和归因摘要不再保留；旧文档对这些路径的引用仅表示历史记录，不代表文件仍存在。CrossVid2500汇总报告已删除，可用 scripts/analysis/summarize_crossvid_2500.py 从保留的原始结果重新生成（会重新创建 outputs/reports/crossvid_2500）。正式 e2e、mvagent 结果、Skill实验、eval/crossvid_2500.json 及固定split未删除。当前35B无Skill结果路径为 outputs/mvagent/no_skill/qwen3_5_35b_a3b_mvagent_no_skill/，其Runtime仍为原strict版本。

2026-09-20 overnight watch expansion: user authorized 8–9 hours of unattended tests.
Entry `scripts/analysis/run_overnight_watch.py launch --output outputs/analysis/20260920_overnight_watch`
prepares immutable inputs and detaches its frozen controller. Prepared1040 questions
(951 known-source-isolated from Train130/Gate300/prior96;89 shared-source diagnostic),
one question per known media component, nine arms N0–N8,24-question paired blocks.
All selection is outcome-blind; source-key isolation is not whole-film/content isolation.
N0 no Skill; N1/N2 previous W1/W2; N3 context only; N4 conditional route/context;
N5 separate then joint/context; N6 N4 plus verification; N7 N2 plus verification;
N8 unchanged historical E3 Video Skill with empty Global. No Runtime or API calls added.
Target8.5h, no new runner after9h, finish admitted child; exceptional long tails can overrun.
No score-based scheduling/promotion, no new evolution or GT-visible policy. Main summary
uses complete nine-arm blocks only; partial last block retained separately. Automatic
report/paired bootstrap/McNemar/Holm summaries and health preserve missingness.
Read saved status/report, do not continuously poll. Resume same identity only after old
children exit; original wall-clock window persists. Never reset service locks or rerun
service replacement. Protocol: `analysis/skill_evolution/overnight_watch_20260920.md`.

2026-09-21 overnight completed:8.545h,29 full paired blocks,696 questions per arm
(607 source-isolated,89 shared-source diagnostic),6264 main+54 smoke rollouts.
No partial final block; all6264 raw records reconciled, final scoring complete/fatal0,
intermediate model/Video/invalid errors remain in health. N0 predictions and scores
match retained historical35B on all696 IDs. Isolated correct N0..N8:
369/351/363/379/372/372/378/339/376 of607. No primary comparison passes Holm.
N5 Comparison only6/68 actually used both analyze and watch; do not claim a verified
two-stage benefit. All203 prepared weak-family questions completed; remaining344
queue questions are protection families. Keep no-Skill default; no additional inference
or deployment launched in this analysis. Report:
`analysis/skill_evolution/overnight_watch_results_20260921.md`; raw reconciliation and
route checks: control-root `postrun_audit.json` / `analyze_completed.py`.

2026-09-21 paired mismatch review:18 cases (14 E2E-only,4 Agent-only), all raw
predictions reconciled;13 cases inspected via timestamped sampled frames, not full
video review or exact inference input replay. Report:
`analysis/skill_evolution/e2e_mvagent_mismatch_20260921.md`; artifacts under
`outputs/analysis/20260921_e2e_mvagent_mismatch/`. Distinguish correct evidence
misread by Global, dropped relation/quantifier constraints, leading verification,
and observation/inference/task-semantics errors; no blanket summary-loss claim.
Fixed-evidence final-decision and fixed-action instruction probes are recommendations,
not implemented or launched. No new inference, runtime or Skill changes in this review.


2026-09-21 expanded mismatch audit completed:4466 closed-task paired cases across31
families;708 E2E-only,834 Agent-only,1487 both-correct,1437 both-wrong. Added104
stratified text reviews disjoint from prior18 (122 total); no new visual verification.
Control root `outputs/analysis/20260921_expanded_mismatch/`; report
`analysis/skill_evolution/expanded_mismatch_20260921.md`. All1842 selected cases ran
three GT-blind fixed-report diagnostics on existing GPU2–7 35B services, no paid API.
R/S JSON wrappers had malformed answer artifacts; retain these failures. Plain-answer
control recovered158/708 but lost248/834 Agent-only and34/300 both-correct controls.
This removes old Global reasoning/history, so it is not exact Runtime node replay or
proof of evidence sufficiency. Preserve input/source/config hashes, all outputs and
separate missing/invalid states. All three statuses completed; no monitoring needed.
No Runtime, Skill or action policy deployed. Exact node replay/instruction-controlled
experiments and branch evolution remain proposals. This supersedes the prior review's
statement that no fixed-evidence diagnostic had yet been launched, not its historical facts.


2026-09-21 user clarified evidence priority: full E2E and no-Skill benchmarks are
primary; overnight Skill and fixed-report probes are auxiliary. Current diagnosis:
`analysis/skill_evolution/full_baseline_diagnosis_20260921.md`, artifacts under
`outputs/analysis/20260921_full_baseline/`. Reconciled29002 Agent headers across
9B/27B/35B and51 source hashes; inspected all11839 retained35B raw records with11830
valid E2E pairs (8713 binary closed,2246 FSA,871 CCQA). Full35B Cross9009 paired macro
34.598→39.810%; MOC+1.060pp and PEA−1.364pp supersede weaker Lite2500 diagnostic
inferences (−3.226/−6.513pp). Do not promote either to a blanket routing rule.
Comparison E2E-only23/24 already watch, CC4/208; distinguish tool choice from evidence
and instruction quality. 27B Cross no-Skill remains Lite2500 only, not a full9015 run.
Added8 panel-external text case reviews, no new visual verification/model/Judge calls
or deployed Skill/Runtime edits. Preserve full-vs-panel and scorer/protocol differences.


2026-09-21 systematic mechanism audit: report
`analysis/skill_evolution/systematic_bottlenecks_20260921.md`, artifacts under
`outputs/analysis/20260921_systematic_bottlenecks/`. Scanned all11839 35B and5324 27B
retained trajectories. Constraint transfer and evidence sufficiency are hypotheses,
not labeled root-cause rates. Short trajectories do not establish short contexts.
Completed local reason-cap replay: initial512 calls changed only top-level Schema,
leaving branch caps1200, so that arm is not a valid length intervention. Preserve it.
Corrected `cap_complete_contract/` changes all4 Schema reason caps and3 Prompt
annotations; same256 nodes,512 successful calls,256 baseline answers reproduced.
Expanded cap produced244 direct answers (23 recovered,14 lost) and12 new evidence
actions without continuation. No full-system gain claim, deployed Prompt/Skill edits,
paid API use or active experiment. Validation and protocol hashes retained. Full
baseline remains primary; enriched diagnostic samples are not independent Test.


2026-09-21 Git checkpoint: current accumulated implementation/configuration/reports
committed as `9a2085b`, tagged `mvagent-pre-prompt-validation-20260921`; keep the older
`mvagent-base-20260909` tag fixed. Generated outputs remain ignored and local.
Next fixed-Prompt validation draft is
`analysis/skill_evolution/fixed_prompt_results_20260921.md`: separate Global
answer consistency (D) and Video summary fidelity (S), then matched full trajectories.
Target1200 development questions is a design target, not a frozen/available split.
No new Prompt implementation, execution script, model run or default change from
that draft yet. Preserve private/public evidence boundaries and distinguish fixed
observation diagnostics from actual end-to-end validation.

2026-09-22 fixed-Prompt implementation: `scripts/analysis/run_fixed_prompt_validation.py`
freezes checkpoint9a2085b into B0/D/S source copies; D changes only Global answer
consistency, S only Video finish/terminal-summary fidelity. No default Runtime or
Skill changes. Controller runs32-question preflight per arm then paired96-question
blocks on1200 questions (400 weak/400 protection/400 other), no paid API/optimizer.
Control root: `outputs/analysis/20260922_fixed_prompt_validation/`. Strict source-isolated
subset is only506 (20 weak/86 protection/400 other);694 supplemental questions are
explicit shared-source diagnostics. Confirmation IDs excluded but Cross sources
can overlap supplement, so combined results cannot establish source-independent
generalization. Earlier `20260922_fixed_prompt/` is preparation-only, never launched.
Fixed-evidence diagnostics are deferred until fresh full trajectories; no causal claim
of identical observations. Two CPU tests cover Prompt scope/rendering and grouped
pairing/missingness. Frozen executable/input hashes verified before launch; statuses
and partial records retained, no outcome-based stopping or automatic deployment.

Fixed-Prompt controller launched from implementation commit16bd706; six35B endpoints
verified. Read `outputs/analysis/20260922_fixed_prompt_validation/status.json` for
current stage; preflight automatically precedes main paired blocks. No need for
continuous polling. Estimate appears after three preflights, report after each paired
block. Do not restart resident services or edit this running experiment snapshot.


2026-09-21 completed fixed-Prompt diagnosis (run directory retains20260922 name):
`analysis/skill_evolution/fixed_prompt_results_20260921.md`. All3600 scores independently
recomputed; B0/D/S597/583/615 correct. D changes1077 first requests; S preserves all1200
first decisions, with937 matched-observation/watch but changed-report cases (33 repairs,
21 losses). S weak net+1/400 and new1 invalid decision: not a validated default gain.
Zero top-level failures does not mean zero internal invalid/model/Video-call errors.
All1200 final-node B0/D pairs additionally replayed locally. Four terminal requests
lack agent metadata; selector corrected to schema+terminal-trajectory,8 corrective calls
retained separately. Authoritative `outputs/analysis/20260921_fixed_prompt_diagnosis/
final_node_probe/corrected_summary.json`:1200 baseline answers reproduced,1179 both
answer nodes with43 repairs/34 losses,21 unexecuted evidence actions. Total2408 calls,
all completed; no running experiment, paid API or deployed Runtime/Skill change.
Analysis entry `scripts/analysis/analyze_fixed_prompt_results.py`; probe entry
`scripts/analysis/probe_fixed_prompt_final_decisions.py`; tests cover observation order,
semantic changes and terminal selection without agent metadata. Keep initial and
corrective artifacts; never silently replace bad-node provenance.

2026-09-21 original-question watch diagnostic authorized: entry
`scripts/analysis/run_original_question_watch.py launch`, protocol
`analysis/skill_evolution/original_question_watch_20260921.md`. Select all1424 binary
35B full-baseline E2E-only errors, excluding exact-template overflow under the existing
1600-character instruction limit. B0 fresh no-Skill vs WQ authored Global Skill only,
both frozen checkpoint9a2085b; no D/S, Video Skill, Runtime change or paid API.
WQ requests full-duration watch with verbatim original question/options inside an
evidence-only wrapper. More than4 videos use sequential groups and are reported
separately. Measure actual copying/routing/coverage, never assume compliance.
Control root `outputs/analysis/20260921_original_question_watch/`;24-question preflight
per arm precedes full B0/WQ, detached and resumable only through the owning controller.
This is outcome-selected error recovery, not total benchmark gain or protection of
originally correct cases. Source, configuration, Skill and input identities are frozen.
Prepared1400 questions (1258 single-watch,142 multi-watch);24 overflow exclusions
are KIR19/Comparison5. Implementation commitfd530c5; controller launched with six
verified endpoints. All1400 original record hashes/questions/wrong scores were
rechecked in selection_validation.json. Read saved status, no continuous polling.

Original-question watch recovery: the initial controller stopped after48 healthy
preflight rollouts because zero cases matched the entire instruction template verbatim,
despite Skill loading and23/24 WQ first-watch decisions. Preserve that failed root.
`run_original_question_watch.py --reuse-preflight PATH` now checks identical frozen
source/Skill/configs/IDs/questions before reusing completed preflight in a new root.
Operational gate checks Skill loading and executed watch; exact copying remains a
reported outcome, never silently reclassified. Revision1 root:
`outputs/analysis/20260921_original_question_watch_revision1/`. Actor and Skill unchanged;
main1400x2 follows without rerunning48 preflights. Report full-input exact, task/options
non-whitespace exact, template exact and coverage separately. No Runtime prompt edits.

2026-09-22 original-question watch completed: revision1 B0/WQ1400 each,0/662 correct,
all B0 predictions reproduce history. This is47.29% recovery on selected errors, not
overall gain; no originally correct protection set was evaluated. First-watch1391,
task/options non-whitespace match1073, full-video coverage1272, full original Question
verbatim0. WQ47 invalid ranges across10 questions (9 newly invalid vs B0), fatal0.
Some watch outputs directly choose options despite the Skill's evidence-only request;
do not attribute every recovery to better evidence transfer. Results/next priority:
`analysis/skill_evolution/original_question_watch_results_20260922.md`. Both stages
completed, no further inference or deployment launched. Preserve initial failed preflight.

2026-09-22 routing/protection authorized: user explicitly cancelled all new no-Skill
and forced-watch runs. `scripts/analysis/run_routing_protection.py launch` runs RQ only:
24 preflight+2000 main,100-question blocks; B0 joins immutable historical records.
No B0/WQ inference stages. Existing WQ only supports overlapping E2E-only diagnostics.
Panel targets1200 historical-correct (600 Agent-only/600 both-correct),800 wrong
(400 E2E-only/400 both-wrong), task-by-cell SRS with frozen inclusion probabilities.
Weighted net-gain target is instruction-feasible paired binary questions, not all11839
or official Cross10; source-cluster95% interval is approximate development evidence.
RQ uses semantic evidence needs for analyze/watch preferences, no task labels/GT.
Runtime checkpoint9a2085b unchanged; Video Skill off. Conditional Global Skill and
Chinese mirror maintained. Protocol: `analysis/skill_evolution/routing_protection_20260922.md`;
control root `outputs/analysis/20260922_routing_protection/`. Shared controller now
supports stage-specific IDs/report callback; frozen old runs remain untouched.
Routing protection launched fromf89851d:2000 sampled from8620 feasible binary pairs
(93 exclusions from8713), weights reconcile to8620,400 overlap with retained WQ.
Six35B endpoints verified; protocol contains21 RQ-only stages. All2000 baseline raw
hashes/questions/correctness rechecked. No fresh B0 or WQ inference; saved status is
authoritative, inspect once rather than continuously polling.

2026-09-22 concise routing retest: previous RQ completed2000, repairs241/losses334,
weighted eligible-binary delta−0.405pp (approximate95% interval−4.467,+3.935).
User authorized a shorter category-first Global Skill and a fresh matched run.
`run_routing_protection.py --global-skill` freezes an authored Skill in a fresh root;
preflight checks the actual full frozen Skill in Global messages rather than a fixed title.
New authored Skill: `analysis/skill_evolution/skills/concise_category_global.md`.
Control root `outputs/analysis/20260922_routing_concise/`; same seeded2000 panel,
24 fresh preflight and2000 fresh RQ only, historical B0/WQ not rerun. Frozen Runtime,
35B GPU2–7, budgets and Video Skill unchanged. Shorter routing and watch instruction
are a joint revision, not a length-only causal intervention. This reused development
panel is not independent confirmation. Inspect saved status; no automatic deployment.

2026-09-22 integrated action/parameter analysis: concise run completed2000, repairs250,
losses361, weighted eligible-binary delta+0.657pp (approximate95% interval−2.793,+4.166);
neither routing version established a net gain. Latest plan:
`analysis/skill_evolution/action_parameter_strategy_20260922.md`, superseding earlier
next-step ordering while retaining full-baseline evidence priority. New read-only6000
record sampling audit: `outputs/analysis/20260922_action_parameter_synthesis/`.
Endpoint-state ordering, coarse-to-fine localization, conflict-triggered verification,
and bounded node branches remain proposals, not deployed Skill or Runtime changes.
No inference/API calls launched; no-Skill/forced-watch rerun cancellations persist.

2026-09-22 action/parameter screening authorized: new entry
`scripts/analysis/run_action_parameter_validation.py prepare|launch|run|summarize`.
Control root `outputs/analysis/20260922_action_parameter_validation/`; five arms
C/OG/OV/T/V, exactly one Global or Video Skill per arm, frozen Runtime9a2085b.
1200 unique development questions, each arm200 mechanism+shared400 protection,
3000 main+120 preflight rollouts. OG/OV share PSS target; T includes continuous FSA
IoU; protection300 historically-correct binary+100 FSA IoU>=0.5. Source-diverse
stratified selection is non-probability development sampling, not independent Test.
V conflict terms are only a proxy, not labeled contradiction truth. Historical B0
reused; no no-Skill/forced-watch reruns, optimizer or API Judge. Preflight checks
exact role Skill plus actual endpoint/multi-observe/extra-evidence proxies for OV/T/V.
Shared watch controller accepts a preflight callback, rechecks it on resume and
estimates total time from each arm's actual stage sizes. Frozen old runs untouched.
Protocol: `analysis/skill_evolution/action_parameter_results_20260922.md`.
Authored Skill contents and Chinese mirror updated; no default Runtime deployment.
Action/parameter controller launched fromf9e2bbf (PID3343444); all six endpoints
verified, initial stagepreflight_C. Prepared1200 unique IDs and exactly3000 main
rollouts; prelaunch checks verify all frozen hashes, one role per arm, shared400
protection and identical OG/OV IDs. Binary scores use native correct booleans;
FSA uses continuous score, never the thresholded correct field. Read saved status.

2026-09-22 five-arm action/parameter screening completed:3000 main+120 preflight,
~3.50h. All main predictions scored. C/OG/OV/V target binary deltas−4/−1/−7.5/−3.5pp;
T target FSA IoU44.063→27.871. Shared300 correct binary losses63/65/50/38/64;
all FSA protection means declined. No promotion or new inference. Re-read3000 new
and1200 historical records, score reconciliation and question/GT identity checked.
OV/T first Global messages/Schema/full decisions match history on600/600 each;
OV endpoint behavior121/200 target questions, T multiple successful observe25/200,
V multiple Global evidence54→47. Do not equate Skill names with complete execution.
Report: `analysis/skill_evolution/action_parameter_results_20260922.md`; audit root
`outputs/analysis/20260922_action_parameter_results/`. FSA653 demonstrates local/source
time confusion; sampled traces do not establish population root-cause rates. Preserve
historical-control/selected-protection limitations and no-Skill rerun cancellation.

2026-09-22 evidence-contract follow-up authorized: entry
`scripts/analysis/run_evidence_contract_validation.py prepare|launch|run|summarize`,
root `outputs/analysis/20260922_evidence_contract_validation/`. Reuses identical
OV/T/V Skills and each prior600-question panel (1000 unique,1800 main+72 preflight).
Only experimental source copies change: OV cropped Observer scope, T cropped
Observer source-time/boundary prompt, V Skill injection after usable evidence.
Default Runtime remains unchanged. Shared controller selects immutable per-arm
`source_roots`; old protocols still use their frozen source. All preflight initial
Global messages/Schema must match historical no-Skill; prior behavioral gates remain.
Direct controls are retained corresponding OV/T/V, plus historical no-Skill safety;
no no-Skill/forced-watch reruns or paid API. This is Runtime/Prompt development
screening, not pure Skill improvement or independent confirmation. Protocol and
Chinese mirror updated. Preserve frozen sources and inspect saved status.
Evidence-contract controller launched PID3291973; initial stage preflight_OV and
six healthy matching endpoints verified. Engineering preflights/main results are
pending; use status.json, not this launch note, as current progress authority.

2026-09-22 critical visual-Skill literature review: latest research priorities in
`analysis/skill_evolution/critical_visual_skill_review_20260922.md` supersede the
survey's default ordering. Do not bundle skill banks, macro-tools, extra planners
and topology search. Visual reflection and node branching are conditional future
experiments; empty-Skill narrow optimization need not wait for a positive manual
seed. No Runtime/Prompt/Skill or active queue changes. Read-only6000 raw routing
records reconciled: long/short repair union358, historical-correct loss union512;
GT-selected oracle is not deployable or population performance. Artifacts:
`outputs/analysis/20260922_skill_literature_critical/`. Existing no-Skill/forced-watch
rerun cancellations persist; no new model/Judge/optimizer calls in this review.

2026-09-22 evidence-contract follow-up completed:1800 main+72 preflight in2.082h.
Raw1800 scores/questions/GT reconciled,1000 historical hashes checked; all three
arms' first Global messages/Schema match history600/600. OV/T/V target scores:
43.50% /27.135 FSA IoU×100 /47.50%; vs prior sameSkill−1pp/−0.736pp/+1pp.
V correct-binary protection improves236→272/300, but historical baseline300;
OV/T retain240/261. All FSA protection means remain below historical71.215.
No promotion: phase gating reduces some side effects, not proven net benefit.
Health fatal0 all; OV model_errors9, T failed_video_requests1. Report:
`analysis/skill_evolution/evidence_contract_results_20260922.md`; audit root
`outputs/analysis/20260922_evidence_contract_results/`. No active follow-up run
or new inference/optimizer/Judge launched by this result review.

2026-09-22 Skill-format review: `analysis/skill_evolution/skill_format_and_routing_20260922.md`
compares official Agent Skills specifications/examples with Dynamo/XSkill and the
actual plain-Markdown loader. Four-section formatting is not a Runtime requirement
or executable trigger. Existing Skills already contain conditional procedures;
format-only, applicability-boundary and example ablations remain proposals. No
Runtime, authored Skill, Chinese prompt mirror or experiment queue changed; no new
model/optimizer/Judge calls. Preserve the no-Skill/forced-watch rerun cancellations.

2026-09-22 dynamic Skill foundation authorized: pre-change checkpoint029bcb8,
tag `mvagent-pre-dynamic-skills-20260922`. Static mode remains for existing evolution;
new mode dynamic selects frozen four-section cards by role and usable evidence.
Video evidence includes retained prior requests, not only the current request.
Four authored cards and Chinese mirror added.32-question real smoke entry:
`scripts/analysis/run_dynamic_skill_smoke.py launch|summarize` (also prepare), root
`outputs/analysis/20260922_dynamic_skill_smoke/`; historical B0 reused, no optimizer,
API Judge or forced-watch run. This is engineering/development evidence, not a new
default or an independent accuracy claim. Inspect saved status; no service resets.

Dynamic smoke completed from8b33d1b:32/32 scored,6 healthy workers,3.23min, no inference
errors;252 decision injections and100 visual-request exclusions audited. Global
initial/evidence selections32/37, Video91/92. Binary baseline17/28 vs dynamic13/28
(1 repair,5 losses); FSA4 meanIoU23.873→3.873 (×100). No promotion/default change.
CPU unittest216 passed; not a claim about pytest-style functions. Report:
`analysis/skill_evolution/dynamic_skill_foundation_20260922.md`. This is a selected
development smoke with31 known groups and no same-content static ablation. No active
test remains. Preparation failure and the corrected partial-score report are retained.

2026-09-23 dynamic Skill literature review:
`analysis/skill_evolution/dynamic_skill_evolution_survey_20260923.md` distinguishes
runtime retrieval from library updates, frozen Actors from trained routers/curators,
and text strategies from executable skills. Skill-Evo4GUI, Memento-Skills, AutoSkill,
SkillAdaptor, EvoSkill and XSkill are direct references; SkillBoost offers a separate
regression-bounded acceptance principle. WikiSkill's evaluated Actor receives all
active skills, not selective loading. Current role/stage selection loads all matching
cards, not a semantic top-k. Single-card edits, protection gates and selector ablations
remain proposals. Paper snapshots: outputs/analysis/20260923_dynamic_skill_literature/.
No Runtime/Prompt/authored Skill changes or inference/optimizer/Judge calls; prior
no-Skill and forced-watch rerun cancellations persist.

2026-09-23 state-aware Skill selection implemented after checkpoint9ee3a95, tagged
`mvagent-pre-skill-selector-20260923`. Current author format adds description; JSON
bank version2 rejects version1 (historical frozen sources/banks unchanged). Runtime
uses role-visible task/history for BM25 recall and a separate LLM applicability check,
then injects selected bodies before the ordinary action decision. No online edits or
automatic bank evolution. CLI adds read-only search; six v002 cards and Chinese mirror
maintained. Smoke entry now targets outputs/analysis/20260923_skill_selection_smoke_revision1/,
reusing32 development questions and historical controls, no no-Skill/forced-watch
reruns, optimizer or Judge. Initial CPU suite218 passed; saved run status is authoritative.
Implementation/report: analysis/skill_evolution/skill_selection_20260923.md.

Initial selector smoke from5dfe6bb completed32, but a new reason regex forced one
character under xgrammar; retain it as diagnostic evidence, not selection-quality
validation. Corrected selector reuses shared text_schema and adds an actual grammar
regression test. Fresh32 revision1 uses its own source/bank/config under the new
default output root; no frozen initial artifacts were edited.


Corrected selector smoke from c80782a completed32/32 with6 healthy35B workers,
zero model errors/invalid outputs/structured repairs. Post-run audit verified235
selector catalogs, parsed outputs and subsequent decision injections;98 visual
requests excluded Skills.204 empty,30 single-card and1 two-card selections; boundary
refinement was never selected in this small real panel. Binary17/28 historical vs
15/28 current (0 repairs,2 losses); FSA4 meanIoU23.873→23.341 (×100). No accuracy
promotion, new default, evolution, or active experiment. Full CPU unittest219 passed
including actual grammar compilation; pytest-style functions are not covered by
that count. Small-bank LLM screening is validated mechanically; large-bank BM25
recall quality remains unmeasured. Results and limits: skill_selection_20260923.md.


2026-09-23 state-aware selector revision: checkpoint4321c35, tag
mvagent-pre-state-aware-selector-20260923. Small eligible catalogs now bypass BM25
and appear in stable ID order (full-catalog-v1, null retrieval scores); larger banks
retain BM25. Candidate metadata adds a320-character Strategy preview and truncation
flag. Selector output requires assessment(current_subtask/evidence_status/evidence_gap)
before selected_ids/reason. Assessment is provisional telemetry, never Runtime-owned
evidence or an action instruction; valid empty selection is never replaced by fallback.
Bank schema2, immutable cards and normal action contracts are unchanged. No embedding
service or online evolution added. Prompt mirror and contract docs updated. Source
ideas come from AutoSkill selection and Skill-Evo4GUI state/precondition matching;
no upstream code/Prompt copied. Smoke default is now
outputs/analysis/20260923_state_aware_skill_smoke/; current auditor expects the new
contract. Use frozen sources to inspect older runs. Existing cancellations of no-Skill
and forced-watch reruns remain in force.

State-aware smoke90c122d completed32/32,6 healthy35B workers, errors/invalid/repairs0.
Audited219 selectors/assessments/body injections and94 visual exclusions;105 empty,
114 single selections. Binary historical17/28, previous selector15/28, new13/28;
FSA4 meanIoU23.873/23.341/9.091 (x100). This validates mechanics, not accuracy gains;
all six cards used does not establish applicability. No default promotion or active
run remains. Full unittest222 passed and compileall passed (not pytest coverage).
Report: analysis/skill_evolution/state_aware_selection_20260923.md.


2026-09-23 optional Skill selector model configuration: pre-change05a30a5 tagged
mvagent-pre-selector-model-config-20260923. Dynamic skill.selector accepts model_type
(required registered model), optional temperature/max_tokens; omission reuses the
owning Global model/Video planner. Explicit refs inherit model-instance defaults for
omitted overrides. Enabled refs enter model_roles as skill.selector for capability
validation, resource resolution, batch pool admission and snapshots. Disabled Skills
never resolve the selector; static mode rejects selector. RuntimeResources remains
model-only, caches by full reference and closes clients once. Selector calls use the
existing BaseAgent structured contract with a per-call model override; no mutation
of Actor clients, change to action/Observer models, new Prompt or error fallback.
No embedding service or new inference experiment was launched for this config change.

Selector-model configuration validation: full unittest224 passed; compileall and
git diff --check passed. Dedicated routing/override/lifecycle checks used CPU doubles,
not a new different-model accuracy experiment; pytest-style functions are not included.


2026-09-23 handwritten v003 validation authorized: seven short four-section cards
under src/mvagent/skills/authored/dynamic-v003/ target visual discriminants, process
order, consistent count units, spatial anchors, event location/boundaries and counts.
Explicit exclusions address prior OCR→temporal-refinement misselection. No Runtime
or selector Prompt changes; Chinese authored-content mirror updated. Runner
scripts/analysis/run_dynamic_skill_smoke.py now defaults to this bank and64 questions
(8 per family), retaining prior32 and adding32 in fixed hash order from the existing
development panel, preferring unused known groups then filling. Flags --skills-dir
and --per-family configure preparation; at least4/family retains the seed panel.
Output outputs/analysis/20260923_handwritten_v003/; historical no-Skill reused, no
forced-watch baseline, optimizer or API Judge. Both selectors explicitly use the
same35B Actor registry entry; existing GPU2–7 pool verifies identity, no resets.
Summarize also exports selection_traces.json with actual visible state, candidate IDs,
assessment, selected Skill hashes, subsequent action/parameters and full trajectories.
This outcome-enriched, reused panel is development evidence, not independent Test.

Handwritten v003 run0747019 completed64/64 with no model errors/invalid outputs/repairs.
480 selector outputs/context injections and196 visual exclusions audited;239 empty,
234 single and7 double selections. Binary baseline32/56→31/56 (7 repairs,8 losses);
FSA8 meanIoU38.56→18.93 (x100). Old32 binary prior v00213/28→v00316/28, historical17/28;
extra32 binary15/28→15/28, FSA53.26→17.67. No default promotion or active experiment.
Global visual card selected61 times but watch followed only28; none of those28 copied
the entire original question verbatim (not a semantic omission rate). FSA initial
watch1/8→7/8 bypassed Video refinement on those7; sole boundary-card selection was
still an OCR mismatch. Detailed real contexts/actions and scored examples:
analysis/skill_evolution/handwritten_v003_20260923.md. Text audits are not new visual
verification. Retain all raw records, frozen bank and selection_traces.json.

2026-09-23 27B model diagnostic authorized: control root
outputs/analysis/20260923_handwritten_v003_27b/. Same64 development IDs and unchanged
v003 bank (8f476577...), all Actor/Observer/Selector roles switch35B-A3B→27B; no
Prompt/interface edits, no new no-Skill/forced-watch arm or API Judge. GPU2–7 service
replacement is separately audited and must never be repeated on experiment resume;
GPU0/1 excluded. Controller verifies six healthy27B endpoints, runs64 full trajectories,
then428 exact saved35B text requests (214 nodes, selector and Actor separately).
First node per question in Global initial/later and Video initial/later strata,
outcome-blind within the already enriched development panel. Actor replay retains
original35B selected Skill, independent of new27B selector output; no tools execute.
Entry scripts/analysis/replay_skill_model_nodes.py prepare|run freezes/hash-checks
inputs and persists per-call results/status. Read saved status.json/replay_status.json;
results are model diagnostics, not benchmark-wide gains or isolated selector causality.

2026-09-23 optional semantic Skill recall: dynamic `skill.embedding` accepts local
`endpoint`, `model`, optional `timeout_sec` (60). Absent means existing BM25. Eligible
role/stage catalogs <=K still bypass all retrieval; larger catalogs use normalized
embedding cosine topK then the unchanged LLM selector/abstention. Shared adapter:
`src/models/embeddings.py` (separate `/v1/embeddings`, not a generative model instance).
Documents cache by full card content + endpoint/model per process; model revision
requires a distinct alias. Query prefix is mirrored in current/prompt_chinese_reference.md;
Actor/Selector/Observer prompts and action schemas unchanged. Errors propagate, no
silent BM25 fallback; response identity/order/finite vectors/dimensions validated.
Tests: test_skill_embeddings plus existing test_dynamic_skills.

Cohost profile `configs/inference/local_qwen35_27b_skill_embedding.yaml` keeps27B
weights/context/frame limits, reserves80% GPU memory, enables frozen v003 bank and
embedding endpoint8110. It uses existing gpu2_7_qwen35_27b_single execution pool.
Native vLLM service config `configs/inference/execution/qwen3_embedding_8b_tp4.yaml`
uses Qwen3-Embedding-8B, pooling LAST, BF16, TP4 on GPU4–7,10% GPU budget,8192 input
limit and eager execution. GPU0/1 excluded. This is a separate profile, never edit
or resume the ongoing90%27B comparison with it. Control root
outputs/analysis/20260923_embedding_service/ waits for the full64+428 comparison,
then checks input hashes, idle queues/process identities, replaces only its six27B
services, starts embedding, and runs four real engineering samples with K2 to exercise
retrieval. Default K8 with seven cards still bypasses embedding. Inspect status.json
and integration_audit.json; queued work is not proof of completed deployment or gain.
The replacement is one-off and guarded; do not rerun after replacement_started.json.

2026-09-23 completion and next-plan update: the27B64-question comparison and428
fixed-text calls completed. Binary35B/27B31/56 versus37/56 (10 repairs,4 losses);
FSA8 meanIoU0.1893/0.1853. End-to-end event spans351.626/1429.333 seconds,
about4.06x; not a controlled decoding-speed benchmark or general quality proof.
Embedding cohost subsequently completed: six27B80% services plus Embedding-8B TP4
on GPU4–7; four K2 engineering samples yielded31 embedding calls,23 semantic
retrievals and15 full-catalog decisions, all completed. Default K8 still bypasses
retrieval for the seven-card bank. No need to resume completed controllers.
Latest proposal: analysis/skill_evolution/dynamic_bank_evolution_plan_20260923.md.
Keep27B for an initial bounded offline pilot; adapt the old static SkillSet/rollout
to immutable dynamic banks before evolution. Single-card proposals, whole-bank
paired evaluation, protected task strata and complete cache identity are plans,
not implemented mechanisms. No new inference, split, optimizer call or model
switch occurred in this research work. Historical next_steps/survey descriptions
of absent dynamic selection are superseded; full baselines remain primary evidence.

2026-09-23 reference acquisition: official MIT repositories SkillAdaptor and SkillBoost
were shallow-cloned under references/skills_self_evolve/ at b26d1ab5a798f07e53048b5ff509e8535e9fa228
and2435016962b91184ef55a490e5ee259f1c3e70d3. Reference trees remain ignored, unmodified
and unimported; no dependency installation or upstream experiment was run. Tracked
provenance and source walkthrough: analysis/skill_evolution/skilladaptor_skillboost_walkthrough_20260923.md.
It records scoped/cached SkillAdaptor validation and post-hoc step annotations,
plus SkillBoost's configurable gates; do not mistake paper/policy descriptions for
the exact code paths or defaults when adapting either framework.

2026-09-23 lifecycle research: user requests automatic gap filling, merging and
retirement. Latest design: analysis/skill_evolution/skill_lifecycle_research_20260923.md.
Official shallow reference clones added under references/skills_self_evolve/:
AutoSkill94c47ca, ReMe554eec1 (official v0.2.0.6 procedural-memory code, not main),
SkillClaw3938f75, Memento-Skillsee9b9a4, Skill-Evo4GUId13b1b5. Full commits and
license distinctions are in the tracked report; file hashes under
outputs/analysis/20260923_skill_lifecycle/source_manifest.json. Reference code stays
unmodified, ignored and unimported; Skill-Evo4GUI is released prompts/schemas,
not a complete execution framework. No dependencies installed or inference run.
The proposed lifecycle is add/refine/merge/retire/keep, one operation per candidate,
with an atomic two-card same-role merge exception to the earlier single-card plan.
Strict positive-gain capability updates and separately validated non-regressing
merge/retire maintenance are proposed distinct gates; neither is deployed. Do not
delete live cards from age, low usage or co-occurring failure statistics alone.
Current Actor remains27B, and old static evolution rollout still needs adaptation.

2026-09-23 lifecycle implementation supersedes the earlier proposal-only status.
Pre-change tag: mvagent-pre-bank-evolution-20260923 at acd2981. Current runner and
controlled tests implement empty-bank bootstrap, add/refine/merge/retire/keep, paired
whole-bank screening/Gate, independently reserved maintenance confirmation, immutable
snapshots and atomic resume. See src/skill_evolution/README.md and test_bank_lifecycle.py.
No live Skill deployment, GPU service change, real optimizer call or benchmark launch
was made for this implementation; controlled fixture gains are not measured model gains.

2026-09-23 GEPA pilot: `algorithm: gepa-pilot-v1` selects the actual upstream
GEPA engine through algorithms/gepa/{adapter,trainer}.py. Recipe gepa_pilot_27b.yaml
uses2 proposals, minibatch8 and one candidate per mutation. Fixed MIT upstream
ba30ee24e8f63dfdb9e557ed8cfaaec7aa09a6df is a direct Git dependency in requirements.txt.
No reference source was edited or imported through a hidden path fallback; controlled
checks explicitly used its src on PYTHONPATH without installing in resident environments.
Search components are global_bank/video_bank JSON lists; all rollouts use the full bank.
Partition-fixed weights make full-validation GEPA mean equal official hierarchical macro;
minibatch sums use those same fixed weights. GEPA owns search and checkpoint/resume.
Validation capture_traces is allowed for upstream execution, but Train-only reflection
checks prevent its use by optimizer. Final release compares search best versus seed,
requires strict macro improvement, all task protection and no new per-question fatal/invalid.
Search may retain unreleased candidates; output search_bank.json is distinct from final_bank.json.
This pilot has no equal-score maintenance acceptance; GEPA merge=False disables parent
candidate merging, not Skill Builder merge. Existing lifecycle stays a comparison path.
Shared role proposals, routing audit and release checks moved to infra/proposals.py;
unchanged proposer text moved to infra/prompts/bank_proposer.md, no duplicated search loop.
CPU integration uses the actual GEPA engine with fixture Actor/optimizer. No GPU/API
call or live Skill deployment; controlled scores are not benchmark gains. Evidence:
outputs/analysis/20260923_gepa_adapter_smoke/verified_final/verification.json. See algorithms/gepa/README.md.

2026-09-23 real CrossVid GEPA pilot authorized. Preparation entry:
scripts/prepare_crossvid_gepa_pilot.py; detached launcher:
scripts/analysis/run_crossvid_gepa_pilot.py launch|status (controller is internal).
Control root outputs/analysis/20260923_crossvid_gepa_real/. Outcome-blind selection
excludes all Lite2500 IDs and protected source keys, then checks selected video byte
hashes against size-matched protected-panel media. Frozen Train80/Eval40:8/4 per each
of10 tasks, distinct known media components. This is development data, not unseen Test
or whole-film isolation. GEPA starts empty,27B Actors,4 proposals, batch16; CCQA uses
configured official Judge. Four closed Eval questions run first as engineering smoke.
The controller then waits up to24h for the user-filled ignored600-permission file
.local/skill_evolution_keys.env (BIGMODEL_API_KEY and DEEPSEEK_API_KEY). Keys are read
as data, never shell-executed or included in artifacts. Frozen recipe/runtime/execution,
source and GEPA dependency snapshots support unattended sequential execution. Inspect
status.json and logs; never relaunch an existing control root or change frozen inputs.
No resident service replacement is authorized by this launcher; normal pool verification
remains mandatory. .local/ is ignored for local credentials only.

2026-09-23 GEPA real pilot retry: initial run completed 104 empty-bank questions
(Eval40/Train64), but all four optimizer rounds failed HTTP401; its completed
status does not establish a successful search. Adapter now latches optimizer exceptions,
prevents duplicate upstream reflection retries, and checks the failure before further
evaluation, at search stopping and before release. Controller reports failed on abort.
No upstream/Runtime/Prompt changes. Launcher --cache-dir supports exact-identity reuse.
Retry root outputs/analysis/20260923_crossvid_gepa_real_retry1/ preserves the original
Train80/Eval40 split, 27B and four rounds; original failed records remain unchanged.

2026-09-23 researched proposal adapter pilot: shared RoleProposer now validates
JSON Schema and build_candidate before returning. ID pattern, operation cardinalities
and required coverage are exposed in Schema; one bounded semantic correction receives
the original Train input, draft and validation errors. Attempts persist separately;
transport errors propagate, exhausted invalid proposals raise instead of becoming keep.
Existing per-call JSON repair remains, so at most four generations, not two HTTP calls.
No model/Runtime/scorer changes or new dependencies. Mechanism references: AutoSkill
extraction repair and PydanticAI output validators; no upstream code copied.
Report analysis/skill_evolution/proposal_adapter_research_20260923.md. Real pilot root
outputs/analysis/20260923_crossvid_gepa_real_adapter_pilot/; unchanged split/27B/four
rounds with exact-key cache reuse. Prior retry1 ended with four invalid proposals,
not a negative skill-effect result.

2026-09-23 user-directed GEPA Actor switch to35B-A3B: the adapter_pilot27B
controller was stopped with provenance before its first candidate rollout. User
authorized replacing six GPU2–7 endpoints; retain GPU0/1 and embedding8110. New
registry dynamic_35b_embedding.yaml keeps0.8 GPU fraction to cohost embedding;
gepa_pilot_35b.yaml selects it. run_crossvid_gepa_pilot.py now accepts --config
and --execution-config and defaults to35B/gpu2_7_single; frozen old launchers remain
unchanged. Deployment control outputs/analysis/20260923_gepa_switch_35b/ verifies
idle/exact ownership before one-off replacement, six services and embedding afterward,
then launches outputs/analysis/20260923_crossvid_gepa_35b/. Check both saved statuses;
never rerun replacement_started. Train80/Eval40/four rounds/batch16 unchanged;
new model uses a new cache and new baseline, never relabel27B trajectories as35B.

2026-09-23 35B startup correction: all six80% services exited after loading because
262144 context needs5.08GiB KV but profiling left2.34GiB. Disk weights are intact;
embedding8110 remains resident. dynamic_35b_embedding now reserves85% (27B stays80%).
Recovery root outputs/analysis/20260923_gepa_35b_memory_recovery/ starts GPU4 first,
checks inference/embedding, then starts remaining five. It uses isolated compiler
cache paths per service without removing old caches. No context/frame/Prompt change.
This supersedes the previous80%35B deployment instructions; preserve failed logs.

2026-09-23 user overrides85% recovery: main35B must reserve90%; adjust embedding
to the remainder. Control outputs/analysis/20260923_gepa_90pct/ stopped the85%
controller and exactly its six Actor services plus the owned embedding service after
idle/ownership checks. New dynamic_35b_embedding uses0.9; native embeddingTP4 profile
uses0.05 perGPU4–7, same BF16/model/8192 limit/pooling. Old embedding profiling measured
3.53GiB weights and5.5GiB KV at10%, so5% is expected to support8192 with lower cache
capacity; verify actual free memory and a real embedding request after Actors start.
GPU0/1 excluded. GPU4 Actor is checked first, remaining five follow; embedding starts
last, then six-worker verification and GEPA launch. Do not restart older controllers.

2026-09-23 completed35B GEPA pilot:4 valid proposals,2 Train-screen survivors,
Eval40 seed47.9633%/best49.0028%; BU/FSA regressions vetoed release. Best search
bank is one Video card; final bank remains empty. User requested generalization.
New entry scripts/analysis/run_gepa_generalization.py evaluates only that frozen
search bank on600 outcome-blind selected questions (200 each CrossVid/CVBench/MVU),
excluding known media components of priorTrain80/Eval40 and checking byte aliases.
Historical35B no-Skill predictions are reused, never rerun; exact question/video
inputs are checked. Runtime sources differ, so historical paired comparisons are
diagnostic, not strict causal ablation. These reused research benchmarks are held
out from this search, not pristine unseen Test. No optimizer or automatic promotion.
Protocol analysis/skill_evolution/gepa_generalization_20260923.md; control
outputs/analysis/20260923_gepa_generalization/ with audit/status/comparison/report.

Generalization preparation correction: initial root failed before inference because
unselected cross-benchmark bridge questions overconnected components. Revision1 at
outputs/analysis/20260923_gepa_generalization_revision1/ retains full-CrossVid component
exclusion, removes direct shared path/filename questions first across benchmarks, then
constructs remaining components and checks byte aliases. No outcome-based resampling.

2026-09-23 expanded GEPA: user authorized larger Train/Eval and search from empty.
Preparation scripts/prepare_crossvid_gepa_expanded.py preserves pilot partition
assignments, excludes Lite2500 and prior diagnostic CrossVid sources, and groups
byte aliases before assigning remaining sources. Target caps40/20 per task; scarce
tasks stay smaller, repeated questions may share a source within one partition.
Actual counts/groups: outputs/analysis/20260923_crossvid_gepa_expanded/data/audit.json.
Recipe configs/skill_evolution/gepa_expanded_35b.yaml uses16 proposals/batch32;
35B90%+Embedding5% deployment and release gates unchanged. Pilot launcher now honors
recipe training settings and derives counts from split instead of hardcoded4/16,80/40.
Control/source/status under that expanded root; protocol
analysis/skill_evolution/gepa_expanded_20260923.md. No automatic Skill-count reward.
Prior600 diagnostic completed: CrossVid five tasks40 each, macro+0.9374pp;
CVBench-4.5pp, MVU-2.5pp. It did not establish stable transfer.

2026-09-24 GEPA padded-batch repair: upstream epoch sampling pads383 to384 and
can repeat an ID within a32-question batch. Adapter now executes/scorers distinct
IDs once, returns outputs/scores/trajectories in original order with multiplicity.
Empty/mixed/unknown batches still fail. Nine focused GEPA tests pass, including
real upstream padded sampling and cache/position checks. Expanded run stopped
before proposal12 after11 proposals; checkpoint recovery uses a separately hashed
evaluate-only overlay in outputs/analysis/20260923_crossvid_gepa_expanded/
recovery_20260924/, retaining original frozen source and identity checks plus
explicit repair provenance. This is repaired-code continuation, not identical-code
resume. Original checkpoint/status/manifests are backed up there; no models,
Skill prompts, datasets, scoring, sampler or16-proposal budget changed.

2026-09-24 completed expanded GEPA and routing audit: all16 proposals completed,
Train383/Eval181; best37.5997%→41.0626%, but MOC/MSR regressions veto release.
Search bank has2 cards, final bank empty. Recovery spawn-entry guard was fixed;
failed launcher/log are retained under recovery_20260924.
Read-only scripts/analysis/audit_gepa_expanded.py audits9 full-validation banks
(1629 rollouts on181 shared questions),16 proposal inputs and actual body injection.
Outputs: outputs/analysis/20260924_gepa_routing_audit/. Report and proposed
targeted-edit/selection-duration experiments:
analysis/skill_evolution/gepa_targeted_updates_20260924.md. Global conflict card
selected at165/181 initial decisions without evidence; Video first-selected197
requests include189 with only one observe. Optimizer input actually covers
Global6–11/Video3–6 questions per proposal after100000-char evidence selection.
Per-QA/per-request persistent selection and targeted editing remain proposals;
this audit changes no Runtime, prompt, Skill, service or experiment configuration.

2026-09-24 Skill duration experiment authorized and implemented: dynamic
skill.selection_scope=decision (default) or task. Global task lasts one QA;
Video task lasts one request_id. First successful selection, including empty,
is held as ordered bodies; invalid selection is not cached. New Video requests
select again. Stage eligibility applies at activation only in task mode.
Reuse emits skill_reuse, never a fictitious selector call; Observer/finalizer
and Memory/History evidence boundaries unchanged. Scope enters config/cache
identity. Proposer routing audit understands actual reused injection.
256 unittest checks pass; pytest-style functions are not included.
Frozen two-card Eval181 four-arm DD/DF/FD/FF entry:
scripts/analysis/run_skill_duration.py launch; control
outputs/analysis/20260924_skill_duration/. Each arm has8 engineering smoke
questions followed by181; smoke caches reused where identical. Full DD is
rerun with Skills under the same new source (no no-Skill rerun),724 main
rollouts overall. No optimizer, service replacement or card/prompt edits.
Protocol analysis/skill_evolution/skill_duration_experiment_20260924.md.
Inspect status and true request progress; controller is detached and locked.

2026-09-24 duration experiment completed:724 paired rollouts; DD/DF/FD/FF macro
41.226/42.086/41.520/41.943%, all scope/body injection audits passed, fatal/invalid0.
DD/FD each recorded17 intermediate model errors; DF/FF0. No bank was promoted.
User then explicitly chose Global once-per-QA selection and Video once-per-request
selection, each holding one card across normal decisions. Current35B registry
configs/skill_evolution/runtime/dynamic_35b_embedding.yaml now explicitly uses
selection_scope=task for both roles; selection is now always limited to one or none. Zero selection remains legal
for empty/inapplicable banks and persists too; new Video requests can change cards
using retained Memory. Generic scope defaults and frozen experiments stay unchanged.
Current selector uses one concise SELECTOR_SYSTEM across roles/scopes. Candidate
catalogs contain only id/description/when_to_use; full bodies load after selection.
Global input: question/options, video IDs/durations and public history. Video input:
local instruction and own history. Role/stage filtering is internal and remains in
telemetry; no role, stage, action definitions or Strategy in selector input. Output
contract now has only reason (nonblank, <=400 chars) then selected_ids (candidate enum, maxItems1, empty allowed); assessment is removed. Managed vLLM uses schema-compiled grammar plus full response validation. Retrieval, task persistence and Observer/finalizer boundaries are unchanged.
This replaces the historical full-Strategy task selector; old results use frozen sources.
257 unittest checks pass, including16 dynamic Skill checks; pytest-style functions
are not counted. No new inference/evolution run was launched for this change.
Targeted evidence sampling and proposer updates remain plans documented in
analysis/skill_evolution/task_scoped_evolution_20260924.md; GEPA search and release
rules are unchanged. New Runtime/config identity cannot resume old checkpoints.


2026-09-24 selector applicability audit completed: all dynamic profiles now enforce
one card or none; max_selected configuration is removed/rejected. Schema maxItems1
and bank rendering both reject multiple IDs. Both selector Prompts require actual
prerequisites/exclusions; task mode distinguishes requested outputs from incidental
context. Output order is assessment, reason, selected_ids so applicability precedes
commitment in the existing vLLM grammar; no new model call or Skill-body edits.
Global QA/Video request persistence remains. CPU257 unittest checks and compileall
pass; pytest-style functions are not included.
Entry scripts/analysis/audit_skill_selector.py freezes221 pre-labeled contexts
(149 real,72 controlled); dev89/confirm132,16 ambiguous excluded from primary metrics.
Labels are assistant-authored applicability judgments, not independent human gold.
Source/config/banks and raw calls: outputs/analysis/20260924_selector_quality/.
Final revision2 confirm agreement108/121 vs baseline67/121; Global47/59,Video61/62,
positive46/48, correct abstention62/73. Repeated132 selections identical twice.
K2 stress recall Embedding48/48 vs BM2535/48; actual embedding used72 contexts,
79 successful embedding requests. Current default K8 small bank bypasses embedding.
Residual Global boundary errors remain; do not claim end-to-end accuracy gains,
universal routing reliability or independent generalization. No evolution/QA rerun,
optimizer/Judge call or service replacement. Report and next checks:
analysis/skill_evolution/selector_quality_20260924.md.


2026-09-24 reference selector comparison: offline-only entry
scripts/analysis/compare_selector_methods.py launch --output PATH --cases JSON.
It freezes audit_skill_selector.py, selector_methods.py, source/config/banks/panel,
and runs8 predeclared methods (current, full body, AutoSkill/GUI/ReMe adaptations,
SkillFlow-inspired two-pass applicability, temperature0.3 and1024-token variants).
Current Runtime Prompt/cards/selection lifetime are unchanged. Actual upstream
prompts/defaults and deviations are documented, not claimed as faithful reproductions.
Old221 contexts are all development now; new91 contexts exclude their QA IDs,
with18 premarked ambiguous,73 primary cases. No source-video isolation or independent
human gold claim. All calls use resident35B GPU2–7; no service replacement, optimizer,
Judge or complete QA inference. Detached suite selects two deterministic finalists
using development only, then confirms them and current on91 and repeats the first.
Control outputs/analysis/20260924_selector_methods/run/suite_status.json; no automatic
runtime promotion. Current audit artifact layout is partition_mode_repeat/method/;
historical controllers keep their frozen layout. SkillFlow reference checkout:
references/skills_self_evolve/SkillFlow/, commit4d56783ef5da6ae30ed9861af3bcc78330a5e36c.
Protocol/source parameters: analysis/skill_evolution/selector_methods_20260924.md.


Reference selector suite completed:2353 context evaluations,2618 local model
requests, zero error/invalid events. Development primary counts current183,
full_body181,AutoSkill181,GUI165,ReMe170,two_pass186 of205. No alternative met
all predeclared role/positive-hit protections. Diagnostic confirmation on73
unambiguous new contexts: current58,full_body56,two_pass53; positive hits33/36,
31/36,20/36 respectively. Two-pass repeated91/91 identical; temperature0.3
changed10/221 selections across two runs;1024/2048 full-body budgets matched221/221.
Fresh panel has no exact input overlap with old221; source-video isolation remains
unproven. Four old synthetic ordering cases have task/video-count contradictions;
post-run sensitivity is separate, frozen labels/finalist decisions unchanged.
Keep Runtime/Skill bodies unchanged; no promotion/evolution/complete-QA run.
259 unittest checks and compileall pass. Full results: selector_methods_20260924.md.

2026-09-24 compact selector validation: reason→selected_ids only; reason one sentence
with at most30 words requested, nonblank <=400 characters enforced. Catalog metadata
only; current report analysis/skill_evolution/selector_compact_schema_20260924.md.
Two versions completed806 text-only requests; final403 had zero errors/repairs,
91 repeated contexts selected identically. Development agreement196/205 and66/73;
all are reused development data, not independent Test or QA accuracy. Global's
real-panel29/33 is below historical30/33 despite overall gains. First version's
400-character saturation artifacts retained, not promoted. Final source/configs and
status outputs/analysis/20260924_selector_compact_schema_v2/. Full259 unittest checks
passed using PYTHONPATH=src:references/skills_self_evolve/GEPA/src (gepa not installed
in base environment); no packages/services changed. Source is frozen per run.

2026-09-24 real selector96 diagnostic completed: new QA IDs and exact media paths
excluded against prior selector312; no source-film independence claim. Full96QA,
337 selections,692 injection/reuse checks; zero final question/selection errors.
Assistant blind applicability labels give Global69/85 (11 ambiguous omitted),
Video228/241 but only11 positives (9 correct); label-scope sensitivity documented.
Correct visual-card selections follow first-watch in10/32 only. Artifacts
outputs/analysis/20260924_selector_real96/, report
analysis/skill_evolution/selector_real96_20260924.md. No optimizer, API Judge,
no-Skill rerun or service changes; no new policy edits based on this panel.

2026-09-24 evolution design update only: user clarifies authored Skill applicability
labels and adherence are not utility GT. Current future plan:
analysis/skill_evolution/outcome_conditioned_evolution_20260924.md. Four outcome
groups organize evidence, never map mechanically to CRUD; routing metadata and
procedure edits have separate evidence scopes, but current full-content embedding
and full-body injection couple their effects. Keep GEPA and evaluate full-bank
freely routed task gain. Targeted card attribution/local counterfactual replay remain
planned; no optimizer, Runtime, Skill or experiment change in this research item.


2026-09-24 Global-only evolution: explicit `algorithm: global-targeted-v1` dispatches
`algorithms/targeted/global/trainer.py`; recipe `configs/skill_evolution/global_targeted_35b.yaml`.
This is an independent loop, with no GEPA imports or role rotation. `targeted/video/`
is reserved only. Shared infra supplies rollout/scoring/store and bounded proposal repair.
Global must use dynamic/task selection. Actual selected/injected provenance groups Train
cases; routing edits preserve procedural sections, procedure edits preserve description/
When-to-Use. Procedure/joint refinement targets must all belong to the actually injected
source card, spanning at least two source groups. Unknown exposure is not abstention.
Video cards stay byte-equivalent across all candidates. One operation per round;
add/refine/merge/retire/keep; candidate whole-bank Train screening then full Gate strict
positive macro gain, every task bucket protected versus parent/seed, no new per-question
fatal/invalid. No zero-gain maintenance acceptance in this algorithm. Artifacts under
`global_evolution/`, `rounds/`, `evaluations/`, `routing/`; unchanged frozen resume rules.
Prompt and design: `analysis/skill_evolution/global_targeted_implementation_20260924.md`.
Real engineering smoke: `outputs/analysis/20260924_global_targeted_smoke/`, 12 Train/8 Gate
CC/PI from previously used development split, 35B Actor, GLM optimizer, frozen authored
Video cards; not independent Test. Read saved status; do not edit its frozen source.

Global-targeted smoke completed on 2026-09-24: one valid GLM add proposal without
repair, `global-narrative-bridge`; Train8/12 unchanged, Gate3/8→4/8 (PI:101 corrected,
no regression), final Gate fatal/invalid0; all three Video cards unchanged. Saved
experiment bank has five Global plus three Video cards; default bank not replaced.
This 8-question Gate includes CC0/4 and cannot establish broad protection or generalization.
270 unittest checks pass. Full result/limits in the implementation report above.

2026-09-24 Global Train-memory extension: `targeted/global/experience.py` stores
immutable Train-only observations (exact whole-bank identity) and per-round attempts;
Gate reports/acceptance are not arguments to memory recording. Same-bank observations
can accumulate; historical other-bank attempts are explicitly marked historical_only.
Target-local history retrieval uses existing SQLite FTS5 BM25, at most4 attempts;
no new embedding service or Runtime memory. `reflection.py` / `reflection.md` implement
persisted target-specific success/failure/uncertainty reflections, bounded one repair,
with enumerated Train refs. Proposal and reflection history never see Gate details.
Config: use_train_memory=true; reflection_minibatch_size=8 (0 disables); exploration_interval=4
(0 disables periodic exploration). Recipe now rounds4/batch64. Train collection uses
native-task stratified epoch coverage without replacement. One focus per round, two
reflection minibatches maximum under100000 evidence characters; boundary cases included.
Task families are offline aggregator categories, never Runtime routing rules.
Exploitation permits target refine/keep; exploration also permits new strategies/cards.
No eligible existing card allows uncovered-family discovery even outside periodic slots.
Prior source-qualified target visits rotate scheduling; these are proposal opportunities,
not success probabilities or a bandit. Video frozen, independent loop (no GEPA), unchanged
full-bank Train/Gate acceptance. Current proposal evidence drawn from historical same-bank
Train cases is included in matched candidate screening. Artifacts add train_memory/,
rounds/*/focus.json and reflections/. Resume retains atomic identity/proposal safeguards.

Train history retrieval follows both focus and proposal card lineage, so new/merged cards
inherit the attempts that created them. Non-keep proposal target coverage must include
two source groups of the scheduled focus; boundary-only evidence cannot replace ownership.
Real stagewise validation control: `outputs/analysis/20260924_global_memory_validation/`.
Stage1 replays9 retained real Train traces with exact deduplication and cross-bank isolation;
stages2/3 use3 rounds, Train12/Gate8, reflection8, interval2 (engineering override), 35B+GLM.
Read saved status and preserve frozen source; default recipe remains interval4/batch64.

2026-09-24 SkillClaw Global port supersedes the five-operation targeted proposer above.
The explicit global-targeted-v1 entry now uses SkillClaw model actions improve_skill,
optimize_description, create_skill, skip. Global merge/retire and joint refinement are
removed. No-skill groups allow create/skip only. Internal immutable transactions remain
add/refine/keep; shared lifecycle/BankStore retain their independent operation contracts.
proposer.md adapts SkillClaw execution.py at3938f7537645c961d94498a0a79fc0a977019595;
MIT notice is global/SKILLCLAW_LICENSE. Input separates current_skill, actual injected
session_evidence, boundary_sessions, existing Global skills, Train history and reflections.
One QA is one session; original public trajectories/parameters remain with structured
minibatch analysis. optimize_description changes description+When-to-Use only; improve_skill
preserves both. A declared exploration slot chooses evidence, not a mandatory operation.
Shared RoleProposer normalizes validated provider output to transactions and persists both
model_value and normalized value; action-specific repair is bounded once. Runtime, Video,
Actor/optimizer sampling and whole-bank Train/Gate acceptance remain unchanged.
Engineering smoke control: outputs/analysis/20260924_global_skillclaw_smoke/; 12 Train/8 Gate
reused development questions,35B+GLM. Read saved status; preserve frozen source.
SkillClaw smoke completed: improve_skill parsed/validated without repair, Train8/12→7/12,
CC:183 protected loss; rejected at Train screen, no candidate Gate. Original bank retained,
final Gate3/8 unchanged and Video cards unchanged. 278 full unittest checks and19 final focused
checks passed. This is engineering validation, not positive evolution/generalization evidence.

2026-09-24 user authorized expanded SkillClaw Global evolution from zero skills.
Control: outputs/analysis/20260924_global_skillclaw_empty_expanded/. Initial bank has
zero Global AND zero Video cards; Video remains empty/frozen. Reuses audited CrossVid
Train383/Gate181 outside Lite2500 protected sources, all10 tasks,12 rounds/batch64,
reflection8/exploration4,35B six cap1 replicas GPU2–7 plus existing Embedding8110.
CCQA Judge uses authorized DeepSeek profile; preserve requested/returned identity distinction.
No new GEPA or online mechanism. Read saved status, do not duplicate launch or alter frozen
source. Fresh parent empty-bank evaluation is necessary to this experiment, not an extra
full no-Skill benchmark. Dataset is reused development, not independent Test. Protocol:
analysis/skill_evolution/skillclaw_empty_expanded_20260924.md. Estimated8–14h, potentially18h
with many full Gates/long tails; controller has no time cutoff and preserves progress on failure.

2026-09-24 Global candidate recovery: `ProposalValidationError` identifies exhausted
candidate validation; only GlobalTrainer records `invalid_proposal`, retains its parent
bank and advances the round. Transport/scoring/identity errors still propagate.
Global repair selects the matching action Schema branch and reports field lengths;
writing targets are content2000/description450 characters, hard limits remain2400/600.
The empty expanded experiment failed at round0 after245 scored baseline episodes
(description659/content2591, correction content2424). Recovery control:
`outputs/analysis/20260924_global_skillclaw_empty_expanded_revision1/`; it reuses the
original exact rollout/scorer cache, repeat ID, split and Runtime, with a new source
snapshot. Original frozen failed run remains intact. Consult saved status for progress.

2026-09-25 selector replacement: Runtime uses AutoSkill compact selector metadata
and byte-identical original system Prompt, pinned94c47ca488d4ba4117d20272e66d49b9877e68cf.
Source subset/provenance: src/mvagent/skills/. When-to-Use maps to triggers;
preview0 (metadata only), max_selected1, history6 turns/2000 upstream text units.
Native output use_skills/selected_skill_ids/reason replaces reason/selected_ids.
Strict Schema and boolean consistency remain; upstream forced keyword fallback is
not ported. Empty selections remain empty; errors propagate. Existing retrieval,
role/stage isolation and task-scope injection unchanged. Paired real181 x two-bank
routing audit: outputs/analysis/20260925_autoskill_native_selection/. No QA inference
or improved end-to-end performance is implied. Historical method ablations use frozen sources.

2026-09-25 extraction pilot: `outputs/analysis/20260925_autoskill_extraction_ablation/`
contains four native AutoSkill trajectory-extractor GLM calls (CC/MOC, target-only
vs neighboring Train cases), plus362 successful selector calls under routing/.
Native system Prompt unchanged; structured API caps and input grouping are adapters.
Examples stayed in raw sidecars after an initial6000-char bank packaging rejection;
no generation retry/truncation. Selector-only wrappers are NOT accepted evolution
cards or deployed Actor policies. Native candidates still contain semantic conflicts;
no QA improvement demonstrated and production proposer remains unchanged.
Protocol/results: analysis/skill_evolution/native_extraction_experiment_20260925.md.

2026-09-25 authored input-grounded Global library: 10 cards under
src/mvagent/skills/authored/crossvid-v001/, exported to
configs/skill_evolution/skills/crossvid_global_v001.json (schema_version2).
All Global/initial, intended task-scoped selection; no profile switched or model calls.
CrossVid all9015 inputs surveyed;6 real examples per10 types with actual prepared-media
ID/duration in analysis/skill_evolution/crossvid_global_library_20260925/.
Official task labels are not routing GT: MSR includes counts; MOC includes lane/car-length
separation. Cards route by visible goal, not dataset code. Library is authored/unvalidated
for performance, not accepted evolution output. K8 retrieves from this10-card bank;
full-catalog tests must explicitly configure K>=10. Chinese authored mirror updated.

2026-09-25 pattern-based authored alternative:8 Global/initial cards in
src/mvagent/skills/authored/crossvid-patterns-v001/, exported as
configs/skill_evolution/skills/crossvid_global_patterns_v001.json. Four shared workflows
(evidence matrix, contextual interpretation, synchronized snapshot, track history)
replace six category-oriented cards; four specialized cards remain byte-identical.
Analysis and60 author-hypothesis mappings: analysis/skill_evolution/crossvid_global_library_20260925/patterns.md.
These are not routing GT or QA results; old10-card bank preserved, no default switched.
Default K8 shows this entire8-card catalog; matched old/new tests should set K10.
Chinese Prompt mirror updated.

2026-09-25 authored pattern bank evaluation: user authorized a larger routing+guidance
validation. scripts/analysis/run_pattern_skill_evaluation.py freezes1000 CrossVid IDs
(100/task, outcome-blind), excludes60 authoring IDs and recent383/181 Train/Gate known
sources, then runs10-question engineering smoke and main with exact smoke-cache reuse.
Control outputs/analysis/20260925_pattern_skill_1000_revision1/. Original control failed
on removed max_selected config before inference; preserved. Global selects one/none,
task scope, full8-card catalog; Video dynamic role filter has zero eligible cards.
No optimizer or no-Skill rerun; historical35B baseline copied by ID/hash, CCQA scores
joined by exact prediction. Current Runtime differs: historical comparison is not a
fresh causal ablation. DeepSeek scoring authorized; actor six35B replicas unchanged.
Automatic audits verify selection lifetime/body injection and export all action parameters,
blind routing inputs and paired scores; semantic routing/execution review remains separate.
Protocol analysis/skill_evolution/pattern_skill_evaluation_20260925.md. Read saved status;
resume only frozen controller after owning processes exit, never relaunch into same root.

2026-09-25 Skill content/context audit (no Runtime change): eight frozen-builder
renders and24 actual Global requests from the1000-panel smoke show card H2 sections
at the same level as outer Decision strategy. Bodies remain intact; injection/lifetime
audit passed10 questions. This is a structure issue, not demonstrated accuracy loss.
Details/proposed isolated formatting, parameter-detail and example experiments:
analysis/skill_evolution/skill_content_context_review_20260925.md. Exact rendered/actual
messages: outputs/analysis/20260925_skill_context_audit/. Example JSON is illustrative,
Schema-checked, not observed video evidence or a deployed Skill. Current1000 main phase
started after smoke; do not change its frozen rendering, cards, source or controller.

2026-09-25 Skill Markdown fix: mvagent/skills/prompts.py rebases ATX headings to
H3 or deeper under the planners' H2 Decision strategy, preserves fenced code,
rejects unclosed fences and is idempotent. SkillBank.render and both role Prompt builders
use it; stored cards retain the four H2 sections. Content hashes refer to raw cards;
selection/reuse rendered hashes refer to nested bodies. Static Skill prompt injection
also normalizes headings. Empty Skills unchanged; no action/schema change. Chinese
mirror and actual-body audit updated. Current1000-panel frozen source remains unchanged.
New authored alternative:4 Global/initial acquisition strategies under
src/mvagent/skills/authored/acquisition-v001/, exported as
configs/skill_evolution/skills/global_acquisition_v001.json. Direct detail watch,
independent local analysis, survey-then-focus, synchronized event check. No default
switch/new inference; examples are illustrative, not observed facts. Scope and future
comparison: analysis/skill_evolution/acquisition_skills_20260925.md.

2026-09-25 expanded acquisition-style library: user clarified that four cards were
writing-style examples, not a size limit. New11-card Global/initial candidate bank:
configs/skill_evolution/skills/global_acquisition_v002.json; English authored sources
src/mvagent/skills/authored/acquisition-v002/. Re-reads the existing60 CrossVid inputs,
not the1000-run outcomes, and maps all60 to primary/acceptable alternative hypotheses.
Seven explicit workflows supplement/reframe the earlier four: local temporal relations,
interval event ledger, reference-step localization, state-transition ordering,
context-supported interpretation, missing-event bridge, procedural error checking.
Generic local/survey cards have narrower boundaries; no category-code routing in cards.
Report/mapping/full text: analysis/skill_evolution/acquisition_library_v002_20260925/.
Chinese Prompt mirror updated. All11 <=2400 chars;74 full-context combinations checked,
no model calls/default switch. Evaluation should explicitly use retrieval_top_k=11
for full-catalog testing (default8 would retrieve); max_selected field is removed.
Validation/source hashes: outputs/analysis/20260925_acquisition_v002/validation.json.

2026-09-25 user authorized acquisition-v002 real evaluation on the same1000-question
CrossVid panel. Control: outputs/analysis/20260925_acquisition_v002_1000/. Actor/selector
35B six cap1 replicas unchanged; full11-card catalog (K11), task-scoped Global,
zero eligible Video cards, fixed Markdown nesting. run_pattern_skill_evaluation.py
now accepts --bank and splits10 smoke +990 main with disjoint manifests, then writes
combined_audit/review/routing_blind for all1000. This avoids hashing the entire panel
at BOTH startups; main still hashes its own media. Each QA runs once; no optimizer or
no-Skill rerun. Historical no-Skill reused; old8-card comparison also changes rendering,
so do not attribute its delta solely to library content. Frozen controller imports its
own src for audits. Protocol: analysis/skill_evolution/acquisition_v002_test_20260925.md.
Read saved status; resume only owning frozen controller after its processes exit.

2026-09-25 acquisition-v002 transfer validation: run_pattern_skill_evaluation.py
supports --panel transfer for outcome-blind CVBench/MVU-Eval stratified sampling,
excluding prior Train130/Gate300 exact IDs and flagging known source overlap.
Frozen912 QA panel: CVBench592 (15 fine tasks), MVU320 (8 tasks);23 disjoint smoke
then889 main, all same11 Global cards/K11/task scope, no Video cards/optimizer/API Judge.
Control outputs/analysis/20260925_acquisition_v002_transfer912/; historical35B no-Skill
reused after exact question/videos/label checks. Closed scores may be represented by
boolean correct rather than numeric score. Separate per-dataset/task/cohort/source
reports and known-media-group paired bootstrap; A/B not source-disjoint, historical
Runtime not causal control. Protocol analysis/skill_evolution/acquisition_transfer_test_20260925.md.
Resume only owning frozen controller; preserve active files/services. No default switch.

2026-09-26 handwritten Video Skill matrix: seven short cards at
src/mvagent/skills/authored/video-evidence-v001/, exported as
configs/skill_evolution/skills/video_evidence_v001.json (Video initial+evidence).
Chinese mirror updated. Based on32 instruction examples collected from5434 historical
Global analyze requests; prior inspected failures are acknowledged authoring exposure.
New entry scripts/analysis/run_video_skill_matrix.py freezes four arms G0V0/G1V0/G0V1/G1V1,
all fresh under identical Runtime/35B services; G uses unchanged11-card acquisition-v002.
User explicitly requested2x2, so fresh empty-bank control is included despite historical
no-Skill reuse in earlier experiments. Role-filtered full catalogs/K11, Global QA scope,
Video request scope; no Observer Skill/optimizer/API Judge/runtime contract change.
Panel460: CVBench300/MVU160,20 per23 fine tasks; authoring IDs excluded, shared authoring
media groups flagged (strict group exclusion removes an entire counting category).
Each arm23 smoke then437 main; all four smokes audited before main. Controller is detached
and process-locked; preserve snapshots/active caches. Control
outputs/analysis/20260926_video_skill_matrix460/; protocol
analysis/skill_evolution/video_skill_matrix_20260926.md. Development, not independent Test.


2026-09-26 structured Skill contract supersedes earlier dynamic-format/selection notes:
Current authored Skills are individual JSON files, banks schema_version3. Old v2
hash snapshots/frozen outputs are historical only; no runtime compatibility parser.
BM25 and embedding index description/when_to_use only; >8 eligible cards require
embedding and hybrid RRF top8. Selector sees metadata only, chooses one or none.
Only Strategy is rendered, with H3 outer/H4 inner headings.
Common Pitfalls in current authored cards were preserved as strategy constraints.
Full-card hash and rendered hash are distinct. Global routing edits preserve both
execution fields; procedure edits preserve both routing fields. All4 text fields
count toward evolution max_card_chars. Current config pins point to new v3 snapshots.
Management --file accepts individual JSON; search --embedding-config accepts JSON
endpoint/model/timeout_sec and uses runtime candidate recall. Frozen experiments
must use their own frozen source. No new inference benchmark or default Skill enabled.
Selector audit prepare now requires --learned-bank (schema3); --mode hybrid uses current
runtime recall. Historical full/BM25-only/embedding-only ablations require frozen source.
Validation:296 unittest cases passed with the existing GEPA reference source on PYTHONPATH;
4 synthetic live selector probes passed (Global11→8 hybrid, Video7 full catalog), no video
inference/benchmark gain claim. Artifacts: outputs/analysis/20260926_structured_skill_smoke/.

2026-09-26 structured Skill real validation completed at
outputs/analysis/20260926_structured_skill_real46/: first46 of the historical460 matrix
panel,2 per23 tasks; fresh Global+Video Skills only,35B cap1 six replicas, no optimizer/
Judge/no-Skill rerun. Old/new correct30/28 (3 gains,5 losses), fatal/invalid0;320 selected
body injections audited without errors. Fixed-input selector changes Global14/46,
Video3/38. Fixed-skill fresh old/new body probes42 Global+34 Video:6/0 action changes;
Video13 parameter changes only what, no where/FPS changes. All76 old-body action/parameter
controls reproduce historical decisions. Small development evidence, not independent
Test or significant overall regression/gain. Original controller's probe extractor
assumed parsed events carried schema; unchanged46 QA preserved, separately pinned
probe_revision1 completed replays and fresh body controls; frozen files untouched.
Entry scripts/analysis/test_structured_skill_runtime.py now validates replay jobs before
inference. Summarizer scripts/analysis/summarize_structured_skill_test.py; report
analysis/skill_evolution/structured_skill_real46_20260926.md. No runtime prompt change.

2026-09-27 Global-only evolution design review (proposal only):
analysis/skill_evolution/global_skill_evolution_design_20260927.md records primary
research, task-scoped five-field Skill writing, illustrative non-deployed JSON,
source-disjoint Train/Gate/Confirm planning, separate routing/procedure edits and
whole-bank freely routed acceptance. Source guard lists1867 path-disjoint candidates,
not6515 fully isolated training questions. Historical empty Global12-round run ended
with0 accepted cards (7 screen rejections,3 Gate rejections,2 invalid proposals).
No Runtime, Prompt, authored Skill, service or experiment changes were made; no model,
optimizer or Judge calls were launched. Previously inspected target benchmarks remain
development/transfer evidence, not pristine blind Test. Existing execution authorization
and cancellation boundaries remain unchanged.

2026-09-27 Global Skill authoring specification:
src/skill_evolution/infra/global_skill_specification.md is the English reference for Global
five-field JSON cards, based on official OpenAI and Claude authoring guidance and
current MVAgent contracts. It distinguishes enforced limits from writing recommendations,
documents routing/execution visibility and action/evidence boundaries, and includes
two illustrative cards. Documentation examples are not installed Skills; this change
does not alter Runtime, model-visible Prompts, service state, or experiments.

2026-09-28 Selector Prompt update: SYSTEM_TEMPLATE in skills/prompts.py is shared;
build_selector_system_prompt(role) inserts GLOBALAGENT_BACKGROUND or VIDEOAGENT_BACKGROUND
from skills/prompts.py. Global selects a whole-question method with VideoAgents as
instruction/report black boxes; Video selects a complete-current-instruction method
with Global as an instruction-only caller and its own retained Memory. Shared rules
distinguish applicability prerequisites from visual facts the workflow will obtain.
Role backgrounds explain the evidence-gathering inputs: Global videoagent_request
and instruction/videos/clip, Video what/where/fps. answer and finish submit generated
results rather than control evidence acquisition; the opposite role stays a black box.
Each background uses a Target Agent section with Available information, Available actions and Required result subsections;
all actions are parallel list items with signatures. answer(answer) and finish(summary)
retain their required nonempty result arguments, as defined by the action Schemas.
Selection timing, retrieval, candidate/input fields and Actor injection are unchanged. Chinese Prompt mirror is synchronized; no model experiments launched.
Selector output instructions use the Agent Prompt style: Output contract, Fields,
Rules, and multiline JSON examples for single selection and abstention. Output now
contains exactly use_skills and selected_skill_ids; reason is removed from the Prompt,
Schema and model-selection telemetry. Extra fields are rejected. skills/prompts.py
owns readable User input formatting; skills/__init__.py only exports the public entry points.
Selector User is text (Input (Question for Global or Instruction for Video, optional Videos), Candidate skills), not JSON. It includes
no history or max_selected. Agent execution Memory, retrieval queries and role/stage
filtering are unchanged; large-bank retrieval still uses its existing history query.
System separates selection task, target Agent, input, selection rules and output contract.
The obsolete AutoSkill history formatter and text-sizing helpers are removed.

2026-09-28 Selector heading layout: standalone System and User messages start at H1.
User Input contains H2 Question (Global) or Instruction (Video), plus optional H2 Videos;
Candidate skills is a sibling H1 with H2 candidate IDs. Selection and output contracts are unchanged.

2026-09-28 Selector backgrounds now describe information access, actions and required
results directly, without architectural role names in model-visible prose. Python
GLOBALAGENT_BACKGROUND/VIDEOAGENT_BACKGROUND names and action contracts remain unchanged.

2026-09-28 Runtime skills module consolidation: bank.py owns SkillCard/SkillBank,
validation, path resolution and hash-pinned static/dynamic loading; prompts.py owns
selector templates, User input and heading rendering; selection.py owns hybrid
retrieval, LLM selection, validation/cache and telemetry. __init__.py only exports
SkillBank/load_skill. loader.py and formatting.py are removed, without import shims.
Authored cards, frozen banks, prompt bytes and selection behavior are unchanged.

2026-09-28 current Selector audit completed: outputs/analysis/20260928_selector_current91/.
Frozen current source/dynamic-v003, existing verified GPU2–7 Qwen3.5-35B-A3B services;
91 text-only initial selections, no QA/optimizer/Judge calls, all valid and zero repairs.
Original assistant-authored clear-label agreement62/73 (Global27/33, Video35/40);
18 ambiguous cases separately18/18. Global negatives0/5 correctly abstained; Video
positives4/8 selected. Some mismatches reflect action/event scope and auxiliary-method
label ambiguity; preserve labels and do not call all mismatches proven model errors.
All catalogs small/full-catalog: no large-bank retrieval or end-to-end gain evidence.
No old-Prompt paired rerun, Prompt edits, service replacement or deployment in this audit.
Full requests, hashes, pool verification and diagnostic report are retained in that root.

2026-09-28 Selector input clarification: SYSTEM_TEMPLATE no longer contains a shared
Input section. Each role background defines its actual Selector input: Global
Question/Videos/candidates, Video Instruction/candidates without separate video
catalog or Memory. Target Agent execution information/actions/results remain separate;
Selector output stays use_skills/selected_skill_ids. No routing or input-renderer change.
The earlier current91 audit predates this wording change; it is not its measured result.

2026-09-28 Selector simplification: remove separate Selector input sections; integrate
actual input and execution-time evidence boundaries into each Target Agent Available
information section. Candidate metadata is described once in the shared selection task.
Actions, required results, User rendering and selection output contracts stay unchanged.

2026-09-28 Selector wording refinement: Available information only lists received
inputs; Required result only describes the deliverable. Shared rules positively
define task/evidence matching, applicability checks, evidence-acquisition goals,
whole-task fit, abstention and one-card output. Auxiliary-only matches now explicitly
lead to abstention; no essential-bottleneck exception remains. Prior current91 metrics
predate this revision. Actions, input rendering and output Schema remain unchanged.

2026-09-28 Selector readiness audit: outputs/analysis/20260928_selector_readiness91/.
Same91 inputs/bank/model/execution as current91, current positive-rule Prompt frozen.
Two fresh91-case runs:182 valid requests, zero repairs, selections identical91/91.
Clear-label agreement63/73 vs62/73 previously (Global29/33 vs27/33; Video34/40 vs35/40),
paired3 wins/2 losses; ambiguous18/18 separate.65 focused CPU tests passed, including
empty-bank evolution/Gate/resume with test doubles. Suitable as a controlled Global
evolution baseline, not evidence of end-to-end gain. No optimizer/QA/Judge calls or
service replacement. All real selections used small initial full catalogs; large-bank
quality and Video evidence-prerequisite observability remain open. See report.md and
comparison.json; no evolution launched and no prompt adjusted after these results.


2026-09-28 evolution cleanup: algorithms/ now keeps targeted/ (current Global), lifecycle/
(explicit runnable comparator), and shared proposals.py. infra/proposals.py moved to
algorithms/proposals.py; paired_gate/compact_report belong to infra/evaluation.py and
routing_audit/role_routing to infra/trajectory.py. infra/prompts/ was removed; its
lifecycle proposer text is preserved verbatim in algorithms/proposals.py. Active
targeted Prompt files and benchmark Judge Prompt stay in their owning components.
The English Global Skill specification is infra/global_skill_specification.md under
src/skill_evolution/ (documentation only, no automatic injection). Removed static
SkillOpt/GEPA implementations, exclusive tests/launchers, three GEPA recipes and GEPA
requirement. Shared data/scoring/trajectory/static-diagnostic utilities remain active.
Historical reports, frozen sources and outputs were not changed. Credential reading
for retained diagnostic launchers now lives in scripts/analysis/credentials.py.


2026-09-28 analysis/scripts/tests cleanup: analysis/README.md is the concise current
entry; historical_index.md retains the old catalog. skill_evolution/handoff.md now
contains current contracts and links to historical_handoff_20260928.md for unchanged
dated evidence. The old next-step plan is historical_next_steps_20260920.md. Fixed
Prompt, action-parameter and evidence-contract protocol documents are consolidated
verbatim into their respective *_results_*.md files; links were updated. Removed
scripts/prepare_crossvid_gepa_pilot.py, prepare_crossvid_gepa_expanded.py and
scripts/analysis/analyze_dynamic_constraints_run.py. Historical inputs and frozen
outputs remain intact. Shared test helpers now live in tests/evolution_fixtures.py;
test_historical_action_contracts.py was renamed test_action_contracts.py with unchanged
coverage. Retained watch/diagnostic scripts still have active import dependencies.
No model-visible Prompt, runtime behavior, experiment or service changed.


2026-09-28 user-requested algorithm reset supersedes the earlier cleanup decision to
retain lifecycle. No old optimizer loop or proposer remains in algorithms/. New
alternating/{global,video} packages are scaffolding only. Shared bank checks remain
in tests/test_bank_infra.py; old training-only tests were removed. Runtime and frozen
outputs are unchanged; no new training or API calls launched.

2026-09-28: Global SkillAdaptor-inspired sequential process is documented in
`src/skill_evolution/algorithms/alternating/global/flow.md`. It is a design only:
Localizer → case grouping → Linker → Reviser/Generator → Train → full Gate → update.
Video remains frozen during Global optimization. No training implementation or new
model-visible Prompt was added; stage Prompt responsibilities only are described.

2026-09-28 Global flow revision: flow.md now follows representative-fault deduplication,
Linker attribution, Reviser/Generator, candidate validation and fault-chain retry.
Cross-case retrieval, two-source generation prerequisites and Train prescreening were
removed from the design. Full Gate reruns and no detailed Gate feedback remain explicit
MVAgent adaptations. Documentation only; no executable optimizer or Prompt added.

2026-09-28 Global implementation supersedes the earlier algorithm-reset placeholder.
New tests/test_global_skilladaptor.py checks public evidence, direct routing, Global-only
edits, fault matching, bounded repair, interruption replay and overall-score-only Gate.
Prompts are new MVAgent adaptations of SkillAdaptor concepts, not verbatim upstream.

2026-09-28 Global SkillAdaptor real smoke completed under
outputs/analysis/20260928_global_skilladaptor_smoke/: fixed-seed Train4/Gate4 from
historical CrossVid CC/PI development partitions, empty Global/Video,35B existing pool,
GLM-5.3-Flash optimizer, no API Judge/Test.24 raw rollouts,4 full-Gate candidates,
3 rejected/1 accepted; Gate2/4→3/4, not a generalization result. First two candidates
were not selected; last two selected+injected on2 PI questions.16 GLM calls include2
length corrections; raw health counts all0.222 unittest tests pass,10 new Global tests;
real resume exit0 leaves108 raw/stage records unchanged. Detailed report in
analysis/skill_evolution/global_skilladaptor_smoke_20260928.md. No default Skill deployed.


2026-09-29 Global SkillAdaptor input rendering: stage User messages (including repairs)
reuse infra.trajectory.render_case_value for readable Markdown. Global training-case
projection omits decision.reason and final_answer.reason; raw rollouts remain unchanged.
Stage audit inputs retain structured payload plus exact user text; rendered input enters
cache identity. Optimizer attribution reasons and JSON output schemas remain intact.

Global evolution trajectory rendering uses evidence.render_stage_input: Step → Action → Observation,
with complete JSON parameters inline after the action and untruncated public results.


2026-09-29 轨迹显示更新：Global 轨迹使用 infra/trajectory.py::render_global_steps，
每步一行 `Step N: action=动作名 完整参数 | obs=返回报告`，不截断。
analyze_videos 作为一个普通函数调用，obs 按 video_id 标记返回报告，不展开 VideoAgent 内部过程。
移除 Status、request_id、round、selected 等执行元信息；有实际注入时显示 skills，未知注入明确标记 unknown。
保留真实错误、证据不确定性及 runtime finalizer 不可编辑标记。最终答案只显示 answer。
Video 私有观察仍由独立的 _render_observation_result / _render_memory 路径处理，不混入 Global 渲染。
此段替代此前关于多行 Action/Observation 及全部元信息展示的描述。


2026-09-29 模型输入精简：render_stage_input 不向模型展示 sample_id、bank_hash 或重复 final_answer；
视频元信息合并为 `video_1 (259.54 seconds); video_2 (288.96 seconds)`。
末尾 offline_feedback 仅渲染 Ground truth，取非空 reference_answer 或 ground_truth 标签；
不再展示 score 和评分解释。结构化审计数据及原始 rollout 保留，不影响评分和接受规则。
background.md 对应改为 separately marked offline ground truth。


2026-09-29：Global 优化器案例不再包含 unpaired_public_executions。该字段表示公开 History 中
未匹配到 Global 决策步骤的剩余执行记录；infra 投影保留它用于诊断轨迹对齐问题，
不进入当前 Localizer/后续优化阶段的模型输入。原始 History 和执行记录不变。


2026-09-29 并行调用轨迹展示：一个 Global 决策仍对应一个 Step。
analyze_videos 的全部参数在 action 同一行，各返回报告另起一行 `obs[video_id]: 报告`，
表示同批独立请求，不把 VideoAgent 内部动作展开为 Global 步骤；实际并发度仍由 Runtime 控制。
watch_videos 在同一行保留完整参数和一份联合 obs；answer 只显示包含答案的 action，不输出空 obs。
不同 Step 之间空行分隔，其余证据、错误、实际注入及 finalizer 边界规则不变。
代表性示意样例：analysis/skill_evolution/global_trajectory_examples.md（非实测轨迹）。
本段替代此前“每步严格一行”的展示说明。


2026-09-29 Global optimizer prompts now live as triple-quoted Python constants in
algorithms/alternating/global/prompts/__init__.py and localizer.py; runtime prompt Markdown
files were removed (upstream reference documentation is unchanged). Localizer composes
trajectory reading, fault definitions, analysis instructions, four Global examples,
JSON output, shared constraints and stage constraints. Schema enforces located/nonempty
versus skip/empty chains and allowed editable steps; distinct step IDs remain business-validated.


2026-09-29 Localizer 输入平级分区：去掉 Case，按 `## Input`、`## selected skill`、`## steps`、
`## output`、`## ground truth` 展示。selected skill 只展示轨迹实际选中的卡，按 ID 去重；
没有选中时为 None，缺失选择记录明确说明未知。步骤中的 skills 仍指实际注入，与选中分开。
output 仅含最终提交答案，不含 reason；ground truth 仅含参考内容。后续编辑阶段继续附带完整库及编辑上下文。
Localizer 不再接收未选中的库卡，因此 skill_missing 表示当前指导的方法缺口，完整库是否已有对应方法由 Linker 后续核查。


2026-09-29 Localizer 版式：System 仅提供 BACKGROUND，User 使用 build_localizer_prompt 将真实轨迹
插入 Full Step-Level Trajectory。User 只有一个一级标题 Fault Localization Analysis；
轨迹的 Input、selected skill、steps、output、ground truth 为三级标题，规则为二级标题。
顺序为任务/轨迹、Fault Type Definitions、Examples、Analysis Instructions、SHARED CONSTRAINTS、
STAGE CONSTRAINTS、Output Format。示例使用原版 <example type="..."> 标签。
JSON Schema 与步骤校验不变；修复保留同一份完整输入，末尾追加 Response Correction。


2026-09-29 remaining Global optimizer stages use prompts/{linker,reviser,generator}.py,
with common.py owning shared background and __init__.py assembling text.
All stages send their TASK plus shared BACKGROUND as System and rules plus rendered evidence as User;
case headings nest below the context section. Linker now returns responsibility attributions; candidate validation is programmatic and empirical validation uses the full Gate. Stage calls validate one response without a correction call. Schema enforces revise/nonempty target versus create/skip/empty ID,
and candidate/object versus skip/null. No Runtime or acceptance-rule change.


2026-09-29 Localizer-only real diagnostic completed at outputs/analysis/20260929_localizer_real4/:
reused frozen Train4 (2 wrong + 2 correct controls), empty Skills, GLM-5.3-Flash returned
glm-5.3-flash; 4/4 first-pass valid, zero repairs/errors, 23164 total tokens. No Actor,
Judge, Gate or downstream optimizer calls. Source/inputs frozen. Correct controls are
not a change to training selection. Two wrong cases localized plausibly, but report
paraphrase fidelity, prediction-task guidance and pre/post-action evidence remain
limitations; no localization accuracy or causal gain claim. Report:
analysis/skill_evolution/localizer_real4_20260929.md. No Prompt fix deployed in this diagnostic.

2026-09-29 Localizer-only diverse36 diagnostic completed: frozen prior real4 source/Prompt,
36 historical Train trajectories (28 wrong, 8 correct; 9 CrossVid closed-task families).
36 first-pass valid, zero repairs/errors, 232389 tokens; wrong located26/skip2, correct skip8.
Five earliest-first chain-order violations pass existing validation. No localization GT,
Actor/Judge/Gate/Test/downstream calls or Prompt fixes. Qualitative evidence limitations
and full provenance: analysis/skill_evolution/localizer_diverse36_20260929.md.

2026-09-29: Removed SHARED_CONSTRAINTS from all Global optimizer stage prompts and removed
REPAIR plus the stage-level correction loop. common.py now owns BACKGROUND only.
Schema/business validation and persisted response reuse remain; invalid stage outputs
raise StageValidationError without another stage call. Shared model-client behavior is unchanged.

2026-09-29: Each Global optimizer prompt module now separates TASK from INPUT.
build_system_prompt assembles stage TASK then the user-simplified BACKGROUND.
User retains evidence, rules, examples and output format. Removed unused action_contract
plumbing from Stages/GlobalTrainer/runner; no dynamic contract is injected into this background.

2026-09-29: Localizer User no longer repeats the Fault Localization Analysis title.
Its six main sections use H1; trajectory fields and classification heuristics use H2.
System TASK and other stages are unchanged; build_localizer_prompt renders at minimum_level=2.

2026-09-29: Localizer prompt uses a single Agent/action-contract perspective, without
GlobalAgent/VideoAgent/Actor role explanations. It separates request quality from returned
result quality and subsequent handling. Literal action parameter videoagent_request remains.
Shared background input wording is stage-neutral; other stages retain their existing terminology.

2026-09-29: Current Global evolution Chinese prompt mirrors moved to global/chinese_prompts/,
one Markdown per English Python file, plus README. General prompt_chinese_reference.md
now links there instead of retaining duplicate Global stage versions. Documentation only.

2026-09-29: Global prompts/ now groups localizer/linker/reviser/generator into
packages with prompts.py and schema.py. Stage schemas directly declare their contracts; generator/schema.py owns the candidate-card
shape reused by reviser/schema.py. Stage schemas own Localizer/Linker validation.
stages.py retains calls/persistence/candidate-bank construction. Chinese mirrors remain flat, one Markdown file per stage with Prompt and Schema explanations. Prompt strings and output contracts unchanged.

2026-09-29: Removed global/prompts/schema.py and its Chinese mirror. Stage schemas
use direct JSON Schema dictionaries; Reviser imports Generator build_schema for their
identical candidate contract. Validation behavior and model-visible schemas unchanged.

2026-09-29: chinese_prompts/ restored to a flat reading layout: common.md,
localizer.md, linker.md, reviser.md, generator.md, __init__.md and README.md.
Each stage file includes its Schema explanation; no per-stage Chinese subdirectories.

2026-09-29: Localizer Analysis Instructions now follows the SkillAdaptor sequence
(chain, primary fault, obvious patterns, concise improvement, answer requirement),
with joint input/trajectory/final-answer/GT assessment. Four hypothetical examples
explicitly include all inputs, actions/results, final answer and GT; skip still distinguishes
answer mismatch from actionable decision fault. Schema unchanged; Chinese mirror updated.

2026-09-29: Current Localizer paired retest completed at outputs/analysis/20260929_localizer_current36/.
Same36 historical Train trajectories/model config as diverse36; current frozen source.
36 first-pass valid, no failures, 179161 tokens. Wrong located25/skip3, correct skip8;
7 descending fault chains vs prior5. Mixed qualitative changes; no localization accuracy
or causal gain claim. Multiple prompt changes and temperature1 single draws confound attribution.
No Actor/Judge/Gate/Test/downstream calls. Report: analysis/skill_evolution/localizer_current36_20260929.md.

2026-09-29: Localizer fault_type now includes action_execution_error. Specific public
execution defects are separated from request defects; located chains contain subsequent
editable mishandling, while skip records defects without an actionable decision. GT mismatch
alone does not establish this category. Four-field JSON unchanged; six complete examples.
Trainer already routes by status, and fault dedup preserves category; no new downstream route.

2026-09-29: action_execution_error Localizer retest completed, same36 Train traces
and GLM config as current36, at outputs/analysis/20260929_localizer_execution36/.
36 first-pass valid, no failed stages; 216744 tokens. New category used7 times
(located4/skip3), wrong located26/skip2, all8 correct controls skip. Four descending
chains vs prior7; BU41/CC543 category contradicts uncertainty in reason. No localization
GT or general improvement claim. No Actor/Judge/Gate/Test/downstream experiment calls.
18 CPU tests pass including category/status routing. Report:
analysis/skill_evolution/localizer_execution36_20260929.md.

2026-09-29: FaultMatcher diagnostic on execution36 located results completed at
outputs/analysis/20260929_fault_dedup26/: 26 inputs, threshold .85 retains23, duplicates3.
One local qwen3_embedding_8b call (4096 dimensions,9053 tokens), no LLM/Actor/Judge/Gate.
MSR501→MSR339 may merge distinct gaps; reverse order retains24. Algorithm unchanged.
flow.md now documents literal last1200-character execution JSON, first chain entry,
first qualifying retained representative and no evidence merge. Report:
analysis/skill_evolution/fault_dedup26_20260929.md.

2026-09-29: Fault embedding representation comparison completed on same26 faults:
current JSON tail1200 retains23; same-step semantic head150 retains18 (14 answer steps
have no observation, causing overmerge); previous-observation semantic head150 retains25.
One52-input local embedding call,5743 tokens; baseline vectors reused, no LLM/Gate.
No algorithm change; these are explicit SkillAdaptor-style mappings, not original adapter replay.
Report: analysis/skill_evolution/fault_embedding_compare_20260929.md.

2026-09-29：完成26条真实定位的聚类探索，新增156条embedding输入，无生成式LLM调用。助手预设主方法参考分组（非官方故障GT）上，原则/理由相似度0.75/0.25加权、阈值0.75、complete-link候选得到19组，配对TP8/FP0/FN5；当前实现23组、TP2/FP2/FN11。参数在同批样例上选择，未独立验证，正式算法未修改。详见 `analysis/skill_evolution/fault_cluster_explore_20260929.md`；完整输入、向量和探索脚本在 `outputs/analysis/20260929_fault_cluster_explore/`。

2026-09-29：补测题目/action与定位分析的9种文本（234条embedding、72,947tokens），共240项表示/阈值配置；未超过前轮原则/理由融合的样本内配对F1。分析区分故障去重与最终Skill边界，多故障可共享完整解题方法，不能按簇数生成卡。未修改正式算法、未生成Skill或运行Gate。报告：`analysis/skill_evolution/fault_action_question_20260929.md`。

2026-09-30：完成故障分组稳定性实验（190条新embedding、18,363tokens），固定0.75融合方案，历史定位版本及44单故障项、各阈值100次排列/子集诊断。推荐整轨迹原则/理由双向量、complete-link0.75、保留全成员、Linker确认共同目标；正式实现未改，组输入Linker/Gate尚未验证。方案：`analysis/skill_evolution/fault_grouping_plan_20260930.md`；实验：`outputs/analysis/20260930_fault_stability/`。

2026-09-30：正式Global流程替换故障去重：整链principles/完整reason双向量权重0.75/0.25，SciPy complete-link默认0.75，稳定ID与均值代表、完整成员保留。faults.json为groups/skipped；Linker新增supported_faults（案例+库版本+步骤引用）并接收组证据，生成/审查同样接收。新库接受后刷新待处理案例；每案例每轮尝试上限为初始链长度，拒绝不丢弃其他成员。旧实验使用冻结源码恢复，不兼容旧stage响应。SciPy已列requirements；中文镜像同步。

2026-09-30：按用户要求，Linker移除GlobalAgent/VideoAgent架构叙述，加入action_execution_error责任边界，输出仅attributions[{skill_id,weight,reason}]，Schema约束候选ID/0–1权重/唯一ID。删除supported_faults。按SkillAdaptor原版0.55阈值和skill_wrong最高分/注入回退分支处理多个候选，reasoning_wrong沿原版默认可生成；用户明确action_execution_error低归因交Generator。空候选不调用Linker模型。候选目录增加operation_M，接受后刷新剩余任务，完整Gate规则不变。中文镜像、配置及flow同步；旧响应不兼容。

2026-09-30：按用户重申契约，answer 改为无参数决策（parameters={}），Runtime普通answer同样调用独立回答器、自动传问题与History，答案为执行输出；上限finalizer仍保留。Selector/离线background/中文镜像同步。Global轨迹展示answer()与output，历史parameters.answer仅作为旧记录输出解释。Linker专用分层渲染，当前轨迹只出现一次；去掉Source bank/Fault ref/重复Available evidence，Skill使用只依据Injected确认，Unknown不推断为无。此Runtime行为与冻结旧baseline不同，未重跑benchmark；对照新收益需匹配新baseline。

2026-09-30：Linker移除独立Output段，答案保留于最后answer()执行输出；Global步骤渲染不再展示逐步skills，案例层面的Used skills保留一次。仅调整离线展示，不改变选择范围和原始记录。中文镜像同步。


2026-09-30 Reviser input rendering: reuse Linker public Current/Related case sections;
target Skill appears once with ID and three text fields (Role/Stages omitted from this
display); attribution and rejected candidates have explicit sections.
Recent failure history excludes the current sample+bank, retains the latest three other
records with original input, localization and full action parameters, and omits nested
execution/group copies. Trainer persists input with each revision-history record.
Recorded failure_count includes the current attempt and is not a confirmed-defect count.
Generator also reuses Linker case/localization rendering, followed by generation task,
rejected candidates, existing Skills and card length limit.

Linker/Reviser Skill displays use bold field labels and trim outer field whitespace;
fields are separated by a single newline, including before Worked example.

Reviser now returns update_mode (revise_existing/skip), target_skill_id, revision_summary,
and skill_profile (three content fields or null). Its separate schema pins the target ID;
Stages inherits target metadata and converts the response to the internal candidate/skip
representation. Persisted stage results retain the model's revision format. No legacy
status/card/reason Reviser response is accepted; Generator directly returns id and three content fields; the program marks it as a candidate; it has no model-selected skip. Existing downstream candidate checks remain active.

Generator model output is a flat object with id and three content fields, without card or meta nesting. Generator proposal conversion supplies
role=global and stages=[initial, evidence] before candidate validation; model-supplied
role/stages are rejected by Schema. Stored model responses retain the flat object; the program constructs bank-format meta.

Generator has neither status nor reason output fields; Schema rejects either as an extra property.
Reviser retains revision_summary.

Reviser and Generator share CARD_CONTRACT from global/prompts/common.py, documenting
whole-question Skill purpose, selection/execution field boundaries and writing rules.
For these two stages System is TASK + BACKGROUND + CARD_CONTRACT + CARD_EXAMPLE; User contains
case evidence, stage guidance/examples and output instructions without repeating the
card specification. Other stages keep TASK + BACKGROUND. Its Chinese mirror is in
chinese_prompts/common.md; stage mirrors link to it.

Skill authoring prompts require numbered steps with
one concise numbered strategy step per line, encoded as JSON \n escapes.
Reviser/Generator examples have no candidate type label; internal candidate
status remains an implementation detail.

Proposal length control: validate each generated/revised card directly against
max_card_chars. Oversized cards fail stage validation; the response and errors are
persisted and replayed without another model call. No length-specific rewrite stage
or per-draft field budget remains. Shared model JSON-format repair is unchanged.

Current card authoring (updated 2026-10-02): common.py owns the action/parameter guidance
contract and one complete hypothetical four-field CARD_EXAMPLE. Strategy separates
task constraints alongside concise numbered steps specifying
observable conditions, actions, parameter/instruction rules and answer readiness.
Short conditional guidance is encouraged; exhaustive decision trees and step jumps
are avoided. The Agent applies the guidance to actual evidence. worked_example uses
Hypothetical question:, Videos: and ordered Step N — Action:/Result: pairs, ending
with answer(parameters={}) and its result. It retains decisive public evidence and
parameter dependencies while omitting private traces and full logs. Reviser completes acquisition
guidance for old recovery-only cards while retaining supported rules. Stage prompts
and Chinese mirrors follow the same format. Output schemas and length limits are
unchanged. Shared example and prompt assembly are covered by focused CPU tests.

2026-09-30 research-informed authoring: CARD_CONTRACT distinguishes input-time
applicability from report-dependent evidence needs, and asks each action item for
purpose, parameters, parameter sources and requested evidence. Small task-specific
constraints remain alongside flexible Agent scheduling. CARD_EXAMPLE derives joint
clips from a reported event interval rather than a universal fixed window. Generator
checks method novelty and nearby-task applicability; Reviser preserves useful rules
while removing generic repetition. Chinese mirrors updated;29 focused CPU tests pass.

2026-10-01: Removed the independent LLM content-review stage, its prompts/schemas and content-rejection branch. Valid nonduplicate candidates proceed directly to the full Gate; acceptance still requires strictly positive overall score gain. Frozen historical runs remain unchanged.

2026-10-01: Linker only attributes the one Skill verified across all ordinary decisions of a question. No-Skill cases bypass the LLM Linker and generate directly. Missing or inconsistent usage aborts; runtime finalizers are excluded. Removed attribution-card retrieval and multi-target repair; weight>=0.55 revises, skill_wrong falls back to the used card, other cases generate.

2026-10-01: Linker now returns flat {status: revise|generate, reason}. Removed responsibility weights, attribution_weight_threshold configuration and skill_wrong forced-revision fallback. Program binds the question Skill for revise; no-Skill bypass returns generate. Reviser context contains Revision reason without weights. Historical frozen runs/reference documentation preserve their original contracts.

2026-10-01: Linker input is one used_skill object, not a candidate catalog. Its rendered context shows Input, Skill Used for This Question, Trajectory, Ground truth, Localization and Related Cases at level 2. Train cases retain the verified used-card snapshot; related evidence is labelled by actual card ID/content equality, not bank equality. Only same-version cases directly support current-card defect analysis.

2026-10-01: Localizer now outputs only status/reason/fault_chain at the top level. Each chain entry independently classifies action_selection_error, action_parameter_error or action_execution_error. Schema restricts parameter faults to actual analyze_videos/watch_videos steps, excludes runtime finalizers, and validation rejects duplicate steps. An ordinary answer with sufficient History but a contradictory result is an execution fault, not an answer-parameter fault. Execution faults require feasible public action/evidence improvements to locate; otherwise skip explains them. Trainer and related-case contexts consume each entry type; grouping remains whole-chain principle/reason embeddings. Old Skill-based categories and top-level fault_type are removed without compatibility.

2026-10-01: Shared Global evolution BACKGROUND now specifies pre-call History, concurrent analyze_videos instruction boundaries, private per-video state, and question/Skill/report/GT evidence roles. Localizer prompts separate each step's decision basis, action and returned result, require step/action alignment and verifiable task-relevant execution defects, and derive reusable corrections from runtime-available evidence. Event timestamps alone do not establish observation coverage. Prompt examples and Chinese mirrors are synchronized; output Schema and routing are unchanged.

2026-10-01: Localizer TASK now documents the exact rendered sections Input, selected skill, steps, output and ground truth. It defines selection as the selector's best-fit judgment or no suitable card, explains trajectories with and without Skill guidance, and separates action correctness from Skill compliance. The Chinese mirror is synchronized; rendering and output Schema are unchanged.

2026-10-01: Localizer selected-skill rendering now uses the shared four-field card renderer and omits all Meta fields (id/role/stages); internal provenance is retained. Missing selected-card content remains explicit. User requests Localizer quality conclusions from actual no-Skill trajectories only; distinguish empty selections in bank-enabled runs from injected-Skill cases.

2026-10-01: Localizer prompt refinement after the 45-case no-Skill diagnostic adds explicit task-form/quantifier/inference checks, task-relative answer sufficiency, direct step-specific execution evidence, coarse-to-fine request assessment, and feasible condition/action/evidence repair principles. Four examples are replaced with overview/refinement, explicit label confusion, suspicious timestamp and uncertain prediction contrasts; eight examples total, Schema unchanged. Chinese mirror synchronized.

2026-10-01: DeepSeek ApiLLM now emits model_response with returned model, request ID, finish reason, usage and final text via the existing event scope. Credentials and reasoning_content are excluded. This enables per-call cost estimation for optimizer experiments without changing request payloads.

2026-10-01: Input-only question clustering diagnostic is authorized separately from
production fault grouping. `scripts/analysis/probe_question_embedding_clusters.py`
uses existing Qwen3-Embedding-8B on8110, samples at most20 per native category
(seed20261001) from CrossVid Lite2500, CVBench1000 and MVU-Eval1824, covering all
three benchmarks. The full preparation was stopped before embedding at the user's
request to reduce sample size. Question/options and optional runtime-local video IDs/durations are the
only encoded fields; benchmark categories are external evaluation labels, never
embedding inputs. Source-overlap exclusion is a nearest-neighbor diagnostic, not
proof of whole-film isolation. Artifacts under
`outputs/analysis/20261001_question_embedding_clusters_small/` freeze inputs/code and cache
batches. No LLM optimizer, QA inference, API Judge, Gate or runtime change. The formal
whole-chain fault grouping remains unchanged pending this diagnostic's results.

2026-10-01: The input-only embedding diagnostic completed660 questions (CrossVid200,
CVBench300, MVU-Eval160;33 categories x20). Metadata-input top8 same-category rates
are93.50%/43.88%/70.94%; these are similarity diagnostics, not QA accuracy. The old0.75
threshold severely fragments CVBench; lower-threshold exploratory results do not
establish a deployable threshold. Video durations have no consistent benefit versus
question/options only, and category agreement does not prove shared-Skill efficacy.
Report: `analysis/skill_evolution/question_embedding_clusters_20261001.md`. Initial
and extended threshold metrics, all assignments, embeddings, frozen source, usage
and independent pair-enumeration validation are retained in the small diagnostic
root. No production grouping or selector changes were made.

2026-10-01: Cross-benchmark extension of the input embedding diagnostic reuses all
saved660 vectors/cluster assignments without model calls. Entry:
`scripts/analysis/audit_cross_benchmark_question_clusters.py`.179 input-read broad
strategy references (counting/order/difference/gap completion) are exploratory
assessment labels only; unannotated questions remain unknown. Question/options-only
at0.50 produced a37-question shared ordering group (CrossVid PSS20/CVBench9/MVU TR8).
Adding video IDs/durations broke the CrossVid link despite all160 PSS/MVU-order
pair similarities remaining>=0.60; complete-link group composition also matters.
Do not equate native benchmark labels with cross-benchmark strategy truth or claim
shared-Skill effectiveness. Report extension and `cross_benchmark/` artifacts under
the existing small diagnostic root retain references, affinities, mixed groups,
source, full cross-neighbors and independently checked pair counts. Formal runtime
selection/evolution grouping remain unchanged.

2026-10-01: Question-material grouping validation completed under
`outputs/analysis/20261001_question_grouping_validation/`.12 representations x45
configs were chosen on330 development questions and confirmed on330 held-out IDs;
49 known source groups cross that ID split, so it is not independent Test. A
separate known-source-disjoint335-question stress split and five fixed-config seed
checks are diagnostic only. Local overlapping k16/.65 pools with strategy embedding
instruction+structural summary outperform complete/.75; normalized-input cross-family
F1 is61.10%, but preserving FULL runtime question contexts reduces it to44.97%
(source stress37.10%). Do not strip task-specific question preambles in an implementation.
Full660 yields519 overlapping groups; collect materials around actual failures rather
than generate one card per group. No formal grouping/selector change is deployed.

Actual pipeline tests used existing no-Skill Localizer traces,7 GLM Generator calls
and374 local Selector calls (zero Selector call/schema errors). All7 formal candidates
exceeded2400 characters (3263–3704); none passed candidate validation or reachedGate.
Explicit shadow banks of these rejected drafts were used for selection ONLY. MMR
selected three-benchmark ordering examples without benchmark labels, yet the draft
still restricted applicability to cooking/arrow-format and selected onlyCrossVid10/10,
CVBench0/8 andMVU0/3. Do not claim complete evolution feasibility or QA gain. Existing
first-selection records can help material affinity but hard same-card buckets mix
strategies; reference-subset bonus tests are exploratory, not adopted weights.
Report: `analysis/skill_evolution/question_grouping_validation_20261001.md`.
Entries: `scripts/analysis/test_question_grouping_methods.py` and
`test_grouped_skill_pipeline.py`; source/configs/inputs, metadata/query text, vector
batches, split audits, development/fixed-confirm metrics, stage responses/usage,
strict validation failures and shadow selection provenance are retained. GPU2–7
services were verified/reused, never replaced; no QA/APIJudge/service installs.

The question-graph diagnostic imports NetworkX3.6.1, already present in the current
Torch environment; it is now an explicit requirements.txt dependency. No packages
were installed/upgraded. The optional Louvain comparison is diagnostic-only.

2026-10-01: User authorized no-fixed-K/cross-batch grouping tests. Entry
`scripts/analysis/test_no_k_cross_batch.py`; protocol
`analysis/skill_evolution/no_k_cross_batch_protocol_20261001.md`; artifacts
`outputs/analysis/20261001_no_k_cross_batch/`. It reuses660 FULL-input cached vectors,
selects81 HDBSCAN/DBSCAN/average/Louvain/local-neighborhood configs on original330 dev
IDs, then freezes choices for confirm/source stress and135 sequential-arrival checks
(3 seeds x3 schedules x3 batch sizes x5 methods). Accumulated refits compare with
frozen batch-local groups; noise remains independent singletons. This is input-only
arrival simulation, not a deployed cross-batch trajectory store or Skill/QA validation.
Exploratory labels/shared-source limits remain. No model/Gate/Judge calls or production
changes. The detached frozen controller writes atomic status/results, records ETA,
and holds a process lock; inspect saved status and resume only after owner exit.
scikit-learn1.7.2 is added to requirements; it and joblib1.5.2/threadpoolctl3.6.0 were
installed ONLY into the experiment's isolated system-site-packages venv, not resident
service environments. Source/inputs/vectors are hash-frozen; no prompt changes.
The no-fixed-K diagnostic completed in37.78 seconds:81 dev configs,15 static checks,
135 sequence runs; validation.json passed. Detailed quality analysis is deferred to
user's next request. No Skill effectiveness or QA gain conclusion is established.
2026-10-01: No-fixed-K result analysis is appended to
`analysis/skill_evolution/no_k_cross_batch_protocol_20261001.md`;
`analysis_results.json` and its independent pair-enumeration script remain under the
experiment root. Confirm cross-family pair F1: Louvain59.10%, neighborhood52.72%,
average44.05%, HDBSCAN39.03%, DBSCAN30.84%; source stress changes rankings, with
neighborhood48.25%/Louvain37.53%. Full660 graph/DBSCAN have271/405-member mixed groups,
HDBSCAN341 noise points. Accumulated batches outperform frozen batch-local grouping,
but this is input-arrival simulation, not real trajectory/Skill efficacy evidence.
No unique algorithm or production change is adopted; coarse grouping plus anchored
material retrieval is a proposed next validation path, not deployed behavior.

2026-10-01: User requested a controlled embedding-input replacement: preserve FULL
question/options plus each runtime-local video_id paired with duration_sec, remove
video/option count and min/max/mean/ordered-duration summary fields. The fixed
strategy embedding instruction is retained. Entry `test_no_k_cross_batch.py launch
--representation video_id_duration`; output
`outputs/analysis/20261001_video_id_duration_clusters/`. Reuses the same660 rows,
partitions,81 dev-only configs and135 sequential tests, with additional15 static
checks using previous fixed specs to isolate input changes from parameter retuning.
Existing frozen diagnostic inputs/code remain untouched. New embedding uses verified
Qwen3-Embedding-8B8110; no optimizer/selector/QA/Judge or production changes. The
existing isolated sklearn environment is reused; no new package/service changes.
Chinese documentation mirror records the diagnostic input template.
The video_id-duration replacement diagnostic completed:21 embedding requests/660
texts/114913 input tokens,81 dev configs,30 static checks,135 sequences; controller
39.83s, validation passed. Confirm cross-family F1 after dev-only reselection:
Louvain52.68%, neighborhood51.14%, average42.19%, DBSCAN32.81%, HDBSCAN32.32%.
Most confirm scores decrease versus summary input; old-fixed-spec source Louvain
improves while confirm decreases, so no consistent advantage is established.
This simultaneously adds local IDs and removes statistics; do not attribute effects
separately. New input and existing instruction are mirrored in the Chinese reference;
no production deployment or actual trajectory-pool/Skill/QA validation. Results are
appended to `no_k_cross_batch_protocol_20261001.md`, with input_comparison.json and
analysis_results.json under the new artifact root.

2026-10-01: Global flow.md and its README are rewritten against current Trainer,
Stages, evidence rendering and stage Schemas. They document actual one-card Linker,
flat Generator vs full-profile Reviser outputs, program-vs-model input boundaries,
complete-link current-round grouping, initial-chain attempt budget with refresh after
acceptance, exact-only duplicate checks, strict full-Gate aggregate acceptance and
round-level recovery. Input-only Louvain, cross-batch trajectory material storage and
noise filtering remain explicitly pending integration; no production implementation
or model-visible Prompt/Schema changes were made in this documentation work.

2026-10-02: Global common.py BACKGROUND now states analyze_videos' instruction-focused
per-video text compression and watch_videos' direct joint-clip visual comparison,
textual retained result, clip/sampling/perception and correspondence limits.
CARD_CONTRACT guides Generator/Reviser action choice by task evidence granularity,
explicit report criteria, fine visual comparison and localization-then-watch or
initial watch when ranges are known. It does not mandate watch for every comparison
or treat joint viewing as guaranteed coverage/correctness. Chinese common.md and
flow.md are synchronized; action parameters, Schemas and acceptance remain unchanged.

2026-10-02: User authorized GLM-5.3-Flash Localizer selected-skill visibility A/B.
Entry `scripts/analysis/test_localizer_skill_visibility.py`; summarizer
`scripts/analysis/analyze_localizer_skill_visibility.py`; output
`outputs/analysis/20261002_localizer_skill_visibility/`.16 frozen real CrossVid
trajectories (13 distinct question IDs),7 actually using Skill and9 with none,
including4 correct-answer controls;2 arms x2 repeats=64 fresh calls,4 workers.
without_skill removes the selected-card section and all corresponding TASK/rule/
example/BACKGROUND guidance wording, preserving original question/action/results/
GT and action information boundaries. Natural question/report 'dance skills' stays.
No production Prompt/Schema or Runtime changes; experimental Chinese changes are
recorded in chinese_prompts/localizer.md. Frozen inputs/source/config and model/event
usage persist; requests use env credentials without storing keys/reasoning_content.
Inspect saved status; long controller is detached. Agreement/validity is not quality,
repeat temperature1 variability must be compared. Completed64/64 without errors;
qualitative review/report live in the same output root. Repeat chain agreement is
14/16 with Skill versus9/16 without; located21/32 versus16/32. These are not accuracy.
Review found both Skill-compliance bias and unsupported skips after ablation; no
validated production improvement. Review labels were shuffled, but textual Skill
references can reveal arms; no strict blindness or human localization gold standard.
Summarizer counts usage from model_response events; rerunning resets its pending
review flag, while saved evidence_review.json/report.md remain available.
No Actor/Judge/Gate calls, no independent Test or evolution effectiveness claim.

2026-10-02: Localizer FAULT_TYPES now includes task-derived pre-skip checks for
output/options/quantifiers, explicit report-scope gaps, event/function definitions
and feasible candidate verification. It separates insufficient-evidence answer
selection from sufficient-evidence answer execution, preserves prediction/GT
boundaries and avoids inferring hidden coverage from sparse timestamps or adding
same-scene counts across views. Chinese localizer.md is synchronized. Production
selected-card input remains unchanged. A fresh no-skill old/revised comparison uses
`test_localizer_skill_visibility.py --baseline-without-skill` pointing to the frozen
visibility run, with identical16 cases/schema,2 repeats/arm,64 calls and4 workers.
Output `outputs/analysis/20261002_localizer_task_checks/`; both arms exclude selected
Skill, historical responses are not reused. Summarizer reads protocol arm names.
This is a targeted development retest, not independent quality confirmation; inspect
saved status and use the frozen controller for resume. No Actor/Judge/Gate calls.

2026-10-02 Localizer task-check retest completed64/64, zero errors,571.52 seconds.
Fresh original/revised no-skill calls located21/32 versus24/32; repeat structural
agreement both11/16. Qualitative report/evidence_review.json in the task-check root
find candidate-omission and endpoint-check gains, but remaining GT-based hidden-event
claims, report-coverage overclaims and premise-based execution assertions. This is
non-blind single-analyst public-text review on reused development cases, not measured
localization accuracy or independent validation. Production selected Skill input
remains unchanged; no further API/Actor/Judge/Gate work launched during analysis.

2026-10-02: Localizer now distinguishes direct public defects, concrete actionable
verification needs and unexplained outcome discrepancies. An uncertain/omitted
item or premise conflict alone does not establish execution failure. Explicit
subinterval report scope does not prove hidden frame omission; endpoint ambiguity
does not prove actual partial exit or a later true time. Decision faults use only
pre-step evidence; actual retry parameter changes matter. Chinese localizer.md is
synchronized; production selected-card input and fault Schema remain unchanged.
Expanded diagnostic sampler `scripts/analysis/prepare_localizer_boundary_panel.py`
freezes16 regression traces plus72 previously untested question IDs,24 each from
CrossVid/CVBench/MVU-Eval (8 correct,16 not fully correct each), using retained35B
no-Skill records and native-task round-robin/hash selection. Input/selection archives
from prior Localizer diagnostics are excluded by question ID; media-source isolation
is not established. CrossVid closed/scored tasks only; no new API Judge. CVBench
native_task=all does not ensure fine-category coverage. Outcome strata are diagnostic,
not representative benchmark prevalence or independent Test.
Authoritative panel `outputs/analysis/20261002_localizer_boundary_panel_v2/` replaces
an unused first selection draft. Run `outputs/analysis/20261002_localizer_evidence_threshold/`
compares fresh last-revision and tightened no-skill prompts,88 cases x2 arms x2
repeats=352 GLM-5.3-Flash calls,4 workers. Both exclude selected Skill. The launcher
accepts `--inputs-json` plus `--baseline-without-skill`; source/prompts/panel sampler
and source hashes freeze for resume. Summarizer handles dynamic case counts and
reports regression/expansion and expansion benchmark subsets separately. Inspect
saved status, detach long tests, and resume only the frozen owning controller.

2026-10-02: User authorized a DeepSeek Flash repeat of the Localizer evidence-boundary
diagnostic. Launcher test_localizer_skill_visibility.py now accepts --model
(deepseek-v4-flash or glm-5.3-flash) and --prompts-from <frozen-run> for exact
matched prompts/inputs/Schemas. DeepSeek diagnostic uses api_llm, thinking enabled,
reasoning_effort high, max_tokens16384, timeout600, four workers and two repeats;
temperature/top_p are omitted by the existing provider in thinking mode, so this is
not exact cross-provider sampling equivalence. Actual returned model is recorded
in model_response events; requested name is not proof of returned identity.
Run outputs/analysis/20261002_localizer_evidence_threshold_deepseek/ reuses all88
inputs and both no-Skill arms verbatim from the GLM evidence_threshold run (352
fresh calls). Preflight compared all input/prompt/schema bytes and source hashes
and loaded runtime successfully; focused DeepSeek telemetry test passed. No
Actor/Judge/Gate calls or production Localizer changes. Preserve frozen artifacts
and inspect saved status; resume only owning controller.

2026-10-02: global/flow.md now records the agreed target flow separately from
implemented behavior: authors omit whole-bank catalogs (Reviser keeps target),
and one Merge entry runs only after batch failure processing and before commit.
Merge searches current same-stage Global card pairs using cached description/
when_to_use/strategy embeddings, checks at most one unchanged-unchecked pair per
batch, and combines compatibility judgment/generation in one call. Proposed
Merge acceptance permits zero gain only with overall and every-question Gate
nondecrease and no new per-question fatal/invalid. Create/revise strict-positive
acceptance stays unchanged. Merge, its state/cache/Schema and author input
removal are NOT implemented by this documentation update; current code still
passes catalogs and supports create/revise only. Louvain/material pool and
Localizer selected-Skill removal remain separate pending directions.

2026-10-02: Current Global Trainer replaces Localizer reason/principle complete-link
with full fixed Train-input embedding + mutual-kNN Louvain in question_groups.py.
Input is complete question/options and ordered video IDs with individual positive
finite durations plus the tested strategy embedding instruction; no derived
statistics, GT, outcomes, benchmark labels, traces or selected cards enter vectors.
Runner probes Train video metadata before trainer initialization; no video inference.
Fixed graph k32/cosine>=.55/resolution2/seed20261001; no predeclared cluster count.
Unconnected questions remain singleton/unclassified; additional noise filtering
is absent. Old fault_similarity option and FaultMatcher are removed, no migration.
question_groups.json records index/parameters/groups; embeddings/ caches input
batches. Healthy success, partial/failure, skip and invalid-localization traces enter
a Train-only pool; fatal/invalid executions are excluded and remove stale peers.
Each question contributes only its latest episode to retrieval; per-round historical
updates remain on disk. Current located failure retrieves up to4 distinct same-cluster
peers ranked by input cosine, preferring2 full-score successes and2 non-successes,
then fills available slots. Related cases show outcomes, actual final answer,
localization status, public trace/reference and card-version relationship; success
is not causal Skill evidence. Current old-bank anchor still refreshes before edits;
refreshed outcomes update the pool. round materials.json plus committed path/hash
restore the pool across batches/resume, rejecting altered files. Generator/Reviser
whole-bank catalogs are removed (Reviser retains target); rejected candidates and
revision history remain. Author/Linker guidance and Chinese mirrors synchronize.
Gate acceptance remains strict overall improvement for create/revise. Merge and
its zero-gain rule remain documentation-only; no real training launched here.

2026-10-02: DeepSeek Localizer evidence-threshold repeat completed in
outputs/analysis/20261002_localizer_evidence_threshold_deepseek/:352 planned
structured calls,351 successful,1 invalid after bounded repair,3461.71 seconds.
Actual379 model_response events all returned deepseek-flash;27 repairs,26 succeeded,
28 length-terminated responses. Failed case03 revised repeat1 had empty final
text after both16384-token responses. Inputs and original prompts/Schemas exactly
match GLM; provider schema transport/reasoning/sampling still differ. Expanded72
DeepSeek repeat chain agreement53/72→54/72; comparable revised71 cases GLM61/71
vs DeepSeek53/71. This is repeat agreement, not accuracy. report.md, comparison.json,
cross_model_comparison.json and21-case nonblind targeted evidence_review.json saved;
exhaustive quality labels remain pending. No video replay/human gold/new Judge.
No supported default model switch or selected-Skill removal concluded; production
unchanged, no new API/Actor/Gate work started during analysis.

2026-10-02: User authorized a matched DeepSeek Localizer repeat with thinking off.
Diagnostic launcher supports --no-thinking for DeepSeek only; default remains on.
Output outputs/analysis/20261002_localizer_evidence_threshold_deepseek_no_thinking/
uses the same88 inputs and176 exact frozen prompts/Schemas, two repeats/four workers
(352 calls), max_tokens16384. Non-thinking sends temperature1/top_p.95 and omits
reasoning_effort; this sampling change is recorded and limits a pure reasoning-only
comparison. Existing completed runs are untouched; no production setting, prompt,
Actor/Judge/Gate or evolution change. Frozen controller owns this detached run.

2026-10-02: DeepSeek no-thinking Localizer diagnostic completed352 calls in210.52s,
348 valid/4 invalid. Revised expansion repeat chain agreement30/71; thinking-on54/72,
GLM61/71 (denominators differ; identical-case comparison saved).20 repairs/18 succeeded;
108136 completion tokens including repairs. report.md and cross_model_comparison.json
saved; only targeted nonblind spot checks, exhaustive quality review remains pending.
No production model/thinking switch or new Actor/Judge/Gate work.

2026-10-02: User authorized DeepSeek Pro without thinking on the same Localizer
panel. Diagnostic --model now also accepts deepseek-v4-pro through existing DeepSeek
provider/credentials and --no-thinking. Detached output:
outputs/analysis/20261002_localizer_evidence_threshold_deepseek_pro_no_thinking/.
Same88 inputs,176 frozen prompts/Schemas,two repeats/four workers (352 calls),
max_tokens16384,temperature1,top_p.95; returned model recorded independently.
Production Localizer/Actor/Judge/Gate are unchanged; preserve frozen prior runs.

2026-10-02: global/flow.md target design now aggregates edits per fixed-parent
Train batch, validates once on predeclared related Gate inputs plus fixed cross-type
regression questions, then updates the working bank atomically. Epoch full Gate
checks compare to the last full-Gate-approved checkpoint; failed accumulated edits
roll back, final output must be a full-approved bank. Train batch scores cannot
replace independent validation. Merge stays a single batch-end proposal entry,
included in the same candidate validation; pure Merge permits zero gain with
per-question no loss. New local/epoch gates require no new fatal/invalid; create/
revise need strict aggregate gain. All batch aggregation/local Gate/epoch/rollback/
Merge changes remain documentation-only; current Trainer still uses per-candidate
full Gate with refresh. Local selection quotas/thresholds/configs are not implemented.

2026-10-02: global/flow.md clarifies that batch acceptance measures independent
local Gate improvement, not the authoring Train batch score. The planned frozen
Gate mapping uses cosine against normalized Train cluster mean embeddings,
stable tie-breaking, predeclared similarity/minimum-size rules and input-only
neighbor supplementation; insufficient coverage falls back to full Gate.
Only clusters supplying valid batch edits contribute related validation IDs.
This mapping and batch acceptance remain design-only; no Trainer or Prompt change.

2026-10-02: After replenishing API balance, user authorized a fresh full DeepSeek
Pro no-thinking Localizer repeat. Detached frozen controller PID2372662 owns
outputs/analysis/20261002_localizer_evidence_threshold_deepseek_pro_no_thinking_retry1/.
Same88 inputs and176 exact frozen prompts/Schemas,352 fresh calls,four workers,
max_tokens16384,temperature1,top_p.95. Prior balance-failed run remains intact;
check saved status before analysis. Production and Actor/Judge/Gate unchanged.

2026-10-02: global/flow.md is now a concise sequential prose specification matching
the supplied reference format, replacing its expanded sections/tables/diagram.
It retains the planned fixed-parent batch update, frozen embedding local Gate,
regression checks and full-Gate checkpoints; implementation status is unchanged.

2026-10-02: global/flow.md now follows the supplied reference paragraph order
and wording, retaining random Train batch sampling rather than defining epoch
traversal. Full Gate checkpoint cadence is predeclared by training stage; its
configuration and all planned batch/local validation changes remain unimplemented.

2026-10-02: DeepSeek Pro no-thinking retry1 completed352 calls in385.43s:
339 valid,13 invalid; no balance failure. Saved comparison.json and
cross_model_comparison.json provide structural repeat statistics; agreement is
not localization accuracy. Exhaustive quality review remains pending; production
Localizer/Actor/Judge/Gate unchanged. Prior balance-failed run retained.

2026-10-02 clarification: global/flow.md retains a detailed operational design
with module contracts, frozen local Gate mapping, batch acceptance, full-checkpoint
rollback and recovery requirements. Only its short explanation follows the supplied
reference prose style; this supersedes the preceding format-only simplification.
All proposed runtime/trainer changes remain unimplemented.

2026-10-02: Localizer quality review saved at
outputs/analysis/20261002_localizer_grounded_quality_review/ (report.txt,
evidence_review.json, case_review.txt, validation.json, full case dossiers).
Reviewed20 targeted trajectories (19 unique question IDs,5 correct-answer controls),
four identical-input/prompt model settings,two revised-arm repeats:160 planned
outputs,155 valid/5 invalid. Single-assistant nonblind public-text review, not
independent gold or full88-case accuracy; no video replay or new API/Actor/Judge/Gate.
Concrete supported faults,missed roots,unsupported attribution and harmful correction
examples are recorded, with separate45-panel high/low evidence. GLM Flash high has
useful grounded diagnoses but direct-contract misses; DeepSeek Flash high catches
some misses but can oververify; Pro no-thinking has documented arithmetic/option/
trajectory reading errors. No universal quality ranking,production switch,Prompt
change or proven downstream Skill benefit is concluded.

2026-10-02 Generator structured-card diagnostic: user-authorized GLM-5.3-Flash test
completed 12 fresh Generator calls on real historical no-Skill CrossVid Train cases
across nine tasks. Current projector, Train383 input-only Louvain grouping, healthy
scored material pool343, related-case selection and Stages.generate were used;
Localizer outputs were reused, not rerun. Frozen source/config/input and all raw
responses: outputs/analysis/20261002_generator_structured12/; report.txt and
generated_skills_readable.txt contain results and full cards. All12 matched JSON
Schema and the two-section strategy/Action-Result layout, but all exceeded the
2400-character total (3025–4822), so zero candidates passed validation. Manual review
found chronology, answer-consistency and selection-boundary defects. No Actor/Gate,
Prompt repair, deployment or old/new paired comparison; this is generation-quality
development evidence, not benchmark gain. Actual returned model: glm-5.3-flash.

2026-10-02 question clustering audit: replayed the current input-only Train383
Louvain grouping from the Generator diagnostic's frozen embedding cache. All383
questions are exported with full input/video metadata and cluster IDs under
outputs/analysis/20261002_question_cluster_audit383/ (report.txt, questions.csv,
all_questions_by_cluster.txt). Eleven clusters; exact replay and ten additional
Louvain seeds agree. Native-task purity99.48%/ARI0.9825 are descriptive proxies,
not Skill-method accuracy; traffic count variants remain mixed. No new model calls,
parameter tuning, production change, or downstream efficacy evaluation.

2026-10-02 cross-benchmark clustering diagnostic added frozen CVBench300 (15x20)
and MVU-Eval160 (8x20) to CrossVid Train383. Current input template and exact
cached vectors were verified; current Louvain rebuilt all843 inputs with unchanged
parameters and no new model calls. Outputs: outputs/analysis/20261002_cross_benchmark_clusters843/.
42 clusters include22 singleton isolates,11 mixed-benchmark clusters (539 questions),
4 spanning all three. Manual input-only review finds shared action-intersection,
odd-one-out and ordering methods, but count-unit/topic overmerges and missed ordering
links remain. Prior coarse-family proxy covers only99 questions and is not exact
Skill-method accuracy. New samples include old exploratory dev+confirm identities;
no independent Test or training split change, no Actor/Gate or transfer-gain claim.

2026-10-03 Global directory split: all former global/ content moved into global/adaptor/,
then copied into global/cluster/ excluding generated bytecode. Existing
global-skilladaptor-v1 runner and live diagnostics import global.adaptor; no old-path
re-export/fallback remains. global/cluster is an independent development copy with
baseline algorithm code, not an implemented SkillOpt cluster optimizer or registered
training algorithm. Each variant owns its prompts, schemas, Chinese mirrors and
reference materials. Historical output snapshots remain unchanged; resume uses the
owning frozen source. Input-only clustering validation does not establish one
universally effective Skill per cluster. See global/README.md for current paths.

2026-10-03 cluster implementation supersedes the earlier development-copy status:
`global-cluster-v1` is registered alongside adaptor; recipe global_cluster_35b.yaml.
Fixed Train-only embedding/Louvain; one initially empty Global card slot per cluster,
Video frozen. rounds=epochs, batch_size=within-cluster batch, patience=consecutive
nonaccepted batches per cluster. Train runs only the slot card plus Video cards with
normal task-scoped selection (abstention allowed); full-bank Gate uses normal selection.
Healthy public success/failure batches feed reflect then unchanged generator/reviser;
common and author Schemas remain unchanged. No Localizer/Linker, slow/meta or local Gate.
Only strict full official aggregate improvement accepts. Gate details never enter
optimizer; rejected cards carry status only. Initial Global cards rejected; --resume
restores accepted slot bindings through cluster_evolution/state.json batch commits.
Stage replay and whole-bank rollout caches persist; operational errors propagate.
Artifacts: batches/, question_groups.json, cluster_slots.json, final_bank.json.
Chinese mirrors include reflect.md and evidence.md. Tests: test_global_cluster.py.
This is a simplified SkillOpt-inspired variant, not the original patch-budget algorithm.

2026-10-03 cluster engineering validation: 45 affected CPU tests passed. Fresh
8 Train (BU11/123/14/94, PSS122/132/153/617) +2 Gate (BU110/PSS1) inherited
original Train/Eval memberships; current embedding/Louvain yields2 four-question
clusters. Qwen3.5-35B-A3B verified existing GPU4–7 pool, GLM-5.3-Flash optimizer,
no API Judge or service deployment. Default2400 run completed with2 oversized
cards (4247/3464 chars), zero candidates reaching Gate. Separate6000-cap two-epoch
engineering run evaluated4 candidates, all Gate ties (0.5), none accepted;
default recipe remains2400. Actual full-body injection verified for each candidate's
matching Gate task; no missing injection records. Accepted/reviser branches are
CPU fixture coverage, not observed real gains. Tiny Gate is not independent Test.
Artifacts: outputs/analysis/20261003_cluster_smoke/ and
outputs/analysis/20261003_cluster_smoke_cap6000/. Latter reuses exact no-Skill
rollout identities, runs fresh candidate-bank questions; report.txt in first root.

2026-10-03 length update: user requested all Skill caps5000. Runtime
MAX_SKILL_CHARS=5000 (four text fields and rendered body); adaptor/cluster and
shared candidate defaults use that constant. Recipe max_card_chars/max_skill_chars
values updated to5000; frozen experiment files unchanged. description600 and
when_to_use1200 remain; action answer length unchanged. Historical2400/6000
reports are not current defaults. Cluster optional training.cluster_anchor selects
one existing Train cluster after clustering ALL Train, not reclustering a subset;
unknown anchor raises. training_scope.json records optimized IDs, summary includes
optimized_clusters. New test targets the prior40-question PSS cluster with20 original
PSS Eval questions as Gate; all383 Train inputs retained for grouping only.

Expanded cluster run launched under outputs/analysis/20261003_cluster_pss40_gate20/:
original383 Train grouping reproduces11 groups and the exact prior40 PSS members;
20 original PSS Eval questions form the development Gate. rounds1/batch8/patience10,
cluster_anchor=crossvid:PSS:122, empty initial Global/Video, GLM-5.3-Flash,
verified existing GPU4–7 pool. Detached controller owns the run; check status.json.
66 affected CPU checks and97 shipped card validations passed under5000. No service
replacement, private traces or Gate details are added to optimizer inputs.

### 2026-10-03 Skill word budget

当前 Skill 长度规则：四个文本字段合计最多 **1200 words**，description和when_to_use无独立硬上限；渲染正文（含标题）最多1200 words。统一由 `count_words` 统计字母/数字/下划线组成的词，词内撇号和连字符不拆分，独立标点不计数；cat、analyze_videos、segment_1 各计1 word，1->2 计2 words。这是英文词计数，不是 tokenizer 或中文分词。Prompt 要求简洁英文，通常900–1100 words或更少，上限不是写作目标。配置改为 max_card_words/max_skill_words；旧字符配置不再支持。JSON Schema 仅保留非空和结构检查，单词上限由程序统一校验。冻结实验仍保留原字符口径，不能混用新源码恢复。

2026-10-03 multi-cluster word-budget expansion: user authorized a fresh empty-bank
run across all closed-task Train clusters, followed automatically by paired empty/full-bank
heldout evaluation and selection/injection audit. Control root:
`outputs/analysis/20261003_cluster_multigroup_words1200/`.
Source-group-preserving Gate/holdout partition is frozen before rollout; original
CrossVid383 Train minus40 CCQA leaves343 Train across9 closed tasks. No API Judge.
Historical development examples are not independent Test, even when stored under
split=test for this run. One epoch, batch16, patience3 per cluster,1200-word cards,
GLM-5.3-Flash optimizer, existing verified GPU4–7 Actor pool; no service replacement.
The current one-slot-per-cluster Train algorithm is unchanged; Gate/holdout select
from the full bank naturally. Detached controller sequentially trains then evaluates
both heldout arms using one frozen source snapshot; check saved status, do not poll.
Evaluation mode now writes routing_audit.json through the existing routing_audit:
actual full-body injection, selected IDs and action parameters. These are observed
exposure records, not automatic semantic applicability/compliance or causal proof.

2026-10-03 user stopped the multi-cluster experiment early to prioritize selector
attribution. Owning trainer received SIGINT; controller/workers exited, resident
services untouched. Checkpoint and partial batch/cache artifacts remain preserved;
status.json says stopped, not completed. New diagnostic control:
`outputs/analysis/20261003_selector_three_arm/`. Fixed two-card bank
b7844886531c91812da94f0cea4fcaf161cd56ce857104be66770dd5b49c2fe9;
71 historical heldout questions, fresh empty/normal/assigned arms. Assigned labels
were frozen from question/options and card prerequisites only, with reasons and
borderline cross-task flags; these are Codex judgments, not independent human gold.
Only its isolated source snapshot overrides Global selector return by exact question
hash via MVAGENT_DIAGNOSTIC_SELECTION; production source and Actor prompts unchanged.
All arms share that snapshot; assigned retains normal schema/rendering/task cache and
routing audit. 71 override/persistence/rendering checks plus unknown rejection and
normal selector invocation passed. No optimizer/Judge calls, no card repairs; current
card action-contract defects deliberately retained to isolate selection. Automatic
report compares official macro, task scores, assignment agreement, actual injection,
normal abstention prompt equality, and borderline-label subgroup results. Inspect
saved status rather than polling; no independent Test or optimal-selector claim.

2026-10-03 metadata-only controlled test: user authorized one frozen-body description experiment at `outputs/analysis/20261003_metadata_only/`. The owning `controller.py` creates GLM-5.3-Flash provisional input-only labels on Train71 (53 fit/18 check), proposes three description/when_to_use candidates, replays the actual frozen Selector, then evaluates fresh empty/original/candidate banks on full historical Gate90. Card meta/strategy and Runtime/Selector prompts remain fixed; no automatic library deployment. Fit selects candidates while preserving correctly selected confident positives; check is not author evidence. Labels are not human gold and Gate is development data. Same GPU4–7 model services, normal pool verification, no replacements. Source/input/protocol hashes and experiment Chinese prompt mirror are in the control root. Inspect saved status and detach; do not continuously poll.

2026-10-03 follow-up ablation: `outputs/analysis/20261003_maneuver_metadata_only/` runs fresh original and maneuver-metadata-only arms on the same historical Gate90. Only synced-maneuver-joint-confirm description/when_to_use use the previous Train-authored candidate_0; fact-eliciting-multiselect is fully restored to original and all bodies/meta remain exact. No optimizer/Judge calls or automatic deployment. This is a post-hoc development ablation selected after viewing prior Gate, not independent confirmation. Owning detached controller, frozen source/input hashes, protocol and Chinese mirror live in the root; GPU4–7 services are verified without replacement. Check saved status once and avoid continuous monitoring.

2026-10-03 independent-cluster diagnostic: user authorized isolated optimization of multiple clusters and interference analysis. Control `outputs/analysis/20261003_isolated_clusters/` freezes the prior words1200 cluster source and unchanged Actor/Selector/author prompts. Ten existing Train343 Louvain clusters run sequentially from independent empty Global/Video banks, batch8/epoch1/patience10, GLM-5.3-Flash, local fixed Gate only; PSS40/20 is scheduled first. Gate161 explicitly reuses historical Gate90 plus development holdout71 (not independent Test), assigned before rollouts by input-only cosine to normalized Train centroids. Nine substantial clusters and one tiny2-Train/3-Gate cluster (exploratory). Full343 Train inputs preserve clustering; cluster_anchor selects the one original cluster per run. After optimization, final IDs receive consistent cluster prefixes in both fresh isolated and merged confirmations, with all other fields frozen. Fresh empty/local-bank confirmations and merged-bank normal selection on the same161 questions quantify library interference using paired official task macro and routing. No automatic deployment; Gate gains are development selection outcomes. Owning detached controller and saved status are authoritative; GPU4–7 services are verified, never replaced. Source hashes, split/recipe/protocol hashes, CPU checks and Chinese experiment prompt-boundary mirror are retained in control root. Do not continuously monitor.

2026-10-04 isolated-cluster recovery: all10 independent trainings completed;5/9 substantial clusters improved their local development Gate,4 retained empty, tiny2-Train cluster retained empty. Original controller failed before confirmation because its cluster_XX- prefix violated Skill ID schema. New owning `outputs/analysis/20261003_isolated_clusters/recover.py` validates legal cXX- IDs (max64 chars), keeps all card text/role/stages identical, and resumes only fresh empty/local/merged confirmations. Frozen controller/source/recipes and all training remain unchanged. Provenance and failure status are saved; inspect current status rather than stale original PID. Mixed MOC/MSR local macro gain is magnified by1 MSR Gate example; final union report uses official task macro, not an average of cluster scores. No cross-cluster interference conclusion until paired confirmations complete.

2026-10-04 independent-cluster confirmation completed: owning recovery finished02:01UTC. On161 reused development questions, official macro empty36.252%, isolated47.780%, merged43.007%. Merged loses4.773pp versus known-cluster single-bank exposure but remains6.755pp above empty. Five cards preserve all their owner-cluster scores;34 none→card choices occur only on four no-card clusters (BU/CC/FSA/MSR-position), causing4 improved/11 regressed/19 unchanged. Other127 choices/scores match. Every question recalls all5 cards and all regression injections are verified: evidence points to final Selector applicability spillover, not retrieval truncation. No independent Test/generalization proof. Merged health fatal0/invalid1/model_errors0; invalid responses and failed Video calls remain recorded. Results and routing_analysis live in `outputs/analysis/20261003_isolated_clusters/`; no active controller remains and no cards deployed.

2026-10-04 five-card routing controls: user authorized comparing metadata-only edits with Selector-only improvements. Control `outputs/analysis/20261004_skill_routing_controls/` freezes the isolated experiment's five-card merged bank. Three fresh arms on same reused development Gate161: original, one Train-authored description/when_to_use candidate with original Selector, and original bank with Global-only applicability-check Prompt. Bodies/meta, Actor/Video prompts and action schemas stay fixed; no combined arm or automatic deployment. GLM-5.3-Flash input-only labels on Train71 (53 fit/18 check); check withheld from metadata author, provisional labels are not gold. Real Selector replay records agreement and false positives/misses. Only selector_src/mvagent/skills/prompts.py differs from base src; English rules and Chinese mirror in control root. Existing GPU4–7 services verified without replacement, Judge disabled. Owning detached controller, full hashes/protocol/status retained; inspect saved status once and avoid monitoring loops. Selector rule design was informed by prior development evidence, so no independent Test claim.

2026-10-04 manual selection-metadata experiment: user explicitly requested Codex review and direct rewriting of all five description/when_to_use pairs without GLM authoring. Control `outputs/analysis/20261004_manual_skill_metadata/` runs fresh original/manual arms on same161 reused development Gate, original Selector and exact frozen Actor/Video/source/bodies/meta. Manual edits distinguish numeric object count from spatial answers, narrative attributes from general comparisons, assembly errors from ordinary action presence, missing-middle inference from independent-video comparison, and full cooking order from interval matching. No optimizer/Judge calls; existing five-card Train labels are reused only for optional diagnostic agreement, not gold. English edits in prepare.py/manual.json, complete Chinese mirror and invariant check retained. Non-blind manual edits informed by previous development outcomes; no independent Test or automatic deployment. Existing GPU4–7 services, normal pool verification, detached controller, saved status and hashes; do not continuously monitor.

2026-10-04: Manual five-card metadata-only diagnostic completed: Gate161 official
macro43.0068→46.6685%;38 card→none changes,11 gains/6 losses; unchanged123
selections preserve scores. Provisional Train labels show fewer false positives but
seven new missed positives; narrower metadata does not establish generality.
User-authorized small cross-benchmark transfer controller lives at
`outputs/analysis/20261004_crossbench_skill_transfer/`: CVBench12 + MVU-Eval TR12,
input-selected attribute comparisons/chronological segment orders. Three fresh
empty/original/manual bank arms, natural Selector, unchanged bodies/source/Actor,
no optimizer/Judge. Freeze provenance and current status; do not poll continuously.
Canonical choice-letter scoring preserved; specialized card output/domain conditions
are transfer boundaries. No new generalized Skill or production change. Small
selected development panel, not representative benchmark or independent Test.

2026-10-04: User-authorized generalized-order retest lives at
`outputs/analysis/20261004_generalized_order_skill/`. Fixed185 development questions:
CrossVid161 + prior CVBench12 + MVU-Eval TR12; three fresh empty/previous-manual/
generalized-bank arms, natural task-scoped Selector. Only ordering card changed:
metadata/body generalized to shared event/process temporal continuity, chain/list or
option-letter output; ID renamed c09-temporal-segment-order. Other four cards,
source/runtime/Actor/Selector remain frozen. English card and full Chinese mirror,
word checks/protocol/hashes saved. No optimizer/Judge or production deployment.
Report per-benchmark official metrics and paired ordering/off-target behavior;
not whole-benchmark or independent Test. Detach owning controller after health
verification, inspect saved status without continuous monitoring.

2026-10-04 expanded CrossVid-Skill transfer test (user authorized): control
`outputs/analysis/20261004_expanded_crossbench_transfer/`, CVBench50 + MVU-Eval80
manually input-selected questions. CVBench30 same-source complete-order tasks and20
nearby qualitative comparisons; MVU48 process orders +32 event-clip orders. Previous24
retained,106 additions reported separately; do not assume event family is all non-cooking
or procedure similarity means strict narrative card applicability. Three fresh empty/
previous/generalized arms reuse exact prior frozen five-card banks/source/runtime,
normal Selector, GPU4–7 cap1; no author/Judge calls or additional Skill changes.
Canonical input/scoring preserved; per-case whitelist/rationale, source/config/Skill
hashes and Chinese mirror retained. Paired per-benchmark/stratum/routing/health reports
and conditional source-group bootstrap intervals; purposive development evidence,
not full benchmarks or independent Test. No CrossVid rerun in this expansion.
Use detached owning controller and saved status; do not continuously monitor.

### 2026-10-04 shared-library Train and split authors implemented
Current cluster uses the complete Global library on Train; clusters organize batches only, with no slot/card binding. reflect chooses generate/revise_metadata/revise_body/skip from actual selection and exact-version exposure; body revisions require the anchor actually used the target version. Generator/Reviser author all three card fields in one call, using whole-library metadata and related used cards. Metadata-only revisions programmatically freeze body/meta. Prompts forbid incidental domain narrowing and unsupported generalization. Train-only normal Selector replay (first four members per cluster) records selection changes for subsequent author feedback; it is not gold applicability or an acceptance gate. Full Gate strict-positive acceptance remains. No Runtime Selector change, body prescreen, or slow/meta update. Chinese per-file mirrors updated. Historical slot checkpoints resume only through their original frozen sources.
Controlled experiment: outputs/analysis/20261004_shared_library_split_author/. Old frozen slot/coupled-author vs new full-library/split-author, both empty seed, Train343 CrossVid / Gate161, epoch1,batch32,patience10,1200words, GLM-5.3-Flash, same Actor/Selector GPU4–7. Fresh empty/old/new confirmations on Gate161 and fixed transfer130 (CVBench50,MVU80). All reused development data; two modifications combined, no individual attribution or independent Test claim. Sources/configs/splits/hashes frozen; 58 affected CPU tests and compile passed. Use owning detached controller and saved status; no sustained polling.

2026-10-04 reflect-only diagnostic: `scripts/analysis/run_reflect_diagnostic.py`
replays all343 frozen healthy Train cases from10 isolated clusters/45 batches,
with historical catalogs and exact exposed versions preserved. Current mixed
reflect vs separate failure/success analysis then merge with originals, two
repeats each; GLM-5.3-Flash, two API workers, no GPU Actor/Judge/Skill edits.
Control `outputs/analysis/20261004_reflect_diagnostic/`; frozen owning controller.
Structural checks and repeat consistency are not semantic accuracy; output ends
awaiting_semantic_review for Codex evidence audit. Gate excluded. Unequal API
budget, reused development and weak multi-card error coverage are explicit limits.
Prompt Chinese mirrors/protocol: analysis/skill_evolution/reflect_diagnostic_20261004.md.
Shared-library optimization continues unchanged in its separate frozen controller.

2026-10-04 user stopped shared-library full optimization to prioritize reflect diagnostic. Owning controller and descendant workers stopped, no resident model services stopped or pool locks reset. Artifacts/checkpoint retained; stop_requested.json and post_stop_services.json record shutdown. Reflect-only controller continues independently. Do not automatically resume optimization.

2026-10-04 reflect diagnostic output analysis: all180 final outputs completed;
mixed78/90 and split86/90 pass program contracts, not semantic accuracy.
Saved analysis_metrics.json independently recomputes distributions/pairing; frozen
inputs verified. Codex textual evidence review now covers45 outputs,12 batches,
all10 clusters (86 source questions);135 outputs remain unaudited. Review is
purposive, not independent human gold or raw-video verification. Inputs contain
29 empty-library and16 single-card batches, no multi-card selection coverage.
Evidence supports retaining reflect duties while improving fact/step grounding,
method-fit routing and executable edit hypotheses; no split superiority or
downstream gain established. Detailed report: analysis/skill_evolution/reflect_diagnostic_20261004.md;
manual_audit_expanded.json and analysis manifests retained in the diagnostic root.
No Prompt/Schema/Runtime changes, new model calls or optimization resume.

2026-10-04 reflect context-load analysis: provider prompt_tokens median/max
mixed7484/29793; split merge9300.5/32054. Longest8-case batch repeats the same
6138-character card9 times (49104 duplicate characters); token savings unmeasured.
context_load_analysis.json retained in reflect diagnostic root. Length alone is
not established error causality. Report proposes dedup/step clarification first,
then a separate single-case evidence check and batch edit routing experiment;
proposal only, no Prompt/Schema/Runtime implementation or new model calls.

2026-10-04 user explicitly resumed the stopped shared-library Train experiment. Owning frozen controller restarted from next_round1, unchanged source/config/split/bank/cache identities; resume_launch.json records new owner. Complete new/old training and fresh Gate161/transfer130 confirmations remain scheduled. Reflect calls completed; semantic audit remains pending and is not a demonstrated reliability result. No reflect redesign applied to this resumed experiment.

2026-10-05: Selector now checks requested-result fit, necessary prerequisites and exclusions before ranking; retrieved candidates do not imply applicability. Existing two-field JSON contract unchanged; acquisition goals are distinguished from prerequisites. Chinese mirror updated. Authorized frozen two-arm diagnostic: outputs/analysis/20261005_selector_applicability/, original five cards, fresh161 development QA and71 provisional-label routing checks; no optimizer/Judge calls or service replacement. Saved status/results are authoritative; no independent Test claim.

2026-10-05: Removed independent description/when_to_use word caps; all three fields still require nonempty text, total card/rendered body remains1200words. Cluster metadata author uses two concise method-boundary examples; adaptor/shared author instructions and Chinese mirrors agree. Historical frozen experiments unchanged. Failed12 metadata cases replayed separately under outputs/analysis/20261005_metadata_no_field_caps/.

2026-10-05: CARD_CONTRACT and cluster metadata author now specify result-plus-evidence-method descriptions, input-visible applicability and per-restriction body justification. Three hypothetical narrow-to-transferable examples cover ordering, missing events and fine visual comparison; domain scoring dependencies remain real restrictions. Both Global common Chinese mirrors and cluster metadata mirror updated. This changes author prompts, not existing deployed cards or observed QA performance.

2026-10-05: Removed independent CARD_EXAMPLE from Global adaptor/cluster author System assembly. CARD_CONTRACT includes plain-text strong/weak examples beside each of description, when_to_use, strategy, with rejection explanations. Per-role Chinese mirrors and author composition checks updated. This changes writing guidance, not Runtime card schema.

2026-10-05: Cluster metadata author removed. Generator returns id plus all three card fields; Reviser returns status/revision_summary plus four fields (all null on skip). revise_metadata runs Reviser with program-enforced unchanged body/meta; revise_body updates supported body and consistent routing text. Artifact paths proposal/generator or proposal/reviser. Current runtime selector unchanged. Historical split-author replay/resume must use its frozen source. Chinese mirrors updated.

2026-10-05: Cluster reflect.py split into prompts/reflect/{__init__,prompts,schema}.py, aligned with generator/reviser. TASK and REFLECT live in prompts.py; dynamic Schema and evidence validation in schema.py. Caller and maintained diagnostic imports updated, same rendered Prompt/contract. Chinese reflect mirror/index updated. Frozen sources unchanged.

2026-10-05: CARD_CONTRACT reorganized into Purpose, Card structure (field responsibilities/shared total budget), and Design requirements with H3 field sections. Weak-example explanations integrated into requirements; separate Evidence/scope and final length sections removed, essential evidence constraints retained under strategy. Chinese mirrors and layout checks synchronized.

2026-10-05: Global cluster/adaptor Generator no longer outputs an id. Runtime next_skill_id assigns max existing numeric reference+1 (string); revisions retain references. Semantic identifier naming validation removed; references remain opaque nonempty strings for selection/version links. Historical authored/frozen bank identities unchanged. CARD_CONTRACT now objectively defines roles/content, starts Design requirements with an introductory sentence, removes independent-field-cap prose, and retains shared total budget. Mirrors and controlled tests updated.

2026-10-05: strategy no longer has a Global requirements section. Authors and field examples use Steps: only; necessary definitions, evidence constraints and input relationships are attached to the relevant steps. Adaptor/cluster prompts, Chinese mirrors and documentation synchronized. No Runtime parser requires the removed section.

2026-10-05: strategy begins directly with numbered steps; no Steps heading is required. Global author prompts/examples and Chinese mirrors updated; worked_example Action/Result labels unchanged.

2026-10-05: CARD_CONTRACT Card structure explicitly links description to implemented strategy, applicability to actual method dependencies/capabilities, and worked_example to the same procedure. Repeated field consistency, execution visibility, parameter sourcing and illustrative-evidence prose consolidated; per-field examples and evidence safeguards retained. Adaptor/cluster Chinese mirrors updated.

2026-10-05: Removed worked_example from current SkillCard schema, rendering, authors, evidence and duplicate checks. Cards now contain meta plus description/when_to_use/strategy; Actor receives strategy only. No old-field fallback. Published authored cards/config Skill examples updated; dynamic-v003 snapshot hash and live config references replaced. Generator/Reviser return three content fields, skip requires all three null. Historical outputs/frozen sources remain unchanged. Chinese mirrors/docs and tests updated; short examples may be embedded in strategy when useful but no example field is required.

2026-10-05: Expanded adaptor/cluster CARD_CONTRACT weak examples across all three content fields, covering incidental scope restrictions, unsupported breadth, unavailable selection evidence, incomplete procedures, action/parameter and information-boundary violations, evidence misuse, leading requests and unbounded repetition. Rejection criteria remain in each field specification; examples use plain strong/weak example lines. Chinese mirrors updated.

2026-10-05: CARD_CONTRACT examples now use one strong example and one weak examples label per field, with individual examples as plain bullets. Weak examples are paraphrased development failure patterns, not verbatim model outputs: proposal_workflow_examples_20260930 (missing initial acquisition, unavailable anchors, invalid clip argument, unequal-view counts, nearest-option substitution), selector_quality_20260924 (static-count/event-search mismatch), reflect_diagnostic_20261004 (instant/cumulative ambiguity, omitted segments, unobservable middle, fallback to contradicted reports), and retained 20261003_metadata_only proposal (option-count restriction). Generalized scene-scope examples also reflect user-reported cooking/movie/sports over-specialization. Both Chinese mirrors and affected contract checks updated; no claim of measured model improvement.

2026-10-05: Adaptor/cluster CARD_CONTRACT explicitly separates metadata-only retrieval/selection (description and when_to_use matched to the current question) from strategy-only injection into the Agent system context after selection. Reference numbers identify choices. Chinese mirrors updated; Runtime behavior unchanged.

2026-10-05: Removed description from the current card schema; meta plus when_to_use/strategy only. when_to_use combines task, core method and applicability. BM25 and embedding index only when_to_use; Selector receives id and when_to_use; Actor receives strategy only. Generator/Reviser, evidence/duplicate checks, CLI listing, authored cards/config banks, snapshot hashes and mirrors updated. Existing description text merged into when_to_use to preserve discovery information; no runtime compatibility conversion. Historical frozen outputs remain unchanged.

2026-10-05: Simplified the prose before CARD_CONTRACT examples into plain field definitions and short task/method/input/scope/exclusion and acquisition/comparison/parameter/follow-up/completion bullets. Existing examples, action/evidence boundaries and two-field schema are retained; adaptor/cluster Chinese mirrors updated.

2026-10-05: Replaced CARD_CONTRACT field preambles with direct prose explaining suitability/method/required conditions and acquisition/use/follow-up/completion. Removed checklist-style labels and repeated explanations; examples and Runtime contracts unchanged. Both Global prompt variants and Chinese mirrors updated.

2026-10-05: Replaced the restrictive applicability paragraph in CARD_CONTRACT with selection-input-oriented wording: when_to_use uses natural task phrases from questions/options/video metadata, identifies video relationships and requested results, and briefly distinguishes the method. A few common paraphrases are supported; keyword lists and incidental scene details are discouraged. Adaptor/cluster Chinese mirrors updated; Runtime/Selector unchanged.

2026-10-05: Authorized when_to_use style diagnostic uses scripts/analysis/test_when_to_use_styles.py and outputs/analysis/20261005_when_to_use_styles. Freeze 11 acquisition-v002 Global cards (strategy unchanged), 71 reused CrossVid development inputs, and Codex question/body applicability labels before inference. Compare short/compact/detailed metadata through current RRF8 retrieval and Qwen3.5-35B-A3B Selector, two repeats, existing verified GPU4–7 cap1 pool and Embedding8110. No deployment, Actor QA, optimizer or Judge. Retrieval currently uses question plus empty recent history; video IDs/durations enter Selector only. Record CPU/source/config/input/metadata/body identities, raw requests/events, retrieval and selection errors separately. Repeats are paired observations, not 142 independent questions; labels are not independent human gold. Report analysis/skill_evolution/when_to_use_styles_20261005.md.

2026-10-05 when_to_use style diagnostic completed all426 Selector calls with zero errors; each arm repeated the same selections on all71 sampled questions. On64 clearly pre-reviewed questions, short/compact/detailed matched53/40/55; all63 positive questions had an acceptable card in fused top8. Shorter metadata improved fused MRR and reduced measured Selector input tokens, but did not uniformly improve selection. Labels are Codex applicability review, not independent human gold; one clear no-card negative is insufficient to establish refusal performance. No QA run or default-card/Prompt change. Full report: analysis/skill_evolution/when_to_use_styles_20261005.md.

2026-10-05: Expanded Global Selector rejection diagnostic at outputs/analysis/20261005_selector_rejection_coverage via scripts/analysis/test_selector_rejection_coverage.py. 134 unique real initial inputs (CrossVid102/CVBench8/MVU24), 115 clear and19 uncertain pre-reviews, including11 natural no-primary cases. Fixed short/compact/detailed metadata, unchanged strategy and selector, full/missing/near_only/single_near catalog conditions, two repeats:3216 planned calls plus6 no-eligible-card engineering controls. Additional64 trajectory source fingerprints and initial-step identities verified; one sample overlap deduplicated. Controlled catalog removal is not natural deployment frequency; partial utility is not necessarily primary-method suitability. Semantic labels are Codex review, not human-independent gold. Existing GPU4–7/Embedding8110 only; no deployment, QA, optimizer or Judge. Results report analysis/skill_evolution/selector_rejection_coverage_20261005.md.

2026-10-05 expanded rejection audit completed3216 model requests, zero errors, plus6 initial-stage empty-catalog controls with0 model requests. On115 clear questions x2 repeats, short/compact/detailed refusal counts: missing65/76/72 of230; near-only20/88/70; single-near148/136/146. Full-bank positive applicability matches176/126/190 of208, recall208/200/208. Compact lost4 MVU ordering questions in both repeats; count these as retrieval failures. Mid/long repeated decisions identical, short had one changed missing-bank MSR112 decision. Labels remain frozen Codex review; generic facts and spatial/count tasks have semantic debate, not automatically QA regressions. Report and selected-case audit preserve those limits. Default prompts/banks unchanged; no QA or optimization started.

2026-10-05: Authorized retrieval diagnostic uses scripts/analysis/test_selector_retrieval.py and outputs/analysis/20261005_selector_retrieval. Existing11 detailed-metadata Global cards,134 unchanged real inputs and frozen applicability labels reused. Compare BM25-only, embedding-only and RRF (branch depth8) with final shortlist4/8, full/missing-primary conditions, two repeats (3216 planned). Isolated experiment replaces retrieval callable only; production fixed top8 config and Selector Prompt remain unchanged. Actual budget is identified by experiment_arm/retriever (inherited Runtime telemetry retrieval_top_k still8). GPU4–7 existing services verified, no unavailable endpoints; no deployment, Actor QA, optimizer or Judge. Frozen owning controller runs detached; saved status authoritative. Report analysis/skill_evolution/selector_retrieval_20261005.md; reused development labels are Codex review, not independent human gold. No candidate-library expansion in this first controlled comparison.

2026-10-05 retrieval diagnostic completed3216 actual model requests, zero errors; frozen file/source hashes verified. Clear positive recall/match (208 paired observations): RRF8 208/190, RRF4 178/172, embedding8 208/178, embedding4 200/176, BM25-8 184/176, BM25-4 162/162. Missing-primary refusal (230):72/126/72/74/84/104 respectively. All sampled repeat pairs agree. RRF4 improves refusal but loses15 unique positive questions from recall; no configuration demonstrated improvement on both objectives. Default RRF8/Selector/banks unchanged; semantic development evidence only, no new QA gains established.

2026-10-05: Selector System removes Global/Video BACKGROUND, action signatures and role-specific result descriptions; both roles share the concise task/applicability/output Prompt. Six rules prioritize independent main-task fit, prerequisites/exclusions, acquisition goals and abstention under unresolved necessary conditions before comparison. Examples use sequential references ["1"]; current runtime IDs remain strings (next_skill_id returns str), output Schema unchanged. No integer-ID migration or historical artifact edits. Chinese mirror synchronized. This prompt revision has CPU contract checks only; improved semantic selection/refusal remains to be tested.

2026-10-05: Simplified Selector output to exactly selected_skill_ids, an array containing at most one supplied string reference; [] means no selection. Removed use_skills, boolean consistency branch and outdated smoke consumption. Schema rejects null, obsolete use_skills and other extra fields; no compatibility fallback. Runtime rendering/cache/telemetry retain existing selected arrays. Prompt/Chinese mirror/current docs and affected tests synchronized. This removes a redundant output and invalid consistency state, not evidence of improved semantic selection.

2026-10-05: Authorized real Selector prompt revision audit at outputs/analysis/20261005_selector_prompt_revision via scripts/analysis/test_selector_prompt_revision.py. Fresh previous/current arms,134 unchanged real development inputs, full/missing-primary catalogs, two repeats (1072 requests). Both arms use same sequential string references, frozen mapping/labels, unchanged11 detailed cards and RRF8. Previous loads frozen background/eight-rule/two-field modules, current uses no-background/six-rule/single-field source. Combined intervention, not individual attribution; numeric-ID setup differs from previous semantic-ID results. Existing GPU4–7/embedding only, detached frozen controller, no deployment/QA/Judge/optimizer; Codex labels not independent gold/Test. Preserve frozen hashes and report analysis/skill_evolution/selector_prompt_revision_20261005.md.

2026-10-05 prompt revision audit completed1072 calls with0 errors; source/file hashes checked. Fresh embedding produced24 candidate order/composition differences (8 set differences) across536 previous/current pairs, so268 current fixed-User replays additionally completed (1340 total model requests,0 errors). Fixed-candidate clear unique positives previous/current95/94 of104, false abstention0/0; missing-primary refusal35/46 of115; natural no-primary0/0 of11. Current fixes cumulative/snapshot MOC132 but FSA substitutes another mismatched method. MVU descriptive lookup regressions have helper-method ambiguity. Mean main-run input1733.4→1335.3 and output14.0→8.6 tokens; no per-change attribution or QA gain. Report/controlled_summary/comparison preserved; repeats not independent Test, Codex labels not human gold. Frozen replay script under control root, no running jobs or service replacement remain.

2026-10-05: Authorized explicit per-card applicability diagnostic runs scripts/analysis/test_selector_explicit_applicability.py at outputs/analysis/20261005_selector_explicit_applicability. 134 real questions × full/missing-primary × direct/explicit × two repeats=1072 planned, identical frozen User/candidate order/numeric references, no retrieval calls. Both one model call; explicit adds every-card fit/auxiliary/conflict/uncertain+short reason before selection. Schema enforces candidate coverage; program records fit/selection inconsistency without correcting it. Current runtime output/Prompt unchanged. Existing GPU4–7 verified/reused, no deployment, Actor QA, Judge or optimizer. Source/config/input/parent hashes and Chinese experimental mirror retained. Reused development/Codex labels not independent human gold/Test; use detached frozen owning controller/status. Report analysis/skill_evolution/selector_explicit_applicability_20261005.md.

2026-10-05 explicit applicability diagnostic completed1072 actual model requests,0 errors/no extra model requests; frozen/source/parent hashes and identical User inputs verified. Direct/explicit clear unique positive matches94/93 of104, false abstention0/0; missing-primary refusal46/22 of115; natural no-primary0/0 of11. Both sampled repeats identical. Explicit6 unique missing cases have fit judgments but empty selection (12 outputs); no semantic corrections applied. Mean input1335.4/1447.4, output8.6/457.3 tokens. Reviewed7 representative questions/14 responses: explicit ignores cumulative-count and missing-middle exclusions, fabricates functional-equivalence scope in temporal-relations reasoning. Current single-call classification+reason variant is worse; production direct Selector remains unchanged. Does not refute every explicit/two-stage approach or demonstrate QA effects. Report/case_review/comparison/schema_check saved.

2026-10-05: User requested one reason before selected_skill_ids. Current Selector Schema/Prompt now require reason first (nonblank string, no separate hard cap) then selected_skill_ids; use_skills remains removed. Rationale remains in raw selector responses, not Actor evidence. Chinese mirror/docs/tests updated. Authorized scripts/analysis/test_selector_reason.py fixed-User audit at outputs/analysis/20261005_selector_reason: direct frozen single-field vs current reason-first, same6 rules/134 real questions/full+missing/two repeats=1072 planned; existing GPU4–7 only, no retrieval/QA/Judge/optimizer/service deployment. Inputs/source/config/parent hashes frozen; source change not yet proven performance improvement. Report analysis/skill_evolution/selector_reason_20261005.md.

2026-10-05 reason audit engineering correction: first outputs/analysis/20261005_selector_reason used pattern \\S, which installed xgrammar interprets as single-character whole-string generation. Observed comma reasons invalidate semantic comparison despite structurally valid results. Preserve original artifacts and invalid_semantic_experiment.json; do not claim its all-abstain outcomes as model performance. Correct source/schema uses existing [\\s\\S]*\\S[\\s\\S]* nonblank pattern, already handled by provider generation-schema sanitization and full response validation. Actual grammar test now passes. Fresh corrected1072-call frozen audit runs under outputs/analysis/20261005_selector_reason_v2; no frozen edits or service replacement.

2026-10-05 corrected reason_v2 completed1072 actual model requests,0 schema/call errors/no extra requests; all frozen/parent hashes and identical User verified. All536 reason responses order reason before selected_skill_ids. Unique clear positive match94/94 of104 direct/reason, false abstention0/1; missing-primary refusal46/36 of115; natural no-primary0/0 of11. Sampled repeats agree. Mean input1335.4/1425.4, output8.6/141.5. Two unique cases produce punctuation-only reasons (4 repeated outputs), retained as semantic quality failures, not hidden by structural-valid claims. MOC132 reason explicitly overrides interval-total exclusion, regressing refusal. Current source retains reason-first per user request, not demonstrated performance improvement; rationale is diagnostic, not Actor evidence.28 affected CPU tests/actual grammar and compile passed. No QA, independent gold or default gain established; invalid first grammar trial remains separate.

2026-10-05: User removed Selector reason after paired experiment. Current System/Schema restored to exactly selected_skill_ids, one supplied string reference or [], rejecting reason/use_skills/null. Mock contracts/current docs/Chinese mirror updated. Frozen reason/direct experiments preserved; no model rerun. Runtime Global action reason remains unchanged. Current complete example can be rendered using recorded numeric candidate User with current System/Schema; do not represent historical reason trial as current runtime.

2026-10-05: Candidate User headings now explicitly render `## Skill ID: <id>` instead of isolated identifiers. Current Chinese mirror/example and metadata boundary checks updated; no retrieval/order changes. Recent prompt/explicit/reason audits used unchanged detailed when_to_use, not short variants. RRF candidates sorted descending fused rank score, lexical-string id for ties; eligible catalogs<=8 sorted lexical-string id, not numeric order. Frozen experiments unchanged.

2026-10-05: User authorized short when_to_use retest with current Selector via scripts/analysis/test_current_when_to_use.py at outputs/analysis/20261005_current_when_to_use. Same134 real inputs, numeric-string references, unchanged11 strategies, frozen prior short/detailed fields, RRF8, current six-rule/no-background/no-reason single-field Prompt and Skill ID headings. Full/missing-primary, two repeats=1072 calls planned. Metadata changes retrieval and selector information jointly; no fixed-candidate causal isolation. Source/config/input/bank hashes frozen; existing GPU4–7/Embedding8110 verified only, no deployment/Actor QA/Judge/optimizer. Labels remain Codex development review (115 clear19 uncertain), not independent gold/Test. Report analysis/skill_evolution/current_when_to_use_20261005.md; Chinese experimental style mirror appended. Formal authored cards unchanged.

2026-10-05 current short/detailed audit completed1072 actual calls,0 errors/no extra requests; frozen source/file hashes verified. Both clear positive recall208/208; short/detailed match194/188, false abstention2/2. Missing-primary refusal76/127 of230 (short38 perrepeat; detailed64 then63 unique of115). Natural no-primary8/4 of22, provisional auxiliary-method labels. Average input788.8/1359.3 (~42% reduction), output8.6/8.4. Short repeated choices all identical; detailed FSA2030 missing one change. Missing PSS short2/15 vs detailed15/15, showing lost supplied-clip vs within-video-event boundary; positives97/94 unique each repeat. Existing cards remain unchanged, no general short optimum or QA gain claimed. Report/case_review/comparison retained; next proposed compact task+essential boundary is untested.

2026-10-05: User chose short when_to_use design despite refusal tradeoff. Adaptor/cluster CARD_CONTRACT now defines one short English task sentence plus essential input relationship, matching original question/options/video metadata. Removes requirement for method summary, execution steps, paraphrase inventory and separate exclusion list; preserves necessary supplied-clip/within-clip, cumulative/instant and reference-interval distinctions in task phrasing. Card structure/coherence and per-file Chinese mirrors aligned; strategy unchanged, total budget/schema unchanged. Existing banks and frozen experiments not rewritten; this author-prompt change is not a demonstrated performance gain.

2026-10-05: when_to_use examples reduced to three adjacent strong/weak pairs covering incidental domain/count narrowing, execution detail in retrieval text, and conflated momentary/cumulative counting. Adaptor/cluster contracts and Chinese mirrors synchronized; existing format test updated for paired when_to_use while strategy examples remain unchanged. No schema/runtime/card content changes.

2026-10-05: User questioned abstention labels and authorized prompt-based improvement. Isolated scripts/analysis/test_selector_boundary_prompt.py freezes current short/detailed actual User/candidate lists (134 QA×2 catalogs×2styles) and compares current/boundary-veto rules, two repeats=2144 calls. Same one-field contract, no reason/assessment/retrieval, no production Prompt edits. Boundary rules require target+input-relation fit and treat explicit exclusions as veto while allowing valid generic fact collection. Existing GPU4–7 verified only; no QA/Judge/optimizer/deployment. Historical labels unchanged; chairs-most versus independent facts and error-diagnosis versus auxiliary evidence have semantic debate, do not count every substitute as proven harmful. Codex review is not human gold; inspect core method subset separately as sensitivity, no independent Test claim. Source/config/parent requests frozen; Chinese experiment mirror updated. Control outputs/analysis/20261005_selector_boundary_prompt; report analysis/skill_evolution/selector_boundary_prompt_20261005.md.

2026-10-05 boundary prompt audit completed2144 actual model calls,0 errors/no extra requests; source/files/536 parent hashes and identical per-style User/Schema verified, sampled repeats identical. Unique old-label positive match short current/boundary97/95 of104, false abstention1/6; missing refusal38/54 of115. Detailed match94/95, false abstention1/0, missing64/86. Five newly refused short MVU ordering positives lack input proof of one-continuous-video prerequisite; classify as unresolved applicability in post-results scope review, not proven bad abstentions. Counting1 independent-fact choice cannot confidently be must-reject; PEA446/helper and CV598/navigation remain debated. Old labels unchanged. Prior67 core minus5 unresolved=62: short full61→62/missing24→34; detailed full62→62/missing48→59. Sensitivity only, no independent gold/QA gain. Production Selector unchanged; short boundary candidate needs new confirmation/human scope review. Report/comparison/case_review/scope_review retained.

2026-10-05: `scripts/analysis/test_current_when_to_use.py` now compares short, lightly enhanced task/method-cue, and detailed metadata on the frozen 134-question development panel, full/missing-primary catalogs, two repeats (1608 Selector calls). Current experiment artifacts: `outputs/analysis/20261005_enhanced_when_to_use/`. Runtime Selector and CARD_CONTRACT remain unchanged pending evidence; applicability labels are development annotations, not human gold.

2026-10-05 enhanced when_to_use diagnostic completed all1608 calls with zero errors. Short/enhanced/detailed primary matches194/178/188 of208; missing-primary refusals76/82/125 of230 under historical development labels. Enhanced wording is not promoted to CARD_CONTRACT/Runtime. Report: `analysis/skill_evolution/enhanced_when_to_use_20261005.md`.

2026-10-05: At user request, the maintained when_to_use probe was restored to short/detailed arms (1072 planned calls), removing experimental enhanced wording from its source. The completed enhanced experiment retains its immutable controller/source/banks under its output root for historical replay. CARD_CONTRACT remains short.

2026-10-05: Selector rules now state declared task scope, asymmetric speculative-selection cost, conflicting-prerequisite veto, and three applicability examples; short when_to_use and single-field selected_skill_ids remain. Chinese mirror updated. Controlled diagnostic `scripts/analysis/test_selector_conservative.py` compares frozen prior/current prompts on134 reused real questions, five library-coverage conditions, two repeats (2680 calls); output `outputs/analysis/20261005_selector_conservative/`. Includes covered-small positive controls to distinguish missing skills from small catalogs. Labels remain development annotations, not human gold.

2026-10-05 conservative Selector diagnostic completed2680/2680 calls, zero errors; full primary match194→188/208, candidate recall208/208 both; missing refusal76→142/230. Covered-small match196→188/208 is a3.85pp loss. Labels are reused development annotations with disputed input relationships, not independent gold or final-QA gains. Report `analysis/skill_evolution/selector_conservative_20261005.md`; new rules retained, short cards/single-field output unchanged.

2026-10-05: User-authorized shortlist diagnostic `scripts/analysis/test_current_selector_retrieval.py` compares RRF top8/6/4 and embedding top4 on frozen134 real development inputs, current conservative Selector, unchanged short cards/numeric references, full/missing-primary libraries, two repeats (2144 calls). Output `outputs/analysis/20261005_current_selector_retrieval/`; production retrieval remainsRRF8 during the diagnostic. Frozen source/config/bank/request provenance retained; no Actor QA/Judge/optimizer.

2026-10-05 current shortlist diagnostic completed2144 calls, zero errors. RRF8/6/4 and embedding4 match94/78/77/81 of104, recall104/89/88/91 of104; missing refusal71/83/85/80 of115. Reduced shortlists fail90% matching target; production remainsRRF8. Report `analysis/skill_evolution/current_selector_retrieval_20261005.md`.

2026-10-05: Expanded retrieval diagnostic is authorized: `scripts/analysis/test_expanded_selector_retrieval.py` runs six strategies on old134 plus200 new stratified real questions (CrossVid120, CVBench40, MVU40), full/missing-primary, two repeats (8016 calls), current short cards/conservative one-field Selector unchanged. New questions are exact-video-path disjoint from old panel and each other, not proven whole-film/session independent. Pre-inference scope labels:168 clear (163 positive/5 hidden-rule-inference negatives),32 uncertain; old labels kept for comparison. New/old reported separately. Panel `outputs/analysis/20261005_selector_expanded_panel/`; frozen run `outputs/analysis/20261005_expanded_selector_retrieval/`. Query-cleaning applies only to experimental BM25 input, not production or embedding prompt; production remainsRRF8.

2026-10-05 expanded retrieval completed:334 real questions (previous134/new200: CrossVid120,CVBench40,MVU40), six strategies, full/missing applicable-card catalogs, two repeats. New labels frozen before inference:168 clear (163 positive/5 natural none),32 uncertain; previous labels unchanged. Same11 short cards/current conservative Selector, no production changes, Actor QA/Judge/optimizer or service deployment.8016 effective successful Selector requests verified with identical inputs/banks and frozen file hashes. Initial cleanrrf6 failed1336 attempts before model invocation due missing sklearn; preserve main failed records/source. Stdlib stopword repair completed1336 in separate outputs/analysis/20261005_expanded_selector_retrieval_clean_fix; other five strategies remain main outputs/analysis/20261005_expanded_selector_retrieval. New clear match: RRF8/6=91.41/70.55%,embedding8/6/4=82.21/76.07/74.54%,cleanrrf6=85.28%; corresponding missing refusal64.29/75/67.26/70.24/72.02/64.29%. RRF8 andembedding8 recall both99.39%; candidate composition/order jointly differ, no ranking-only causal claim. Keep productionRRF8. Exact-video-path isolation is not whole-film/session independence; Codex labels not independent human gold. Report analysis/skill_evolution/expanded_selector_retrieval_20261005.md, merged comparison.json in main root. Maintained test_expanded_selector_retrieval.py supports --arms for separate subset runs; never mutate frozen controllers.

2026-10-05 further abstention experiment authorized: test_selector_abstention_review.py replays fixed RRF8 User/candidate order from expanded334 development questions, same short11-card metadata and single-field output. Fresh current/strict single calls, plus independent proposed-card retain/reject review conditional on current nonempty selection; reviewer cannot replace card, empty current skips review.2672 first calls, at most1336 reviews, two repeats; targets ~90% correct selection and>=70% missing-card refusal (75% aspirational). Existing GPU4–7 verified through pool only, no service deployment/Actor/Judge/optimizer/production changes. Labels unchanged; these reused cohorts are not held-out Test. Conditional review requests/errors tracked, parent request/source/config/Skill hashes frozen; owning controller/status at outputs/analysis/20261005_selector_abstention_review/. Chinese experimental mirror updated; CPU review-input isolation selfcheck/compile passed.

2026-10-05 prompt/order factorial authorized: scripts/analysis/test_selector_prompt_order.py crosses current/prior strict/balanced operation-mismatch veto/task-scope check with original retrieval rank or numeric-ID ascending. Fixed334 reused development questions/full+missing RRF8 sets; Schema enum order unchanged, two repeats10688 single calls, no reason/review. Existing GPU4–7 pool only, no production changes/Actor/Judge/optimizer/deployment. Frozen parent requests and input/config/bank/source hashes; Chinese experimental mirror updated. CPU ordering/set-preservation/no-Schema-mutation selfcheck passed. Control outputs/analysis/20261005_selector_prompt_order/, saved status/owning frozen controller. Target approximately90% selection and70–75% missing refusal; no post-result relabeling or held-out claim.

2026-10-05 prompt/order audit completed10688 calls zero errors; frozen files verified. New clear scope_rank match294/326=90.18%, missing refusal244/336=72.62%, versus current298/326 and216/336. Combined clear scope480/534=89.89%,396/566=69.96%; prior cohort89.42/66.09%, no stable75% claim. All four rules show ID numeric ascending improving new missing refusal but reducing new correct match; do not promote ID order. Source/User candidate sets and Schema unchanged within rule; order effect supported, particular positional mechanism unproven. Production remains current/RRF8. scope_rank is a development finalist requiring new inputs, not deployed optimum or QA gain. Report analysis/skill_evolution/selector_prompt_order_20261005.md.

2026-10-05 user authorized researched prompt/example comparisons in one batch. test_selector_principled_prompt.py compares current/scope/no_examples/merged/rubric/rubric_examples and two seeded-shuffle rubric arms, same real334 RRF8 candidate sets/Schema, plus24 authored cross-domain input conditions on synthetic two-card libraries, two repeats11072 calls. Transfer reported separately, not real-video OOD or benchmark claims; reused real cohorts not independent Test, labels frozen. Sources include official Anthropic context/routing/tool guidance, OpenAI prompt docs, demonstrations/generalization/position papers; adapted criteria not universally validated template. Existing GPU4–7 pool only, no deployment/Actor/Judge/optimizer or production changes. Chinese experiment mirror updated, parent/source/config/bank/input hashes frozen at outputs/analysis/20261005_selector_principled_prompt/. CPU ablation/output-contract/order/set tests and compile passed; owning controller/status only.

2026-10-05 principled prompt batch complete11072 requests zero errors, frozen file hashes verified. New clear current/scope/no_examples/merged/rubric/rubric_examples match91.41/90.18/90.80/91.41/90.18/90.18%, missing refusal64.29/72.62/56.55/65.48/44.05/50.60%. Abstract rubric not a demonstrated improvement; keep production current. Example ablation supports benefit on reused distribution; removing examples leaves original task-boundary rules, no completely generic causal claim. PSS missing12/12 current/no_examples versus0/12 rubric variants, PI12/12 all, FSA0/12 all (first new repeat). Synthetic transfer all perfect, ceiling cannot discriminate or establish OOD. Report selector_principled_prompt_20261005.md; scope needs new-real-input confirmation, combined refusal69.96% not stable75%.

2026-10-05 user authorized general task-scope metadata/Selector alignment test. test_selector_scope_alignment.py crosses original/aligned short when_to_use, current/general added alignment rule and fixed/live RRF8 retrieval, eight arms334 reused real inputs×full/missing×two repeats10688 calls. Conditions cover main operation/input unit/time scope/reference/criterion/evidence, not universal video provenance restrictions. strategy/meta/IDs unchanged; fixed holds ID/order/Schema, live records real changed retrieval and positive recall. Two immutable bank snapshots and parent/source/config/input hashes frozen at outputs/analysis/20261005_selector_scope_alignment/. Existing GPU4–7 pool/Embedding8110 only, no deployment/Actor/Judge/optimizer; no production prompts/cards changed. Chinese experiment mirror aligned, CPU selfcheck/compile passed, labels unchanged and reused development cohorts not independent Test. Saved status and owning frozen controller govern continuation.

2026-10-05 scope alignment completed10688 calls zero errors, frozen files verified. Aligned all-card metadata regressed: new fixed current match270/326 vs298, missing182/336 vs216; live recall326/326 but match266/326, missing151/336. Main errors are changed choices (fact card absorbs interpretation/assembly diagnosis), not stricter abstention; all-card edits confound per-card attribution. Original metadata+general System296/326 match and234/336 missing refusal, development tradeoff90.80/69.64%, no stable75% result. Keep production original cards/System; full report selector_scope_alignment_20261005.md. No label changes, Actor QA or independent Test claim.

2026-10-05 user confirmed production Selector edit and retest: shared src/mvagent/skills/prompts.py SYSTEM_TEMPLATE integrates main-task scope matching into five Selection rules, removes need for appended Decision criterion, preserves original three Applicability examples/output and unchanged11 short cards/RRF8/ranked order. Global/Video share rules; no action contract change. Chinese authoritative mirror synchronized.16 affected dynamic Skill CPU tests incl actual grammar passed, compile passed. New test_selector_integrated_confirmation.py compares frozen previous System with current: original334 fixed candidates plus60 fresh real questions excluding previous334 IDs/exact video paths, two regimes/two repeats3152 calls. Fresh labels frozen pre-inference:49 clear (47 positive/2 natural none),11 uncertain; not independent human gold or full-film/session Test. Control outputs/analysis/20261005_selector_integrated_confirmation/, panel outputs/analysis/20261005_selector_confirmation_panel/. Source/config/cards/input/reviewer/sampler/previous System/parent requests hash frozen. Existing GPU4–7 pool and Embedding8110 only, no deployments/Actor QA/Judge/optimizer. Confirm results before claiming performance; no automatic relabeling.

2026-10-05 integrated confirmation startup correction: initial outputs/analysis/20261005_selector_integrated_confirmation/ failed before model requests due obsolete aligned-bank unpacking in new probe; frozen failed source/log/startup_failure.json preserved. Maintained script corrected to single original bank; fresh identical-input/config run at outputs/analysis/20261005_selector_integrated_confirmation_v2/ is the owning active experiment. Do not use initial prepared status as active run or claim initial zero engineering errors. Production prompt unchanged by this correction.

2026-10-05 user explicitly chose general alignment instead of integrated scope rules: production shared SYSTEM_TEMPLATE now exactly equals frozen scope_alignment original System plus its GENERAL/# Task-scope alignment text (tested original_general arms), not integrated rules plus that text. Original three examples/output, short cards/strategy, RRF8/rank unchanged. Authority Chinese mirror updated.16 affected dynamic Skill tests/grammar and compile passed. Frozen integrated_confirmation_v2 continues testing its previous integrated snapshot and must not be represented as validation of this new production choice; do not edit/stop frozen experiment. Maintained confirmation selfcheck recognizes appended general section while preserving examples/output; future prepares snapshot current selected production. Prior general development match90.80%,missing69.64%, not stable75% or QA gain.

2026-10-05 user requested unified general-alignment layout: production SYSTEM_TEMPLATE now folds general task/input-unit/time/reference/criterion checks into five Selection rules, removes separate Applicability examples and Task-scope alignment headings. Original two mismatch examples sit under boundary rule3, general predicate positive under rule4, example sentences unchanged; Selection task/Output contract unchanged. One shared Global/Video template, not parallel maintained versions; historical frozen prompts untouched. Chinese authoritative mirror synchronized.16 dynamic Skill tests and maintained example/output preservation selfcheck passed. This consolidation rewrites/reorders model-visible rules, so prior general metrics are contextual evidence, not exact validation of this latest layout; no new inference claimed. Short cards/RRF8/selection JSON unchanged.

2026-10-05 user requested actual top-level rule synthesis rather than concatenation: production shared SYSTEM_TEMPLATE now four rules (direct main-task fit, method-essential input conditions, semantic/domain generalization without capability expansion, eligibility before preference), with few illustrative examples; Selection task/output unchanged. Chinese authority mirror synced, short cards/RRF8/rank unchanged.16 dynamic Skill CPU tests incl grammar, structure selfcheck and compile passed. test_selector_refined_rules.py compares historical general, immediate concatenated and current refined Systems on same fixed788 User/Schema inputs (394 questions×full/missing), two repeats4728 calls. All cohorts reused incl confirmation60, not new Test, labels unchanged. Frozen systems/source/config/bank/parents at outputs/analysis/20261005_selector_refined_rules/, existing GPU4–7 pool only/no Embedding or deployment/Actor/Judge/optimizer. Performance not assumed from cleaner structure.

2026-10-05 refined rules batch complete4728 calls zero errors, frozen file hashes verified. General/concatenated/refined on reused confirmation60 clear: match86/86/84 of94, missing refusal72/72/58 of98. Original general outperforms refined, but historical334 general refusal384/566=67.84%, so no universal70–75% claim. Current production remains authorized refined (no silent rollback in analysis); recommended exact general requires subsequent change. Rule rewriting/example wording/order confounded, do not attribute loss solely to abstraction. Report selector_refined_rules_20261005.md, no QA/independent Test evidence.

2026-10-05 case-driven semantic refinement authorized: test_selector_semantic_fit.py keeps four-rule production baseline, tests operation parsing versus answer-format wrappers, direct-method coverage versus auxiliary observations, and combined (one contrastive example changed in operation/combined).394 reused real questions, same788 User/candidate order/Schema, two repeatsfour arms6304 calls. Baseline production unchanged pending evidence; cards/output/retrieval unchanged. Frozen Systems/source/config/bank/parent hashes at outputs/analysis/20261005_selector_semantic_fit/. Prior failed/correct cases audited, disputed TR provenance/OR risk labels not relabeled. Chinese experimental mirror synced; structure/check/compile passed. Existing GPU4–7 pool only/no deployment/Embedding/Actor/Judge/optimizer; mature guidance is motivation not guarantee, no independent Test or QA gain claim.

2026-10-05 semantic-fit completed6304 calls zero errors, frozen file hashes verified. All clear cohorts combined positive match560/570/566/562 of628 and missing refusal376/384/418/392 of664 (baseline/operation/coverage/combined). Coverage best refusal tradeoff90.13%/62.95%, below70%; operation90.76%/57.83%, combined89.49%/59.04%. FSA31 clear cases first repeat all three variants missing0/31 refusal. Do not promote as target achieved or assume additions compose positively. Production remains four-rule baseline pending explicit selection; labels unchanged, no Actor QA/OOD/Test claim. Report selector_semantic_fit_20261005.md.

2026-10-05 user selected coverage for further optimization: production shared SYSTEM_TEMPLATE now exactly preceding semantic_fit systems.json coverage, with authoritative Chinese mirror, short cards/RRF8/output unchanged.16 dynamic Skill CPU/grammar tests, compile and structure check passed. test_selector_coverage_followup.py tests exact coverage, whole target/reference/trigger relationship binding, declared-operation paraphrase without inventing a missing main operation, and combined; same four rules/examples.394 reused questions×full/missing×2×4=6304 calls, fixed User/order/Schema. Frozen Systems/source/config/bank/parents at outputs/analysis/20261005_selector_coverage_followup/. No model reasoning inferred; related auxiliary usefulness/primary labels remain debatable, no relabeling or independent Test/QA claims. Existing GPU4–7 pool only/no deployment/Embedding/Actor/Judge/optimizer. Further variants isolated pending outcomes.

2026-10-05 coverage_followup complete6304 calls zero errors/frozen hashes verified. Coverage/binding/closure/combined combined clear match90.13/88.85/88.54/87.58%, missing refusal62.95/65.66/62.35/64.46%. Binding modest refusal gain costs selection, no target achieved. FSA31 cases first repeat missing0/31 all arms. Keep productioncoverage; new60 binding71.43% refusal is small reused subset, not overall>=70% or independent confirmation. Further task-operation diagnosis recommended, not more blanket veto text. Report selector_coverage_followup_20261005.md.

2026-10-05 explicit none abstention experiment authorized: test_selector_none_output.py compares empty_array selected_skill_ids=[]/[ID], array_none=['none']/[ID] mandatory one value, scalar_none selected_skill_id='none'/ID. Exact coverage rules/examples/User/candidates preserved except required return-value wording; output Schema/decoder differ, scalar also changes field name so not pure lexical contrast.394 reused real questions×two regimes×two repeats×three arms4728 calls, labels unchanged, no independent Test claim. Actual xgrammar/local Schema/decoding check and compile passed. Frozen Systems/source/config/bank/parents at outputs/analysis/20261005_selector_none_output/. Chinese experimental mirror synchronized. Existing GPU4–7 pool only/no deployment/Embedding/Actor/Judge/optimizer. Production coverage retains original empty-array contract, no compatibility layer; invalid output not successful refusal.

2026-10-05 none_output complete4728 calls zero errors, frozen hashes/successful rows/none decoding verified. Clear all cohorts empty_array/array_none/scalar_none match566/588/590 of628 (90.13/93.63/93.95%), missing refusal418/138/170 of664 (62.95/20.78/25.60%). Explicit none worsens abstention dramatically, positive gains accompany lower abstention not proof better precision. Keep production coverage+empty array; FSA31 first-repeat missing0 all arms. Output wording/grammar/shape change jointly, no universal none-token causal claim. status skip/selected not yet experimentally tested; no model effect claim. Report selector_none_output_20261005.md.

2026-10-05 user authorized status skip/selected real test: test_selector_status_output.py compares unchanged empty_array coverage with two-field status_first and ids_first contracts, same four rules/examples/User/candidates. oneOf forces skip=>[]/selected=>one supplied ID; actual xgrammar tested both valid states and rejected reversed field order; local schema/decoder validates consistency/order.394 reused questions×full/missing×two repeats×three arms4728 calls, no label changes/Test claim. Frozen systems/source/config/bank/parents at outputs/analysis/20261005_selector_status_output/. Chinese experimental mirror synchronized. Existing GPU4–7 pool only/no deployment/Embedding/Actor/Judge/optimizer. Production remains coverage single-array contract; record actual JSON field order and do not treat structural errors as correct refusal. No reason field or compatibility layer.

2026-10-05 status_output4728调用完成零错，冻结哈希及全部status响应实际字段顺序/状态一致性核验通过。empty_array/status_first/ids_first合并清晰队列正选566/582/582 of628（90.13/92.68/92.68%），缺卡拒选418/208/106 of664（62.95/31.33/15.96%）；full误拒30/6/0、错选32/40/46。先status优于先ID但远低于原空数组，未改善兜底；FSA31第一重复三组仍0拒选。保留正式coverage+单数组，不部署status。394题全复用，重复非独立样本，无Actor QA/Test保证；报告analysis/skill_evolution/selector_status_output_20261005.md。

2026-10-05授权分析11卡误选并手改测试：test_selector_card_scopes.py固定coverage/System、strategy、候选ID/顺序和Schema，仅改1/2/3/4/5/10的简短when_to_use，original/task_precise394复用题×full/missing×两重复3152调用。控制outputs/analysis/20261005_selector_card_scopes/，协议analysis/skill_evolution/selector_card_scopes_20261005.md，中文实验镜像同步。仅固定候选LLM测试，不宣称检索/QA收益；正式卡不改。既有GPU4–7池无部署/Embedding/Judge/optimizer，查保存status。

2026-10-05 card_scopes完成3152调用零错，冻结哈希通过。原卡/task_precise全清晰正选566/550 of628（90.13/87.58%）、缺卡拒选418/402 of664（62.95/60.54%），full正例错选32→62。卡4/5缺卡误选26→0、12→2，但卡1/3增112→132、46→76；配对改善52退化68。六卡联合改写不部署，原卡保持；局部收益需单卡消融而非推断独立因果。报告selector_card_scopes_20261005.md，复用开发/固定候选非检索QA或Test证据。

2026-10-05授权继续卡4/5单卡消融并扩展：test_selector_card_ablation.py四组original/card4/card5/card4_5，旧394＋新增120题×full/missing×两重复8224调用。新增CrossVid60/CV28/MVU32，排除旧ID/精确视频路径，推理前冻结93清晰（87正6自然none）、27存疑标签；非人工金标/整体源隔离Test。新题原库RRF8后再修改文字，旧候选冻结，实际候选记录核验；仅既有GPU4–7和Embedding8110，无部署/Actor/Judge/optimizer。正式卡保持。控制outputs/analysis/20261005_selector_card_ablation/，协议analysis/skill_evolution/selector_card_ablation_20261005.md，查保存status勿重复启动。

2026-10-05 card_ablation8224调用完成零错/hash通过。原/card4/card5/双改合并清晰正选89.53/88.78/89.03/88.78%，missing拒选62.82/65.88/64.71/67.29%；新增120正选87.36/85.06/86.21/85.06%，拒选62.37/65.59/65.59/68.82%。边界改写局部有效但未达到目标，不自动部署。新增检索各组独立执行导致共4条件排序不一致（2清晰missing），排除后拒选计数不变、分母850→848，方向保持；不可称全严格固定候选。后续先冻结候选，勿改历史冻结源。报告selector_card_ablation_20261005.md，标签非独立人工/Test、重复非独立、无QA或改写检索证据。

2026-10-05用户授权简化规则测试：test_selector_minimal_rules.py两组current/minimal，后者只有默认不选、保守判断when_to_use、高度匹配才选一个，否则[]。514复用题×full/missing×两重复4112调用，原11卡/strategy/任务/output固定；候选直接复用card_ablation original repeat0的User/Schema，不重新检索。425清晰（401正24自然none）、89存疑分列，非新Test/人工金标。冻结控制outputs/analysis/20261005_selector_minimal_rules/，协议analysis/skill_evolution/selector_minimal_rules_20261005.md，中文实验镜像同步，compile及固定输入/System/Schema检查通过。正式coverage不改；既有GPU4–7零部署/Embedding/Actor/Judge/optimizer，查status勿重复启动。

2026-10-05 minimal_rules4112完成零错，冻结hash及全部两组User/Schema一致核验通过。current/minimal清晰正选718/558 of802（89.53/69.58%），missing拒选534/604 of850（62.82/71.06%）；full误拒40→172、错选44→72。后续120正选87.36→65.52%，拒选62.37→67.74%。纯默认none短规则过度拒绝并丢失操作判别，不部署；正式coverage保持。报告selector_minimal_rules_20261005.md，非新Test/QA证据。

2026-10-05授权基于保守简化版继续联合优化：test_selector_compact_joint.py 2×2 minimal/compact（3短判据：默认none直接主操作结果、必要关系/未知观察区分、正常语义泛化）×原卡/仅卡4/5边界改写，514复用题×full/missing×两重复8224请求。固定前轮原候选User顺序/Schema、策略/meta/其余卡不变，输出单数组。控制outputs/analysis/20261005_selector_compact_joint/，协议analysis/skill_evolution/selector_compact_joint_20261005.md，中文镜像和compile/一致性检查完成；正式coverage原卡不改。既有GPU4–7无部署/Embedding/Actor/Judge/optimizer，非新Test或人工金标，查status勿重复启动。

2026-10-05 compact_joint8224完成零错，冻结hash/全部候选顺序Schema一致通过。minimal/compact/minimal_cards/compact_cards正选69.58/77.06/68.83/77.81%，missing拒选71.06/59.06/67.53/63.06%；后续120联合正选74.71%拒选60.22%，未达目标。卡4边界局部有效，卡5改写在minimal下误选34→70，规则与卡片交互显著；长版历史89.53/62.82仍较好折中。不部署，正式coverage原卡保持。报告selector_compact_joint_20261005.md，无新Test/人工金标/QA证据。

2026-10-05用户授权输入关系＋结果when_to_use测试：test_selector_input_scopes.py原卡/仅9/全部11三组，coverage固定、strategy/meta/候选顺序/Schema保持，514复用题×full/missing×两重复6168调用。卡9明确参考视频起止区间和另一目标视频对应事件定位；不写具体ID或从时长猜关系，无不必要数量约束。控制outputs/analysis/20261005_selector_input_scopes/，协议analysis/skill_evolution/selector_input_scopes_20261005.md，中文镜像与compile/策略meta一致性检查完成。固定候选非真实检索/QA或新Test，正式卡不改；既有GPU4–7无部署/Embedding/Judge/optimizer，查status勿重复启动。

2026-10-05 input_scopes6168完成零错/hash及全部候选顺序Schema一致通过。原/仅9/全11清晰正选89.53/89.78/86.78%，missing拒选62.82/62.59/67.29%；全改full错选44→92。37清晰区间匹配题两重复full全组74/74，missing0/0/74 of74，全改局部修复来自其它仍在库卡的文字（9已删除），不可归因于卡9自身改写。误吸引2为54→106、3为56→104，不部署整库，正式保持。后续单卡/组合消融范围，报告selector_input_scopes_20261005.md，非新Test/QA或真实改写检索证据。

2026-10-05授权按真实簇原始输入归纳新when_to_use：test_selector_cluster_scopes.py original/cluster_all/cluster_specialized（保留2/3/10）三组6168请求，输入类型/主要操作/答案内容，来源20261002_cross_benchmark_clusters843原问题选项ID时长。纯簇5/12/13/14与混合6/7等有完整cluster_materials/逐题子类型审阅，不将真实任务差异默认为聚类错误，不超出策略。514复用、固定coverage/candidates/schema/strategy/meta；无新Test/人工金标/QA或真实检索证据。控制outputs/analysis/20261005_selector_cluster_scopes/，协议selector_cluster_scopes_20261005.md，中文镜像/compile一致性通过，正式卡不改。既有GPU4–7无部署/Embedding/Judge/optimizer，查status。

2026-10-05 cluster_scopes6168完成零错/hash及全部候选顺序Schema一致。原/全11/专门（保留2/3/10）正选89.53/88.28/89.53%，missing拒选62.82/77.88/77.88%；后续120专门87.36/82.80%，原87.36/62.37%。专门开发折中显著改善，full正确恢复/损失均34次，missing改善186退化58；卡6缺口74/74→54/74退化，卡9 0→74/74、11 66→88/100、8 24→40/58。推荐专门候选继续验证，不自动部署；簇843与复用514有重叠，非独立Test/人工金标/QA或真实检索证据。报告selector_cluster_scopes_20261005.md。

2026-10-05按用户方向完善cluster CARD_CONTRACT when_to_use：一句简洁范围，明确必要输入类型/关系、主要任务和答案内容；直接事实任务可更短，不强制Given模板。保留策略一致性、任务单位/区间累计与快照/已见解释与未见推断边界；不以ID时长猜关系，不包含答案值、格式命令或执行步骤。三组一一对应正反例为参考区间/片段排列/同步快照。修改仅cluster/prompts/common.py及对应chinese_prompts/common.md，无独立metadata作者或Runtime/selector/卡库变更。9项global_cluster CPU检查通过；尚未实测自动作者新描述或真实检索/独立QA收益。

2026-10-05用户请求从0完整Global进化，已准备独立冻结outputs/analysis/20261005_cluster_from_zero/：当前global-cluster-v1和新CARD_CONTRACT，空Global/Video，Video冻结，Train343/Gate90/保留71历史闭题split；3epochs/batch8/patience3/seed20260928/1200words，GLM optimizer既有授权，35B Actor/coverage Selector/RRF8既有GPU4–7及Embedding8110。无CCQA/API Judge或手写卡导入。拥有者controller依次train、holdout_empty、holdout_final，新cache/source/config/split身份冻结，runner先数据审计再模型。非独立Test/跨benchmark/保证收益。协议analysis/skill_evolution/cluster_from_zero_20261005.md，查保存status与日志，恢复仅用拥有者冻结controller，勿改旧实验。cluster README清理当前作者字段/独立上限过期描述。

2026-10-06 zero进化初次在seed_gate失败：controller缺__main__保护导致spawn子进程重复训练争抢lock，90题worker exited、两试180错误，无成功prediction/Train批次/作者调用，不能当QA退化。10簇已建，state0。保留原src/config/controller及失败，新增guarded recovery_controller.py（__mp_main__导入检查通过），重验四服务后按原身份resume；initial_worker_failures/summary/provenance保留。新的拥有者recovery_controller.py，查status/recovery日志，无服务替换/锁重置。协议cluster_from_zero_20261005.md更新。

2026-10-06按用户要求精简new_Skill_Evolution_Design.md为165行算法说明：删除Skill/库格式重复介绍、重复伪代码和五轮虚构详例，保留六步流程、诊断表、Cal/池/Gate决策、预算/缓存/恢复及简短状态转移例；更新过期字符上限为沿用现有word预算，明确未部署。仅文档编辑，当前zero进化冻结源/控制器/服务保持，结构及核心约束检查通过，无Runtime/prompt改动。

2026-10-06按用户要求保留清晰伪代码与模拟运行：new_Skill_Evolution_Design.md补六步主循环、五轮父版/搜索池/Gate状态表、唯一12题评分fixture。降分L3有两题互补（与配置一致），不部署却可继续修用途；第五轮子集在生成前纳入Q3。核验总分6/7/8/7/10/11、小集与互补计数一致；仅设计文档，未改当前运行实验。

2026-10-06完善new_Skill_Evolution_Design.md鲁棒性设计，六步框架与单卡候选/严格正增益Gate不变：区分事实和归因假设，历史关键证据在当前父库核实；真实检索/选择检查跨卡干扰，WHEN/STRATEGY保持范围一致；Cal固定分层且不混入Train，互补收益按预定配对复测并记录来源集中；探索预算与最终验收预留，实际请求缓存及任务恢复记账。同步伪代码和模拟T3/Q3隔离说明，链接/结构/评分fixture检查通过。仅文档，未部署新算法，当前zero进化冻结源/控制器/服务未改。

2026-10-06按用户要求补充new_Skill_Evolution_Design.md模块职责表：reflect/generator/reviser三optimizer阶段与10项程序职责的输入、输出、调用位置，明确职责名不等于新增文件或已实现Schema；六步标题/主伪代码/模拟运行统一使用模块名。reflect有界补测经diagnostic_probe→rollout→evidence回送，WHEN/STRATEGY共用reviser，candidate_builder分配ID并校验，selector仍属于在线rollout。13模块覆盖/链接/六步结构/模拟评分核验通过；仅文档，当前冻结实验不改。

2026-10-06按用户要求从新流程重新划分new_Skill_Evolution_Design.md，替代此前沿用旧阶段的建议：issue_analyzer不读卡库、分析轨迹事实和假设；edit_planner结合相关卡/实际路由与有界补测确定ready/probe/skip计划；card_author统一WHEN/STRATEGY/NEW模式且只输出可变字段，candidate_builder先验计划再复制冻结字段/构建库。文档列明三种划分的取舍、旧实现可复用原则和须重写的Schema/调度，正常三optimizer阶段及其额外成本需同预算验证。六步框架/Cal池/Gate保持，伪代码/模拟同步，新模块覆盖、链接和模拟数据核验通过；仅下一版设计，未改当前冻结实验或Runtime/prompt。

2026-10-06按用户确认更新new_Skill_Evolution_Design.md：核心模块简名analyzer/planner/generator/reviser，生成与修订保留独立Prompt和Schema、共享内容规范和基础设施；正常单轮调用analyzer→planner→一个作者。optimizer表格删除位置与权限列，仅模块/输入/输出；流程/复用边界/伪代码/模拟同步，移除此前card_author合并建议。名称/三列表格/六步结构/作者分支/链接/模拟总分检查通过；仅文档，未改Runtime或冻结实验。

2026-10-06按用户要求删除new_Skill_Evolution_Design.md的划分依据整节，后续模块说明依次重编号0.1–0.3；四模块契约和六步流程保持。仅文档。

2026-10-06按用户要求简化new_Skill_Evolution_Design.md：删除Cal_small/Cal_mid分层及子集取样/晋级，所有有效候选直接评价固定完整Cal；同步cal_evaluator契约、参数、伪代码、恢复身份和模拟表格，作者前预留完整评价及最终Gate预算。完整Cal降分互补留存与严格正增益Gate保持。分层残留/六步结构/链接/模拟表格与总分检查通过；仅文档，当前冻结实验不改。

2026-10-06用户截图提示旧Cal分级参数残留，复查磁盘目标文档与非冻结src/analysis/configs文档，未检出截图旧行或相关分层规则；进一步删除起始参数表中重复Cal评价行。目标文档分层关键词/模块与伪代码/模拟完整Cal总分核验通过；历史变更记录与冻结输出保持。

2026-10-06进一步检查新设计文档的评价语义，清理模拟仍有的“预先纳入Q3”表述，明确Q3自实验开始就在固定完整Cal中；验收条款分别说明完整Cal搜索池留存与严格正增益Gate正式接受，统一完整Cal命名和模块输入。正文/表格/伪代码/模拟逐段核对，分层/扩评/诊断后加题残留检查及模拟总分通过；仅文档，冻结运行保持。

2026-10-06按用户指定格式改写新设计文档四个optimizer模块：analyzer/planner/generator/reviser各设独立小节，按输入/作用/输出列点，原表格和重复解释整合入对应模块。职责、输出契约与主流程保持；四模块结构及六步框架检查通过，仅文档。

2026-10-06按用户要求将新设计文档四个模块名提升为三级标题，输入/作用/输出保留内部加粗标签；模块总称改为加粗引导，同级控制/复用标题去掉过期小节编号。仅文档标题层级调整。

2026-10-06: cluster_v2 is copied from cluster and registers global-cluster-v2. Its four optimizer modules are analyzer/planner/generator/reviser, each with prompts and Schema; Chinese mirrors live under global/cluster_v2/chinese_prompts/ and the general prompt document indexes them. Training requires explicit nonempty source-disjoint train/cal/eval (Gate); Test remains evaluate-only. Train+Cal fixed input groups, card-free analyzer, bounded one-time diagnostic static-policy probes, WHEN/STRATEGY field locks, complete Cal paired repeats, weighted complement/finite exploration pool, periodic strict-positive Gate and final reserve are implemented. State is cluster_v2_evolution/state.json with pending round and idempotent task reservations; final_bank.json is Gate-accepted only. Recipe: configs/skill_evolution/global_cluster_v2_35b.yaml; tests: tests/test_global_cluster_v2.py. v2 rounds are optimizer rounds, not v1 epochs. Existing whole-bank rollout cache is reused; request-level/cross-bank equivalent-execution cache is not implemented. No Runtime/model-service change or real v2 experiment was launched. The 20261005_cluster_from_zero v1 experiment was stopped at next_round24 on user request; artifacts retained.

2026-10-06 cluster_v2 structure cleanup: root implementation now comprises trainer.py (composition/main loop), optimizer.py (four stages plus candidate validation/build), evaluation.py (Evaluator owns rollout/Cal/Gate/probe dependencies), search.py (scheduler/pool/state/budget), evidence.py and question_groups.py. Removed the eight superseded small modules without forwarding aliases. Prompt/Schema packages remain independent and model-visible text unchanged. Detailed design moved to cluster_v2/docs/design.md; flow.md merged into README, Chinese assembly explanation merged into chinese_prompts/README.md. Configs, algorithm behavior and persisted artifact layout unchanged; use frozen sources to resume historical runs.

2026-10-06 cluster_v2 real engineering smoke authorized and launched from an empty bank: outputs/analysis/20261006_cluster_v2_smoke/. Frozen old-Train development sources only, CrossVid BU/CC Train8/Cal4/Gate4, no Test, declared groups/content audit disjoint; 3 rounds, one candidate per round, one predeclared repeat per complete Cal/Gate. Actor35B-A3B GPU4–7 cap1, GLM-5.3-Flash optimizer, closed official scoring, no Judge API. Guarded owning controller and frozen source/config/split/provenance; inspect saved status and resume only that controller. First startup failed because stopped v1 left endpoints quarantined; existing ModelPool identity/empty-queue/inference checks recovered all4 without service restart or lock reset, then same-identity resume. Completed after same-identity recovery in509.57sec:3 rounds,2 valid NEW candidates eachCal2/4, no pool retention/acceptance, final empty bankGate1/4.9 optimizer stages validated; no runtime fatal/invalid. Completed-state resume added no inference events. Reviser, candidate Gate acceptance and exploration paths were not exercised by this real smoke. See analysis/skill_evolution/cluster_v2_smoke_20261006.md; this is pipeline verification, not evidence of generalization gains.

2026-10-06 cluster_v2 simplification: diagnostic probe branch removed on user request, including static-policy adapter, executor override, replanning, contrasts evidence, max_probe_cases config and probe/alternative output fields. Current planner status is ready/skip only; insufficient causal evidence skips authoring, and each round calls planner at most once. Analyzer→planner→generator/reviser, complete Cal/search-pool/strict-positive Gate remain. Prompts, Schema, Chinese mirrors, README and docs/design.md updated together. Historical real smoke artifacts and sources remain frozen; resume them only with their owning controller, not current source.

Validation for the cluster_v2 branch removal:59 affected CPU unittest cases passed (v2, cluster v1, adaptor and bank infrastructure); full source/tests/scripts compileall passed. Current v2 source/config/design/mirrors contain no diagnostic-branch remnants. No new model experiment launched for this change.

2026-10-06 cluster_v2 optimizer Prompt refinement: analyzer/planner/generator/reviser now follow adaptor's explicit task/input roles/analysis or authorship requirements/stage constraints/output format structure, with local illustrative examples. Clarifies decision-time evidence, fact/hypothesis separation, original-input scope, catalog vs full method, actual exposure vs adherence, and answer-result errors vs actionable Global guidance. Planner retains ready/skip and WHEN/STRATEGY/NEW; author schemas and field locks unchanged. Per-file Chinese mirrors and v2 README updated.59 affected CPU tests and compileall passed; rendered assembly/contract checks passed. No model rerun, so prior smoke results do not validate these new prompts.

2026-10-06 cluster_v2 original-input grouping audit complete: outputs/analysis/20261006_cluster_v2_grouping72/, frozen CrossVid old-Train sources9 closed tasks×8, Train54/Cal18, no originalGate/Test. Unique declared groups and media audit no partition overlap; development sample only. Existing8110 Qwen3-Embedding-8B,3 batches14,048tokens; no Actor/optimizer/Judge. Current unchanged KNN32/threshold.55/resolution2 yielded7 clusters(16/16/15/8/8/8/1), one isolated. Manual inspection found FSA/PSS method mixing and important MOC/MSR boundaries. Frozen input/vectors/source/provenance and all72 cases retained; report analysis/skill_evolution/cluster_v2_grouping72_20261006.md. No clustering parameter or evolution change deployed.

2026-10-06 grouping scale comparison: current v2 replays historical383 input-only grouping exactly using frozen cached vectors; v1/v2 question_text and build AST match. Restricting those exact historical vectors/texts to the current72 IDs reproduces all7 current clusters/members exactly, zero new embedding calls. Prior each-type40 allowed same-type top32; now each-type8 offers only7 same-type neighbors and threshold.55 retains cross-type edges. This demonstrates node-set/scale sensitivity, not v2 implementation drift. Details appended to analysis/skill_evolution/cluster_v2_grouping72_20261006.md; controls under the same output root/comparison/. No parameter/production changes.

2026-10-06 offline clustering comparison: outputs/analysis/20261006_clustering_methods/ contains30 configs×18 datasets=540 fits using frozen original-input embeddings, zero model requests. Compared current/conservative Louvain, average/complete linkage, Leiden CPM and HDBSCAN on anchor72,5 nested resamples each of72/144/215, full343 closed CrossVid and historical mixed843. Extra libraries isolated under /tmp/mvagent-clustering-libs; project/service dependencies unchanged. Louvain k8/cosine.60/resolution2 is a promising conservative candidate: five72 resamples native-category pair precision/recall97.37/89.68%, FSA/PSS separated throughout; mixed843 prior purposive negative pairs0/3 merged vs original3/3, positive4/6 retained in both. Fragmentation grows: full343 pair recall55.98%,26 groups/5 singletons, residual MOC/MSR mixing. Native labels are proxies, cross-task ordering can legitimately share methods;10 manual pairs are not representative gold/Test. All540 assignments independently checked. Report analysis/skill_evolution/clustering_methods_20261006.md. No production clustering/config/Prompt change deployed.

2026-10-06 CrossVid-only larger grouping diagnostic completed: outputs/analysis/20261006_crossvid_large_clustering/,10 native categories,400-per-category cap exceptPI251 (3851 unique; not full9015).1000/2000 nested resamples×3, full3851, proportional1600 and CCQA-excluded900/1800/3451 controls;13 configs×11 panels=143 fits.121 localEmbedding requests715816 tokens,0 errors; no Actor/Selector/optimizer/Judge. All memberships/metrics independently verified. Currentk32/.55/res2 pair precision/recall98.54/56.16% on3851; conservativek8/.60/res2 96.97/18.63%,288 groups/177 singletons. Closed3451 control current98.77/48.54 vs k8 98.29/18.22%; no universal k8 recommendation. Native categories are proxies:MSR370/397/587 are counting questions legitimately nearMOC. Other mixed quantitative groups still need method-level review. Report analysis/skill_evolution/crossvid_large_clustering_20261006.md; development-only, no independentTest/Skill/QA evidence, no production parameter or service change.

2026-10-06 focused CrossVid HDBSCAN sweep completed: outputs/analysis/20261006_crossvid_hdbscan/, frozen existing3851 vectors, zero model requests.60 configs on5 panels plus3 shortlisted configs on5 follow-up panels=315 fits; all assignments/pair metrics/noise singleton contracts independently verified, script compile checks passed. Promising EOM min_cluster_size3/min_samples2/epsilon.06:3851 category-pair precision99.73%,recall51.47%,770 noise vs original HDBSCAN99.97/26.91%,1108 noise; currentLouvain98.54/56.16%,22 singletons.1000/2000 three overlapping resamples precision99.92/99.86%,recall49.15/50.12%.Closed3451 HDBSCAN recall57.52 vsLouvain48.54 but620 noise. epsilon.10+ causes substantial method mixing; epsilon.30 combines1937 BU/CC/CCQA/NC/PSS questions.72 anchor still mixesMOC/MSR (78.38% proxy precision), no universal replacement. Report analysis/skill_evolution/crossvid_hdbscan_20261006.md; development-only/category proxies/no independentTest/QA gain. No production dependency/config/Prompt changes.

2026-10-06 cluster_v2 design clarification: docs/design.md section1.1 now proposes method-consistent core cases, cross-topic generalization cases and separate boundary cases, then local Train grouping refinement. Clustering serves shared Skill induction; topic diversity only supports scope when the core method transfers. Four optimizer modules and fullCal/search_pool/strict-positiveGate retained; online selector never reads groups. Generated/accepted Skill or actual selection is not grouping truth; structural edits require original-input method evidence, bank-dependent associations are version-bound. Initial implementation order is dynamic material selection then persistent split/move, with unknown/small groups preserved and no new probe branch. This section is explicitly unimplemented; current code/Prompt/Schema still use fixed grouping. README/design smoke-status prose corrected; documentation only, no model runs. Preserve historical frozen experiments.

2026-10-06 user correction supersedes the preceding LLM-assisted grouping proposal: cluster_v2 docs/design.md section1.1 now proposes embedding-driven, variable-K prototype iteration inspired by DP-means, using changed when_to_use embeddings as bounded auxiliary information while preserving frozen question embeddings and member-center compatibility. No extra analyzer/planner analysis or new classification output; four optimizer Prompt/Schema responsibilities stay current. Assignment/center updates, automatic birth of unmatched groups and removal of empty groups are numerical; no target cluster count or count-driven merges. Cal-retained candidate branches carry their own bank-bound grouping snapshot; raw vectors shared; Gate/Test excluded. Plain fixed-vector iterations alone do not ensure semantic improvement, and cosine/Skill extensions do not inherit original DP-means convergence guarantees. README updated; previous section replaced, not appended as parallel design. Documentation only, current Runtime/evolution code remains fixed grouping, no model run.

2026-10-06 current user constraint: only GPU6/7 models may be used. Read-only identity verification found Qwen3.5-35B-A3B replicas8100/8001 eachgpu-memory-utilization.85, and Qwen3-Embedding-8B8110 TP2 on6,7 with.12 (user-deployed; no service restart). Bounded short/structured/13805-token/2-second-video requests on each replica plus concurrent32-inputEmbedding passed;117 input-only scope prototype calls completed, postflight passed. Initial256-output-token preflight truncated JSON, controlled replayfinish_reason=length; actual2048 output config passed. Historical.9 and4–7 pool profiles do not match current services; do not silently reuse them or touch GPU0–5.

2026-10-06 standalone variable-K grouping experiment complete: outputs/analysis/20261006_dynamic_embedding_clustering/,150 fits (90 geometry DP-means,18 generated-scope feedback,24 Louvain-warm-start,18 existing11-scope anchors), frozen CrossVid72/1000/2000/3851/proportional1600. No Actor/QA/Cal/Gate/full evolution/API optimizer/Judge. Only GPU6/7 local scope-author/Embedding traffic. Numerical objectives nonincrease but two feedback rounds had negligible or adverse category-pair changes;1000 lambda.5 precision/recall72.73/53.91→72.70/53.84%,3851 97.51/52.39→97.50/52.18%. Existing scopes also fragment warm groups; no deployment or universal impossibility claim. Threshold/order/initialization sensitivity remains; native labels are proxies.150 memberships/metrics/source hashes independently verified; retained code/source snapshots and Chinese prototype Prompt mirror. Report analysis/skill_evolution/dynamic_embedding_clustering_20261006.md. Current implementation remains fixed grouping.
