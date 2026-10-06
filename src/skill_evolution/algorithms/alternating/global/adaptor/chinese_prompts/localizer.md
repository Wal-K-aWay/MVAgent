# localizer 中文镜像

英文源：[prompts/localizer/prompts.py](../prompts/localizer/prompts.py)。仅供阅读，不被程序加载。各块对应英文常量；字段、action名和变量保持不变。

## TASK

```text
# 故障定位分析

识别多视频解题轨迹中有依据的行动级故障。将每项故障定位到发生的步骤，分类并提出可行、可复用的修正。

## 输入及其作用

轨迹输入包含以下部分，名称与实际段落完全一致：
- **Input**：原始题目、选项及视频ID和时长。题目定义任务，包括量词、比较标准和答案格式；视频元信息用于检查视频引用和时间范围。
- **steps**：Agent在选中Skill指导下解答Input时实际产生的action、参数及返回结果序列。未选中Skill时，Agent依据Input和累计证据自行决定合适的解题流程。指导可能被遵循、调整或错误运用，实际发生了什么以记录的行动为准。每步的决策依据执行前可用信息判断，执行质量依据请求和返回结果判断。
- **output**：该次运行产生的最终答案。依据Input和steps中的证据检查其内容及格式。
- **ground truth**：供离线分析的参考答案，与output比较以确定结果差异。解题时不可用；差异的原因需要steps中的证据支持。

## 分析目标

先从Input确定任务要求，再检查steps中具体的action、参数或结果缺陷。每项发现都依据这些要求及相关步骤当时可用的证据解释。

selected skill用于帮助理解行动可能如何产生。遵循Skill规则仍可能产生错误行动；基于题目和证据偏离指导也可能合理。独立于是否遵循Skill判断行动正确性。Skill示例提供假设演示，不代表当前案例事实。

返回有依据的行动级发现。修改Skill还是新建Skill由后续阶段判断。公开证据不足以支持可执行定位时，返回skip并说明不确定性。
```

## INPUT

```text
# Full Step-Level Trajectory
结合输入、整题Skill、全部步骤、最终答案和GT阅读。对Step k区分：
- 决策依据：题目、视频元信息、固定Skill指导，以及k之前步骤的结果。
- 行动：Step k记录的action和参数。
- 结果：Step k返回的观察或答案，供后续决策使用。

选择/参数错误定位在作出决策的步骤，依据该步骤的决策依据判断。执行错误定位在产生缺陷结果的步骤，依据请求和可用证据判断。后续步骤若错误处理该结果，单独分析后续行动。同一analyze_videos调用的报告属于同一步；watch_videos返回联合观察。普通answer无参数，基于自动提供的问题和History产生答案。
{trajectory}
```

## FAULT_TYPES

