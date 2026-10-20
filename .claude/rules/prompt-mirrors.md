---
paths:
  - "src/skill_evolution/algorithms/**/prompts/**"
  - "src/skill_evolution/algorithms/**/chinese_prompts/**"
  - "src/mvagent/skills/prompts.py"
  - "src/mvagent/skills/authored/**"
---

# Prompt 与中文镜像同步

- 修改 optimizer Prompt 或 Schema（`algorithms/**/prompts/`）时，在同一工作项内同步该算法目录下
  `chinese_prompts/` 中对应的文件。
- 修改运行时 Selector Prompt（`src/mvagent/skills/prompts.py`）或 authored skill 时，同步对应的中文说明。
- 中文镜像只是文档：action 名、JSON 字段、模板变量与英文原文保持一致。
