# MVAgent benchmark evaluation

Global 主动选择 `answer` 时在同一决策中直接提交 `parameters.answer`；循环耗尽时复用 `decide(answer_only=True)`，保留决策 System、视频信息、公开 History 和既有 skill 策略，只允许提交答案。两条路径均保持开放非空答案、2048 输出 token、终答 reason 无字符硬限。User 顺序为 Question→Videos→Available actions→History；视频裁剪仍用 FFmpeg。基础采用已完成4500条测试的简洁 Global System 与原 VideoAgent。已有运行使用冻结源码，不热更新；新运行另建目录。

On the remote GPU host, install the project dependencies first: `uv pip install -r requirements.txt`
from the repository root; see [installation instructions](../../README.md).

This entry evaluates MVAgent on CVBench, MVU-Eval and CrossVid. It uses
`mvagent.batch.BatchExecutor`, the same question execution API used by Skill rollout.
Dataset/scoring adapters live in `eval/benchmarks`; workers receive
only the question and ordered videos, never reference answers.

Use `eval/agent_eval/run.py` for new evaluations. Historical matrix controllers are
preserved in their frozen runs and Git history; they are not general-purpose entry points.
Existing jobs resume with their own frozen sources. Historical completion and reuse
details are recorded in [the experiment log](../../docs/experiments.md).

