# Benchmark evaluation

- [benchmarks.txt](benchmarks.txt): local dataset root directories.
- [CrossVid 2500题目ID](crossvid_2500.json): JSON array of 2500 unique full IDs (`crossvid:<task>:<original_id>`), for filtering the original QA records. This is an ID-only export of the [frozen split manifest](../configs/skill_evolution/splits/crossvid_lite2500_eval_seed20260919.json); use that manifest with `--split-manifest` for Skill evaluation. See the [sampling report](../analysis/skill_evolution/crossvid_lite2500.md) for provenance and boundaries.

`eval/e2e_eval/` is the official-source hub. The separate `eval/agent_eval/`
directory contains the thin MVAgent-system runner for CVBench, MVU-Eval, and CrossVid; it
does not modify or replace official inference and scoring.

The parent MVAgent repository directly tracks the required official evaluation sources
under `eval/e2e_eval/`; there are no nested repositories or submodules. Non-evaluation
assets, data-generation tools, training code, saved predictions, and unrelated lmms-eval
tasks are omitted. The retained files preserve the upstream evaluation logic and their
source URLs/commits are recorded in `eval/e2e_eval/README.md`.

## Official-code audit

| Benchmark | Official test code | Assessment | Important boundary |
|---|---|---|---|
| CVBench | `lmms-eval/lmms_eval/tasks/mvr/` and `Video-R1/src/eval_bench.py` | Complete retained MVR task with the official Qwen2.5-VL and OpenAI-compatible adapters | The upstream generic adapter does not expose the explicit frame budgets and cue handling used for this Qwen3.6 run; use the documented local-vLLM compatibility runner and label its results accordingly. |
| MVU-Eval | `inference/main.py` and `inference/analyze.py` | Functionally complete vLLM inference and aggregate analysis path | `analyze.py` hard-codes its result folder in `__main__`; configure that in an experiment-local copy and keep the upstream answer parsing unchanged for official numbers. |
| CrossVid | ten task scripts under `eval/` plus `eval/score_CCQA.py` | Functionally complete and the clearest of the three; inference supports OpenAI-compatible APIs | `score_CCQA.py` hard-codes API placeholders and service settings. Configure an experiment-local copy, keep its scoring logic unchanged, and never write a real key into this repository or the vendored source. |

The tracked `eval/e2e_eval/api/run.py` adapter adds the researched official API
models across all three benchmarks without editing their imported task logic. Profiles
default to 512 sampled video frames per question and a 720-pixel longest edge; see
`eval/e2e_eval/api/README.md` for supported models, credentials and commands.

## Source provenance and scope

No initialization step is required after cloning MVAgent. The benchmark sources are
ordinary files in the same Git worktree. CVBench retains the lmms-eval runtime, its MVR
task, Qwen2.5-VL/OpenAI-compatible adapters, cue images, and Video-R1 evaluation entry; MVU-Eval retains
`inference/`; CrossVid retains `eval/`. See `eval/e2e_eval/README.md` for exact upstream
commits and omitted directories.

## MVAgent-system evaluation

`eval/agent_eval/run.py` evaluates the normal online MVAgent Runtime from one
frozen source snapshot. It reuses the canonical CVBench/MVU-Eval/CrossVid sample adapters and
`mvagent.batch.BatchExecutor`. `--execution-config` supplies explicitly allowed GPUs
and shared request limits; OpenQA requires an explicit `--judge-model`. It writes
every inference result atomically before independent scoring, and
resumes without rerunning successful samples. See `eval/agent_eval/README.md`.

Its strict option-label score describes the complete Agent system. It is not an
official upstream framework score; publication claims still use the entries under
`eval/e2e_eval/`.

## Official source and local configuration policy

The vendored snapshot is the protocol source. Avoid editing imported upstream logic.
When an upstream script requires a hard-coded local path, endpoint, or credential,
copy that script into the experiment output directory, change configuration values
only, and record the source commit plus the copied-script diff or hash. This preserves
the official inference/scoring logic while keeping machine-specific settings and
secrets outside Git. A rewritten parser, metric, prompt, or request
flow is not an official result path.

## Local Qwen vLLM resource controls

For the local OpenAI-compatible adapter, frame controls are explicit and keep each
benchmark's native semantics:

