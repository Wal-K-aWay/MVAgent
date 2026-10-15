# p09_injection_wrappers.md

这些不是优化器 Prompt，却是 agent 实际看到的固定包装，必须纳入复现。

`inline_skill_for_prompt(skill_text)`：

```text
# SkillAdaptor evolved skills (INLINED — follow these procedures)
The skill body below is authoritative for this task. Prefer it over ad-hoc guesses. You do not need a separate SKILL.md read to apply it.

{YAML-frontmatter-normalized skill text, at most 4500 chars}
```

`format_skills_for_llm_prompt(skills)`（WebShop）：

```text
【Relevant Skills — FOLLOW PROCEDURES WHEN APPLICABLE】
### Skill {n}: {title}
When to apply: {when}
{description}

Procedure:
{body}
---
...

When the situation matches a skill's 'when_to_apply', follow that skill's Procedure.
```

最多 3500 chars。对命令交付物，`build_shell_prompt_prefix` 另加：

```text
[MANDATORY FIRST ACTION — Linux bash/sh only; never PowerShell]
Your first tool call must use write path=`command.txt` (relative filename in the task workspace root, NOT an absolute path like C:\\...).
File content must be **exactly** this one line (plain text, no markdown fence, no explanation):
{canonical_command}
```

