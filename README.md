# MVAgent_API

A two-level multi-agent system for multi-video question answering, with offline
Global/Video planning-skill evolution. GlobalAgent coordinates question answering;
one VideoAgent gathers evidence from each video. Skills modify planning policy,
while the runtime owns action contracts, media processing, and execution.

## Installation

The reference environment is **Linux x86_64 with Python 3.12**. For local inference,
an NVIDIA GPU and a driver compatible with the selected PyTorch/vLLM wheels are
required. Start with a fresh virtual environment rather than mixing CUDA packages
from an existing environment.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
```

`requirements.txt` covers MVAgent, offline skill evolution, local vLLM inference,
and the project's E2E media/scoring runners. All dependencies are declared directly
in this single file; no additional project requirements file is needed.

Do not install upstream SkillOpt: the current algorithm uses the in-repository
implementation and its authored/upstream-derived Prompt files. Tests use Python's
standard-library `unittest`. Vendored third-party training stacks (such as Video-R1
training and the complete lmms-eval model registry) have their own installation
instructions; they are not required to run MVAgent or skill evolution.

The pins document the baseline's direct dependencies, not a full transitive lock
or a guarantee of bitwise reproducibility. Dataset files and model weights are not
included. Runtime clipping uses the FFmpeg executable supplied by `imageio-ffmpeg`.
Legacy standalone scripts may additionally require a system FFmpeg installation.

## Configuration and execution

Configuration is grouped into [system inference](configs/inference/README.md) and
[Skill evolution](configs/skill_evolution/README.md). Shared GPU pool settings live
in `configs/inference/execution/`.

Before running, copy an appropriate YAML from these directories and update local model
paths, dataset paths, API endpoints and GPU assignments for your machine. Existing
experiment YAMLs contain the original research machine's paths and GPU numbers.
Do not assume those paths exist on a new installation. Keep API credentials outside
Git; `scripts/attribution_probe.py` reads `DEEPSEEK_API_KEY`.

GLM-5.3-Flash is available as a text optimizer through `provider: bigmodel`.
Use `configs/skill_evolution/runtime/local_qwen35_35b_a3b_glm53_flash_optimizer_gpu5_7.yaml` and set
`BIGMODEL_API_KEY` in the process environment. The matching 130/70 profile is
`configs/skill_evolution/alternating_multibench_train130_eval70_glm53_flash_gpu5_7.yaml`,
with `configs/inference/execution/gpu2_7_single.yaml` for six replicas on GPUs2–7,
one admitted request per endpoint;
The recipe retains its historical training parameters; consult the
[handoff](analysis/skill_evolution/handoff.md) before starting a new evolution run.
Actor and Judge remain local Qwen. The fixed Judge stays on GPU5/8102. Historical
comparisons retain their frozen `gpu5_7.yaml` execution configuration. GPU4 replacement
and rollout readiness are recorded in
`outputs/services/20260910_gpu4_qwen35_rollout/status.json`.
The API uses JSON mode with local Schema validation and thinking enabled; the profile
selects reasoning effort `high`, temperature 1, top_p 0.95, and 16384 output tokens.
Run `python scripts/analysis/probe_bigmodel_optimizer.py --output outputs/analysis/<fresh-name>`
for a small paid text integration check against archived optimizer inputs. It accepts
a hidden credential prompt if the environment variable is absent. It does not train
or establish a quality improvement, and does not test GLM image/video handling.

```bash
python demo.py --help
python eval/agent_eval/run.py --help
python scripts/run_skill_evolution.py --help
```

- [MVAgent batch evaluation](eval/agent_eval/README.md)
- [Skill evolution and independent Skill evaluation](src/skill_evolution/README.md)
- [E2E benchmark setup and data preparation](eval/README.md)
- [Current architecture and execution flow](analysis/current/system_architecture_and_flow.md)
- [Baseline configuration and validation provenance](analysis/current/runtime_baseline_20260909.json)

Record the Git commit, model/Judge versions, inference settings, dataset split and
Skill hashes for each run. Keep frozen run sources and scored outputs together.
`outputs/`, `.cache/`, datasets and model weights are not committed to Git.

## Basic validation

```bash
python -m pip check
python demo.py --help
PYTHONPATH=src python -m unittest discover -s tests -p 'test_historical_action_contracts.py'
```

Tests that compile local structured-output grammars require the full environment,
including xgrammar. Actual GPU inference and benchmark scores require separately
configured models and datasets; passing import checks alone does not validate them.

The shared runtime/API dependencies were checked in a clean Python 3.12 virtual environment with
`pip check`, all three CLI help entry points, and the historical action-contract tests.
The full manifest was resolution-checked against the installed vLLM 0.19.1 environment;
a fresh full GPU installation was not performed. The public Python-3 decord 0.6.0
wheel was separately installed and imported in the disposable environment. Do not
copy old environment directories or manually reuse interpreter-specific wheel files.

**Known decord packaging issue:** the upstream 0.6.0 Python-3 wheel contains an
internal `cp36-cp36m` tag. On Python 3.12, `pip check` reports
`decord 0.6.0 is not supported on this platform`, even when importing the module
succeeds. This occurs with a fresh public wheel as well as the reference environment.
It affects the optional E2E decoder installation, not API-only MVAgent/skill evolution.
Do not treat this as a fully clean dependency check or suppress unrelated dependency
errors. A fresh-wheel check decoded the first and last frames of a real video successfully
on the reference machine. Repeat an actual video-decoding check on the target
machine before E2E evaluation.
