# __init__.py 中文说明

对应 [prompts/__init__.py](../prompts/__init__.py)。这是拼接代码的说明，不是额外 Prompt。

- STAGE_TASKS：四个阶段目录中 prompts.py 的 TASK。
- STAGE_PROMPTS：四个阶段目录中 prompts.py 的 User 模板。
- build_system_prompt(name)：Reviser/Generator 拼接 TASK、BACKGROUND、CARD_CONTRACT；其他阶段拼接 TASK、BACKGROUND，块之间两个换行。
- build_stage_prompt(name, context)：Localizer 使用 build_localizer_prompt；Linker 替换 {context}，嵌入章节最低二级；其他阶段最低三级。
- build_localizer_prompt(trajectory)：替换 {trajectory}，嵌入章节最低二级。

Localizer User 顺序：INPUT → FAULT_TYPES → EXAMPLES → ANALYSIS → STAGE_CONSTRAINTS → OUTPUT。
其他阶段 User 顺序：INPUT → GUIDELINES → EXAMPLES → ANALYSIS → STAGE_CONSTRAINTS → OUTPUT。

轨迹来自 evidence.render_stage_input：Input、selected skill、steps、output、ground truth。每次 analyze_videos 的多个报告归于同一个 Step；watch_videos 保留联合观察。动作参数和观察不截断。

这里列出的 System/User 是阶段消息。BigModel 适配器另在开头添加含完整 JSON Schema 的 System 消息。没有 SHARED_CONSTRAINTS 或阶段级 REPAIR。

当前拼接：Reviser/Generator 的 System 为 TASK + BACKGROUND + CARD_CONTRACT；其他阶段仍为 TASK + BACKGROUND。User仅保留阶段指导、动态案例和输出合同。共用示例只出现一次。长度采用输入上限，无1800软目标或固定字段篇幅配额。候选直接按输入长度限制校验，超限拒绝。
