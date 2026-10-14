# 固定评测配置名称清理

正式入口统一为 `qwen35-bf16-flashinfer-sync`，不再用配置版本编号。实际推理参数见 [配置总表](../../configs/inference/README.md#固定评测方案)。

同步共享服务、六个 YAML、外部方法 profile 校验、两个契约测试及相关文档；删除失效交接说明，历史报告用具体设置区分实验。
不可变的远端原始路径、实验组 ID 和冻结源码保持原值，不删除负结果或改写过去的 manifest。

- 共享推理实现与改名前逐字比较，仅 PROFILE 字符串不同；数值配置、环境、依赖版本、Prompt 与预算均未变。
- Modal CPU 完整 compileall 通过，13 项契约测试通过（prefix 2、E2E 9、终答 2）。首个测试命令漏加 scripts 到 PYTHONPATH，修正后通过。
- 当前入口文档的本地链接、环境 skill 符号链接、Python 语法和 diff 检查通过。
- 未新增 GPU 推理；现有数值配置验收见 [原验收报告](../fixed_profile_validation_20261014/README.md)。

新客户端只能连接名称、源码哈希和实际配置匹配的新服务。现有任务及 resume 必须使用同一套冻结客户端与服务，不热更新。

Git 检查点只备份本次涉及的源码、配置和可共享 Markdown；共享工作区其他既有改动未纳入，因此检查点标为 WIP，不能称整个工作区已备份或独立部署包。
本地环境 skill、状态笔记与 handoff 按约定不入 git；原始结果仍在 Modal。
