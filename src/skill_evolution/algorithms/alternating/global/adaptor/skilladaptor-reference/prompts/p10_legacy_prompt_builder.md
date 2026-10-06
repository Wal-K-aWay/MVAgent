# p10_legacy_prompt_builder.md

`core/prompts.py` 的 `SkillPrompts` 可生成 G/R 两套早期模板：共同 header 把模型称为“converting execution failures into reusable operational skills”的 agent debugger；G 要 abstract-but-concrete trigger、可验证 procedure、negative knowledge，并输出 `title/principle/when_to_apply/procedure/validation_criteria/negative_example` JSON；R 要最小增量修订，输出 legacy `revision_type/targeted_changes/impact_assessment` JSON。

当前主路径中 Reviser 虽创建 `self.prompt_builder`，但没有调用它；Generator 也使用自己的 `_build_generation_prompt`。因此它是源码保留物，不能与 p03/p04 叠加。若研究历史版本，直接以 [`core/prompts.py`](../../../../../../../references/skills_self_evolve/SkillAdaptor/skill-adaptor/core/prompts.py) 为唯一全文来源。
