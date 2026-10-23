# MVAgent historical baseline reproduction

> This page preserves the reference H100 baseline recipe. For the current H20 research handoff with configurable GPU allocations, use [the server runbook](server-runbook.md).

MVAgent answers questions about multiple videos with a two-level agent system:
a **GlobalAgent** coordinates the task, and one **VideoAgent** gathers evidence
from each video. Optional skill libraries change planning instructions without
training the model weights.

This guide runs the fixed **no-skill MVAgent baseline on CrossVid Lite2500** on a
Linux GPU server, from raw data preparation through inference and final scoring.
It uses the supported repository entry points, without private session files,
Modal-specific launchers, or historical experiment controllers.

- [Installation](#installation)
- [Data and model preparation](#data-and-model-preparation)
- [CrossVid preprocessing](#crossvid-preprocessing)
- [MVAgent evaluation](#mvagent-evaluation)
- [CCQA judging and final scores](#ccqa-judging-and-final-scores)
- [Results and reproducibility](#results-and-reproducibility)
- [Other workflows](#other-workflows)

## Installation

Use **Linux x86_64 and Python 3.12**, with an NVIDIA driver compatible with the
pinned PyTorch/vLLM environment. The reference evaluation uses **8 H100 GPUs**, each
holding a complete BF16 model, TP=1 and one in-flight request per GPU. Inference and
model services must run on the same host/container; endpoints are loopback-only.
Data preprocessing needs CPU, storage and video codecs, but does not run a model.

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) first. Then,
on the compute server:

```bash
git clone --depth 1 https://github.com/Wal-K-aWay/MVAgent.git
cd MVAgent
git rev-parse HEAD

uv venv --python 3.12 .venv
source .venv/bin/activate
uv pip install -r requirements.txt 'flashinfer-python==0.6.6' 'triton==3.6.0'
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"

uv pip check
python -c 'from models.vlm.local.sync_server import execution_profile; print(execution_profile())'
python eval/agent_eval/run.py --help
```

Keep the printed Git commit with your run. A shallow clone avoids downloading
historical result blobs; use a normal clone if you need the complete Git history.
Run all following commands from the repository root, with the environment active.

The profile checks vLLM 0.19.1, torch 2.10.0, transformers 4.57.6, xgrammar 0.2.2,
FlashInfer 0.6.6 and Triton 3.6.0. The two extra install constraints above make the
profile's transitive kernel requirements explicit. Do not upgrade these packages
independently when comparing with the reference results. The requirements are
not a complete transitive lock or a prevalidated image for every GPU server.

The reference environment retains its pinned media dependencies. A decord 0.6.0
wheel can report a Python 3.12 tag mismatch despite successful import; investigate
installation errors and validate video decoding on the target server. Do not
install upstream SkillOpt or third-party training frameworks to run MVAgent.

## Data and model preparation

Choose writable locations outside the code checkout. Replace `/srv/mvagent` with
your storage location before running these examples:

```bash
export DATA_ROOT=/srv/mvagent/data
export MODEL_ROOT=/srv/mvagent/models
export RUN_ROOT=/srv/mvagent/runs
mkdir -p "$DATA_ROOT/crossvid" "$MODEL_ROOT" "$RUN_ROOT"
```

### CrossVid data

Download and restore the missing historical behavior videos with [the data guide](data-preparation.md). The resulting original data must be arranged as follows:

```text
$DATA_ROOT/crossvid/
├── QA/                 # BU.json, CC.json, CCQA.json, FSA.json, MOC.json,
│                       # MSR.json, NC.json, PEA.json, PI.json, PSS.json
├── videos/
│   ├── assembly/
│   ├── behavior/
│   ├── cook/
│   └── movie/
└── uav/
    ├── bbox/
    └── frames/
```

Only CrossVid is required for the main walkthrough below.
Do not replace source videos with re-encoded copies when comparing input hashes.

### Actor and Judge weights

The example uses [Qwen3.5-35B-A3B](https://huggingface.co/Qwen/Qwen3.5-35B-A3B)
as the Actor and
[Qwen3-30B-A3B-Instruct-2507](https://huggingface.co/Qwen/Qwen3-30B-A3B-Instruct-2507)
as the offline CCQA Judge. Download complete, unquantized checkpoints, including
tokenizer, processor and model configuration files.

Use an immutable model-repository commit for each download. Set `ACTOR_REVISION`
and `JUDGE_REVISION` to the full checkpoint revisions you intend to evaluate; for
an exact historical comparison, these must match the original checkpoints rather
than the current upstream `main`. With the
[Hugging Face CLI](https://huggingface.co/docs/huggingface_hub/guides/cli):

```bash
# Set ACTOR_REVISION and JUDGE_REVISION before these commands.
hf download Qwen/Qwen3.5-35B-A3B \
  --revision "${ACTOR_REVISION:?Set the pinned Actor revision}" \
  --local-dir "$MODEL_ROOT/Qwen3.5-35B-A3B"
hf download Qwen/Qwen3-30B-A3B-Instruct-2507 \
  --revision "${JUDGE_REVISION:?Set the pinned Judge revision}" \
  --local-dir "$MODEL_ROOT/Qwen3-30B-A3B-Instruct-2507"
export ACTOR_WEIGHTS="$MODEL_ROOT/Qwen3.5-35B-A3B"
export JUDGE_WEIGHTS="$MODEL_ROOT/Qwen3-30B-A3B-Instruct-2507"
```

Model weights and their original full-file hash manifests are not bundled with
this repository or the compact result packages. Record downloaded revisions and
weight hashes; a matching model name alone does not prove matching checkpoint bytes.
The fixed Actor profile rejects quantized checkpoints.

## CrossVid preprocessing

Prepare the original QA and media using the retained CrossVid-only entry point:

```bash
python eval/data_preparation/crossvid_batch.py \
  --root "$DATA_ROOT/crossvid" \
  --pea-jobs 4 --uav-jobs 4
```

Adjust the preparation worker counts to available CPU/RAM; these control parallel
preparation, not model inference. The command generates `qa.jsonl`, `qa.meta.json`
and `.mvagent_media/` under the CrossVid directory. Its progress, logs and final
`validation.json` are under `.mvagent_prepare/crossvid_qa/`. Require successful
completion before evaluation; rerun the same command to continue interrupted
preparation. Existing nonempty derived media can be reused, so start from a fresh
derived-media directory if the source data or preprocessing protocol changes.

The retained preprocessing uses 10 FPS, a maximum frame side of 960, and the
`mvagent_question_boxes` protocol: referenced MOC/MSR objects are marked during
their first visible second. These are media-preparation settings; Actor requests
still use the fixed 512-frame/448-pixel limits. The question-box representation is
MVAgent's fixed evaluation input protocol.
Do not change these settings for a reproduction comparison.

The lower-level entry is `eval/data_preparation/crossvid.py crossvid`;
`visualize_crossvid_question_boxes.py` and `frames_to_video.py` are its retained
media helpers. See [supported tools](../scripts/README.md).

## MVAgent evaluation

### Configure local paths

Copy the checked-in configuration and change only the checkpoint path. Keep local
copies under `.local/`, which is ignored by Git:

```bash
mkdir -p .local
python - <<'PY'
import os
from pathlib import Path
import yaml

source = Path('configs/inference/modal_qwen35_35b_a3b_no_skill.yaml')
config = yaml.safe_load(source.read_text())
config['models']['qwen3_5_35b_a3b_local']['model_name'] = os.environ['ACTOR_WEIGHTS']
Path('.local/mvagent-35b.yaml').write_text(yaml.safe_dump(config, sort_keys=False))
PY
cp configs/inference/execution/modal_h200x8.yaml .local/execution-35b.yaml
```

The execution file uses local GPU indexes 0–7 and ports 8100–8107. Change GPU indexes
only to match your allocation, leaving one replica per GPU and `max_inflight: 1`.
The `modal_`/`h200` filenames are historical names: the runtime can run on an ordinary
GPU server, and the reference hardware is H100. Do not start generic `vllm serve`
for the Actor: `run.py` starts or validates the fixed synchronous services itself.

The fixed settings are BF16, `seed=0`, temperature 0, thinking disabled, 2048 output
tokens, at most five Global/Video steps, and no skills. Prefix and multimodal
processor caches are disabled. See the complete
[fixed evaluation configuration](../configs/inference/README.md#固定评测方案).

### Run the frozen evaluation subset

Choose a new output directory for each independent experiment:

```bash
export RUN_DIR="$RUN_ROOT/mvagent-35b-crossvid-lite2500"
python eval/agent_eval/run.py \
  --config .local/mvagent-35b.yaml \
  --execution-config .local/execution-35b.yaml \
  --dataset-root "$DATA_ROOT" \
  --benchmarks crossvid \
  --split-manifest configs/skill_evolution/splits/crossvid_lite2500_eval_seed20260919.json \
  --defer-open-qa-judge \
  --output "$RUN_DIR"
```

This selects the **same 2,500 CrossVid questions**, including 239 CCQA questions.
Do not regenerate the split or combine it with `--limit`. The legacy ID list
`eval/crossvid_2500.json` contains the same set in a different order; use the manifest
above for new runs and preserve frozen inputs for resume. Raw answers are written before scoring. Closed tasks
are scored during evaluation; CCQA remains explicitly deferred until the next step.

To resume an interrupted run, repeat the exact command with `--resume`. Keep the
same inputs, model settings and output directory; resume uses the run's frozen
source. Do not point a fresh experiment at another experiment's output directory.

Other fixed Actor variants use the following configuration pairs. Copy and adjust
the model path in the same way, using the model key present in that YAML:

| Actor | Model config in `configs/inference/` | Execution config in `configs/inference/execution/` |
|---|---|---|
| 9B | `modal_qwen35_9b_no_skill.yaml` | `modal_h200x8_qwen35_9b.yaml` |
| 27B | `modal_qwen35_27b_no_skill.yaml` | `modal_h200x8_qwen35_27b.yaml` |
| 35B-A3B | `modal_qwen35_35b_a3b_no_skill.yaml` | `modal_h200x8.yaml` |

## CCQA judging and final scores

Actor services intentionally remain alive after `run.py` exits. **Before reusing
the same GPUs for judging, stop only the Actor service processes belonging to your
completed run and confirm their GPU memory is released with `nvidia-smi`.** Do not
kill other users' processes or start a Judge alongside resident Actor models.
Alternatively, run the Judge on a separate allocation with access to the run and data.

On the host containing the run directory and available Judge GPUs:

```bash
export JUDGE_LOG_DIR="$RUN_DIR/judge-logs"
bash eval/agent_eval/serve_ccqa_judge.sh 0-7 8100

python eval/agent_eval/score_crossvid_ccqa.py \
  --output "$RUN_DIR" \
  --qa-path "$DATA_ROOT/crossvid/QA/CCQA.json" \
  --endpoints 8100-8107
python eval/agent_eval/finalize_results.py --output "$RUN_DIR"
```

`JUDGE_WEIGHTS` selects the checkpoint downloaded earlier. The Judge is local;
no paid API key is required for this no-skill baseline. After scoring, release
only your own Judge processes/allocation as well.

Final outputs include:

| Artifact under `RUN_DIR` | Meaning |
|---|---|
| `records/` | Original per-question inference records and trajectories |
| `run_manifest.json` | Run identity and frozen input/configuration metadata |
| `summary.json` | Original inference summary; CCQA may still be marked deferred |
| `score/ccqa_scores_official_qwen3_30b_a3b.json` | Saved Judge results |
| `summary_scored.json` | Final summary after deferred scoring is merged |
| `benchmark_results.md` | Final benchmark report |

Read the final report and `summary_scored.json`, not only the original deferred
summary. CrossVid O.Avg is the macro average of its ten tasks; CCQA is weighted by
scoring-point count within its task. Report missing records and infrastructure or
Judge failures explicitly. A partial run is not a complete benchmark result.

For optional trajectory/answer tables:

```bash
python eval/agent_eval/export_results.py "$RUN_DIR"
```

The exporter reads saved records without calling models or changing answers. Its
`scores.json` copies the original `summary.json`, so after deferred judging use
`summary_scored.json` and `benchmark_results.md` as the final score authority.
See [Agent evaluation](../eval/agent_eval/README.md) for detailed formats.

## Results and reproducibility

Download the published answers, text trajectories and CCQA scores from
[MVAgent results](https://github.com/Wal-K-aWay/MVAgent/releases/tag/mvagent-results-20261019).
The 9B, 27B and 35B-A3B packages are separate attachments; their `statistics.md`
contains the reference metrics. Verify the published SHA256 values. GitHub's
automatic source archives do not contain these result attachments.
Previously published comparison results remain in their existing Releases;
this repository now contains only the MVAgent evaluation implementation.

For a reproduction comparison:

1. Match the Git runtime, exact checkpoint bytes, source data, prepared media,
   frozen sample IDs, Actor settings and Judge protocol. Preserve configuration
   copies, dependency versions and hardware information with the run.
2. Check that all selected questions and CCQA scores are present. Compare answers
   by question ID and the same official aggregation; retain failures and negative results.
3. Investigate differences through saved input hashes, token audits and trajectories.
   The compact public packages do not include every original media byte or token ID,
   so a full byte-level audit also requires the original run artifacts.

The published fixed runtime and retained preprocessing code are unchanged by the
repository cleanup. That is not a fresh-server end-to-end validation: installation,
media regeneration and inference have not been rerun on every target environment.
Different codecs, dependencies, weights or GPU types may change inputs or outputs;
`seed=0` alone does not guarantee identical answers. The fixed panel has been reused
for development; reproducing its scores is not an independent held-out generalization test.
Historical protocol changes and negative findings remain in
[the experiment record](../docs/experiments.md).

## Other workflows

- **All three benchmarks:** obtain CVBench/MVU-Eval media and upstream annotations,
  build their `QAs.json` files with `scripts/prepare_cvbench_mvu_qas.py`, and place
  them under `DATA_ROOT/cvbench` and `DATA_ROOT/mvu-eval`. Then use
  `--benchmarks cvbench mvu_eval crossvid` with the same split manifest; the split
  filters CrossVid while leaving the other two complete. See
  [benchmark setup](../eval/README.md) and [Agent evaluation](../eval/agent_eval/README.md).
- **Skill generation:** use `scripts/generate_skills.py --role both --output-dir <new-run>`
  with `DEEPSEEK_API_KEY` in the environment. The [one-shot baseline](../docs/llm-skill-generation.md)
  uses task and runtime descriptions without examples or feedback. The new [role-wise evolution loop](../docs/skill-evolution-design.md) starts from empty
  libraries and uses Train feedback plus complete Cal/Gate evaluation; it does not restore old algorithms.
- **Continue the skill research:** start with the [research handoff](../docs/skill-research-handoff-20261022.md).
  It records the completed experiment ledger, evidence limits, frozen artifacts,
  and the next study's runnable entry points and remaining data-preparation work.
- **Runtime regression checks:** see [`tests/`](../tests/README.md). For example, run
  `PYTHONPATH=src python tests/test_direct_answer.py` in the configured compute
  environment. Passing a unit check is not a benchmark result.
- **Repository layout and supported tools:** see [the directory guide](../docs/repository.md)
  and [`scripts/README.md`](../scripts/README.md). Data, weights, results, credentials,
  local agent instructions and session notes are not part of the public code tree.
