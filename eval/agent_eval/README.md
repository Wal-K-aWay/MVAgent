# MVAgent benchmark evaluation

Global 主动选择 `answer` 时在同一决策中直接提交 `parameters.answer`；循环耗尽才调用独立回答器，输入为原问题和已保留的公开 History，返回 `reason/answer`。两条路径均保持开放非空答案、2048 输出 token、终答 reason 无字符硬限。决策 System 保留当前指导规则，User 顺序为 Question→Videos→History→Available actions；视频裁剪仍用 FFmpeg。已有运行使用冻结源码，不热更新；新运行另建目录。

Install the project dependencies first: `python -m pip install -r requirements.txt`
from the repository root; see [installation instructions](../../README.md).

This entry evaluates MVAgent on CVBench, MVU-Eval and CrossVid. It uses
`mvagent.batch.BatchExecutor`, the same question execution API used by Skill rollout.
Dataset/scoring adapters live in `skill_evolution/infra/benchmarks`; workers receive
only the question and ordered videos, never reference answers.

The full three-model comparison uses `scripts/run_full_mvagent.py --output /runs/devbox/mvagent_full_20261013`.
It freezes the current source, reuses the completed E2E selections (997 available CVBench,
1824 MVU-Eval and CrossVid Lite2500), runs one pass per model through this CLI, then applies
the existing local CCQA Judge. `comparison.md` and `comparison/<model>.json` pair the exact
IDs with E2E scores; CVBench uses the same 997-question mean, and CrossVid uses the ten-task
macro with point-weighted CCQA. Partial coverage is explicitly marked.
The companion `scripts/watch_full_mvagent.py` runs only on `modal-gpu` and continues the
frozen run across Sandbox time limits. Do not submit another controller while it is active.
See the [full-run record](../../outputs/mvagent_full_20261013/README.md) for live paths,
shutdown instructions and the distinction between system comparison and equal-budget evaluation.

