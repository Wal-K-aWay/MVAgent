# 进化算法的路径规则

本文件适用于 `src/skill_evolution/algorithms/` 及其子目录，并继承仓库根目录的 [AGENTS.md](../../../AGENTS.md)。

修改任一算法下的 `prompts/**` 或 `chinese_prompts/**` 前，读取并遵守
[Prompt 与中文镜像同步规则](../../../.claude/rules/prompt-mirrors.md)。
修改 optimizer Prompt 或其中的 Schema 时，在同一工作项内同步对应中文镜像；action 名、JSON 字段和模板变量保持一致。

开始修改某个算法前，先读该算法的 `README.md`。scope 的完整循环尚未实现，相关进度与证据分别见
[设计](alternating/global/scope/docs/design.md) 和 [组件探针结果](alternating/global/scope/docs/probe_results.md)。