```text
# Fault Type Definitions
每个fault_chain项选择一个类型，同一轨迹不同步骤可以不同。

action_selection_error：当前行动不适合当时的证据需求。
- 特征：需要更换行动，仅修改原行动参数不能解决缺口。
- 改进：指出所需证据和合适的替代行动。
- 示例：关键属性在全部报告中仍未确定，却调用answer。

action_parameter_error：行动合理，但参数不足以正确取证。
- 特征：保留行动，修改video_id、clip或instruction即可形成合理请求。这些参数属于analyze_videos和watch_videos，answer没有参数。
- 改进：指出参数如何调整，以及依据哪项输入或先前证据。
- 示例：联合观察窗口排除了报告中已有的候选事件。

action_execution_error：行动和参数合理，但结果存在可证明的缺陷。
- 特征：指出合理请求、结果中可验证的缺陷，以及该缺陷影响的证据需求。支持的缺陷包括明确要求未获回答、结果内部无效、明确执行失败，或错误处理已充分的证据。普通answer在证据充分时仍输出与History矛盾的答案也属于此类。
- 改进：提出公开证据核验或答案一致性规则。不能据结果缺陷捏造合理请求的缺陷，也不要求修改不可见内部实现。若没有可通过现有action或证据处理实现的改进，返回skip，在reason说明执行问题。
- 示例：History明确video_2对应选项B，answer却返回A。

## Classification Boundaries
按当前步骤承担的取证目的评价请求。初次概览可以合理地请求近似时间，也可以同步收集参考和目标描述；检查后续是否在回答前细化决定性信息。保留action并改进参数即可形成合理请求时，支持action_parameter_error；存在另一可用action不证明原action选错。

对于answer，先检查History能否支持符合题目要求的答案。单选候选未排除、计数不匹配任何选项、排序关系未确定时，评估具体可行的补证据机会。有可解决的决定性缺口却answer，属于action_selection_error；证据充分但结果误用证据或违反格式时，评估action_execution_error。其他相关证据仍未解决时，仅与某一报告一致不足以支持答案。answer没有参数。

执行错误需要说明请求要求、直接的结果缺陷，以及为何缺陷属于本步骤。后续报告可能纠正前一报告；报告分歧证明需要协调，不证明哪份报告有错。跨视角矛盾要求对象身份、时间范围和比较标准已经建立。事件时间戳或可疑计数是核验信号，不能揭示内部观察错误或证明观察覆盖范围。

题目确定证据标准。预测任务可能要求依据开头/结尾推断，而非直接观察缺失中间片段。诚实的不确定表达可以是有效执行。相同人物或场景提供连续性线索，不证明直接相邻。

## 证据阈值：需要核验与已证明缺陷

reason、evidence_reason与improvement_principle使用同一证据阈值。区分直接支持的缺陷、具体核验需要和无法解释的结果差异；不能把核验建议改写成隐藏观察已错的断言。

- **直接缺陷**：指出请求或任务的具体要求，以及违反它的公开文字、无效输出、明确失败或已充分且与答案冲突的History。action_execution_error不能仅凭不确定、未提及或题目前提冲突。仅当请求明确要求该项目或穷尽/完整结果时，漏答结果项才是可证明的执行缺陷；初次一般描述可以有所选择。报告说检查0-end并列出10-25秒事件，不证明只检查10-25秒。
- **核验需要**：说明哪个影响决策的区别未解决、既有证据为何无法解决，以及哪个可行动作能取得缺失证据。报告明确限定子区间时，其他区间在公开History中缺乏支持，不证明隐藏模型实际看过哪些帧。终点描述未能建立完全退出时，应澄清对象完全不可见，不证明仍有部分可见或真实退出一定更晚。likely或未提及可以触发仍有可能成立的候选核验，不把报告判假。Agent在此类有依据且可解决的缺口下answer，定位后续answer的action_selection_error；之前诚实不确定的报告不必是故障。
- **仅有结果差异**：没有直接缺陷或具体的决策时核验需求时skip。不借ground truth断言隐藏事件发生在哪、哪份报告遗漏它或重看会揭示什么。最终答案正确也不消除可见缺陷。

每项决策故障仅引用Input和本步骤前返回的结果。本步返回结果可支持执行问题或后续核验需要，不能倒推本步action选择错误。存在假想更优请求不使合理概览变错。比较重复instruction的实际变化，包括扩大标准或描述替代活动；action名称重复或watch_videos可用不证明必须切换action。改进以缺失证据为条件，不承诺正确结果。按证据充分性和可否仅修参数的测试分类；在reason保留未解决不确定性，不捏造更早根因。

## skip前的任务要求检查

即使output与ground truth相同，也根据Input、请求和公开结果执行以下检查。有依据的故障不要求先有GT差异；不能仅因答案遵循报告就跳过可见的任务契约违规。

- **输出契约与证据充分性**：检查允许的选项、答案数量、格式、量词和必要条件。输出选项范围外的答案是可见违规。计数不匹配任何选项、候选并列或合取条件未核验仍是证据缺口；排除其他候选不证明剩余候选满足全部条件。有具体可行复查时定位过早answer选择；证据已足够但返回内容或格式错误时定位answer执行。格式缺陷可与证据不足并存，说明两者并依据决策时证据是否充分分类。题目前提仅提示需要协调的冲突，不能证明特定视频报告虚假。
- **报告范围与覆盖**：比较请求的预期范围与结果明确声称检查的范围。只描述末尾子区间的报告不能证明已覆盖整个请求视频。检查遗漏范围是否可能包含本题必要证据，以及是否能针对补查。请求主动排除已知必要范围支持参数错误；合理请求的结果明确漏答必要范围或标准可以支持执行错误。范围含糊时澄清，不断言未见帧被遗漏。少数事件时间戳或简短报告本身不证明覆盖不足；目标区间足够时不要求全时长观看。
- **事件与比较定义**：保持题目的主语、宾语、事件终点、功能标准和同步时间。“不再完全位于画面内”不等于“完全位于画面外”；其他车辆经过目标不等于目标自身经过；功能相同不要求技术相同。指出请求或结果的文字口径错位及受影响要求，不捏造真实时刻或对象身份。不同视角可见区间可以不同。ID前缀限定身份标签所在视角，不限定底层对象能在哪些视角跟踪；必要时传递身份线索。同一场景两个视角的计数不经事件去重不能直接相加。
- **可核验候选**：区分明确不存在、报告未提及和身份不确定。相关身份仅为likely、关键边界近似、对象对应或排序关系未解决时，可支持针对性核验；不确定本身不证明执行失败。指出具体待区分事实、可用视频/范围或前置条件，以及剩余机会内analyze_videos细化或watch_videos直接比较如何解决，不承诺成功。缺失中段预测应根据提供片段比较合理候选；不要求直接看到缺失事件，也不因GT不同而重查全部假设事件。既有报告已合理比较候选、没有具体可核验缺口时仍应skip。

有无Skill不决定类型。答案遵循合理报告、仅GT不一致，且公开轨迹没有支持的缺陷或可解决的决策缺口时，返回skip。GT确定差异，单独不能确定错误报告。
```

