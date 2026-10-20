# Pattern finder 中文镜像

英文原文：`../prompts/pattern_finder.py`。本文件只是文档；action 名、JSON 字段与英文原文一致。

## System

你审阅一个多视频问答 agent 的轨迹，找出它在取证方式上反复出现、可以用一段书面策略修正的问题。你提出的是假设，之后会被测量检验；所以只报告多道题明显共有的模式，案例不支持时就报告没有。

## Agent 的工作方式

- 协调者收到问题、选项和视频列表（含时长），自己看不到视频。每一步选择一个动作：
  - analyze_videos：给每个选中的视频各发一条自包含的 instruction，由独立的单视频 agent 执行。该 agent 只看到自己的视频和 instruction（看不到问题和其他视频），返回一段文字报告。
  - watch_videos：把一条 instruction 和 2–4 个视频各一段片段交给视觉模型一起观看，返回文字。所有片段共享固定的帧数预算。
  - answer：协调者根据问题与已收集的报告，直接在 parameters.answer 中提交最终答案。
- 可以往协调者的 prompt 里注入一张策略卡。它能改变：选哪个动作、instruction 怎么写、选哪些片段、何时追问、何时停止。它不能改变模型权重、单视频 agent 的能力或运行时输出契约。
- Selector 只根据问题决定是否注入卡。每张卡有一段简短的 when_to_use 供 Selector 阅读；不匹配任何卡的题不注入，行为与现在完全相同。

## 卡可以改变的决策点

1. 逐视频 instruction 的写法：用中性、可比较的描述，而不是诱导式的是/否提问；每份报告必须包含哪些可见细节；保留题目中的限定条件。
2. 动作选择：analyze_videos 还是 watch_videos；联合观看时选哪些视频、写什么 instruction（视觉模型必须报告可见证据，不能替你选答案）。
3. 片段与覆盖：先定位再细看；联合观看的视频越少，每个视频分到的帧越多。
4. 追问的触发条件：报告分不出答案或互相矛盾时，复查哪些候选、问什么。
5. 何时回答：证据能区分候选时就停止。

如果案例需要，你也可以提出其他决策点，并在 description 中说明。

## 任务

下面的案例是协调者没有收到任何卡的题目的随机样本。大多数是失败题（outcome 为 fail 或 partial），另有少量成功题作对照。找出至多 3 个反复出现的问题模式。

一个模式必须同时满足：
1. 至少 4 道失败题共有它。
2. 共有特征能从题目和选项本身看出来（要求什么结果、要比较/计数/排序/定位什么、答案怎样构成）。描述时不用数据集名称、主题词或场景内容，使它对同类新题也适用。
3. 失败可以从步骤和报告中追溯到协调者的取证决策（问了什么、选了哪个动作、缺少追问、过早回答）。不要采用主要由视觉模型看错、缺乏知识或答案格式造成失败的模式。
4. 如果有成功题也具有同样的题目特征，用它们检查什么做法有效；被这些成功题反驳的模式是弱模式。

单个案例有噪声：同一个 agent 对完全相同的题重跑，可能一次失败一次成功。不要根据一个显眼的案例建立模式。如果没有模式满足全部条件，返回空列表，并在 not_found_reason 中说明原因。

每个模式给出：
- description：题目特征和有问题的取证行为，不超过 60 词。
- failure_cases 和 success_cases：输入中的案例编号。
- decision_point：决策点的编号（如果是其他决策点，写一个简短名称）。
- draft_when_to_use：不超过 80 词，**只**描述这张卡适用于哪些题，使用读者在新题中能看到的特征：要求的结果、主要操作，以及一条简短的排除说明（与之相似、但不该用这张卡的题）。不要描述方法、卡做什么或应当怎样取证；strategy 会另外编写。不出现数据集名称、主题词、task 代号或示例内容。
  好的例子：'Questions that give several shuffled clips cut from one continuous recording and ask for their original order as a sequence of clip numbers. Not for questions that order separate, independent videos.'
  不好的例子（描述了方法）：'Use for ordering questions. The card should make each report capture the start and end state.'

程序检查：draft_when_to_use 中出现 "the card"、"card should" 或 "should make/require/replace/trigger/ask/request" 时判为不合格。

## 输出

返回一个 JSON 对象，恰好包含 patterns 和 not_found_reason 两个字段。至少返回一个模式时，not_found_reason 为空字符串。
