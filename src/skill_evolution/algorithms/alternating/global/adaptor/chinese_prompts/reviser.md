# reviser 中文镜像

System = TASK + BACKGROUND + CARD_CONTRACT。共用内容见common.md。此文件仅供阅读，不被运行。

## TASK

````text
# 基于失败分析修改Skill

根据证据修改归因目标Skill，按共用规范和内容示例返回完整整题流程。
````

## INPUT

````text
# Skill Revision from Failure Analysis

## 完整步骤轨迹与输入上下文

{context}
````

## GUIDELINES

````text
## 修改指导

保留有依据的决策规则，使完整卡片能从原始输入执行。旧卡从报告之后开始或只有补救建议时，在有证据支持的题型范围内补首次取证指令和结束条件，按需调整action指令和选择字段。保留有效的任务专属约束，删除泛化提醒和重复。

````

## EXAMPLES

````text
## 修改示例

旧规则：“计数冲突后复查，再回答。”
证据支持的缺口：报告使用不同事件定义，复查重复原请求。
````

## ANALYSIS

````text
## Analysis Instructions

1. 在定位决策处对照目标Skill、Current case、Related cases与Revision reason，区分内容缺陷、未遵循及action执行缺陷，依实际证据评估Localizer建议。
2. 用Recent failure history和Previously rejected candidates识别反复缺口和实质差异，拒绝本身不证明原因。
3. 修正有依据的缺陷，按共用编号步骤格式表达完整方法，简洁说明 action 条件及参数/instruction 规则。比较原始输入聚类中的成功和未完全成功 Related cases，保留有依据的规则；成功不证明 Skill 的因果作用，同簇不代表共享方法或该卡存在缺陷。补全执行它们所需的首次取证、参数来源和结束条件。执行缺陷需指定可见触发条件与可用纠正action。
````

## STAGE_CONSTRAINTS

````text
## STAGE CONSTRAINTS

- 仅修改目标Skill，保留标识符与有依据的范围。
- 使用各案例自己的公开证据，分组不代表观察可互换。
- 修改依据内容缺陷及共用卡片合同。
- 历史作为Train证据，不证明Gate表现。
````

## OUTPUT

当前输出合同（JSON 字段和枚举不翻译）：

````text
## Output Format

Return one revision JSON object only, matching the supplied Schema.

Fields:
- `update_mode` (string): "revise_existing" for a justified revision, otherwise "skip".
- `target_skill_id` (string): The ID of Skill to revise, allowed by the supplied Schema.
- `revision_summary` (string): A non-empty explanation of what changes and why the supplied evidence supports it, or why revision is skipped.
- `skill_profile` (object or null): Exactly `when_to_use`, `strategy`, each a non-empty English string; null for skip.

Rules:
- Return exactly these four top-level fields in a single JSON object.
- For "revise_existing", provide the complete two-field profile, including unchanged text. Follow the shared numbered-step strategy format; encode line breaks inside JSON strings as \n escapes.
- For "skip", keep target_skill_id and set skill_profile to null.
- Keep when_to_use concise; both text fields together within the supplied card length limit.
- Return JSON directly without Markdown fences or explanatory text outside the object.

Example (revise_existing):
{
  "update_mode": "revise_existing",
  "target_skill_id": "target-skill-id",
  "revision_summary": "<targeted change and the evidence supporting it>",
  "skill_profile": {
    "when_to_use": "<applicability from the original question and video information>",
    "strategy": "<complete revised numbered condition/action/parameter instructions>"
  }
}

Example (skip):
{
  "update_mode": "skip",
  "target_skill_id": "target-skill-id",
  "revision_summary": "<why no content revision is supported>",
  "skill_profile": null
}
````
