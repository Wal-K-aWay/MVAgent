# 文档导航

当前代码面向普通GPU服务器；历史H100/Modal实验说明不是新机资源配置要求。
先按当前操作文档运行，再根据要修改的部分阅读方法规范。带日期的报告用于追溯证据，不用作当前作业状态。

## 当前操作

| 任务 | 从这里开始 |
|---|---|
| 第一次安装和运行 | [服务器运行手册](server-runbook.md)：自有视频单题、十任务推理检查、评估与进化 |
| 下载和处理数据 | [数据准备](data-preparation.md)：CrossVid当前版本与缺失历史媒体、验收、CVBench/MVU |
| 接续研究 | [研究交接](research-handoff.md)：当前已实现/未实现、完整结果、限制、下一轮问题 |
| 寻找代码入口 | [仓库分层](repository.md)、[工具目录](../scripts/README.md)、[评测目录](../eval/README.md) |
| 选一个已有库或split | [库目录](../src/mvagent/skills/skill_sets/research-20261022/README.md)、[清单目录](../configs/skill_evolution/splits/README.md) |
| 查看回归检查 | [tests说明](../tests/README.md)：与真实模型和数据相关的前提分别列出 |

## 方法与接口规范

| 要理解或修改什么 | 文档与入口 |
|---|---|
| Global/Video动作与信息边界 | [研究交接第1节](research-handoff.md#1-项目解决什么问题)，实现于`src/mvagent/engine.py`与`agents/` |
| 检索、Selector和注入 | [运行时skill](../src/mvagent/skills/README.md)；它不会调用optimizer |
| skill卡片格式 | [写卡规范](../src/skill_evolution/skill_specification.md) |
| 一次生成 | [方法README](../src/skill_evolution/README.md)、[输入与Prompt镜像](llm-skill-generation.md) |
| rolewise默认闭环 | [方法README](../src/skill_evolution/README.md)、[配置](../configs/skill_evolution/README.md)、[Prompt镜像](skill-evolution-prompts.md) |
| 反馈格式诊断 | [反馈Prompt](skill-feedback-prompts.md)：已实现诊断，尚未接入默认rolewise |
| 推理、批量问答与评分 | [推理配置](../configs/inference/README.md)、[评测入口](../eval/agent_eval/README.md) |

`configs/skill_evolution/`是用户配置与split，`src/skill_evolution/configs/`是配置解析和手工诊断定义；
两者职责不同。进化入口在`scripts/`，冻结/恢复/评分协调在`eval/skill_eval/`，搜索算法在`src/skill_evolution/algorithms/`。
先确认自己改的是哪一层，不需要为接手研究迁移整个目录。

## 历史证据与设计记录

下表保留实验的原始口径、失败和协议差异。最新跨轮结论以[当前研究交接](research-handoff.md)为入口；
旧文中的“当前”“下一步”“运行中”、机器路径和GPU分配只描述当时状态。

| 研究阶段 | 记录 |
|---|---|
| 无skill基础框架与迁移 | [实验历史](experiments.md)、[历史H100复现](baseline-reproduction.md)、[旧main同步](main-sync-20261020.md) |
| DeepSeek一次生成 | [先导](deepseek-skill-pilot.md)、[全量计划](deepseek-skill-full.md)、[最终全量结果](deepseek-skill-full-results.md) |
| 早期rolewise与手工诊断 | [初始设计](skill-evolution-design.md)、[接入首测](skill-evolution-probe.md)、[诊断方案](manual-skill-diagnostics.md)、[结果](manual-skill-results.md) |
| 8–9小时扩展探索 | [方案](skill-exploration-study.md)、[完整结果](skill-exploration-results.md)、[该轮执行账本](skill-research-handoff-20261022.md) |
| optimizer输入审查与后续反馈实验 | [输入审查](skill-optimizer-input-audit-20261022.md)、[反馈对照](skill-feedback-iteration-20261022.md)；Video后补完成状态见当前交接 |
| 手工卡片与中文镜像 | [Global](manual-global-skills-zh.md)、[Video](manual-video-skills-zh.md)、[watch-first](manual-watch-first-skills-zh.md)、[时间锚点](manual-global-temporal-single-skill.md)、[终答控制](manual-global-terminal-skill.md)、[Video边界](manual-video-scope-skill.md) |

Git包含代码、配置、精选库与报告；Release包含已经公开的精简结果包。
完整历史研究rollout、Judge缓存和optimizer请求并未全部迁入GitHub。新机可创建新run，不能仅凭Git clone恢复任意旧run。