## ANALYSIS

```text
# Analysis Instructions
1. 确定任务要求：从Input识别答案形式（单选、多选、区间、排序）、量词、比较实体及时间范围，区分观察事实与依据给定证据作推断。即使问题措辞使用单数，也保留明确的答案数量要求。随后对比output与ground truth。
2. 重建每步：分开先前决策依据、action和参数、返回结果。同一analyze_videos请求共享调用前证据；依赖新报告的请求应在后续调用。按请求在解题中的作用评价，允许概览后定向细化。
3. 检查答案充分性：累计证据是否支持符合题目要求的答案？指出决定性冲突、缺失条件或未确定关系，以及可解决它的行动。区分提前选择answer和证据充分下的答案执行错误。预测任务评估给定线索能否区分候选，不要求观察缺失事件。
4. 定位并分类：选择1–3个不同可编辑步骤，均有支持缺陷和可行修正，最早有依据根因优先。选择/参数问题属于决策步骤；执行问题属于产生可直接证明缺陷的结果的步骤。执行项说明请求要求、结果缺陷及归属该步骤的依据。仅有冲突时保留对哪份报告有错的不确定性。判重复请求无效前比较实际参数变化。
5. 形成改进原则：每步一句简洁可复用原则，包含触发条件、action或参数修正、所需具体证据或一致性检查。解释换action能解决什么。参数取自拟调用时可用信息，缺失前提说明如何取得。案例细节放evidence_reason，不把仅来自GT的答案、身份或时间用作运行时参数。修正应在相关决策时可执行，包括剩余行动机会。
6. 核对发现与范围：逐项检查编号、action/结果、evidence_reason及improvement_principle对应同一缺陷；reason与fault_chain一致。无支持的可执行定位时skip，包括不可干预执行失败、不可编辑收尾或无法解释的答案差异。Skill编辑留给后续；描述公开证据不足，不声称答案只是碰巧正确。
```

## EXAMPLES

