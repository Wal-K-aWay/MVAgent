# LLM 一次生成 Skill 库

这是借鉴 SkillOpt 一次生成基线的 MVAgent 适配，不是其未公开生成 Prompt 的严格复现。
仅提供通用多视频问答任务、角色信息边界、目标 Actor 的基础 System、实际动作说明和 Skill 格式；不读取题目、媒体、
答案、轨迹、成绩或已有卡片。不按 benchmark 单独生成，不根据评测结果修订。

在远端项目环境中，凭据通过 `BIGMODEL_API_KEY` 环境变量注入：

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
默认配置 `configs/skill_evolution/llm_generation.yaml` 使用 `glm-5.3-flash`，reasoning_effort=high、temperature=1、top_p=.95、
输出预算16384、HTTP超时600秒；使用现有 BigModel provider 的 JSON mode。
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
生成数据只留实验 runs volume，不进入 Git；可共享的代码和本说明独立备份。

## 代码与配置

核心代码位于 [`src/skill_evolution/generation/`](../src/skill_evolution/README.md)：
`prompts.py` 管 Prompt/Schema，`generator.py` 管调用与产物，`cli.py` 管命令行。
`scripts/generate_skills.py` 仅启动 CLI。模型参数使用已有 `ApiVLMConfig`，
默认文件为 `configs/skill_evolution/llm_generation.yaml`，可通过 `--config` 指定。
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
