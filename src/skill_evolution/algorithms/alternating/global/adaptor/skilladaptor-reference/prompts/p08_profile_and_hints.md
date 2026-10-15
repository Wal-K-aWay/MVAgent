# p08_profile_and_hints.md

这是插入其他主 Prompt 的动态固定片段。

`PromptProfile.shared_constraints_block()`：

```text
## SHARED CONSTRAINTS
- Do not fabricate facts; use only trajectory evidence.
- If repeated actions show no progress, explicitly flag loop risk.
- Never propose runtime package installation or environment creation.
- Flag same-tool same-parameter calls repeated >= 3 times without progress.
- Reject destructive operations targeting system-critical paths; stay workspace-scoped.
```

`constraints_block(stage)` 还追加 `## STAGE CONSTRAINTS`：Localizer/Linker 要结构化分析、不要 action suggestion；Generator/Reviser 要可验证 principle guidance；`concise` template 加 hard stop after 3 retries。`model_specific_block` 以模型名选择 Kimi/GLM/default 的步骤、schema 或验证偏好；对 G/R 都追加“命名 output file 时必须引用它、不得另造场景”。

`adapter_hints.py` 选择 benchmark 专属 `localizer_supplement`、`generator_supplement`、`reviser_supplement`；它们是环境补充而非独立模型调用。精确复刻必须固定 active benchmark 和该文件版本。