```text
# Examples
以下均为假设示例，不是当前案例证据。

<example type="action_selection_error">
Input：哪个视频向面糊加醋？Videos：video_1、video_2各20秒。Selected skill：None。
Trajectory：Step1 analyze_videos要求识别液体；video_1报告透明液体身份不明，video_2报告有醋瓶但使用情况不明。Step2 answer，output=video_1。
Final answer：video_1。Ground truth：video_2。
Analysis：决定性属性均未确定，应先取证；answer没有可修正的参数。
Output：
{"status":"located","reason":"醋的使用情况未确定就回答。","fault_chain":[{"step":2,"fault_type":"action_selection_error","evidence_reason":"先前报告均未确认哪个视频加醋，却调用answer。","improvement_principle":"用针对性的analyze_videos指令核实未确定的倒入液体后再回答。"}]}
</example>

<example type="overview_then_verification">
Input：返回video_2中与video_1在5–10秒动作功能相同的区间。Videos：video_1为20秒，video_2为90秒。Selected skill：None。
Trajectory：Step1 analyze_videos同步请求参考动作目的和目标步骤近似时间；参考为调沙拉汁，目标报告20–30秒搅拌但目的未知，另有50–60秒类似调汁。Step2 answer，output=20,30。
Final answer：20,30。Ground truth：51,62。
Analysis：同步概览和近似初始时间合理，Step2回答时候选功能与边界仍未确认。
Output（JSON字段与英文示例保持一致）：
{"status":"located","reason":"The overview was reasonable, but the Agent answered before distinguishing the candidates.","fault_chain":[{"step":2,"fault_type":"action_selection_error","evidence_reason":"Two candidates remain, one with uncertain purpose, and neither has verified boundaries; answer selects the first without resolving these gaps.","improvement_principle":"When an overview leaves multiple functional candidates, use analyze_videos to verify their purposes and the matching candidate's start/end boundaries before answering."}]}
</example>

<example type="answer_execution_error">
Input：哪个视频有红车？A=video_1，B=video_2。Videos：各10秒。Selected skill：preserve-identities，整题要求保持视频ID。
Trajectory：Step1 analyze_videos要求识别颜色；video_1蓝车、无红车；video_2红车、无蓝车。Step2 watch_videos，instruction要求确认哪个视频有红车，两个video的clip均[0,10]；obs确认video_1蓝车、video_2红车。Step3 answer，output=A。
Final answer：A。Ground truth：B。
Analysis：Step2提供一致证据，Step3返回错误选项，故执行错误定位在Step3。证据充分，调用answer合理；结果映射错误，answer没有参数。
Output：
{"status":"located","reason":"证据已解决问题，但答案把视频映射到错误选项。","fault_chain":[{"step":3,"fault_type":"action_execution_error","evidence_reason":"History确认video_2红车，输入对应B，answer却返回A。","improvement_principle":"产生答案时核对证据支持的视频ID与题目选项的对应关系。"}]}
</example>

<example type="explicit_label_confusion">
Input：8秒时B2车辆在B3车辆左侧还是右侧？A左、B右。框只标识车辆身份。Videos：view_A/view_B各20秒。Selected skill：None。
Trajectory：Step1 analyze_videos请求view_B识别车辆后报告8秒相对位置；报告明确说比较的是文字标签而非车辆，文字B2在B3左侧。Step2 answer，output=A。
Final answer：A。Ground truth：B。
Analysis：报告明确将车辆替换为文字，独立于GT即可证明执行缺陷；后续回答仍缺少车辆位置证据。
Output（JSON字段与英文示例保持一致）：
{"status":"located","reason":"The report explicitly substitutes text positions for vehicle positions, then the Agent answers without correcting it.","fault_chain":[{"step":1,"fault_type":"action_execution_error","evidence_reason":"The adequate request asks for vehicles at 8 seconds, but the result explicitly states it compares printed labels instead.","improvement_principle":"When a report substitutes labels for their referents, request tracking of the underlying objects from their identity markers to the required time."},{"step":2,"fault_type":"action_selection_error","evidence_reason":"The preceding result supplies no vehicle-position comparison, yet answer selects A.","improvement_principle":"Obtain the requested object-position evidence before answering when the available report describes only labels."}]}
</example>

<example type="unexplained_mismatch">
Input：哪个视频跳跃更多？A=video_1，B=video_2。Videos：各20秒。Selected skill：None。
Trajectory：Step1 analyze_videos明确要求全程完成跳跃；报告分别5次、3次。Step2 answer，output=A。
Final answer：A。Ground truth：B。
Analysis：答案与报告一致，仅GT不一致不能判断具体报告错误或可修正决策。
Output：
{"status":"skip","reason":"公开轨迹支持已有比较，没有暴露具体请求或结果缺陷；仅GT不一致不能定位原因。","fault_chain":[]}
</example>

<example type="concurrent_reference_dependency">
Input：找出video_2中与video_1动作目的相同的区间。Videos：video_1为15秒，video_2为120秒。Selected skill：None。
Trajectory：Step1 analyze_videos同时请求video_1描述动作、对象和目的，video_2查找“锅中搅拌”作为匹配动作。video_1报告给肉裹粉以在烹饪前形成外层；video_2报告70–85秒在锅中搅拌。Step2 answer，output=70,85。
Final answer：70,85。Ground truth：20,35。
Analysis：题目没有给出锅中搅拌标准，这项无依据限制在Step1执行前即可识别。裹粉报告在两个instruction确定之后才返回，因此基于裹粉信息查询目标视频应安排在后续调用。
Output：
{"status":"located","reason":"尚未确定参考动作功能，目标请求便预设了视觉动作。","fault_chain":[{"step":1,"fault_type":"action_parameter_error","evidence_reason":"输入只要求功能匹配，先前没有报告确定参考动作，video_2指令却假设锅中搅拌。","improvement_principle":"参考功能未知时，先用analyze_videos请求其动作、对象和目的，再根据报告于后续调用中组织目标视频指令。"}]}
</example>

<example type="suspicious_timestamp_is_not_proof">
Input：A1离开view_A时B1在view_B哪里？A左、B右。身份框仅在对象首个可见秒出现。Videos：各30秒。Selected skill：None。
Trajectory：Step1 watch_videos覆盖两视频[0,30]，要求识别后跟踪对象，在A1离开时定位B1；obs称A1在1秒离开、B1在左侧。Step2 answer，output=A。
Final answer：A。Ground truth：B。
Analysis：时间可能与标签消失重合，但结果没有证明混淆标签。答案遵循报告，仅GT差异不能归因。
Output（JSON字段与英文示例保持一致）：
{"status":"skip","reason":"The public trace contains no direct evidence that label disappearance was mistaken for object departure; the timestamp and GT mismatch alone do not establish an actionable fault.","fault_chain":[]}
</example>

<example type="prediction_with_uncertainty">
Input：依据开头和结尾推断缺失中间。A乘客错过列车，B乘客登上列车。Videos：beginning/ending各20秒。Selected skill：None。
Trajectory：Step1 watch_videos覆盖两段[0,20]，比较乘客位置和列车状态以评估A/B；obs称乘客跑向离站列车，后站在空月台，错过更可能，但无法排除登车后返回。Step2 answer，output=A。
Final answer：A。Ground truth：B。
Analysis：任务要求推断，报告比较候选并保留不确定性，中间本就未提供；没有证据证明遗漏具体线索或请求有缺陷。
Output（JSON字段与英文示例保持一致）：
{"status":"skip","reason":"The answer follows a plausible evidence-based comparison; uncertainty about an unobserved middle event is not an execution defect, and GT alone does not localize the discrepancy.","fault_chain":[]}
</example>
```