Subsequent Qwen3.5 evaluations use the [fixed evaluation configuration](../../configs/inference/README.md#固定评测方案):
8 H100 GPUs with independent full-model replicas and `seed=0`. The `h200` execution-file
names are historical; request `H100!:8` explicitly for this evaluation protocol.

The three `configs/inference/modal_qwen35_*_no_skill.yaml` files and the skill-evolution
35B Actor configuration select `execution_profile: qwen35-bf16-flashinfer-sync`.
The shared implementation is [`src/models/vlm/local/sync_server.py`](../../src/models/vlm/local/sync_server.py):
BF16, TP1/DP1, one in-flight request per GPU, synchronous in-process eager execution,
FlashInfer GDN prefill and native GemmaRMSNorm. Versions, context length (131072),
prefill budget (32768), memory fraction (0.94) and disabled prefix/MM processor caching are fixed
there. Standard decode KV caching remains enabled.
Per-request `usage.prompt_tokens_details.cached_tokens` and `cache_hit_rate` are saved in model_response events.
This is the only supported evaluation profile. Cache counters remain observable and are zero with prefix caching disabled. Conflicting configuration is rejected.
The local service manager starts this server directly; it validates existing service
metadata before reuse. Each complete question leases one replica, including all
GlobalAgent, VideoAgent and Selector calls. Parallel videos share that serial lease.

Actual output token IDs, request/input/prompt hashes, finish reasons and worker
identity are recorded and validated by default for this profile. Ordinary local
vLLM configurations retain the diagnostic opt-in `MVAGENT_RECORD_TOKEN_IDS=1`.
For repeatability checks without accuracy scoring or Judge calls, add `--inference-only`;
records then have `scoring_status: skipped`. Existing CLI arguments remain supported.
Use a fresh output directory after changing execution profiles; resume uses frozen source.

Inference keeps the validated `seed=0` for every run; it does not change with the date.
Routine evaluations need only one pass, with the existing identity/input/token audit.
Repeat a small affected check after changes to weights, numerical settings, dependencies,
hardware type, concurrency, preprocessing or inference routing, or after new failure evidence;
new questions alone do not require another repeatability matrix. These finite checks are
evidence for the tested configuration, not a universal determinism guarantee.
New sampling/shuffling uses seed 0; reuse existing frozen sample manifests with their original
data seeds. A data-sampling seed is separate from the model's inference seed.

The supplied Actor configurations now wait 1860 seconds per request (the shared server
limit is 1800 seconds), and the supplied execution YAMLs allow 7200 seconds per question.
This changes wall-clock limits only, preserving the model, generation budget and Agent policy.
`status: ok` records a completed runtime call; it does not establish answer-format validity.
The answer action schema accepts any nonblank answer string, including invalid
choice/interval answers. Report model/structured errors, repeatability and answer format
separately; see the [current runtime check](../../outputs/validation_history.md#mvagent_runtime_check_20261013-readme).

GlobalAgent submits its final answer in the same decision: `reason`, `action="answer"`,
`parameters.answer`. Runtime returns the existing `{answer, reason, status}` result directly;
there is no separate final-answer prompt or model call. At the step limit, Runtime calls the
same decision interface with only `answer` available, preserving `forced_with_gaps` and the
`terminal_answer` trajectory marker. Evidence decisions still use a 1200-character reason;
answer decisions have no reason character cap. All responses retain the 2048-token budget,
and `parameters.answer` remains an open nonblank string with a 2400-character limit.

A single Global System policy preserves task definitions, checks material evidence conflicts,
and asks for concise decision explanations. The answer action submits the best-supported
judgment in the requested form; uncertainty belongs in its explanation. Selected skill text
is visible to these decisions, including direct answers. Public trajectories now expose the
submitted answer parameter; ordinary answer-parameter faults can be localized by the optimizer.

This changes the answer protocol and may change upstream choices as well as answers. Use a new
output directory and compare empty/evolved skill banks with the same protocol. Running jobs
and resumes continue using their original frozen sources. The prior 25-question fixed-evidence
comparison is a development diagnostic, not the accuracy of this full integration; see the
[protocol comparison](../../outputs/answer_ablation_20261015/README.md).
Current integration checks use `scripts/test_direct_answer.py` and `scripts/verify_direct_answer.py`.

Historical standalone-answer prompt, reason-budget and repeatability experiments retain their
original evidence in the [validation history](../../outputs/validation_history.md) and dated
reports. Their results do not certify the new direct-answer protocol.

The small formal HTTP regression (`scripts/verify_formal_repro.py`, 2026-10-12) passed:
all three BF16 models completed two questions twice through this public CLI, totaling
12 trajectories and 256 model calls. All six trajectory comparisons and 128 paired
call comparisons matched, including inputs, complete tokens, text and finish reasons;
there were no model or structured-validation errors. Two H100 replicas were used per
model, sequentially; eight-replica throughput and nonempty skills were not retested.
See the [formal integration report](../../outputs/validation_history.md#formal_repro_integration_20261012-readme);
the expanded experiment below describes its diagnostic transport separately.

The expanded Agent check (2026-10-12, completed) makes
`confirm_vllm_repro_fix.py` reuse the fixed E2E `ENGINE_CONFIG` and `ENVIRONMENT`:
FlashInfer GDN, native GemmaRMSNorm, memory fraction 0.94 and expandable segments.
`run_mvagent_replica_repro.py --panel ...` accepts a frozen larger panel;
`--max-steps 10` increases both Agent decision limits for a separate long-task
stress run. The regular panel keeps five steps. Both retain the original prompts,
2048-token call budget, 512-frame limit and intermediate-call/trajectory auditing.
That expansion used the in-process diagnostic transport; those test drivers did
not change the production service. The subsequent formal integration is described above. Do not mix its results with the older profile.
All three BF16 models completed 66 questions over four passes, plus a separate
eight-question stress panel over four passes: 888 trajectories and 11,544 model
calls in total. The 666 complete-trajectory comparisons and 9,125 comparisons
grouped by identical request bytes all matched, including process restarts and
GPU rotation. Raw-record audits found no model errors or structural-validation
failures. The longest observed traces reached 37 calls or 10,152 output tokens
(different questions); 12 calls hit their unchanged output limit and repeated
identically. This does not establish answer-format compliance or correctness.
See the [regular Agent audit](../../outputs/repro_expanded_20261012/agent.md),
[identical-input audit](../../outputs/repro_expanded_20261012/identical_inputs_all.md)
and [expanded experiment](../../outputs/repro_expanded_20261012/README.md).
The 330-question E2E expansion is tracked separately there. These finite tests
do not establish determinism for every input, software version or hardware type.

Superseded inference-configuration results were retired on 2026-10-12.
See the [historical conclusions and cleanup record](../../outputs/validation_history.md#repro_cleanup_20261012-history).
Current regression inputs and provenance fixtures remain at their original paths.

The dataset root is the Modal asset Volume mounted at `/assets`, with `crossvid/`, `cvbench/` and
`mvu-eval/` subdirectories (names defined in `skill_evolution/infra/benchmarks/catalog.py`).
CVBench/MVU-Eval `QAs.json` are built by `scripts/prepare_cvbench_mvu_qas.py`; their video paths
are relative to each benchmark directory. CrossVid needs a one-time preparation that writes
`qa.jsonl`, `qa.meta.json` and `.mvagent_media` under `crossvid/`:

```bash
PYTHONPATH=src python scripts/prepare_all_multivideo.py --root /assets
```

Run inside a GPU node whose execution file lists that node's local replicas:

```bash
PYTHONPATH=src python eval/agent_eval/run.py \
  --config configs/inference/modal_qwen35_35b_a3b_no_skill.yaml \
  --execution-config configs/inference/execution/modal_h200x8.yaml \
  --dataset-root /assets --benchmarks cvbench mvu_eval \
  --output <fresh output dir>
```

There is no implicit GPU selection. The execution YAML lists the allowed model
replicas, their physical GPU indexes or UUIDs, endpoints and `max_inflight` limits.
GPU numbers need not be consecutive. Each CPU worker owns one question at a time;
the validated profile holds one matching replica for its complete trajectory. `question_workers: auto`
equals the healthy Agent-service capacities (8 for `modal_h200x8.yaml`).
`max_prepared_requests: auto` bounds media preparation to twice that capacity.
`runtime.video_concurrency` in MVAgent YAML separately controls parallel VideoAgents.

To include CrossVid, add `crossvid` to `--benchmarks`. CCQA is open QA: either pass
`--judge-model` naming a Judge defined in the model configuration, or pass
`--defer-open-qa-judge` and score afterwards with `score_crossvid_ccqa.py` (see below).

The Judge model must exist in the model configuration. A local Judge sharing an
Agent endpoint shares its request admission; an explicitly configured API Judge
keeps its API endpoint. The Judge is never inferred from the first GPU. The standard
model client handles requests; the authored OpenQA scoring prompt is unchanged.

`--limit N` selects N CVBench and N MVU-Eval questions, and N questions per CrossVid
task. Omit `--benchmarks` to select all three benchmarks. Both Skills default to off;
other fixed Skill configurations may be evaluated through the same execution path.
For Qwen3.5-9B, choose `config_qwen3_5_9b.yaml` and a resource file whose model-pool
name is `qwen3_5_9b_local`, with matching 9B services; incompatible running services
are rejected rather than replaced.

`--split-manifest PATH` selects CrossVid samples from the manifest's `eval` entries
while leaving the other requested benchmarks complete. It cannot be combined with
`--limit`; selected IDs are checked against the current CrossVid dataset, and the
manifest path and SHA-256 are recorded in the run identity for safe resume.

`--sample-ids-file PATH` selects an ordered JSON array of exact IDs across the
requested benchmarks, for paired diagnostic panels. Empty, duplicate, unknown or
excluded-benchmark IDs are rejected. It cannot be combined with `--limit` or
`--split-manifest`. The selected ordered ID hash/count are part of resume identity;
keep the input panel and its selection provenance with the experiment. This option
does not change question text, video order, runtime or scoring.

Always choose a fresh `--output` for a new comparison; keep historical results and
their frozen source untouched.

Append `--resume` with the same input/model/scoring configuration and output directory.
The execution file may select different GPUs or worker counts. The original runner
and Runtime snapshot remain fixed. Successful raw inference is reused, including
when only scoring needs retry. A fully completed run resumes without starting GPUs.

Raw results are saved before a separate scoring thread runs. Scoring errors remain
errors, never zero-valued successes. Per-question `worker.pid` identifies the CPU
process; request events record the actual endpoint and GPU UUID. Execution resources
are recorded per invocation under `executions/`; raw events are in
`execution_events.jsonl`. Results, progress and summaries remain under
`records/<dataset>/<sample_id>/`, `progress.json`, `summary.json` and `run_manifest.json`.

Scores keep the existing strict task contracts: uppercase options for CVBench/MVU
and CrossVid choice, `start,end` for FSA, `1->3->2->4` for PSS, and fixed
coverage/correctness judging for CCQA. This is an Agent-system evaluation; official
end-to-end runners under `eval/e2e_eval/` retain their own protocols.

For a completed run with deferred CCQA records under `records/crossvid/`, start the fixed local Judge
(`serve_ccqa_judge.sh 0-7`: Qwen3-30B-A3B-Instruct-2507 on vLLM, one replica per GPU on ports
8100+), then run `score_crossvid_ccqa.py --output <run> --endpoints 8100-8107` and
`finalize_results.py --output <run>`. The scorer uses the CrossVid coverage/correctness
prompt, system message and sampling (temperature 0, top_p 0.95), validates scoring-point counts
and boolean values, caches response text and usage, and records the Judge weights in
`score/ccqa_scores_official_qwen3_30b_a3b.json`. Each replica serves one request at a time, so
greedy judgements are reproducible. E2E runs use the same Judge (`eval/e2e_eval/README.md`).
Finalization requires every deferred answer to match its scored prediction and writes
`summary_scored.json` plus `benchmark_results.md`; raw records and `summary.json`
retain their original deferred state. CrossVid's primary O.Avg is the ten-task mean,
with CCQA weighted by scoring-point count within its task.

## Analysis tables

Raw records are about 270 KB per question, mostly request/response events kept for audit and exact replay.
For analysis, run `python eval/agent_eval/export_results.py <run>` (standard library only, also on a
local copy of the records). It reads `records/` and `summary.json`, never modifies them, and writes `<run>/tables/`:

- `answers.jsonl`: one row per question with `sample_id`, `dataset`, `task`, `family`, `status`, `error`,
  `prediction`, `ground_truth`, `score`, `correct`, `outcome` (pass/partial/fail by the skill-evolution
  thresholds), `answer_valid` (prediction matches the task's answer form), `evidence_actions`,
  `n_evidence_actions`, `first_action`, `stop` (`answered` or `forced_with_gaps`), `time_sec`,
  `prompt_tokens`, `completion_tokens`, `global_skill` (selected card IDs, or null without a dynamic bank).
- `cases.jsonl.gz`: public trajectories in the skill-evolution case format
  (`src/skill_evolution/algorithms/alternating/global/scope/views.py`): question without the generic
  benchmark wrapper, options, video durations, evidence steps with instructions and VideoAgent summaries,
  final and correct answer, outcome.
- `scores.json`: official score per benchmark (copied from `summary.json`) and per-task counts, mean
  score, outcome counts and answer-validity rate.

Deferred CCQA answers have `score: null` until judged; rerun the export after `score_crossvid_ccqa.py`.
