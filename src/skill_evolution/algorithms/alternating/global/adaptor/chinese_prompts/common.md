# common.py 中文镜像

仅供阅读，不被Runtime加载。

## BACKGROUND

````text
# 目标 Agent

## 可用信息
Agent 接收完整的多视频问题，包括选项和约束，以及可用的视频 ID 和时长。

## 可用动作
以下参数是每个 action 的 parameters 对象中的字段。
- analyze_videos(videoagent_request=[{video_id, instruction}, ...])：请求分析所选视频。为每个视频提供仅凭该视频即可回答的完整指令。每条请求返回对应视频的报告。Agent 需要综合报告进行跨视频推理。
- watch_videos(instruction, videos=[{video_id, clip: [start, end]}, ...])：可用时，请求对至少两个不同视频进行联合视觉分析。指定比较内容，并为每个视频提供一个片段，时间使用各自源视频的秒数。结果提供联合观看这些片段得到的证据。
- answer()：根据系统自动提供的问题与累计 History 生成最终答案。该 action 无输入参数，输出为最终答案。

## action 的信息边界
analyze_videos 为每个视频返回一份围绕 instruction 的独立文本报告。报告可以保留明确要求的事件、数量、时间和属性，但它压缩了视觉证据。细微外观、姿态、空间关系或短暂转变可能被遗漏，或描述得过于粗略而无法支持详细比较。未报告的特征仍是未知；描述相同不能证明视觉上等同。每个单视频分析只能检查所分配的视频，因此跨视频对应仍由 Agent 建立。
watch_videos 将选定片段共同提供给视觉模型，按 instruction 进行联合分析，使比较发生在证据被压缩为各视频独立报告之前。它为后续决策返回文本联合观察，不会把全部视觉细节保存在 History 中。证据受所选片段、帧采样和模型感知能力限制。长片段在帧预算约束下可能稀疏采样，片段外或采样帧之间的细节仍未观察到。联合观看本身不能建立同步关系或对象身份；题目和观察到的特征必须支持所需对应关系。

## 信息流
每次决策时，Agent 拥有题目、视频元信息、已选中的整题固定 Skill（如有），以及先前已完成行动的 History。每个 Step 记录所选 action 和参数，随后记录该 action 返回的结果。该结果成为后续决策的依据。
同一 analyze_videos 调用中的所有 instruction 都在本次任何报告返回之前确定。每个视频请求接收自己的 instruction，并可保留其先前的本地观察；除 instruction 提供的内容外，它无法访问其他视频的报告或 Agent 的 History。依赖另一个视频新报告的请求应放在后续调用中。
Agent 看到公开报告与联合观察；action 内部推理和观察轨迹保持私有。报告中的事件区间描述事件，仅在结果明确说明观察覆盖范围时，才可据此确定覆盖范围。

## 证据来源
题目和选项定义任务，包括量词和比较标准。Skill 提供方法指导，其示例为假设情境。action 结果提供带有其声明的不确定性的报告证据。离线分析提供的 ground truth 用于确定答案差异，解题时不可用。关于哪个 action 出错的判断需要公开轨迹支持。

## 必需结果
按照要求的格式，返回完整多视频问题的最终答案。
````

## CARD_CONTRACT 中文镜像
# Skill Card Specification
## Purpose
Skill 提供可复用的整题证据方法，是方法指导而非任务证据。
## Card structure
卡片内容由两个非空英文字符串组成：
- when_to_use：一句简短任务描述及必需的输入关系，用于检索和选卡。
- strategy：可执行的取证与决策流程。
从可用卡库中选择适合当前问题的 Skill 时，检索与选择只根据 when_to_use 匹配题目，不读取 strategy。选定后，只有 strategy 作为方法指导插入 Agent 系统上下文。编号由程序分配；修订保留编号、role 和 stages。
两个字段描述同一方法：when_to_use 标明 strategy 支持的任务，其任务范围和输入关系对应正文真实依赖及能力；strategy 在不读取选择字段时仍可执行。
两字段合计和渲染正文满足输入总词数预算，按解码文本而非 JSON 语法计词。字母、数字、下划线组成词，词内撇号或连字符保留，独立标点不计。
## Design requirements
下面介绍各字段的作用、内容细节和规范。
### when_to_use
when_to_use 是一句简短英文，说明这张 Skill 支持什么任务。它是检索与选择的匹配线索，对应观察前已有的原始问题、选项及视频 ID/时长。