| Benchmark | Per-video cap | Per-question cap | Resolution control |
|---|---|---|---|
| CVBench | `--cv-frames-per-video` | `--cv-question-frame-cap` | `--cv-max-side` (aspect-ratio preserving) |
| MVU-Eval | `--mvu-frames-per-video` | `--mvu-question-frame-cap` | `--mvu-max-side` (aspect-ratio preserving) |
| CrossVid | official `--frames` (total per query) | same value | official `--length` (maximum frame side); launcher alias `MAX_FRAME_SIDE` |

Example smoke run against one local Qwen vLLM endpoint:

```bash
python scripts/run_official_cvbench_mvu.py \
  --model qwen35_local \
  --cv-ports 8001 \
  --mvu-ports 8001 \
  --limit 1 \
  --cv-frames-per-video 2 \
  --cv-question-frame-cap 8 \
  --cv-max-side 224 \
  --mvu-frames-per-video 2 \
  --mvu-question-frame-cap 8 \
  --mvu-max-side 224 \
  --decode-batch-frames 64 \
  --media-cache-dir .cache/e2e_media \
  --output outputs/local_vllm_qwen36_smoke
```

`--decode-batch-frames` bounds the number of decoded RGB frames retained at once by
each worker. The shared `--media-cache-dir` is independent of the model name, so later
model-size runs reuse preprocessing when source identity, effective frame allocation,
maximum side, and JPEG quality match. Different effective frame counts for the same
video have different cache keys. Use `--no-media-cache` for a cold-path comparison.

This adapter is intended to verify and compare the local endpoint. CVBench does not
ship a generic OpenAI-compatible official model adapter, so results from this wrapper
must be labeled as local-vLLM compatibility results rather than unmodified official
framework results. It snapshots only the local compatibility runner under the run
output and references the Git-tracked reduced sources in `eval/e2e_eval/`; it does not
copy those source trees or nested repositories into each output.

The verified high-input setting is `--cv-frames-per-video 512
--cv-question-frame-cap 512 --cv-max-side 720` for CVBench and the corresponding
`--mvu-frames-per-video 512 --mvu-question-frame-cap 512 --mvu-max-side 720` for
MVU-Eval. The question cap is divided evenly across its videos, so the total may be
slightly below 512 when it is not divisible by the video count or when a source video
contains fewer frames. For CrossVid use official `--frames 512 --length 720`, or
`FRAMES=512 MAX_FRAME_SIDE=720` with the launcher; `MODEL` selects the exact served
model name and defaults to `qwen35_local`. Run 512-frame smoke requests
sequentially on one endpoint unless endpoint capacity has been measured for concurrent
requests.

The CrossVid launcher exports `MVAGENT_E2E_MEDIA_CACHE_DIR` from `MEDIA_CACHE_DIR`
(default `.cache/e2e_media`). This optional execution cache has separate whole-video,
interval-video, and bbox-frame namespaces and stores the complete preprocessing return
tuple, including FPS, timestamps, bbox mappings, and encoded frames. Keys contain the
corresponding frame count, resolution, intervals, sampled source frames, and bbox input,
but not the model name, so later model-size runs can safely reuse identical processing.
The safe launcher also sets `DECORD_EOF_RETRY_MAX=40960` so lightly damaged H.264 files
can still return the exact requested source-frame indices, and recycles evaluation pool
children after `CROSSVID_MAX_TASKS_PER_CHILD` questions (default 25) to bound retained
Base64/JPEG allocator memory. These are execution controls; they do not alter prompts,
sampled indices, bbox/timestamp mappings, or scoring.

For a live run that already has one request stream per endpoint,
`scripts/official_crossvid/run_crossvid_accelerator_lane.sh` can own a disjoint list of
remaining tasks. Its child-recycle default is 4 because several simultaneous 512-frame
requests have a larger memory high-water mark. Pair it with
`monitor_crossvid_accelerators.sh`: only accelerator process groups are stopped if
system `MemAvailable` falls below 256 GiB or their aggregate RSS exceeds 64 GiB; the
primary run is never terminated and task files remain resumable. Never assign the same
task to an accelerator and the primary queue at the same time.

CVBench and MVU-Eval entries can be completed independently of inference with one
bounded-memory worker:

```bash
DECORD_EOF_RETRY_MAX=40960 nice -n 19 ionice -c3 \
  python scripts/prewarm_e2e_media_cache.py \
  --only cvbench \
  --cv-frames-per-video 512 \
  --cv-question-frame-cap 512 \
  --cv-max-side 720 \
  --decode-batch-frames 64 \
  --cache-dir .cache/e2e_media \
  --report outputs/e2e_media_cache_prewarm.json
```