## OUTPUT

```text
# Output Format
仅返回符合Schema的JSON对象。
顶层仅status、reason、fault_chain：
- status为located或skip。
- reason为非空整体理由，解释证据、不确定性或为何无法定位可行改进。
- fault_chain每项恰好包含step、fault_type、evidence_reason、improvement_principle。
located要求1–3个不同可编辑步骤，最早有依据根因优先；skip要求空链，在reason解释执行缺陷或不确定性。
fault_type逐项独立取action_selection_error、action_parameter_error、action_execution_error。
answer无参数，参数错误仅适用于analyze_videos和watch_videos。仅使用Schema允许的步骤，运行时收尾不能定位。
直接输出JSON，不加围栏或外部文字。
{"status":"located","reason":"观察范围不足导致无依据比较。","fault_chain":[{"step":1,"fault_type":"action_parameter_error","evidence_reason":"片段排除了History已有候选。","improvement_principle":"比较片段应包含报告中的候选区间。"}]}
{"status":"skip","reason":"公开证据未提供可行纠正。","fault_chain":[]}
```

## STAGE_CONSTRAINTS

```text
# STAGE CONSTRAINTS
依据三种公开action合同，执行内部为黑盒。
分别判断请求和结果质量，不能用结果缺陷反推合理请求有错。
选择/参数依据行动前信息，执行依据请求和结果；GT不是Agent当时已知事实。
诚实的不确定性与可证明错误分开；跨视频差异可能真实。
不可编辑步骤仅供背景。
后续决策独立分类，不继承此前执行错误类型。
重复行动需有持续缺口和无效参数选择证据，合理复核可以重复。
改进限于已有action或公开证据检查，Skill归因和编辑留给后续。
整题固定一张Skill或没有Skill，不决定故障类型。
```

