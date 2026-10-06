# p01_localizer.md

调用：`Localizer._localize_with_llm`，一条 `user` 消息，temperature `0.2`。以下为可复建的固定骨架；`FAULT_TYPE_DEFINITIONS` 和 `SYNTHETIC_EXAMPLES` 是 `core/localizer.py` 内的两个常量，每次会完整插入。后者含购买属性、翻页、日期、计算器、git、Playwright、xlsx、交付物和 nginx 的 few-shot 例子；复制实现时应逐字复制该两常量。

```text
# Fault Localization Analysis
Analyze the failed trajectory to identify the first mistake and classify the fault type.

## Task Description
{task_description[:500]}

## Full Step-Level Trajectory (read every step; mark t* at earliest root-cause step)
```
{formatted up-to-24-step trace}
```
## Trajectory Summary (compressed)
{uniformly sampled up-to-15-step summary}
## Final Steps (Critical Context)
{last up to five "Step N: action" lines}

{FAULT_TYPE_DEFINITIONS}
{SYNTHETIC_EXAMPLES}

## Analysis Instructions
1. **Extract fault_chain**: List 2-4 candidate fault steps (1-based), ranked by evidence strength
2. **Select t_star**: Choose the primary step from fault_chain for this revision round (earliest root cause, not latest symptom)
3. If never product-clicks but next/prev flips => skill_missing; wrong selection => reasoning_wrong; wrong guidance => skill_wrong; repeated tool+parameters 3+ times => reasoning_wrong; ENOENT after skill => skill_wrong.
4. Formulate one concise, domain-tool improvement, never logging/transcript/install/env advice; name prompted deliverable and trajectory-grounded wrong artifact.
5. For named deliverables, return target, wrong artifact, rubric shape, and a principle containing all three.

{active adapter localizer supplement}
{PromptProfile.constraints_block('localizer')}
{PromptProfile.model_specific_block('localizer')}

## Output Format
fault_chain: [step numbers, 1-based, e.g. 2, 5, 7]
t_star: <step number from fault_chain - primary fault for this round>
deliverable_target: <output filename from prompt backticks, or none>
wrong_artifact: <what was wrong in deliverable/action at t* — no golden answers>
rubric_gap: <one rubric-shape gap>
improvement_principle: <must name deliverable + rubric shape + wrong_action at t* — no golden commands>
fault_type: <skill_wrong | skill_missing | reasoning_wrong>
reason: <brief explanation>
```

解析是逐行字段匹配（非 JSON），`t_star` 转为 0-based；越界或空 `improvement_principle` 会中止。

