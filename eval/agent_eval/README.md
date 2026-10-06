# MVAgent benchmark evaluation

Install the project dependencies first: `python -m pip install -r requirements.txt`
from the repository root; see [installation instructions](../../README.md).

This entry evaluates MVAgent on CVBench, MVU-Eval and CrossVid. It uses
`mvagent.batch.BatchExecutor`, the same question execution API used by Skill rollout.
Dataset/scoring adapters live in `skill_evolution/infra/benchmarks`; workers receive
only the question and ordered videos, never reference answers.

On a new server, after downloading the three benchmark directories, prepare the
dataset root once:

```bash
PYTHONPATH=src /home/kww/miniconda3/envs/MVAgent/bin/python \
  scripts/prepare_all_multivideo.py --root /data/Multi-Video
```

This generates CrossVid's `qa.jsonl`, `qa.meta.json` and `.mvagent_media`.
CVBench and MVU-Eval use their raw `QAs.json` and `videos/`; MVAgent creates its
runtime media cache on demand.

```bash
PYTHONPATH=src /home/kww/miniconda3/envs/MVAgent/bin/python eval/agent_eval/run.py \
  --config eval/agent_eval/config.yaml \
  --execution-config configs/inference/execution/gpu5_7.yaml \
  --benchmarks cvbench mvu_eval \
  --output outputs/mvagent_pool_eval
```

There is no implicit GPU selection. The execution YAML lists the allowed model
replicas, their physical GPU indexes or UUIDs, endpoints and `max_inflight` limits.
GPU numbers need not be consecutive. Each CPU worker owns one question at a time;
each model call can use a different matching replica. `question_workers: auto`
equals the healthy Agent-service capacities (6 for the supplied three-replica pool).
`max_prepared_requests: auto` bounds media preparation to twice that capacity.
`runtime.video_concurrency` in MVAgent YAML separately controls parallel VideoAgents.

For all three benchmarks, include `crossvid` and explicitly name the Judge:

```bash
PYTHONPATH=src /home/kww/miniconda3/envs/MVAgent/bin/python eval/agent_eval/run.py \
  --config configs/skill_evolution/runtime/local_qwen35_35b_a3b_qwen38_optimizer_gpu5_7.yaml \
  --execution-config configs/inference/execution/gpu5_7.yaml \
  --benchmarks cvbench mvu_eval crossvid \
  --judge-model qwen3_8_27b_optimizer \
  --output outputs/mvagent_all_benchmarks
```

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

For four Qwen3.5-9B replicas on GPUs 4–7, use
`--config eval/agent_eval/config_qwen3_5_9b.yaml`
`--execution-config configs/inference/execution/qwen35_9b_gpu4_7.yaml`
`--judge-model qwen3_5_9b_local`. This resource profile uses eight question workers
and two admitted requests per replica. Always choose a fresh `--output` for a new
comparison; keep historical results and their frozen source untouched.

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

For a completed deferred run with `open_qa_pending.jsonl`, set `DEEPSEEK_API_KEY`
in the environment, then run `score_crossvid_ccqa.py --output <run>` and
`finalize_results.py --output <run>`. The scorer uses the CrossVid coverage/correctness
prompt, validates scoring-point counts and boolean values, and caches returned model,
response text and usage. Requested model aliases may resolve to newer provider models.
Finalization requires every deferred answer to match its scored prediction and writes
`summary_scored.json` plus `benchmark_results.md`; raw records and `summary.json`
retain their original deferred state. CrossVid's primary O.Avg is the ten-task mean,
with CCQA weighted by scoring-point count within its task.