The historical Qwen3.5 reference uses the [fixed evaluation configuration](../../configs/inference/README.md#固定评测方案):
8 H100 GPUs with independent full-model replicas and `seed=0`. The new H20 server can use a different number of replicas; configure its available allocation using the [server runbook](../../docs/server-runbook.md). The `modal_`/`h200` filenames do not require Modal, and cross-hardware output equivalence has not been established.

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
separately; see the [experiment record](../../docs/experiments.md).

GlobalAgent submits its final answer in the same decision: `reason`, `action="answer"`,
`parameters.answer`. Runtime returns the existing `{answer, reason, status}` result directly;
there is no separate final-answer prompt or model call. At the step limit, Runtime calls the
same decision interface with only `answer` available, preserving `forced_with_gaps` and the
`terminal_answer` trajectory marker. Evidence decisions still use a 1200-character reason;
answer decisions have no reason character cap. All responses retain the 2048-token budget,
and `parameters.answer` remains an open nonblank string with a 2400-character limit.

The Global System states the coordinator's role and visual evidence boundary. It preserves video
identities and requests one available action. VideoAgent receives its instruction and own history,
without an additional copy of the original question. The exact System and accepted results are in
[the experiment record](../../docs/experiments.md). Do not interpret historical standalone-answer or
Video-context experiments as supported runtime switches.

Contract checks live in [`tests/`](../../tests/README.md): direct answers, model-pool leasing,
token audits, cache accounting, score finalization and the short-video regression.
The model-pool check covers the Actor profile and per-question replica binding.
Normal evaluations reuse the accepted repeatability evidence instead of rerunning it every time.

Pass the parent dataset directory with `--dataset-root`. It contains `crossvid/`,
`cvbench/` and `mvu-eval/` subdirectories for the requested benchmarks
(names defined in `eval/benchmarks/catalog.py`); only the requested datasets are needed.
New researchers should follow the [data preparation guide](../../docs/data-preparation.md).
For CrossVid, the current entry downloads pinned inputs, restores the 2416 missing BU
videos from Hub history, verifies them, and writes `qa.jsonl`, `qa.meta.json` and
`.mvagent_media` under `crossvid/`:

```bash
export DATA_ROOT=/srv/mvagent/data  # Choose a writable directory with enough storage.
python scripts/prepare_crossvid_data.py --root "$DATA_ROOT/crossvid" \
  --download-workers 4 --pea-jobs 4 --uav-jobs 4
```

With complete original CrossVid inputs already present, use
`scripts/run_crossvid_qa_preparation.py` as described in that guide. Verify completion
using the current run's status and exit code; the presence of an old manifest alone
does not establish success.

For final CVBench/MVU-Eval evaluation, download their media first using the same guide,
then build both `QAs.json` files with the existing converter:

```bash
python scripts/prepare_cvbench_mvu_qas.py \
  --mvu-source "$DATA_ROOT/mvu-eval/MVU_Eval_QAs.json" \
  --cvbench-output "$DATA_ROOT/cvbench/QAs.json" \
  --mvu-output "$DATA_ROOT/mvu-eval/QAs.json" \
  --cvbench-media-root "$DATA_ROOT/cvbench" \
  --mvu-media-root "$DATA_ROOT/mvu-eval"
```

The converter uses frozen `eval/agent_eval/metadata/CVBench.json` and the downloaded
MVU annotations. Video paths are relative to each benchmark directory. CrossVid-only
work does not require this step. The older `prepare_all_multivideo.py` is not the
newcomer download entry: it requires all three datasets, does not restore deleted BU
media, and duplicates the CrossVid preparation wrapper. Its optional `--check-only`
mode checks layout only.

For a new H20 run, configure local replicas and paths using the
[server runbook](../../docs/server-runbook.md). The following is the **historical
35B configuration example**; `/assets` is the original data mount and its execution
file contains the historical GPU allocation:

```bash
PYTHONPATH=src python eval/agent_eval/run.py \
  --config configs/inference/modal_qwen35_35b_a3b_no_skill.yaml \
  --execution-config configs/inference/execution/modal_h200x8.yaml \
  --dataset-root /assets --benchmarks cvbench mvu_eval \
  --output /path/to/new-run
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
For Qwen3.5-9B, choose `configs/inference/modal_qwen35_9b_no_skill.yaml` and a resource file whose model-pool
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
coverage/correctness judging for CCQA. This directory evaluates the MVAgent system.

For a completed run with deferred CCQA records under `records/crossvid/`, start the fixed local Judge
(`serve_ccqa_judge.sh 0-7`: Qwen3-30B-A3B-Instruct-2507 on vLLM, one replica per GPU on ports
8100+), then run `score_crossvid_ccqa.py --output <run> --endpoints 8100-8107` and
`finalize_results.py --output <run>`. The scorer uses the CrossVid coverage/correctness
prompt, system message and sampling (temperature 0, top_p 0.95), validates scoring-point counts
and boolean values, caches response text and usage, and records the Judge weights in
`score/ccqa_scores_official_qwen3_30b_a3b.json`. Each replica serves one request at a time, so
the existing fixed judging protocol is preserved.
Finalization requires every deferred answer to match its scored prediction and writes
`summary_scored.json` plus `benchmark_results.md`; raw records and `summary.json`
retain their original deferred state. CrossVid's primary O.Avg is the ten-task mean,
with CCQA weighted by scoring-point count within its task.

## Analysis tables

Raw records are about 270 KB per question, mostly request/response events kept for audit and exact replay.
For analysis, run `python eval/agent_eval/export_results.py <run>` (standard library only, also on a
local copy of the records). It reads `records/` and `summary.json`, never modifies them, and writes `<run>/tables/`:

- `answers.jsonl`: one row per question with `sample_id`, `dataset`, `task`, `family`, `status`, `error`,
  `prediction`, `ground_truth`, `score`, `correct`, `outcome` (pass/partial/fail by the diagnostic
  thresholds), `answer_valid` (prediction matches the task's answer form), `evidence_actions`,
  `n_evidence_actions`, `first_action`, `stop` (`answered` or `forced_with_gaps`), `time_sec`,
  `prompt_tokens`, `completion_tokens`, `global_skill` (selected card IDs, or null without a dynamic bank).
- `cases.jsonl.gz`: public trajectories exported by `export_results.py`: question without the generic
  benchmark wrapper, options, video durations, evidence steps with instructions and VideoAgent summaries,
  final and correct answer, outcome.
- `scores.json`: official score per benchmark (copied from `summary.json`) and per-task counts, mean
  score, outcome counts and answer-validity rate.

For runs using deferred CCQA judging, the original records and `summary.json` remain
deferred even after judging. The exporter does not merge the separate Judge file.
Use `summary_scored.json` and `benchmark_results.md` for final metrics; join the saved
CCQA scores by question ID when analyzing per-question judged results.


The runner freezes `src/` plus the supported `eval/` modules. Its frozen entry is
`<output>/eval/agent_eval/run.py`; `run_manifest.json` records both runtime and
evaluation source hashes. Scoring imports are pinned to `<output>/eval/` on first
execution and resume, even if live evaluation modules were imported beforehand.
Older runs must use their original frozen source and layout.
