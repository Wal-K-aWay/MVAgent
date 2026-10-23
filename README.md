# MVAgent：多视频理解与免训练 Skill 自进化

MVAgent 接收一个问题和多个视频，由 **GlobalAgent** 管理全局取证，每个视频对应一个 **VideoAgent**。
研究目标是在冻结模型权重和框架的前提下，优化两个角色的skill文本，让系统选择适用策略并提高回答准确率。
当前包含无反馈一次生成、分角色反馈优化，以及可复核的正负实验记录；**尚未证明自进化稳定优于强一次生成基线**。

这是面向新研究员的普通服务器交接版本，不依赖原作者的Modal账号、私有会话说明或远端控制器。
新环境使用H20，GPU数量和Actor/Judge资源分配由接手者按实际资源配置；历史H100结果仅作为参考。

先完成安装，再按运行手册做**自有视频单题演示 → 十任务小规模推理 → 已有库评估**。
单题演示不要求下载完整CrossVid，也不需要Judge或optimizer；研究历史可以在第一次成功运行后阅读。

| 从哪里开始 | 内容 |
|---|---|
| 1. [新服务器运行手册](docs/server-runbook.md) | 安装、模型与资源配置、首次运行及成功判据，再进入批量研究 |
| 2. [数据下载与预处理](docs/data-preparation.md) | 做benchmark前阅读：CrossVid历史缺失文件恢复、一键预处理、CVBench/MVU-Eval布局 |
| 3. [研究交接](docs/research-handoff.md) | 做研究前阅读：架构、真实实现状态、实验结果、限制与未完成项 |
| 4. [研究资源目录](src/mvagent/skills/skill_sets/research-20261022/README.md) | 16份原字节skill快照、用途与SHA；不自动启用 |
| 5. [历史固定基线复现](docs/baseline-reproduction.md) | 原H100基线的完整推理与离线评分流程 |

全部文档按“当前操作、方法规范、历史证据”分类见[文档索引](docs/README.md)。

## 获取代码

从`main`获取整合后的交接版本；原`codex/research-handoff-20261022`分支和研究提交历史继续保留。不要使用未同步的旧共享工作区替代：

```bash
git clone --depth 1 https://github.com/Wal-K-aWay/MVAgent.git
cd MVAgent
git rev-parse HEAD
```

