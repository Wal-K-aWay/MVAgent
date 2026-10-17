# 运行时 skill 的路径规则

本文件适用于 `src/mvagent/skills/` 及其子目录，并继承仓库根目录的 [AGENTS.md](../../../AGENTS.md)。

修改 `prompts.py` 或 `authored/**` 前，读取并遵守
[Prompt 与中文镜像同步规则](../../../.claude/rules/prompt-mirrors.md)：
在同一工作项内同步相应的中文说明，保持 action 名、JSON 字段和模板变量一致。

修改检索、Selector 或注入逻辑前读 [运行时说明](README.md)；编写或修订 skill 卡片前读
[Global skill 规范](../../skill_evolution/infra/global_skill_specification.md)。
此处的 skill 卡片是模型实验输入；开发环境 skill 的入口是仓库根目录 `.agents/skills/mvagent-environment/`。
