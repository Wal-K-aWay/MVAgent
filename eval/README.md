# Benchmark evaluation

- [benchmarks.txt](benchmarks.txt): local dataset root directories.
- [CrossVid 2500题目ID](crossvid_2500.json): JSON array of 2500 unique full IDs (`crossvid:<task>:<original_id>`), for filtering the original QA records. This is an ID-only export of the [frozen split manifest](../configs/skill_evolution/splits/crossvid_lite2500_eval_seed20260919.json); use that manifest with `--split-manifest` for Skill evaluation. See the [sampling report](../analysis/skill_evolution/crossvid_lite2500.md) for provenance and boundaries.
- [CrossVid 干净训练池](crossvid_clean_pool.json): 1734 个 CrossVid 题目 ID（格式同上），其视频来源与 2500 题完全不重叠，用作 Skill 进化中 optimizer 可读数据（Train）的来源。来源按录像计：Assembly101 同一次录像的不同相机视角、同一部电影的不同片段（`<TITLE>-<n>.mp4`）、MOC/MSR 的同一 UAV 序列都算同一来源。各 task 题数：BU 492、CC 36、CCQA 96、FSA 202、MOC 338、MSR 344、NC 6、PEA 45、PI 15、PSS 160。由 `python3 scripts/prepare_crossvid_clean_pool.py --qa-dir <CrossVid>/QA --output eval/crossvid_clean_pool.json` 生成。池内题目之间仍可能共享视频，切分 Train/Cal/Gate 时还需按来源隔离。

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
| CVBench | `lmms-eval/lmms_eval/tasks/mvr/` and `Video-R1/src/eval_bench.py` | Complete retained MVR task with the official Qwen2.5-VL and OpenAI-compatible adapters | The upstream adapter runs Qwen2.5-VL in-process; `eval/e2e_eval/run.py` reproduces its message layout, prompt and scorer over an OpenAI-compatible endpoint. |
| MVU-Eval | `inference/main.py` and `inference/analyze.py` | Functionally complete vLLM inference and aggregate analysis path | `analyze.py` hard-codes its result folder in `__main__`; configure that in an experiment-local copy and keep the upstream answer parsing unchanged for official numbers. |
| CrossVid | ten task scripts under `eval/` plus `eval/score_CCQA.py` | Functionally complete and the clearest of the three; inference supports OpenAI-compatible APIs | `score_CCQA.py` hard-codes API placeholders and service settings. Configure an experiment-local copy, keep its scoring logic unchanged, and never write a real key into this repository or the vendored source. |

All end-to-end runs go through the unified harness `eval/e2e_eval/run.py` (vLLM endpoints or
the official API profiles in `eval/e2e_eval/api/`). It executes or reads the official prompts,
message order, sampling and scoring from the vendored sources; the only protocol parameters
are the video frames per model call (`--frames`, default 512) and the longest frame edge
(`--max-side`, default 448). See
`eval/e2e_eval/README.md` for the alignment table, commands and output layout.

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
`eval/e2e_eval/CVBench/README.md`.

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
