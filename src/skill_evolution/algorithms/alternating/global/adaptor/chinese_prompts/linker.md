# linker 中文镜像

英文源：[prompts/linker/prompts.py](../prompts/linker/prompts.py)。仅供阅读，不被程序加载。

## TASK

```text
# Skill 修改决策
```

## INPUT

```text
# Skill 修改决策
{context}
```

## GUIDELINES

```text
## 故障类型背景
- action_selection_error：当时行动不适合证据需求。检查卡是否指示该行动、遗漏必要转移或已有充分指导。
- action_parameter_error：行动合理但video_id、clip或instruction不足。核对卡的实际参数规则与执行遵循情况。
- action_execution_error：合理行动返回可证明缺陷，包括普通answer与充分History矛盾。区分内容缺陷与执行不可靠，结果错误本身不支持修改卡。
每个类型描述一个轨迹步骤，不代表Skill责任；同轨迹不同步骤类型可以不同。

## 归因指导
1. 直接指令匹配：指出实际规则，以及被定位行动如何遵循了它。
2. 情境适用性：适用条件缺陷是否促成错误选卡？在明确适用范围外使用正确规则属于选择或推理错误。
3. 内容遗漏：卡在自身范围内是否缺少必要检查？已有检查未执行属于未遵循指导；充分方法未被使用属于选择缺口。
4. 误导性描述：证据是否将描述或适用条件缺陷与不恰当选择联系起来？区分选择条件与行动指导。

## 证据来源
- Skill Used for This Question：本题所有普通决策实际使用的唯一卡的完整内容。strategy 提供行动指导，when_to_use 提供任务、方法和初始选择条件。运行时收尾不直接接收卡，库中其他卡不参与判断。
- Related Cases：标明同版卡、其他版本、其他卡、无卡或使用关系未知。Related Cases按原始输入相似度选取，可以成功、未完全成功或未定位。成功本身不证明当前Skill导致成功，未定位案例不等于已确定故障。只有有依据的同版卡失败可直接支持当前卡的重复缺陷判断，其他案例仅供背景参考；库版本不同不等于卡版本不同。
- Localization：提供定位与改进原则。改进原则是待验证建议，不是卡已有指令。
- Trajectory：说明请求、当时已有证据和回答。潜在补救方法不自动构成内容缺陷证据。

## 决策标准
- revise：指出本题卡的具体内容缺陷及其与已定位错误行动或不恰当选择的联系，且该缺陷可通过修改这张卡解决。
- generate：证据不能确立上述缺陷。例如指导充分但未被遵循、缺失方法超出卡范围，或合理行动返回错误证据。该状态要求探索新方法，不代表新卡已被证明有效。
Localizer的故障类型只提供背景，不决定分流。任何类型都不能在缺少卡内容缺陷证据时强制revise。
```

## EXAMPLES

```text
## 示例
以下仅为假设示例，以实际输入为准。

<example>
故障：题目要求全视频动作总数，Agent只分析开头片段并比较局部计数。
本题Skill：opening-count指导整道题，明确要求仅统计开头。
输出：
{"status":"revise","reason":"卡的策略明确限制观察开头片段，与全视频计数要求冲突。"}
</example>

<example>
故障类型：action_execution_error。
故障：watch_videos请求明确源时间坐标，报告返回不一致时间，Agent未核对便回答。
本题Skill：time-check明确要求回答前核对时间坐标。
输出：
{"status":"generate","reason":"卡已要求相关检查。轨迹显示报告缺陷和未遵循指导，没有证据证明卡内容有缺陷。"}
</example>

<example>
故障类型：action_execution_error。
故障：参数充分的analyze_videos请求返回错误报告，公开证据没有暴露作答前可识别的不一致。
本题Skill：没有指令促成报告错误。
输出：
{"status":"generate","reason":"证据表明报告有缺陷，但没有本题卡促成错误的内容缺陷；探索可复用的补救方法。"}
</example>
```

## ANALYSIS

```text
## 分析步骤
1. 锚定Localization中的Step，识别行动、参数和决策前证据。返回结果说明执行后发生什么，后续决策单独分析。
2. 检查本题卡及经核实的整题使用关系，识别相关规则、遗漏或适用条件缺陷。
3. 区分内容和遵循问题：改进建议是在添加必要检查、重复已有检查，还是超出卡范围？分别判断选择与执行。
4. 相关案例用于支持当前归因，保留各自证据边界。先判断当前故障，再说明相关证据。
5. 决定操作：仅有与目标步骤关联的内容缺陷证据时返回revise，否则generate；说明依据并区分内容缺陷与未遵循指导。
```

## STAGE_CONSTRAINTS

```text
## 阶段约束
- 根据输入、可用行动和公开结果分析，行动内部实现不属于归因证据。
- 按决策前证据判断，历史案例保留自己的边界。
- 只评估used_skill中的本题唯一卡，修改目标由程序提供。
- 故障类型与分组只提供背景，责任须有卡内容和轨迹证据。
- 输出选择修改或生成，候选接受由后续Gate决定。
```

## OUTPUT

```text
## 输出格式
仅返回符合Schema的一个JSON对象。
字段：
- status：字符串，revise或generate。
- reason：非空字符串，说明决策证据。
规则：
- 顶层恰好包含status和reason。
- revise说明卡缺陷及其与定位故障的关系。
- generate说明为何证据不支持修改这张卡。
- 直接输出JSON，不加Markdown围栏或外部解释。
示例：
{"status":"revise","reason":"策略将计数限制在开头片段，而问题要求全视频总数。"}
{"status":"generate","reason":"卡已有完整覆盖检查，但Agent未遵循，未确立相关内容缺陷。"}
```

## Schema

[schema.py](../prompts/linker/schema.py) 要求顶层status和reason，status仅允许revise/generate，reason至少1字符，禁止额外字段。输出没有skill_id、weight或attributions。程序绑定本题卡作为修改目标；无卡时直接生成。没有责任阈值或故障类型强制回退。

## 动态上下文渲染

顶层依次为 Input、Skill Used for This Question、Trajectory、Ground truth、Localization、Related Cases。当前卡仅展示when_to_use、strategy，不另列ID或候选数组。完整轨迹末尾保留答案，GT独立显示。
相关案例按三级标题编号，案例内部章节为四级；每例先标明卡版本关系。相同卡版本可支持当前分析；其他版本、其他卡、无卡或未知仅提供背景，不能直接证明本题卡有缺陷。哈希仅用于程序判断，不进入模型文本。

2026-10-02 动态案例上下文：Related cases最多4条不同题目的最新健康Train轨迹，优先成功/未完全成功各2条，并补足可用空位；显示Outcome、localization状态、Final answer、独立GT、公开Steps与各自实际Skill关系。旧库版本明确标记。未定位案例没有伪造Localization。成功不证明Skill因果，簇不是一张Skill的绑定。Generator/Reviser不再展示整库目录；Reviser仍展示唯一目标卡，拒绝候选和修订历史保留。
