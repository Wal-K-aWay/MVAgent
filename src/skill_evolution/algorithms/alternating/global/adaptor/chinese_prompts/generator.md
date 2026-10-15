# generator 中文镜像

System = TASK + BACKGROUND + CARD_CONTRACT。共用内容见common.md。此文件仅供阅读，不被运行。

## TASK

````text
# 基于失败分析生成Skill

根据失败证据生成一张可复用的整题Skill，遵循共用卡片规范与内容示例。
````

## INPUT

````text
# Skill Generation from Failure Analysis

## 完整步骤轨迹与输入上下文

{context}
````

## GUIDELINES

````text
## 生成指导

````

## EXAMPLES

````text
## 生成示例

事件次数比较将统一完成定义放在相关计数步骤；编号步骤中用 analyze_videos 请求带时间的事件列表，报告事件不确定时在对应视频和区间请求完成特征，可比计数支持所需关系时调用 answer。假设轨迹展示题目、具体请求、简短计数/不确定性结果、必要的定向追查，以及 answer 和最终结果。
````

## ANALYSIS

````text
## Analysis Instructions

1. 阅读原始问题、定位步骤、已有证据、参数和结果。GT用于理解失败，部署决策依据Agent能够取得的证据。
2. 提炼可复用缺口，对照Previously rejected candidates，区分缺少流程与已有流程未遵循；Related cases来自原始输入聚类，用于对照成功与未完全成功的流程，确定共性范围和必要差异。成功不证明Skill的因果贡献，同簇不要求使用同一张Skill。明确新增的证据或参数规则；仅视频题材不同不足以构成新方法。
3. 将共享任务要求与简洁编号步骤分开。明确首次取证、可观察的追查条件、action 参数和 instruction 内容，以及 answer 的证据条件。action_execution_error以公开结果中可识别的缺陷为触发，指定可用的纠正请求。
5. 检查action覆盖问题、参数合法且来源可用、结束证据条件清晰，示例结果支持结论，并用需要另一方法的相似题检查适用条件。返回符合长度限制的完整卡片。
````

## STAGE_CONSTRAINTS

````text
## STAGE CONSTRAINTS

- 提出一个有失败依据的方法，新增价值体现为实质决策规则。
- 保留题目证据关系、时间约定与输出要求。
- 单视频请求保持在对应视频的信息边界内。
- 被拒提案是历史尝试，不证明特定缺陷或未来收益。
````

## OUTPUT

当前输出合同（JSON 字段和枚举不翻译）：

````text
## Output Format

Return one Skill proposal JSON object only, matching the supplied Schema.

Fields:
The reference number is assigned by the program and is not an output field.
- `when_to_use`, `strategy` (strings): Non-empty English text following the Skill Card Design and Writing Specification.

Rules:

- Return a complete new card. Follow the shared numbered-step strategy format; encode line breaks inside JSON strings as \n escapes.

- Keep when_to_use concise; the two text fields together within the supplied card length limit.
- Return JSON directly without Markdown fences or explanatory text outside the object.

Example:
{
  "when_to_use": "<applicability from the original question and video information>",
  "strategy": "<concise numbered condition/action/parameter instructions>"
}
````