记录实际commit。本次整合通过[PR #4](https://github.com/Wal-K-aWay/MVAgent/pull/4)采用普通Merge commit，保留已有研究提交、公开结果报告与移植修正；旧分支、Release和已完成实验不删除。
源码压缩包不含Release中的结果附件，结果下载见下文。新运行使用新的输出目录。

## Installation

在**计算服务器**上使用Linux x86_64、Python 3.12及可用的NVIDIA驱动，先安装[uv](https://docs.astral.sh/uv/getting-started/installation/)。
系统需有FFmpeg/ffprobe与视频解码所需共享库；历史基础环境为CUDA 12.8.1、Ubuntu 22.04。
例如Debian/Ubuntu系统依赖为`ffmpeg libgl1 libglib2.0-0`，由有权限的管理员或容器环境提供。

```bash
uv venv --python 3.12 .venv
source .venv/bin/activate
uv pip install -r requirements.txt 'flashinfer-python==0.6.6' 'triton==3.6.0'
export PYTHONPATH="$PWD/src:$PWD${PYTHONPATH:+:$PYTHONPATH}"
uv pip check
python -c 'from models.vlm.local.sync_server import execution_profile; print(execution_profile())'
python eval/agent_eval/run.py --help
python scripts/evolve_skills.py --help
```

这是历史固定依赖要求，不是已经验收的新H20镜像或完整传递依赖锁。
`decord==0.6.0`上游wheel可能有Python标签问题；不要跳过安装错误后声称成功复现。
硬件变更后的容量和小规模推理检查由接手研究员在新服务器完成，`seed=0`本身不保证跨硬件逐token一致。
完整模型下载、GPU配置及服务命令见[运行手册](docs/server-runbook.md)。

## 数据准备入口

CrossVid当前Hugging Face版本缺少行为视频，**不能只下载当前版本就开始实验**。
一键入口使用固定当前版本获取主数据，再从固定历史版本补齐`videos/behavior/`，核验后调用现有预处理：

```bash
export DATA_ROOT=/srv/mvagent/data  # 改成服务器上有足够空间的目录
python scripts/prepare_crossvid_data.py --root "$DATA_ROOT/crossvid"
```

它在新计算服务器上执行下载与CPU媒体处理，不需要模型GPU；下载/编码并发可配置。
当前版本、历史commit、2416个缺失视频、存储需求、续跑与验收细节见[数据指南](docs/data-preparation.md)。
CVBench和MVU-Eval的准备也在该指南中。后续skill优化只使用CrossVid，另外两套benchmark保留用于最终评估。
原Train80/Cal40/Gate176、补充365和计划400清单已原字节保存到`configs/skill_evolution/splits/research_*.json`，
**这些是已有开发数据，不能当作独立Test**；不要为了统一seed重新生成历史清单。

## CrossVid 2500评测清单

已有成绩使用的固定清单是
[`configs/skill_evolution/splits/crossvid_lite2500_eval_seed20260919.json`](configs/skill_evolution/splits/crossvid_lite2500_eval_seed20260919.json)，
共2500题、十任务（含239题CCQA）。评测时必须显式传
`--benchmarks crossvid --split-manifest configs/skill_evolution/splits/crossvid_lite2500_eval_seed20260919.json`。
不传筛选参数时会读取完整CrossVid；`--limit 2500`不代表此划分。
各任务题数、SHA和旧题号数组的区别见[清单说明](configs/skill_evolution/splits/README.md#crossvid-lite2500正式评测入口)，
完整运行与评分命令见[服务器手册](docs/server-runbook.md#41-复现crossvid-lite2500)。

## 实现与接口

| 目录/入口 | 职责 |
|---|---|
| `src/mvagent/` | Global/Video循环、动作、记忆、自动选卡与注入 |
| `src/models/` | API客户端、本地同步模型服务、模型池与调用审计 |
| `src/skill_evolution/configs/` | 搜索与优化模型配置解析 |
| `src/skill_evolution/infra/` | 库快照、编辑、角色轨迹、反馈格式、调用留存 |
| `src/skill_evolution/algorithms/one_shot/` | 不读取问答样例、轨迹或成绩的一次生成 |
| `src/skill_evolution/algorithms/rolewise/` | 从空库开始的单角色单卡编辑、Train反馈、Cal/Gate整库验收 |
| `eval/` | 数据契约、官方评分、完整rollout与评估协调；`src/`不依赖评测包 |
| `scripts/generate_skills.py`、`scripts/evolve_skills.py` | 一次生成与反馈优化公开入口 |
| `tests/`、`docs/` | 回归检查、运行说明、协议与实验结论 |

Global动作是`analyze_videos / watch_videos / answer`，Video动作是`observe / finish`。
Global看不到Video内部轨迹；Video不自动得到Global原题、其他视频或Global skill。
两个角色各自自然选择至多一张卡或none；Selector读`when_to_use`，Actor只得到`strategy`。
Global整题、Video单次请求沿用首次选择。完整边界见[运行时说明](src/mvagent/skills/README.md)。

默认rolewise仍使用旧轨迹表示；新事件formatter已用于诊断，但未接入默认循环。
跨轮失败经验、候选池、任意换目录resume均未实现。不要把已保存的改进设想当作现有算法。
[运行手册](docs/server-runbook.md)分别给出固定历史库评估、新的一次生成和新rolewise实验，不要求重新生成历史卡。

## 已有结果与复核边界

- [DeepSeek一次生成全量结果](docs/deepseek-skill-full-results.md)：9B/27B/35B-A3B各5321题，四个正点差、五个负点差，没有一致收益。
- [旧轮研究结果](docs/skill-exploration-results.md)：8881评分题次、661个不同开发题；包括手写、固定/自然选择、角色组合与模型迁移。
- [反馈格式与分角色实验](docs/skill-feedback-iteration-20261022.md)：12个完整候选、3552评分题次，零新接受；新恢复Video记录的核验等级见原文。
- [研究总交接](docs/research-handoff.md)：哪些正信号未保持、哪些比较换了对照，以及“强制watch救回约47%错题”尚未严格复现。

公开逐题答案、文本轨迹和Judge记录通过Release附件分发，不放入Git提交历史：

| 结果 | 下载 |
|---|---|
| MVAgent无skill三模型 | [mvagent-results-20261019](https://github.com/Wal-K-aWay/MVAgent/releases/tag/mvagent-results-20261019) |
| MVAgent＋DeepSeek skill三模型 | [mvagent-skill-results-20261021](https://github.com/Wal-K-aWay/MVAgent/releases/tag/mvagent-skill-results-20261021) |
| E2E及其他历史对比方法 | [Release目录](https://github.com/Wal-K-aWay/MVAgent/releases)；实现不回填本公开代码树 |

核对附件SHA256。新研究的完整raw/Judge缓存/优化器请求仍留原Modal volume，未随这次源码交接发布；
当前库和split可以直接用于新实验，但不能仅凭它们重建全部旧运行或直接`--resume`。
本仓库不包含模型权重、视频、凭据、私人AGENTS/会话笔记。更多目录与历史来源见[仓库说明](docs/repository.md)。
