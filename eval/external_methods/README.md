# External video-agent smoke evaluation

Adapters for the released Video-RSI final harness, a locally generated initial MetaVideoAgent,
and Visual-Agentic-Memory (VAM). Upstream code lives in `reference/`; `sources.json` pins its
provenance. The Modal source snapshot includes `external_sources/` as well as all adapters.

On 2026-10-14 the user discontinued further MetaVideoAgent evaluation. Ongoing scoring
and subsequent evaluation scope retain Video-RSI and VAM only. Meta code and existing
outputs remain as historical artifacts; its unfinished panel is not resumed.

The first experiment uses Qwen3.5-35B-A3B BF16 with the existing synchronous v2 server,
seed/temperature 0, thinking disabled and prefix caching off (explicit user decision on
2026-10-14). Each question owns one replica. VAM also uses the original
Qwen3-VL-Embedding-8B through the official Qwen implementation, on a separate reserved GPU.
This is an adapted development smoke evaluation, not reproduction of published paper scores.

## Input and scoring

`prepare.py` selects one question per native task (seed 0, 33 questions: CrossVid 10,
CVBench 15, MVU-Eval 8). CrossVid is restricted to the existing Lite2500 manifest;
the three known corrupt CVBench inputs are excluded before sampling.

All methods use the same concatenated videos: original ordering, 448-pixel letterboxing,
30 fps, visual only. Every question includes original-video identities and measured segment
start/end offsets. Question and answer timestamps remain in the original video's coordinate
system. Re-encoding rounds individual durations to a 30 fps grid; the timeline records both
original and encoded durations. The three shortest selected questions (one per benchmark)
are the initial execution smoke panel, not a representative accuracy sample.

Answer-free input JSON and private labels are saved separately. Raw outputs precede
`score.py`, which reuses project official scorers and task-stratified aggregation. CrossVid's
full macro requires all ten tasks, including CCQA with the fixed local Qwen3-30B Judge.
Infrastructure failures are reported separately and never converted into zero-scored answers.
Meta's raw upstream `gt_answer` is intentionally empty; its derived `is_correct=false`
is therefore not an accuracy result. Only the separate official scorer uses private labels.

## Method-specific changes

- **Video-RSI:** use `artifacts/final_harness`, with original 11 steps, 256 total frame
  exposures and 8192 output tokens per model call. Both language and vision roles use local
  35B. The recorded patch replaces the single-choice-only answer boundary with a nonempty
  string, preserving multi-choice, ordering, localization and open answers. Frames use the
  project 448-pixel limit. Modal lacks Landlock: inference retains candidate seccomp and the
  outer Modal sandbox, but does not reproduce upstream's Landlock filesystem fence.
- **MetaVideoAgent:** use official unlabeled five-frame distribution profiling, codegen
  context, ABI validation, module injection and runtime. Local Qwen generates and repairs
  the bundle; the initial three profile questions have no labels and remain development
  inputs. No evolution rounds or held-out claim. LLM/VLM/OCR use local Qwen; audio and
  embedding capabilities are marked unavailable in this visual-only initial profile.
  The transport fixes numerical generation settings; upstream request token budgets remain.
  A completed answer must also pass upstream behavioral assessment. Early bundles that
  returned a hardcoded `A` after tool errors are excluded from valid predictions.
- **VAM:** preserve its 0.5 fps extraction, adaptive filtering, original visual embedding,
  hierarchical memory, event finalization and agentic retrieval. Only model transports and
  the temporary-file location change. Data URIs are decoded to PIL images before the official
  embedder, and missing visual tensors or changed batch size are errors; upstream's silent
  `NULL` text fallback is not accepted as a visual embedding. Temporary video files share
  the memory store's filesystem so atomic rename works on a Modal volume.

## Execution

Use the `mvagent-environment` skill and the `modal-gpu` dev box. Never run model inference,
video preparation, dependency installation or the full test suite on Lightsail.

`freeze.py` creates a new immutable project/upstream snapshot and applies the recorded RSI
and VAM patches. Run `run_batch.py rsi|meta|vam` from that snapshot, with `--prepared`, `--output`,
`--ports`, and optionally `--smoke`; Meta also needs `--bundle`. `meta.py generate` builds
its initial bundle, and `embedding_server.py` hosts VAM's supporting model. Preserve failed
attempts and use a new output directory for changed adapters. Dependencies, media, snapshots,
raw requests/responses, generated bundles and results stay in the Modal runs volume.

For example, inside the Modal sandbox, rerun the accepted Meta bundle into a **new** directory:

```bash
EXPERIMENT=/runs/devbox/external_methods_20261014
FROZEN="$EXPERIMENT/r9/frozen_repo"
export PYTHONPATH="$EXPERIMENT/support/deps:$FROZEN/src"
python "$FROZEN/eval/external_methods/run_batch.py" meta \
  --prepared "$EXPERIMENT" --output "$EXPERIMENT/meta_new_run" \
  --ports 8100,8101,8102 --bundle "$EXPERIMENT/meta_repair_r3/bundle.json"
python "$FROZEN/eval/external_methods/score.py" \
  --prepared "$EXPERIMENT" --run "$EXPERIMENT/meta_new_run" \
  --judge-endpoint http://127.0.0.1:8110/v1
```

The selected Actor endpoints must already serve the fixed 35B v2 profile; port 8110 must
serve the project's fixed CCQA Judge. Use `rsi` with R4 or `vam` with R7 for the other
accepted protocols. VAM also requires `embedding_server.py` on port 8200. `--smoke` restricts
execution to one shortest selected question per benchmark. Never reuse an output directory
containing predictions, or share an Actor endpoint between concurrent batches.

The current experiment and known limitations are tracked in
`outputs/external_methods_20261014/README.md`. No full benchmark or evolved-MetaVideoAgent
accuracy is established by these smoke runs.

## Backup checkpoint

The `codex/external-methods-20261014` branch backs up these adapters and the one-off
completion scripts. The shared worktree's independent inference-runtime/configuration
changes and local environment skills are outside this checkpoint. Reproducing the
submitted runs requires their full Modal frozen snapshots, not this branch alone.
