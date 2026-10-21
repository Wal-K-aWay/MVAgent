# MVAgent evaluation

`eval/` owns batch evaluation, dataset contracts, scoring, aggregation and split preparation.
`agent_eval/` runs MVAgent on locally supplied CVBench, MVU-Eval and CrossVid data. See the
[root walkthrough](../README.md) for CrossVid preprocessing, fixed inference and
CCQA judging, and [the runner guide](agent_eval/README.md) for all CLI options.

| Entry | Purpose |
|---|---|
| `benchmarks/` | Dataset loading, sample contracts, official scoring, aggregation and Judge protocol |
| `data.py` | Frozen split manifests and media-source grouping |
| `agent_eval/run.py` | Freeze inputs/configuration, run MVAgent and score closed tasks |
| `agent_eval/serve_ccqa_judge.sh` | Start the fixed local CCQA Judge |
| `agent_eval/score_crossvid_ccqa.py` | Judge saved CCQA answers with the existing protocol |
| `agent_eval/finalize_results.py` | Merge deferred scores and report final metrics |
| `agent_eval/export_results.py` | Export saved answers and text trajectories |
| `agent_eval/metadata/CVBench.json` | Annotation metadata for preparation and reporting |
| `crossvid_2500.json` | Frozen list of 2,500 CrossVid evaluation IDs |

Dataset paths are relative to the `--dataset-root` parent directory:

```text
DATA_ROOT/
├── crossvid/       # QA/, videos/, uav/; preprocessing creates qa.jsonl and media
├── cvbench/        # QAs.json and original media paths
└── mvu-eval/       # QAs.json and original media paths
```

Supply only the benchmarks selected by `--benchmarks`. To build CVBench/MVU-Eval
question manifests from locally available annotations and media:

```bash
python scripts/prepare_cvbench_mvu_qas.py \
  --mvu-source "$DATA_ROOT/mvu-eval/MVU_Eval_QAs.json" \
  --cvbench-output "$DATA_ROOT/cvbench/QAs.json" \
  --mvu-output "$DATA_ROOT/mvu-eval/QAs.json" \
  --cvbench-media-root "$DATA_ROOT/cvbench" \
  --mvu-media-root "$DATA_ROOT/mvu-eval"
```

The retained CVBench annotation source is documented in
[metadata/README.md](agent_eval/metadata/README.md). Media paths in generated
`QAs.json` are resolved relative to each benchmark directory.

Use the existing
[frozen split manifest](../configs/skill_evolution/splits/crossvid_lite2500_eval_seed20260919.json)
with `--split-manifest` to select CrossVid Lite2500. Do not resample it for a score
comparison. Raw answers are saved before scoring; Judge failures remain errors.
CrossVid's primary score is the ten-task macro average, with CCQA weighted by
scoring-point count within its task. Final deferred-score summaries are in
`summary_scored.json` and `benchmark_results.md`.

Historical E2E and other-method implementations remain in Git history, and their
published result attachments remain in Releases. They are not required to run
MVAgent. Historical findings and protocol differences remain in
[the experiment record](../docs/experiments.md).

## Code boundary and reproducibility

`src/` implements MVAgent, model adapters and skill methods. It has no dependency
on `eval/`. The batch runner calls MVAgent's existing execution API and imports
`eval.benchmarks`; data preparation scripts use `eval.data`. Generic JSON and hash
utilities live in `src/mvagent/utils/io.py`, shared with skill generation.

New runs freeze both `src/` and the supported `eval/` code into their output directory.
The saved runner is `eval/agent_eval/run.py`; the run identity records separate hashes
for runtime and evaluation source. Resume imports the frozen evaluation package and
rejects changed snapshots. Historical runs continue using their own frozen source;
the new entry does not adapt old snapshot layouts.

This directory relocation preserves the scoring formulas, Judge prompts and model
settings. Existing inline and deferred Judge workflows remain distinct; their
protocol implementation is not rewritten by this move.
