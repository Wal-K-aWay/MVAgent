# VideoAgent 题目背景与职责边界实验计划

状态：2026-10-18按用户要求实施。三组共用已完成扩样的简洁 Global System，固定原102题/模型；A复用，B/C新测。实现与实际进度见[实验记录](../video_context_20261018/README.md)，尚未取得新模型结果。

目标：让完整原题补充定义和判定标准，让 instruction 决定本次执行范围。VideoAgent 仍只负责自己的视频，向 Global 提供证据，不独立完成整题比较或选择最终答案。前次“通用规则＋视频 ID”没有传完整原题，不能据此判断本方案的效果。

## 提示词与位置

System 放固定角色和边界；完整原题、instruction、视频 ID 放 User。普通 Planner 和达到步数上限后的强制总结共用以下 System，具体动作或总结任务由各自 User 与 schema 限定。

```text
You are the text-only planner and reporter for one assigned video. You cannot view the video directly; visual claims must be grounded in retained same-video observations.

Use the Original question only to interpret the active Instruction, including relevant definitions and criteria. It is background context, not an additional task or visual evidence.

Follow the active Instruction within the Assigned video's scope. Preserve relevant definitions when forming observation requests. Do not infer facts about other videos or produce the overall answer. The original question's answer-format requirements do not replace the current task's output contract.

Report instruction-relevant evidence and material uncertainty concisely, without omitting required information. If part of the Instruction exceeds this video's scope, report what is supported locally and state the limitation.
```

User 在 Inputs 最前加入完整原题，在现有 Video context 加入身份，instruction 原文不改：

```text
## Inputs

### Original question (background only)
{original_question}

### Instruction (current task)
{instruction}

### Video context
- Assigned source video ID: {video_id}
- Duration: {duration_sec} seconds

## Memory
{memory_view}
```

普通决策的 Available actions、Rules、Decision strategy、Output contract 保持原样。强制总结也加入原题和身份，但仍只允许输出总结，不增加观察动作。

## 落地范围

- Runtime 直接传入 Global 实际看到的完整题目，包括选项和定义；不让 Global 再摘要，也不拼入 instruction。
- 原题每次请求渲染一次，不写入 Memory、不随轮次累加。视频 ID 使用真实绑定身份；题面有其他命名时，仅添加数据加载器提供的可靠映射，不把视频 ID 当成答案选项。
- 首版视觉观察器保持原接口：仍接收聚焦的 `what` 和视频片段，由 Planner 将相关定义写入 `what`。是否把完整原题直接传给观察器留作独立变量。
- 改动限于 [engine.py](../../src/mvagent/engine.py) 传入原题、[VideoAgent](../../src/mvagent/agents/video_agent/agent.py) 保存并传给两条提示路径、[prompts.py](../../src/mvagent/agents/video_agent/prompts.py) 渲染背景及边界。公开评测入口、Global action schema、Video action schema 和 skill 注入位置不变。
- 这是 Video 可见信息的扩展；实施时同步架构文档中的信息边界说明，新建冻结源码与结果目录，不热改或混算现有批次。

## 小规模对照

简洁 Global 扩样结束并分析后，选定一个冻结的 Global 配置，三组统一使用；同一批固定问题、三个模型，保留现有推理参数、媒体处理、预算与官方评分。

| 组别 | Video 设置 |
|---|---|
| A | 原 Video System 和 User |
| B | 上述边界 System＋视频身份；原题背景位置填 `(not provided)` |
| C | 与 B 完全相同，只将背景替换为完整原题 |

比较 C−B 判断题目背景的贡献，C−A 判断整体方案收益。先做小规模同题筛选，再决定是否扩大；不同时调整 Global、输出上限或观察策略。

记录官方分数、最终格式/空答案、中间截断/修复、调用数和耗时；抽查轨迹是否保留题目定义、遵循 instruction，以及是否越界推断或提前回答整题。记录负结果，不把开发集改善当作普遍收益。
