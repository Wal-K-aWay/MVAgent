# 固定评测代码快照（2026-10-17）

此分支 `codex/current-code-freeze-20261017` 保存本次 System 对照前共享工作区的源码、配置和评测入口，并保留此前已提交的实验驱动。它是恢复点，不代表所有研究算法或外部方法都已通过完整测试。

已完成三模型4500条直接回答测试的可恢复分支为 `codex/direct-answer-large-20261016`，提交 `1b711bf6a466c6dee70c273d24fbd98bd4f0c80d`。该分支还包含已验收的极短视频采样修复；当前共享工作区尚未合入该修复。新对照从该已测试分支派生，不混入其他工作区正在进行的实验。

## 在另一台服务器恢复

```bash
git clone --branch codex/current-code-freeze-20261017 https://github.com/Wal-K-aWay/MVAgent.git
cd MVAgent
git rev-parse HEAD
```

需要沿用已完成4500条测试的修复后运行代码时：

```bash
git switch --create my-next-experiment origin/codex/direct-answer-large-20261016
```

GPU服务器按根目录 README 安装 Python 3.12 与 `requirements.txt`。Lightsail仅编辑、提交、查看日志，不安装推理依赖。数据和权重不在Git中：需在目标GPU环境挂载或配置相应路径。Modal必须经 `modal-gpu`，远端入口说明为 `~/.agents/skills/modal/SKILL.md`；该机器的凭据不随仓库分发。

- 模型：Qwen3.5-9B、27B、35B-A3B，全部BF16。
- 服务：8×H100，8个独立TP1/DP1副本，每卡并发1；整题固定副本。
- profile：`qwen35-bf16-flashinfer-sync`，seed=0、temperature=0、thinking关闭、prefix/MM cache关闭。
- 每次2048输出token、512帧，Global/Video各5步；完整配置见 `configs/inference/README.md`。
- 主动与耗尽收尾都使用直接decision的answer；没有独立兜底回答器。Global User顺序为Question→Videos→Available actions→History。
- 取证reason限1200字符，终答reason无字符硬上限；answer保持开放非空字符串。

公开接口与原来相同。按机器修改配置副本的权重路径、端点、GPU及缓存路径后运行：

```bash
PYTHONPATH=src python eval/agent_eval/run.py \
  --config configs/inference/modal_qwen35_35b_a3b_no_skill.yaml \
  --execution-config configs/inference/execution/modal_h200x8.yaml \
  --dataset-root /assets --sample-ids-file /path/to/frozen_ids.json \
  --defer-open-qa-judge --output /path/to/new_run
```

入口会按配置启动/验证本机副本；`h200`文件名是历史命名，固定评测仍要求H100。9B/27B使用同目录对应模型的两份YAML。CCQA另用固定Qwen3-30B-A3B-Instruct-2507 Judge，详见 `eval/agent_eval/README.md`。新实验用新输出目录；resume只用原冻结源码和配置。

## 结果与本地材料

已有原始数据留在Modal runs volume `wxu-evolve-agent-runs-20261006`：

- `devbox/direct_answer_large_20261016`：原始分片、选择清单、冻结源码。
- `devbox/direct_answer_large_recovery_20261017`：补跑及最终4500条配对分析。
- `devbox/direct_answer_large_diagnostics_20261017`：收益、格式、轨迹与Judge敏感性诊断。

三模型4500条均有效，最终空答案/仅右花括号为0，闭式格式失败79/4350；同题九格官方差值均为正，但部分置信区间跨零。完整结果见 `outputs/direct_answer_large_20261016/README.md`。数值后端已通过范围内的一致性验收可复用；换硬件、依赖或调用路径需对受影响部分复核。

本地 `.claude/status.md`、`.claude/benchmarks.md`、环境skill和SSH/Modal凭据不入Git。没有这些笔记也可通过本说明、各评测README及冻结结果继续工作；使用Modal辅助工具时需在新机器单独恢复环境skill。其他独立worktree的最新工作见各自远端分支，不包含在这份共享工作区快照的验证声明中。
