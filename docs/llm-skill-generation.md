# LLM 一次生成 Skill 库

这是借鉴 SkillOpt 一次生成基线的 MVAgent 适配，不是其未公开生成 Prompt 的严格复现。
仅提供通用多视频问答任务、角色信息边界、目标 Actor 的基础 System、实际动作说明和 Skill 格式；不读取题目、媒体、
答案、轨迹、成绩或已有卡片。不按 benchmark 单独生成，不根据评测结果修订。

在远端项目环境中，凭据通过 `DEEPSEEK_API_KEY` 环境变量注入：

```bash
python scripts/generate_skills.py --role both \
  --output-dir /runs/devbox/one_shot_skills/run1
```

输出目录必须不存在。默认 `--role global`，可选 `video` 或 `both`。
每个角色单独一次请求，默认 1–8 张卡；`--max-cards N` 设每角色上限（N 在 1–8 内），不是固定生成数量。
LLM 根据方法差异选择实际数量，不补齐名额、不按动作或执行阶段凑卡；程序只校验范围，
没有按题目分布或分数估计最优卡数。`--role both` 最多16张，但每个角色最多8张，
各角色候选都可完整展示给 Selector，无需触发大库的 embedding 检索。这不证明8张最优。
两种角色使用独立上下文，不读取另一角色刚生成的卡。
默认配置 `configs/skill_evolution/llm_generation.yaml` 使用 `deepseek-flash`，thinking启用、reasoning_effort=high、
输出预算16384、HTTP超时600秒；复用现有 DeepSeek provider 的 JSON mode。该客户端在thinking模式不发送temperature/top_p，
DeepSeek当前服务默认top_p=1；不是此前GLM的top_p=.95。参数依据[官方Thinking文档](https://api-docs.deepseek.com/guides/thinking_mode/)
及[Chat API文档](https://api-docs.deepseek.com/api/create-chat-completion/)。本次不修改生成System/User Prompt、预算或数量上限；
JSON Schema的附加说明由各自现有provider注入，包装措辞可能不同，不声称两个模型的完整HTTP请求逐字一致。
没有任务反馈、自动重试、生成修复、人工润色或按分数挑选。
该生成配置不改变 Actor 固定的 seed=0 等评测设置。

程序分配顺序数字 ID，role 由调用方设置，所有卡的 stages 为 initial/evidence。
Selector 的 task scope 保持原样；Global 每题、Video 每次请求首次选择后沿用。
现有 Runtime 校验字段、字数及渲染，之后重新按 SHA256 加载 role bank 和完整 bank。
完整库成功后生成 `runtime_with_skills.json`：复制输入模型/Agent/推理配置，只替换两个角色的 skill 引用；
本次生成的角色启用同一完整库，显式 `selection_scope: task`，绑定绝对路径和SHA256，
未生成的角色关闭skill，不沿用输入配置中的旧库。现有 YAML 配置加载器也可读取此JSON，
评测时直接将它传给 `eval/agent_eval/run.py --config`；该文件不会启动服务或运行评测。
移动产物时必须更新库路径；现有实验沿用自己的冻结配置。
这些检查不证明选卡适用性、真实行为或准确率收益；本入口不运行 Actor 或 Judge。

结果包含每角色 request.json、response.json、events.jsonl、validation.json、bank.json，
以及合并 bank.json、summary.json、runtime_with_skills.json、生成配置、输入运行配置、源码快照和逐文件 SHA。
summary 记录每角色实际卡数、每角色上限与目标selection_scope；失败时不发布配套运行配置。
响应在解析之前保存；失败目录保留，不能覆盖后假称首次成功。
events 包含实际请求体、响应正文、模型身份、finish_reason、usage 和耗时；不含认证请求头。
使用现有 provider 日志，不声称保存了供应商完整 HTTP 响应或 reasoning_content。
原始生成数据保留在实验 runs volume，不进入 Git。明确选定的冻结 JSON 库可作为运行时资源
原样收录到 [`src/mvagent/skills/skill_sets/`](../src/mvagent/skills/skill_sets/README.md)，
同时记录来源、规范化步骤和 SHA256；生成器本身不自动向源码目录发布库。
当前已收录 DeepSeek-Flash 的 14 张规范化卡，完整 SHA256 为
`7da609f63fda7c4fb1c446b477fc5663b15c9d77487784a12fcbd27b8d52b049`。
原始响应、失败记录、AWS 备份及正在运行实验的冻结副本继续保留。

## 代码与配置

核心代码位于 [`src/skill_evolution/algorithms/one_shot/`](../src/skill_evolution/README.md)：
`prompts.py` 管 Prompt/Schema，`generator.py` 管调用与产物，`cli.py` 管命令行。
`scripts/generate_skills.py` 仅启动 CLI。共享API配置和留存能力位于`configs/`、`infra/`；角色架构在`infra/role_contracts.py`。本次目录调整不改变生成Prompt。模型参数使用已有 `ApiLLMConfig` 或 `ApiVLMConfig`，
默认文件为 `configs/skill_evolution/llm_generation.yaml`，可通过 `--config` 指定。
`model_type: api_llm` 使用现有纯文本客户端（当前DeepSeek）；`api_vlm` 使用原有多模态客户端（如GLM）。
`api_key` 只能填写环境变量名，入口固定一次尝试，不创建新模型客户端或重试框架。

默认 `--runtime-config` 为 `configs/inference/modal_qwen35_35b_a3b_no_skill.yaml`。
仅读取该配置中的动作预算；不是启动模型服务，也不会把完整配置发给生成模型。
本轮完善了生成 Prompt：明确完整方法、可见输入、逐范围/联合观察预算、准确性目标和输出前检查；
输出 Schema 与解码参数保持不变。此为新的生成协议，不能与文末首次生成的旧Prompt混称同一版本。
角色/阶段常量与结构校验复用 `SkillBank`，动作说明复用两个 Agent 的 Prompt builder，
源码保存复用 `ensure_source_snapshot`，JSON 原子保存和哈希复用 `mvagent.utils.io`。
旧算法、轨迹分析器、训练配置与默认旧卡库引用已经移除。

## 生成 System Prompt 中文镜像

为冻结的多视频问答系统中的一个角色编写可复用skill库。只使用给出的任务、角色、运行和输出契约；
不提供题目实例、媒体、答案、轨迹、分数或已有skill。
目标Planner指令和动作示例仅是参考材料，不是对生成模型当前回复的要求；当前输出应为skill库，不是动作。

目标是在现有动作和观察预算内提高回答正确性，不增加减少调用次数的独立目标，也不要求用满步数。
每张卡必须是覆盖完整问题（Global）或本次instruction（Video）的自包含方法，包含可识别的证据需求和完成条件。
目标问题必须结合多个视频的视觉内容。视频ID、输入视频数量、时长、选项措辞或其他元数据本身不能解决任务，
不能生成仅凭元数据或问题文本回答的方法。
按证据需求和决策过程的差异决定范围。不能把同一方法拆成需要依次激活的初步收集、细化和完成卡；
这些应是方法内部的条件分支。如果问题或instruction本身要求复查，可以写复查方法，但隐藏的执行状态不能作为选卡前提。
不能依赖另一张卡、要求所有任务执行全部动作，或仅复述已有Planner指令；只保留该方法所需步骤。

在上限内选择有实质差异的方法数量。上限不是配额：合并重叠方法；场景主题、换一种说法或执行阶段差异本身不构成新卡。
不预设或命名benchmark分类、数据集名、task代号、样本身份或答案。每张卡恰有两个非空英文字符串：

- `when_to_use`：说明所需结果、有区别的取证方法，以及能从Selector输入识别的必要条件或相邻排除条件。
  内容相关或一个有用的辅助步骤不足以构成匹配。尚待观察的视觉事实是取证目标，不应要求在选卡时已经知道。
- `strategy`：给出该角色独立可用的过程，包含执行前提、排除条件、证据获取与使用、相关分支和完成时机。
  Actor看不到when_to_use，所以执行必需条件必须在strategy内。

Selector看不到History或Memory。依赖未提供的先前观察、冲突、证据充分性或失败尝试的条件放在strategy内，由Actor检查自己的证据。
问题/instruction明确给出的要求或上下文属于选卡时可见的输入。
不虚构工具、共享记忆、输出字段、观察事实、时间锚点或角色可见的额外信息。保持问题/instruction及所有动作与回答契约。
若选中方法的前提不满足，应使用现有动作继续基础取证流程；不能因为选了此卡就强制采用其首选动作或提交无依据答案，
这不需要重新选卡。Video请求可能已有先前请求保留的可用观察；决定observe或finish前，先根据当前instruction检查Memory，
不能假定Memory为空或要求每次请求都重新观察。
采样选择必须联系证据需求和给定限制，不能把自行设定的FPS范围、分段数或重试次数当成普遍硬要求。
不能对卡片覆盖的所有任务无条件限定只细化一次或只观察两次；允许的检查仍可改变判断时继续，证据充分或进一步检查无用时结束。
卡片保持简洁，字数上限不是写作目标。

返回前逐卡检查：适用性可从Selector输入判断；方法能在整个选卡范围内使用而不换卡；动作、预算单位与完成条件符合角色契约。
检查卡片差异来自方法而非仅主题、措辞或执行阶段。只返回一个JSON对象，唯一顶层键是skills。
每项只能有when_to_use和strategy；不能额外添加prerequisites、exclusions、checks或解释字段；执行前提与排除条件写在strategy字符串内。
这些是同一次生成内的检查要求，不是额外LLM调用或程序化语义验证。

## 生成 User Prompt 与动态角色契约中文镜像

任务：回答证据分布在多个视频中的问题，答案需要多个视频的视觉内容；元数据只能指导取证，不能替代视觉证据。
全局协调者综合返回证据，每个视频的证据Agent响应局部instruction；
内部观察不会自动共享。目标角色为`{role}`，拼接的角色契约如下：

- Global Planner仅处理文本，看完整问题、视频ID/时长和公开History；看不到VideoAgent内部Observe或中间观察。
  analyze_videos发送互相独立、各自完整的局部指令；后续动作可把已返回事实写入新指令。
  watch_videos对至少两个不同视频做联合视觉调用并返回文本证据；answer提交parameters.answer。
  Global策略不会自动传给VideoAgent或视觉模型，必要任务上下文必须通过动作instruction传递。
  普通轮次重复决策，但不提供剩余步数计数。
- Video Planner仅处理文本，负责一个视频，看本次局部instruction、源视频时长和按时间排列的同视频Memory；
  看不到完整Global问题、其他视频、Global History或视频像素。observe提供一个视觉问题、有序源区间和一个计划FPS；
  有可用观察后可以finish总结。观察在同视频跨请求保留，但当前instruction定义本次任务。普通轮次重复决策，不提供剩余步数计数。

Global普通决策上限为`{global_max_steps}`。一次watch_videos的全部所选片段共享`{max_video_frames_per_request}`帧上限；
Runtime分配容量并决定采样，不能给每个片段各算一份完整预算。
Video每次instruction的普通决策上限为`{video_max_steps}`。一次observe内每个range单独调用视觉模型，
每个range各有`{max_video_frames_per_request}`帧上限；整个observe或instruction没有这一总帧数预算。
同一动作提供一个计划FPS，Runtime根据每个range的容量调整实际FPS；不能把一个帧上限除以全部range时长之和。

随后按角色原样拼入本次源码中的Planner System及动作说明：Global的GLOBAL_AGENT_SYSTEM_PROMPT与动作builder，
Video的VIDEO_PLANNER_SYSTEM_PROMPT与动作builder。数值来自输入运行配置；这不是新增示例skill或数据集样例。

选卡与注入契约为`selection_scope={SELECTION_SCOPE}`，固定为task：

- Global Selector只看完整问题、视频ID与时长；看不到History、观察或报告。取证前选一次，整题沿用，包括不选。
- Video Selector只看当前instruction；看不到Memory、源时长或Global问题。每次instruction开始选一次并沿用，包括不选。
  后续请求重新选，Actor的同视频观察Memory仍保留。

Selector只读候选when_to_use，最多选一张或不选；必须直接匹配所需结果和主要取证操作，仅内容相关或辅助步骤不够。
最近似或唯一候选仍可能被拒选。Actor只接收strategy，范围内不会激活其他卡；后续依赖证据的决策必须在策略内部条件分支中完成。
Global强制answer-only终答保留策略；Video强制总结只读Memory/instruction，不读取规划策略。

输出1至`{max_cards}`张不同方法卡，模型自行决定数量；继续生成会重复方法时就少生成，不为达到上限而额外添卡。
每卡两字段合计与包含标题的strategy渲染正文分别不超过`{MAX_SKILL_WORDS}`words，优先简洁可执行的指令。
只返回`{"skills": [{"when_to_use": "...", "strategy": "..."}]}`；调用方分配ID、role和stages。
不返回metadata、额外键、Markdown围栏或说明，输出前检查字段名与全部契约。

## 历史测试库清理（2026-10-21 UTC）

按用户要求，已删除以下三轮GLM测试的完整`bank.json`、`global/bank.json`、`video/bank.json`，
以及后两轮的`runtime_with_skills.json`（共11个文件）：

- `devbox/one_shot_glm53_20261020/run1/`
- `devbox/one_shot_contract_20261021/run1/`
- `devbox/one_shot_contract_20261021/revision2/run1/`

原始请求、响应、事件、校验记录、summary和冻结源码保留；下面的库哈希与加载结果属于历史记录，
对应库文件现在已经删除。清理回执位于同一runs volume的
`devbox/one_shot_skill_library_cleanup_20261021/receipt.json`。
该清理发生时，DeepSeek首次生成的原始响应与失败记录保留，尚无通过校验的DeepSeek库。
随后仅删除额外 null 字段得到当前规范化库，来源和限制见[库目录说明](../src/mvagent/skills/skill_sets/README.md)。
后续成功生成时，库仍写入`--output-dir`指定目录下的`bank.json`，配套配置为`runtime_with_skills.json`。

## 首次真实生成（2026-10-21 UTC）

运行源码 `98ad0c4`；Modal CPU app `ap-KtgWYywyIdxH6SrYeqKfzK` 已正常结束，GPU使用为0。
两个针对性测试和完整 `compileall src scripts eval/agent_eval demo.py` 通过。
每角色一次请求，无自动重试/格式修复；两次返回模型均为 `glm-5.3-flash`，finish_reason=stop。

| 角色 | 卡数 | 耗时/秒 | 输入token | 输出token（含reasoning） | 每卡字数 |
|---|---:|---:|---:|---:|---|
| Global | 5 | 23.94 | 1892 | 1064 | 173/179/140/133/129 |
| Video | 4 | 31.62 | 1338 | 1501 | 293/246/248/210 |

全部通过结构、字数、渲染与哈希加载。结束后通过新的 Volume SDK 读取核实完整库及两个角色库 SHA。
原始输入、响应、日志及库位于 runs volume 的 `devbox/one_shot_glm53_20261020/run1/`。
完整 `bank.json` SHA256：`1b9d4d10ceee49924b1a473c31a639a1d39de7f9ab5ac206866b9a0f5ccd5ee3`。

输出示例（Global第5张）：
“If phase-1 reports already resolve the question completely, skip phase 2 and answer directly”。

本次只验证生成流程，没有运行真实 Selector、Actor、视频问答或 Judge。
阅读产物发现 Global第3/4张、Video第6–9张的部分 when_to_use 依赖 History/Memory，
而当前 Selector 看不到这些信息，可能无法正确触发；Video策略还将每范围的帧上限写成跨范围共享上限。
这些是生成基线的局限，产物保留原样，没有据此改写或重新生成；不能据格式通过宣称策略有效。

## 清理与分层后的验证（2026-10-21 UTC）

源码 `39217ef`：旧算法和训练入口移除；生成器分层，共享评测迁至 `src/evaluation/`。
角色 Prompt、Schema 与有效模型配置逐项对比首次运行保存的请求，全部相同。
评分模块移动前后逐字节一致。26 个 CPU 回归用例通过（首轮25个通过，
一个新测试因排序GT误用整数失败；仅修为契约要求的字符串后补测通过），
另有 token 自检、完整 compileall 和5个CLI入口检查通过。
没有重装依赖、运行媒体测试、启动GPU、Selector、Actor或Judge。

真实 GLM 冒烟 app `ap-QQOhYUejHNczs0ya93OoF4` 已停止，tasks=0。
仅一次 Global 请求；返回 `glm-5.3-flash`、finish_reason=stop、1892输入/1339输出token，
返回5张卡，但第一张包含未允许的 `prerequisites` 字段：

```text
$.skills.0: Additional properties are not allowed ('prerequisites' was unexpected)
```

原始字段值为 `No cross-video evidence in History yet, or existing reports are insufficient for the question.`。
生成器先保存响应，再按现有 Schema 拒绝；没有发布角色库或合库，没有继续 Video 调用，
没有删除字段、自动修复或重新抽样。因此本次测到的是一次真实的格式失败及正确的失败留存，
不是新的有效skill库或准确率结果。此前首次运行的9张有效卡及原始材料保持不变。
记录仅在 runs volume 的 `devbox/skill_generation_cleanup_20261021/checks2/smoke1/`；
测试日志在同父目录及 `devbox/skill_generation_cleanup_20261021/step0.log`。


评测目录随后统一迁至 `eval/`，通用保存工具改为 `mvagent.utils.io`。
生成器及其源码快照不依赖评测包；本次目录调整不改变上面的 Prompt、模型参数或历史产物。


## 契约完善过程中的实测记录（2026-10-21 UTC）

源码`22d563b`首次加入完整流程、可见性、Actor基础System和预算单位说明后，
GLM每角色一次返回Global 3张、Video 4张，均stop，完整库SHA256为
`0b6a368c589467870e30f8619033978387a56d03bf79d4756b569fc6cd1d1f87`。
Global 51.86秒、2483输入/2040输出token；Video 57.96秒、1963输入/2507输出token。
这说明卡数由模型决定，并非固定生成8张。原始记录在runs
`devbox/one_shot_contract_20261021/run1/`。

该次输出仍有明确缺陷：Global第1张尝试仅凭元数据回答，且误选后仍禁止取证；
部分Video策略假定没有既有观察，并要求固定的观察/细化次数。它们与本任务的
多视频视觉内容要求及跨请求Memory契约不符；没有将这些卡手工改写为合格产物。
源码`160165a`进一步明确了这些任务/运行契约，单独在`revision2/run1/`生成；
没有加入题目、答案、轨迹、分数或把第一版卡片提供给生成模型。
两次是不同Prompt版本的工程冒烟，不应合称同一次生成，也不是按问答分数挑库。

源码`f92bf6c`另修复输出目录解析：保留`/runs/`等公开挂载路径，避免将符号链接
解析为容器内部路径。8个针对性测试与完整compileall通过；第一版库仅修正配套
运行配置和summary中的路径，原文件备份在`path_fix/`，10个受保护原始文件SHA不变，
修复没有调用模型。生成卡片、请求、响应、事件和冻结源码均未改写。


最终源码`160165a`的独立生成已完成，app `ap-YdY81lar9DTML1VW7BoWI5` exit0、stopped/tasks0。
8个针对性测试、完整compileall和CLI检查通过。每角色一次GLM请求，无修复、重试或重抽，均finish_reason=stop。

| 角色 | 卡数 | 耗时/秒 | 输入token | 输出token（含reasoning） | 每卡字数 |
|---|---:|---:|---:|---:|---|
| Global | 3 | 58.13 | 2684 | 2588 | 276/275/247 |
| Video | 4 | 75.94 | 2164 | 3320 | 383/317/314/318 |

完整库SHA256：`45c4ac01fe78c374b073ada108d81819d02b361a0c20a6ee0a3dfe2d2a1d7adc`。
记录位于runs `devbox/one_shot_contract_20261021/revision2/run1/`，配置为同目录的
`runtime_with_skills.json`。新的SDK读取已核对库文件SHA和两个角色的task选卡引用、SHA及`/runs/`路径。
产物文字观察：Global不再有仅凭元数据作答的卡，四张Video卡都先检查并复用Memory；
例如第4张以 `Compare the active instruction with all retained same-video Memory lines` 开始。
这不是语义合格的自动证明：Global第1/3张范围存在重叠，第3张正文有偏向恰好一个匹配视频的假设，
局部取证与采样策略也仍需验证。保留原样，尚未运行真实Selector、Actor、视频问答或Judge，不能声称精度提升。


## DeepSeek-Flash首次生成记录（2026-10-21 UTC）

按用户要求，默认生成模型改为`deepseek-flash`，复用已有纯文本客户端；
源码`84cd9f9`的生成System/User Prompt与上一版GLM相同，每角色上限仍为8。
Provider注入的Schema说明不同；DeepSeek thinking/high沿用现有客户端行为，
不发送temperature/top_p，不将其与GLM的采样参数称为完全一致。
9个针对性测试、完整compileall和CLI检查通过。密钥只从环境变量/Modal Secret读取。

Global首次请求正常返回6张候选，finish_reason=stop，2819输入/11210输出token
（其中reasoning8734），请求至响应约63.65秒。每张均含额外的`strategy_note: null`，
严格校验拒绝，错误为`$.skills.0: Additional properties are not allowed ('strategy_note' was unexpected)`。
原始响应和事件保存在runs `devbox/one_shot_deepseek_flash_20261021/run1/global/`；
没有删除多余字段、修改卡片、修复或重抽，也未发布Global库。
原both流程在Global失败后中止，随后单独完成Video的首次请求；两个角色仍各仅一次生成，
不能把这次记录称为一次成功的双角色库生成。

Video首次请求返回8张候选，finish_reason=stop，2287输入/8911输出token
（其中reasoning6219），请求至响应约52.26秒。每张均含额外的`strategy_placeholder: null`，
同样被严格校验拒绝；原始记录在runs
`devbox/one_shot_deepseek_flash_20261021/video_first_attempt/run1/video/`。
两个角色均未发布bank或runtime_with_skills.json；本次没有可运行的新skill库。

新SDK读取确认每角色各一个model_request/model_response，实际请求为deepseek-flash、
thinking/high、JSON mode且不带temperature/top_p；两个角色的生成器request.json分别与
上一版GLM的对应文件内容相同（provider附加的Schema包装除外）。两份response.json的SHA256：

- Global：`a1f7b237076dbbb676b582d289deb302279316f74a987ef3c0392e84dfaff11b`
- Video：`85e3531c31a572fced9c4149d358399e6e55ab4738b485b3400b85db34257fd9`

CPU apps `ap-RW9miB9iKB3x0QsdB4LfZg` 与 `ap-09goeiMARMSgnmEOdYWi94` 均已stopped/tasks0。
无GPU、Actor、Selector或Judge调用，0道问答/0项准确率评分。结果说明当前Prompt配合JSON mode
未能保证该模型一次遵循Schema，不证明策略内容的效果，也不证明DeepSeek普遍无法生成合格库。
