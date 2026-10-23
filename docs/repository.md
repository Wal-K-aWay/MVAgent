# Repository layout and results

| Path | Purpose |
|---|---|
| `src/` | MVAgent, model adapters, runtime utilities and skill generation/evolution |
| `configs/` | Inference/generation settings and frozen split manifests |
| `eval/` | Batch evaluation, benchmark loading/scoring, splits, reports and annotation metadata |
| `scripts/` | Five entry points: data download/conversion, new split, skill generation/evolution |
| `tests/` | Runtime, evaluation and generation regression checks |
| `docs/` | Shared documentation, historical findings and protocol differences |
| `demo.py`, `requirements.txt` | Demo entry point and environment dependencies |

Local agent instructions, session notes, worktrees, analysis artifacts, result
directories and reference clones are excluded from the public tree. Keep these
locally; `.gitignore` prevents accidental addition. Model-facing prompts and authored
skills under `src/` are part of the implementation and remain versioned.
When changing optimizer prompts or schemas, keep the adjacent Chinese mirrors
consistent, including action names, JSON fields and template variables. Changes to
runtime selector prompts or authored skill text also require the corresponding
Chinese documentation to be updated.

## Current research handoff

Start with the [documentation index](README.md). For a first run, follow the [H20 server runbook](server-runbook.md); then read [data restoration](data-preparation.md) and [the research handoff](research-handoff.md) before benchmark experiments. Main includes the rolewise research chain and feedback fixes, retaining the prior commits; it does not revive retired external/E2E implementations. Private launchers are not required for new runs. Historical raw research runs remain separate from the curated banks and split manifests now included in Git.

## 分支与保留策略（2026-10-22交接）

`main`是唯一交接入口；PR [#5](https://github.com/Wal-K-aWay/MVAgent/pull/5)的脚本精简和
[#6](https://github.com/Wal-K-aWay/MVAgent/pull/6)的研究方案通过普通merge commit整合，原提交与全部分支保留。
后续从更新的`main`创建新`codex/`分支，不继续向历史分支追加开发，也不把“未合并”自动视为待办。

| 分支或引用 | 状态与用途 |
|---|---|
| `main` | 当前源码、操作文档和研究方案，接手者的唯一入口 |
| `codex/newcomer-onboarding-20261022`、`codex/skill-experiment-plan-20261022` | 本次整理与方案记录，保留追溯 |
| `codex/skill-evolution-20261021`、`codex/skill-mechanism-tests-20261021`、`codex/skill-exploration-20261021`、`codex/skill-feedback-20261022`、`codex/research-handoff-20261022` | 历史提交已完整进入主线，不再作为活动开发入口 |
| `codex/deepseek-skill-release-20261021` | 报告内容已吸收，不因分支未整体合并而再次合入 |
| 其他旧协议、`agentcvr-*`、`lenswalk-*`、`rsi-*`、`external-*`及临时恢复分支 | 历史归档，按报告定位具体提交，不整体合回活动源码 |
| `handoff-20261022` tag | 本次源码/文档交接里程碑；不是H20运行验收，不含全部历史实验原件 |

当前研究排程只维护在[自进化方案](skill-experiment-plan.md)；[研究交接](research-handoff.md)维护事实，
[服务器手册](server-runbook.md)维护工具用法，[数据准备](data-preparation.md)维护输入流程。
旧设计与带日期报告保留，其“下一步”“运行中”不代表当前任务。

以下材料保持原字节；保留不意味着重新运行：

- [冻结split](../configs/skill_evolution/splits/README.md)：Lite2500 manifest是已有2500题评测的唯一推荐入口；旧九任务split、clean pool和旧题号数组仅供追溯。
- [研究库](../src/mvagent/skills/skill_sets/research-20261022/README.md)：476532为当前非空父库，1275c1和229e74为待测候选；一次生成和失败库继续作为历史证据，不自动启用。
- 全部结果Release、正负报告和原提交保留。退役脚本与旧算法从Git历史查阅，不恢复兼容入口。

无skill和无反馈一次生成已有结果，本轮不新增生成或评测；缓存缺失、换硬件或恢复失败不能触发自动回补。
本机旧共享工作目录的未提交材料单独保全，不用清理或合并操作覆盖。

## Released results

Existing Releases and their result attachments are retained:

| Method | Release |
|---|---|
| MVAgent with DeepSeek skills | [Skill results](https://github.com/Wal-K-aWay/MVAgent/releases/tag/mvagent-skill-results-20261021) |
| MVAgent 9B / 27B / 35B-A3B | [MVAgent results](https://github.com/Wal-K-aWay/MVAgent/releases/tag/mvagent-results-20261019) |
| Qwen3.5 E2E | [E2E results](https://github.com/Wal-K-aWay/MVAgent/releases/tag/qwen35-e2e-results-20261017) |
| AgentCVR | [AgentCVR results](https://github.com/Wal-K-aWay/MVAgent/releases/tag/agentcvr-results-20261018) |
| LensWalk | [LensWalk results](https://github.com/Wal-K-aWay/MVAgent/releases/tag/lenswalk-results-20261019) |
| Video-RSI | [Video-RSI results](https://github.com/Wal-K-aWay/MVAgent/releases/tag/video-rsi-results-20261020) |

Download the named result attachments from the Release page; GitHub's automatic
“Source code” archives contain the repository, not the result attachments.
Use the published SHA256 values to verify downloads. Original experiment records
remain in the runs volume; compact public packages do not replace those originals.

## Historical source and cleanup boundary

The tree before this cleanup is
[`fbdcefac2bf2f20cedd62e17c9049497fabd6823`](https://github.com/Wal-K-aWay/MVAgent/tree/fbdcefac2bf2f20cedd62e17c9049497fabd6823).
It retains the old portable result snapshots and intermediate experiment scripts
in Git history. Historical script names in [experiments.md](experiments.md) refer
to that history or to the explicitly named experiment branch, not to supported
current entry points. No Git history or Release is rewritten by this cleanup.
A normal full clone still downloads historical Git objects.

The cleanup preserves the contents of runtime code, model-facing prompts, inference
and split configurations and dependencies. The follow-up evaluation cleanup removes
the E2E runner and moves required CVBench metadata unchanged into `eval/agent_eval/`.
The scoring formulas and Judge prompt are preserved; the optional E2E report
comparison is removed. The Actor-pool regression is retained without E2E imports.
Completed answers and scores are not recomputed. Existing jobs keep their frozen
source and paths; they must not be switched to a new checkout while running.

An old shared development checkout may contain local modifications that differ from
the accepted public runtime. Cleaning its auxiliary files does not authorize
resetting those modifications. Keep a local snapshot before retiring worktrees,
and use a separate clean checkout for public-repository maintenance.

The skill cleanup removes previous evolution algorithms, prompts, training recipes
and optimizer-only infrastructure from the current tree. One-shot generation is
organized under `src/skill_evolution/algorithms/one_shot/`; the new role-wise loop uses shared `configs/` and `infra/`. The pre-cleanup source is `de28149`;
its algorithms and negative findings remain in Git history and frozen experiments.

Evaluation lives entirely under `eval/`: `benchmarks/`, `data.py` and `agent_eval/`.
Media preparation internals live in `eval/data_preparation/`; they are called by the
public data entry points rather than listed as separate tools to run in sequence.
`src/evaluation/` is removed without forwarding imports. Generic JSON/hash helpers
live in `src/mvagent/utils/io.py`; source under `src/` does not import the evaluation
package. New evaluation runs snapshot both trees and verify the evaluation-source
hash when resuming. Existing runs keep their own frozen source and layout.
