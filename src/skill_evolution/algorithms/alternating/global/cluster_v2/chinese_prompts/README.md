# cluster_v2 中文 Prompt 索引

这些镜像是阅读文档，Runtime 不加载。

- [common.md](common.md)：共享 BACKGROUND 与 CARD_CONTRACT，复制自 cluster。
- [analyzer.md](analyzer.md)：无卡文本的轨迹问题分析。
- [planner.md](planner.md)：编辑和跳过计划。
- [generator.md](generator.md)：NEW 完整卡作者。
- [reviser.md](reviser.md)：WHEN/STRATEGY 单字段作者。
- [evidence.md](evidence.md)：阶段证据及诊断输入边界。

## System/User 拼接

四阶段为 analyzer、planner、generator、reviser。System 为对应 TASK + BACKGROUND，generator/reviser 另加 CARD_CONTRACT；User 使用 TEMPLATE 的 {context}，沿用 Markdown 层级渲染。拼接字符串在 prompts/__init__.py，调用、校验和作者调度在 optimizer.py。

动态证据仍由 evidence.py 构造；evaluation.py 执行正常与诊断 rollout。重构没有修改模型可见文本、Schema 或证据边界。