The prewarmer deduplicates by the same cache key, skips hits without loading their
Base64 payloads, processes only one missing video specification at a time, and writes an
atomic resumable coverage report. Use `--audit-only` to measure coverage without writes.

## Run the upstream evaluations

First follow each upstream README for dependencies and dataset placement. Keep large
datasets and result files outside tracked upstream files.

### CVBench

CVBench's primary path is its bundled lmms-eval task:

```bash
cd eval/e2e_eval/CVBench/lmms-eval
pip install -e .
python -m accelerate.commands.launch --num_processes=1 -m lmms_eval \
  --model qwen2_5_vl \
  --tasks mvr \
  --batch_size 1 \
  --output_path /absolute/path/to/outputs/cvbench
```

The alternative official Video-R1 path is documented in
`eval/e2e_eval/CVBench/README.md`. Do not substitute the removed MVAgent compatibility
runner for an official CVBench score.

### MVU-Eval

Start the vLLM server exactly as documented upstream, then from the vendored source root run:

```bash
python inference/main.py \
  --model_name Qwen/Qwen2.5-VL-3B-Instruct \
  --port 8007 \
  --data_filename QA_json_file.json \
  --data_root /absolute/path/to/MVU-Eval-Data/videos

python inference/analyze.py
```

Before running `analyze.py`, make an experiment-local configuration copy as described
above and point its hard-coded result folder at the output from `main.py`. Do not edit
the vendored source.

### CrossVid

Each task owns its official inference and scoring behavior. Example:

```bash
python eval/BU.py \
  --model your-model-name \
  --port 8000 \
  --threads 20 \
  --frames 128 \
  --length 360 \
  --video_root /absolute/path/to/CrossVid/videos \
  --QA_path /absolute/path/to/CrossVid/QA/BU.json \
  --save_path /absolute/path/to/outputs/crossvid/BU_result.json
```

For CCQA, first generate answers with `eval/CCQA.py`. The upstream
`eval/score_CCQA.py` contains hard-coded API placeholders, so run a secured
experiment-local configuration copy as described above. Change only credentials and
service settings; retain the official prompt, per-question scoring, and aggregation.

## Updating an upstream pin

1. Clone the official repository into a temporary directory and inspect the new commit,
   README, inference entry, scorer, dependencies, and metric changes.
2. Copy only the required evaluation files into `eval/e2e_eval/<benchmark>/`.
3. Update the source commit and retained/omitted scope in `eval/e2e_eval/README.md`.
4. Run the vendored-source tests and record any protocol change in the experiment
   manifest and result report.

Do not silently follow a moving branch for reported experiments. The MVAgent commit and
the three recorded upstream source commits together identify the protocol.

## Deferred OpenQA scoring

Use `--defer-open-qa-judge` with `eval/agent_eval/run.py` to generate CrossVid
CCQA answers without a Judge; it cannot be combined with `--judge-model`.
This option participates in the resume identity. Deferred rows retain the prediction,
reference answer, scoring points and trajectory with `score=null`, `correct=null`
and `scoring_status=deferred`. References remain offline and never enter Actor prompts.
Closed tasks retain their existing scorers. Summary fields distinguish inference
completion, scored completion and deferred scoring; CrossVid `accuracy` is null until
its CCQA scores exist, while `scored_subset_accuracy` covers scored questions only.

The full no-Skill run uses `outputs/mvagent/no_skill/qwen3_5_35b_a3b_mvagent_no_skill/`, replacing
its prior contents as authorized. Its frozen driver and stability checks are under
`outputs/analysis/20260915_no_skill_full_deferred/`; the driver sets `PYTHONPATH`
to its frozen source and exports `open_qa_pending.jsonl` in the result directory after
inference completes. Later DeepSeek-v4-flash judging is a separate, not yet implemented
step. See [the protocol](../analysis/reports/no_skill_full_deferred_20260915.md).

CrossVid 固定 2500 题历史结果复算：`/home/kww/miniconda3/envs/MVAgent/bin/python scripts/analysis/summarize_crossvid_2500.py`，输出 `outputs/reports/crossvid_2500/report.md` 与逐题 CSV。读取已有预测/Judge，不调用模型。
