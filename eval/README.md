# MVAgent evaluation

`eval/` owns batch evaluation, dataset contracts, scoring, aggregation and split preparation.
`agent_eval/` runs MVAgent on locally supplied CVBench, MVU-Eval and CrossVid data. See the
[root walkthrough](../README.md) for CrossVid preprocessing, fixed inference and
CCQA judging, and [the runner guide](agent_eval/README.md) for all CLI options.
For a fresh server, the [data acquisition and preparation guide](../docs/data-preparation.md)
provides official download sources, pinned revisions, directory layouts and known media issues.

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
| `skill_eval/run.py` | Freeze and resume rolewise experiments; reached through `scripts/evolve_skills.py` |
| `skill_eval/evaluator.py` | Run complete libraries on Train/Cal/Gate through the native runner and official scoring |
| `skill_eval/selector_probe.py` | Diagnose Selector choices without measuring answer accuracy |
| `crossvid_2500.json` | Frozen list of 2,500 CrossVid evaluation IDs |

For skill research, the call chain is:

```text
scripts/evolve_skills.py
  → eval/skill_eval/run.py                  # freeze inputs and construct the evaluator
  → src/skill_evolution/algorithms/rolewise # propose edits and accept/reject libraries
  → eval/skill_eval/evaluator.py           # complete partition evaluation
  → eval/agent_eval/run.py                 # MVAgent rollouts and official scoring
```

The algorithm receives the evaluator as an interface; `src/` does not import `eval/`.
To measure a fixed library, use `agent_eval/run.py`; to generate new libraries through
feedback, use `scripts/evolve_skills.py`. Rolewise requires CrossVid-only
`train/cal/eval` partitions, each covering all ten tasks; its `eval` partition is Gate.
The native runner's `--split-manifest` selects only `eval`. See the
[server runbook](../docs/server-runbook.md) for commands and final score locations.

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


## Relocation validation

Source `3be6b13` was checked on Modal CPU: 27 regression cases passed across the
initial run and the targeted snapshot rerun, plus the token-audit self-check, full
Python compilation and eight CLI help calls from outside the repository directory.
The new snapshot check scores a synthetic sample, resumes after changing live
scoring code, and rejects an altered frozen snapshot. Skill generation imports
successfully with only `src/` on `PYTHONPATH` and no evaluation module loaded.
The benchmark implementation and generic I/O functions were moved byte-for-byte.
The first snapshot check needed Git added to the test image, and its scorer fixture
needed the existing required `open_qa_scorers` argument; neither changed scoring.
No model calls, GPU execution, media decoding or benchmark accuracy evaluation
were performed. Detailed check logs remain in the runs volume under
`devbox/eval_consolidation_20261021/`; the final check is in `checks3/`.