句子说明所需结果，以及识别该任务必需的输入关系，例如同一视频打乱的片段、缺少中段的前后片段，或指定事件时刻的同步视角。这些区别属于任务本身：已提供片段排序不同于片内动作关系比较，累计事件次数不同于某一时刻状态，对应区间定位不同于细粒度视觉比较。

范围与 strategy 实际支持的任务一致。可复用任务不因偶然题材、对象、具体视频数、时长或选项数而缩窄，除非方法确实依赖这些条件。尚未得到的观察、返回报告和私有记忆不是选卡输入。“视频分析”等泛泛表述不能识别具体任务。

字段采用自然任务表述，不包含执行步骤、动作名、参数规则、关键词清单、重复近义表述或独立排除列表。必要的任务区别融入该句；具体方法及执行要求属于 strategy。

examples:

- strong example: Order shuffled segments from one continuous video.
- weak example: Order five cooking clips according to the recipe.

- strong example: Infer the missing event between earlier and later video segments.
- weak example: Use analyze_videos to inspect both endpoints, compare their states, then test which event connects them.

- strong example: Count event occurrences over a video interval.
- weak example: Count objects or events across videos, either at one moment or over an interval.

### strategy
strategy 是完成任务的编号流程。它说明先获取什么信息、怎样使用这些信息、重要细节仍不清楚时检查什么，以及哪些证据足以支持回答。每步明确 action、相关视频和 instruction 要求获取的信息。计数单位等必要定义放在使用它们的步骤中。

流程使用可用的 Global action 和合法参数。视频 ID 和时间来自输入或此前结果，不能依赖尚未返回的报告。每条 analyze_videos 请求只凭所分配的视频即可回答。watch_videos 至少比较两个不同视频，每视频一个合法 clip，instruction 明确比较内容；需要解决视觉差异时使用，而非每次比较都自动使用。

补查针对可能改变答案的具体缺口，改变相关 instruction 或范围。未报告的细节仍是未知，不能据此判定不存在；描述相同不能证明对象相同，联合观察也受片段和采样限制。训练答案、样例和偏好的选项不是观察事实。所需结果得到支持后调用 answer(parameters={})，未解决的不确定性保留在 History 中。流程遵守题目的判定标准和输出要求，不阅读 when_to_use 也可以执行。

strong examples:
- 1. Use analyze_videos with one videoagent_request per supplied segment; each instruction requests its start state, end state, actions and uncertainty from that video alone.
  2. Match reported end states to start states. If an adjacency is ambiguous, use watch_videos on the disputed videos with clips inside their supplied durations; instruction requests the distinguishing boundary cue.
  3. When the chain is supported, check that every segment occurs exactly once, then call answer with no parameters. If observation cannot resolve a boundary, preserve the uncertainty in History.

weak examples:

- Compare the returned counts. If they disagree, request another check and choose the best-supported option.
- Ask view_C to locate the anchor event; in the same analyze_videos call, ask view_D to count at 21 seconds before that anchor time has been established.
- Add a top-level clip parameter to analyze_videos to limit the request to the disputed interval.
- Counts from synchronized views must match. Recheck different counts until they agree.
- If the named event cannot be located, use a representative nearby moment to answer the event-time question.
- If the event is absent from the report, mark it absent from the video; if no option fully matches, choose the closest option.
- Order the segments from their reported states and answer, without checking that every supplied segment appears exactly once.
- To infer a missing middle event, watch the supplied beginning and ending clips until the middle event is directly observed.
- If joint observation contradicts the individual reports and a repeat does not reproduce it, fall back to the original reports.
