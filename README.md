# MVAgent

A two-level multi-agent system for multi-video question answering, with offline
Global/Video planning-skill evolution. GlobalAgent coordinates question answering;
one VideoAgent gathers evidence from each video. Skills modify planning policy,
while the runtime owns action contracts, media processing, and execution.

## 固定框架与恢复

当前唯一无 Skill 基础为 **简洁 Global System + 原 VideoAgent + 直接回答/同接口强制终答**。
采用 FFmpeg 裁剪及已验收的极短视频修复，三模型统一 BF16、seed=0、temperature=0。
详细配置见 [固定评测方案](configs/inference/README.md#固定评测方案)，所有历史实验与负结果集中在
[实验记录](docs/experiments.md)。不要从历史实验脚本另选一套 Prompt 或推理配置。

已清理、可继续开发的分支为 `codex/frozen-framework-20261018`。在其他服务器恢复：

```bash
git clone --branch codex/frozen-framework-20261018 https://github.com/Wal-K-aWay/MVAgent.git
cd MVAgent
git rev-parse HEAD
```

数据、权重、运行结果和凭据不在 Git 中。结果来源见实验记录；配置中的路径按目标机器映射。
Modal 访问必须经 `modal-gpu`，读取该机 `~/.agents/skills/modal/SKILL.md`；本地环境 skill、
`.claude/status.md` 和 `.claude/benchmarks.md` 需单独保留，不随仓库分发。
既有任务继续用各自冻结源码，新实验必须新建输出目录。

## Installation

The reference environment is **Linux x86_64 with Python 3.12**. For local inference,
an NVIDIA GPU and a driver compatible with the selected PyTorch/vLLM wheels are
required. Install on the GPU server, not on the Lightsail session host. Use an isolated environment.

```bash
uv venv --python 3.12 .venv
source .venv/bin/activate
uv pip install -r requirements.txt
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


## Configuration and execution

Configuration is grouped into [system inference](configs/inference/README.md) and
[Skill evolution](configs/skill_evolution/README.md). Shared GPU pool settings live
in `configs/inference/execution/`.

Before running, copy an appropriate YAML from these directories and update local model
paths, dataset paths, API endpoints and GPU assignments for your machine. Existing
experiment YAMLs contain the original research machine's paths and GPU numbers.
Do not assume those paths exist on a new installation. Keep API credentials outside
Git; use environment variables or Modal Secrets.

GLM-5.3-Flash is the text optimizer (`provider: bigmodel`, credential `BIGMODEL_API_KEY`) and
DeepSeek is the CCQA Judge (`DEEPSEEK_API_KEY`); both are defined in
`configs/skill_evolution/runtime/dynamic_35b_embedding.yaml`. Offline CCQA scoring of finished runs
(E2E and MVAgent baselines) uses the local Qwen3-30B-A3B-Instruct-2507 Judge instead
(`eval/agent_eval/serve_ccqa_judge.sh`, `eval/agent_eval/score_crossvid_ccqa.py`). The optimizer uses JSON mode with local
Schema validation, thinking enabled, reasoning effort `high`, temperature 1, top_p 0.95 and 16384 output tokens.

```bash
python demo.py --help
python eval/agent_eval/run.py --help
python scripts/run_skill_evolution.py --help
```

- [MVAgent batch evaluation](eval/agent_eval/README.md)
- [Skill evolution and independent Skill evaluation](src/skill_evolution/README.md)
- [E2E benchmark setup and data preparation](eval/README.md)
- [Architecture and repository rules](AGENTS.md)
- [Accepted baseline, historical experiments and next refinements](docs/experiments.md)

Record the Git commit, model/Judge versions, inference settings, dataset split and
Skill hashes for each run. Keep frozen run sources and scored outputs together.
Generated results, caches, datasets and model weights are not committed to Git; tracked Markdown documents may describe them.

## Basic validation

Run these checks in the remote project environment.

```bash
python -m pip check
python demo.py --help
PYTHONPATH=src python scripts/test_direct_answer.py
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