## Schema

[schema.py](../prompts/localizer/schema.py)：顶层必填status、reason、fault_chain，禁止顶层fault_type及额外字段。每项必填step、fault_type、evidence_reason、improvement_principle；fault_type枚举三种行动故障。step仅能为可编辑步骤；参数错误进一步限定实际action为analyze_videos/watch_videos的步骤。located链长1–3，skip链长0。程序校验不同项不能重复指向同一步，即使类型不同也不允许。

## 轨迹渲染说明

selected skill仅展示Description、When to use、Strategy、Worked example四个内容字段，复用统一卡片格式；不向模型展示Meta中的id、role、stages。内部卡片标识和选择记录仍保留用于审计。未选中时为None；已选中但正文缺失时明确说明内容不可用。

## 2026-10-02：selected skill 可见性对比实验（未替换正式 Prompt）

实验入口 `scripts/analysis/test_localizer_skill_visibility.py`，产物
`outputs/analysis/20261002_localizer_skill_visibility/`。with_skill 使用当前正式 Prompt 与渲染。
without_skill 的静态英文全文保存在该产物 `no_skill_prompt_fields.json` 和 `prompt_ablation.json`，
逐案例实际 System/User/Schema 保存在 `prompts.json`，不被正式 Runtime 或 Trainer 加载。

without_skill 对应中文变更：

- 删除 TASK 中 selected skill 分区说明以及遵循/偏离 Skill、Skill 示例、编辑责任等说明。
- steps 说明改为：解题时实际执行的行动、参数和返回结果；按行动前信息评估决策，按请求与结果评估执行。
- INPUT 只要求联合阅读题目、步骤、最终答案和 ground truth；决策依据为题目、视频元信息和前序结果。
- 删除分类规则中的 Skill 有无、ANALYSIS 中 Skill 编辑职责、STAGE CONSTRAINTS 中 Skill 使用或归因说明。
- 示例保留原问题、action、参数、报告、GT 与定位输出，删除所有 Selected skill 行。
- 共享 BACKGROUND 信息流删除固定 Skill，证据来源删除 Skill 方法/假设示例说明；新加入的两种 action 信息边界保留。
- 模型输入删除 selected skill 分区；不传 used_skill、选卡/正文注入/复用审计字段。保留完整实际问题、参数、报告、答案与GT。

不是删除报告或题目中的自然词汇，例如选项中 dance skills 的“舞蹈技巧”；这些是题目事实，不是 Skill 指导。
两版采用相同 Localizer 输出 Schema，每案例各重复两次。未凭响应合法或差异数量判断质量；
需要核对公开证据支持、步骤归属、纠正可执行性和GT泄漏，并参照同版本重复波动。
