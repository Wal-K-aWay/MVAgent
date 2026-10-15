# PRO6000 源码对齐与后续实验方案

2026-10-15。**状态：源码对比已完成，以下实验尚未执行。按用户要求，等主进程结束后再实施。** 本工作项只保存这份文档，不修改推理代码、不提交 GPU 作业、不安排自动启动，也不改变已有任务及其冻结源码。

目标：在保留当前确定性推理配置、MVAgent 架构和公开接口的前提下，判断哪些源码差异解释了旧 PRO6000 结果与当前结果的差别，优先寻找减少格式错误、空答案且没有明显准确率损失的最小改动。源码对比只能提出原因假设，不能证明恢复旧代码就会恢复旧分数。

## 1. 来源与比较边界

已核对的 GitHub 快照固定为 [`6b1e5641719e5e12202737ed66f218250a8b4bd6`](https://github.com/Wal-K-aWay/MVAgent/commit/6b1e5641719e5e12202737ed66f218250a8b4bd6)，提交说明 `Add portable results and source snapshots`，提交时间 2026-10-15 19:55（北京时间）。后续取源码必须固定此 SHA，不使用会移动的 `main` 代替历史证据。

| 来源 | 应使用的目录 | 说明 |
|---|---|---|
| 旧 9B | [9B source_snapshot](https://github.com/Wal-K-aWay/MVAgent/tree/6b1e5641719e5e12202737ed66f218250a8b4bd6/outputs/portable/mvagent/no_skill/qwen3_5_9b/source_snapshot) | 较早实现，schema、结构化生成、裁剪方式均与后来版本不同 |
| 旧 27B | [27B source_snapshot](https://github.com/Wal-K-aWay/MVAgent/tree/6b1e5641719e5e12202737ed66f218250a8b4bd6/outputs/portable/mvagent/no_skill/qwen3_5_27b_mvagent_no_skill/source_snapshot) | 结果目录名为 `qwen3_5_27b_mvagent`；其 portable manifest 的 `source_model` 指向左列目录，不应因命名不同认错来源 |
| 旧 35B-A3B | [35B source_snapshot](https://github.com/Wal-K-aWay/MVAgent/tree/6b1e5641719e5e12202737ed66f218250a8b4bd6/outputs/portable/mvagent/no_skill/qwen3_5_35b_a3b/source_snapshot) | 与旧 27B 的核心运行时很接近，但不是旧 9B 的同一版源码 |
| GitHub 根目录 | [根目录 src](https://github.com/Wal-K-aWay/MVAgent/tree/6b1e5641719e5e12202737ed66f218250a8b4bd6/src) | 普通 answer 动作仍调用独立回答器；不是要恢复的旧直接回答实现 |
| 当前比较对象 | 本地已经采用直接回答的 `src/` | 本地 HEAD 为 `4eb309b`，存在未提交修改；不能只凭 HEAD 还原运行时，须使用逐文件 SHA 和冻结源码 |

本次只获取相关源码：四套目录共 244 个 Python/Markdown 文件、97 个不同 Git blob，约 0.8 MB，逐个核对 Git blob SHA；未把原始实验结果或媒体下载到本地。没有重算整份历史 `runtime_snapshot_sha256`，也没有验证旧环境镜像、全部依赖及实际 GPU 内核。临时源码目录不是长期实验依赖，以以上固定提交和路径为准。

该远端提交是无父提交的导入快照，不是本地主线的普通后继提交。**不要通过覆盖当前 `src/`、直接 pull/reset 或合并整个快照来做实验。** 只抽取明确指定的组件，保留独立分支和结果目录。

## 2. 已核实的关键差异

### 2.1 正常终答已经恢复；步数耗尽的终答仍有差别

- 三套旧 PRO6000 快照的正常 `answer` 动作，均从同一次决策的 `parameters.answer` 直接取答案。当前代码已经恢复这个结构。
- 旧快照的 `GLOBAL_ANSWER_SYSTEM_PROMPT`、`GLOBAL_ANSWER_PROMPT_TEMPLATE` 和 `GlobalAgent.answer()` **并非完全没有调用**：正常回答不用，但达到步数上限时，Engine 调用独立终答方法。
- 当前步数耗尽时调用同一 `decide(answer_only=True)` 接口，只开放 answer；不再有独立回答器。
- GitHub 根目录版本则在正常 answer 和步数耗尽时都调用独立回答器，因此不能把根目录当成旧 PRO6000 直接回答基线。

证据：[旧 27B Engine](https://github.com/Wal-K-aWay/MVAgent/blob/6b1e5641719e5e12202737ed66f218250a8b4bd6/outputs/portable/mvagent/no_skill/qwen3_5_27b_mvagent_no_skill/source_snapshot/mvagent/engine.py#L467)、[旧强制终答调用](https://github.com/Wal-K-aWay/MVAgent/blob/6b1e5641719e5e12202737ed66f218250a8b4bd6/outputs/portable/mvagent/no_skill/qwen3_5_27b_mvagent_no_skill/source_snapshot/mvagent/engine.py#L780)、[根目录 Engine](https://github.com/Wal-K-aWay/MVAgent/blob/6b1e5641719e5e12202737ed66f218250a8b4bd6/src/mvagent/engine.py#L481)。

建议：保留当前直接回答架构；把主动结束和步数耗尽分别统计。不要为了“复原旧代码”默认加回已经删除的独立回答器。

### 2.2 Global 决策提示没有完整恢复为旧版

| 项目 | 旧三模型快照 | 当前直接回答 |
|---|---|---|
| System | 短角色说明：协调多视频、只使用公开视觉证据、保留视频身份、选择取证或回答 | 更长的通用规则：核实冲突、改变检查焦点、停止条件、一至两句说明、完成输出 |
| User 排布 | Question → Videos → **History → Available actions** | Question → Videos → **Available actions → History** |
| 正常 answer 的门槛 | 证据应充分解决完整问题及决定答案的分析；不能只是“已有一些证据” | 判断有支持，或进一步检查不能带来有用信息时，提交最佳判断 |
| reason 与 answer | 明确要求答案表达 reason 已确立的唯一结论，不另换选项、不在答案中继续推理 | 保留简洁、按题意作答，但没有同样明确的结论一致性约束 |

这会影响第一轮动作、取证路线和停止时机，不只影响最终输出格式。不能把当前恢复 `parameters.answer` 后的分数变化全部归因于删除一次回答调用。

旧 System 原文如下；第一项实验只替换这一段，其他内容逐字保留：

```text
You are a coordinator for multi-video question answering. You cannot view videos directly. Your visual evidence consists only of successful single-video summaries and completed joint-watch results in History. Preserve video identities and choose one available action that either obtains missing evidence or returns the final answer.
```

来源：[旧 Global prompts](https://github.com/Wal-K-aWay/MVAgent/blob/6b1e5641719e5e12202737ed66f218250a8b4bd6/outputs/portable/mvagent/no_skill/qwen3_5_27b_mvagent_no_skill/source_snapshot/mvagent/agents/global_agent/prompts.py#L13)。旧 answer block 中特别值得单独观察的要求是：`parameters.answer` 与 reason 已形成的最终结论一致；不能仅因“已有一些证据”就停止取证。它们是否改善准确率，仍需实测。

### 2.3 旧三个模型的输出限制不是同一套

| 限制 | 旧 9B | 旧 27B / 35B | 当前 |
|---|---|---|---|
| reason 字符上限 | 无 | 1200 | 取证 1200；answer 决策无字符硬限 |
| answer / instruction / what / summary / visual text | 无对应 maxLength | 2400 / 1600 / 1600 / 3200 / 2000 | 与旧 27B/35B 相同 |
| analyze 指令总预算 | 没有后来这套动态字符预算 | 4800 字符含 reason，给指令预留 3600；单视频不超过 min(1600, floor(3600/N)) | 与旧 27B/35B 相同 |
| 单次完整生成预算 | 2048 token | 2048 token | 2048 token |

旧 9B 的 schema 还更宽松；旧 27B/35B 与当前有更严格的视频 ID、范围、重复 ID 和动作分支约束。当前 VideoAgent schema 与旧 27B/35B 内容一致。

`maxLength` 是字符约束，2048 是整次生成 token 预算，两者不可混称。有限预算内反复生成 reason、导致 answer 尚未输出，是另一类问题；放开所有字符限制不等于解决这种循环。也不能把旧 9B 的无上限策略泛化为三模型历史统一设置。

来源：[旧 9B Global schema](https://github.com/Wal-K-aWay/MVAgent/blob/6b1e5641719e5e12202737ed66f218250a8b4bd6/outputs/portable/mvagent/no_skill/qwen3_5_9b/source_snapshot/mvagent/agents/global_agent/schema.py)、[旧 27B 共享字符约束](https://github.com/Wal-K-aWay/MVAgent/blob/6b1e5641719e5e12202737ed66f218250a8b4bd6/outputs/portable/mvagent/no_skill/qwen3_5_27b_mvagent_no_skill/source_snapshot/mvagent/schema.py)。

### 2.4 9B 还有结构化生成和媒体裁剪两项独有差异

- **结构化生成**：旧 9B 发 `response_format=json_schema`、`strict=True`。旧 27B/35B 在托管模型池路径及当前代码使用 xgrammar 的 compact grammar（`any_whitespace=False`、紧凑分隔符）。不能把 compact grammar 当成三个旧模型都未使用的新改动，也没有证据认定它导致分数下降。
- **接口兼容**：当前同步服务支持 `structured_outputs`，不接受旧 `response_format` 请求字段。以后测试 JSON schema 路径，必须在当前协议内验证 `structured_outputs={"json": schema}` 等受支持形式及实际约束效果，保留完整事后校验；直接复制旧 HTTP 参数不是有效对照。相同 JSON schema 也不代表不同依赖版本会产生相同 token 约束。
- **裁剪**：旧 9B 用 OpenCV 按帧取片段并重新编码；旧 27B/35B 和当前用 FFmpeg stream copy 为主，需补帧时才转码。后两者的 `mvagent/utils/media.py` 内容相同。两种方法可能产生不同解码边界和帧序列，同一问题、同一时间范围未必对应逐帧相同的视觉输入。

来源：[旧 9B provider](https://github.com/Wal-K-aWay/MVAgent/blob/6b1e5641719e5e12202737ed66f218250a8b4bd6/outputs/portable/mvagent/no_skill/qwen3_5_9b/source_snapshot/models/vlm/api/providers/openai_compatible.py)、[旧 27B provider](https://github.com/Wal-K-aWay/MVAgent/blob/6b1e5641719e5e12202737ed66f218250a8b4bd6/outputs/portable/mvagent/no_skill/qwen3_5_27b_mvagent_no_skill/source_snapshot/models/vlm/api/providers/openai_compatible.py)、[旧 9B 裁剪](https://github.com/Wal-K-aWay/MVAgent/blob/6b1e5641719e5e12202737ed66f218250a8b4bd6/outputs/portable/mvagent/no_skill/qwen3_5_9b/source_snapshot/mvagent/utils/media.py)。

### 2.5 不支持优先回滚的项目

- Global/Video 的 memory 实现在三个旧快照与当前之间内容相同。没有证据把现象归于新引入的“历史记忆机制”，也不应先把全部 reason 塞入历史。
- 旧 27B/35B 的 Video prompt 与当前主要是 skill 文本注入辅助实现的差异；本比较双方 skill 均关闭，不能把未启用的 Selector 当成原因。
- 旧服务走标准 `vllm serve`，旧配置为 dtype `auto`、上下文上限 262144；当前显式 BF16、上限 131072，并固定同步服务及数值后端。旧参数未显式固定现在的全部内核和缓存选项，不能据此断言旧实际精度/内核与当前相同。
- 旧 9B 多视频调用顺序与后来的并行设置不同；旧请求超时较短，当前更长。没有实际超时、上下文触顶或调度故障证据时，这些不是第一批改动目标。

## 3. 已有结果能支持什么

已完成的 [126 条完整 Agent 对照报告](../direct_answer_panel_20261015/README.md) 中，直接回答相对独立回答器的格式不合格数为 **38→2**、空答案 **12→0**，新协议 1352 次模型调用无服务错误。但是面板包含定向旧失败题，不能把该比例当作全量故障率；共同随机面板仅 32 题，9B/35B 有准确率退步，不能声称准确率无损。

具体需要解释的现象：

- **9B Comparison1662**：旧路线分别分析视频，最终 D 正确；新路线改为联合观看，视觉报告和答案改变，A 错误。应检查最早动作及证据分歧，不能只比较最后一次回答。
- **9B MOC170**：旧答案 `}`，当前直接答案 C 正确。说明直接协议已修复部分格式问题，没有必要把独立回答器作为默认恢复方案。
- **27B ICL1125、35B KIR188**：当前仍出现 reason 循环、2048 token 截断，修复后输出完整但答案仍错。结构完整和判断正确必须分别衡量。
- **35B PEA555**：原空答案变为非空 D，但答错且 reason 仅逗号。非空字符串并不保证内容质量，不应再加合法选项枚举掩盖模型行为。

主进程正在扩大的计划面板为每模型 300 题、三模型 900 个配对，见本地主线 `outputs/direct_answer_random_20261015/README.md`；本次未核验其最终完成状态。**后续以主进程的最终冻结源码、manifest、样本表、有效结果和审计为基线，不能把本文中的阶段状态视为已完成。** 既有独立回答器、PRO6000 与 E2E 数据是次级历史对照，不代替当前直接协议基线。

## 4. 后续实验固定项

以下各臂均保持相同，只有明确列出的实验因素可变化：

- 三模型：Qwen3.5-9B、27B、35B-A3B，BF16；8×H100，每卡独立 TP=1 / DP=1 / 并发=1，池级 DP=8，整题固定副本。
- `qwen35-bf16-flashinfer-sync`，FlashInfer GDN、原生 GemmaRMSNorm，seed=0、temperature=0、top_p=1、thinking 关闭；不引入采样惩罚或投机解码。
- prefix/MM processor cache 关闭，正常解码 KV 开启；保留输入哈希、实际 token、服务身份及缓存计数。
- 2048 输出 token、每次最多 512 帧、Global/Video 各 5 步；当前媒体预处理、视频调用方式、修复逻辑、超时设置保持基线值。
- Global/Video skill 均关闭；接口、动作集合、VideoAgent 信息边界、直接回答架构保持不变。answer 仍为开放非空字符串，不按 benchmark 枚举合法答案。
- 同题、同输入文件、同评分器；保存原始轨迹后评分。任何源码/配置不同的实验另建目录，不混写主进程结果。

只改 prompt 时沿用已验收推理配置，不重复整套一致性矩阵。若改变结构化生成路径或媒体预处理，仅对受影响路径做少量逐请求输入/token 和完整轨迹复核；有限样本通过不等于任意输入保证。

## 5. 实验顺序：先最小对照，再决定扩展

### 5.1 固定面板和基线

1. 主进程结束后，先读取最终报告，确认三模型有效条数、冻结源码和配置。以其**当前直接回答**作为 A 基线；源码和输入相同的已有轨迹直接复用，不为新日期重跑。
2. 从上述共同 300 题中用 seed=0 预先固定 **60 题筛选面板：每 benchmark 20 题**。CV/MVU 按原生 task 分层、尽量保持总体权重，Cross 九闭式任务尽量均衡；三模型共用题号。保留抽样清单及哈希，选题不读候选答案/得分。不得改写主进程原 300 题清单。
3. 已知 `}`、空答案、循环及 Comparison1662 等案例另列诊断组，仅复用已存在该模型轨迹的对应题；不把专挑失败题的改善混入随机面板指标。
4. 首个测量单元是 **9B 的 S 臂完整跑完这 60 题并与 A 配对**；不要求其他消融或诊断工具全部准备完。无严重回退时，再完成另外两个模型。代码有效但结果负向也应保存和报告。

### 5.2 首轮只考察 Global prompt

所有改动限制在实验快照的 `src/mvagent/agents/global_agent/prompts.py`，不修改共享正式文件。

| 臂 | 相对前一臂的唯一组件变化 | 要回答的问题 |
|---|---|---|
| A | 最终冻结的当前直接协议 | 当前真实基线是什么？ |
| S | 相对 A，只替换为第 2.2 节旧 System 原文 | 较长的新通用决策规则是否改变路线、停止行为或造成负收益？ |
| H | 相对 S，只把 History 移到 Available actions 前 | 提示排布的增量作用是什么？这一步明确属于 User 模板改动，不称为 System-only |
| P | 相对 H，只恢复旧 `ANSWER_ACTION_PROMPT_BLOCK` 的内容；保留下面的强制终答例外 | 更明确的证据门槛和 reason–answer 一致性契约是否改善直接回答？ |

按 S→H→P 顺序推进，逐臂同时报告相对 A 和相对前一臂的差值。这是**顺序消融**，H/P 的效应依赖前面已改变的背景，不能声称已经测出所有交互或独立主效应；证据不足时不扩成全排列。若 S 明显退步，先分析再决定是否运行后续臂，不自动把 S 采用为正式设置。

P 不能机械恢复旧门槛后让步数耗尽题拒绝作答：在当前 `answer_only` 情境明确“没有进一步取证机会，提交现有证据支持的最佳判断；重要不确定性放在简短说明中”。只在实验提示渲染中表达这个例外，不恢复旧独立回答器、增加额外调用或延长步数。P 是恢复回答约束的候选，不宣称与历史整套运行时完全相同。

每臂记录：第一轮 analyze/watch/answer 比例、总轮数、强制终答比例、取证次数、reason 长度/重复、最终格式、逐题分数及最早轨迹分歧。固定旧 History 重放只能辅助区分“取证变化”与“终答变化”，不能代替完整 Agent 主指标。

### 5.3 仅在前面结果仍有未解释问题时追加

每次只选一个有实际证据支持的项目，不预先启动全矩阵。

| 条件 | 最小实验 | 不能据此声称 |
|---|---|---|
| 27B/35B 的 answer reason 仍循环或反复触顶 | 固定同一 prompt，对比当前终答无字符硬限与旧 1200 字符限制；总预算仍 2048 token，提示标注和 schema 同步 | 限字数一定提升准确率，或旧 9B 也应采用 1200 |
| 9B 指令/报告实际受字符限制，丢失题目定义或关键证据 | 先定位具体字段，再只放宽该字段；保留 ID、时间范围、非空和完整 JSON 校验 | 可以一次去掉所有限制，或所有 schema 差异都已排除 |
| 9B 仍存在难解释的格式/生成问题 | 相同 prompt/schema，对比 compact grammar 与当前服务支持的 JSON-schema 生成路径；先验证约束真正生效及少量重复调用 | 新接口等于旧环境的精确复现，或不同方案之间 token 必须相同 |
| 9B 的同片段视觉证据显著变化 | 固定原视频和同一时间范围，先比较两种裁剪的实际解码帧数、时间位置和内容哈希；有差异再做完整 Agent 对照 | 帧不同就必然导致准确率下降，或 27B/35B 也发生了同一裁剪回退 |
| 退步集中在步数耗尽题 | 分层比较主动/强制终答，必要时固定相同 History 做离线终答诊断 | 应恢复独立回答器架构；那是另一个需要明确决策的变更 |

框架已在运行中提供的服务恢复、超时和修复逻辑保持原样；除非本批出现明确运行故障，不把本任务扩成工程重构。

## 6. 评分、可靠性与采用标准

- **每模型 × 每 benchmark 单独报告**：n、官方聚合分、相对 A/前一臂差值、逐题改善/退步数；CV/MVU 沿用现有 task 权重，Cross 只覆盖九闭式任务 macro，FSA 按连续 IoU。此面板不含 CCQA，不运行 Judge，也不称为 CrossVid 十任务总分。
- 格式不合格数明确是否含空答案，另列空答案、合法 JSON 但答案格式偏差、JSON/schema 失败、输出截断、修复次数、传输/服务失败。工程故障保留原始记录并单列，不能伪装成模型正常答错；若重跑，保留所有尝试和统一重试口径。
- 沿用现有官方评分器和已修正的格式检测器。CV 多选项在一个字符串中、`: C` 可读答案、Cross 参考尾空格等已知问题按既有报告口径披露；不修改评分器来“修复”候选收益。MVU 的 E2E 原指令位置与移后版本分别标明，不混合来源。
- 对每个分数差给出同题、按 task 分层的配对 bootstrap 区间（抽样 seed=0），复用现有统计实现。小样本无显著差异不等于证明无损；不要用三模型平均掩盖 9B 或某个 benchmark 的下降。
- 人工检查有代表性的改善/退步轨迹，优先找最早动作或证据分歧，分别判断证据丢失、错误观察、证据解释、答案表达及工程故障。reason–answer 一致性作诊断，不加进官方得分。
- 耗时、请求数、输出 token 和峰值上下文作为辅助结果，不以速度抵消准确率损失，也不因更快而选定方案。

60 题只作筛选。候选若减少格式/空答案、没有明显分模型/benchmark 回退且轨迹解释合理，再扩到原共同 **300 题/模型**，复用其中已完成的候选 60 题，不重复推理。不预先声称有统计把握证明零损失；区间很宽、退步集中或证据冲突时结论写“未确定”，保留负结果。所有这些数据都属于开发面板，选优后仍不能当独立留出验证。

完整三 benchmark 最终结论还需覆盖原计划的完整数据及 CrossVid 2500（含 CCQA 的正确评分）；本小规模方案不替代那一阶段。正式采用前先提交对照结果和候选差异，不能凭本文自动覆盖主线配置。

## 7. 主进程结束后的执行与交付

1. 读取主线最新 `.claude/status.md`、`.claude/benchmarks.md` 及最终实验报告，确认任务已结束、结果持久化，定位实际冻结源和 manifest。本文不承担后台监控或自动启动。
2. 使用独立 worktree 和新 Modal 结果目录，从实际冻结源码复制实验基线，再应用每臂唯一补丁。每臂保存源码、配置、样本、模型/硬件身份和逐文件 SHA；本文备份分支不是后续运行环境的替代品。
3. 开展 Modal 工作前读取项目 `mvagent-environment` skill，经 `ssh modal-gpu` 读取该机 `~/.agents/skills/modal/SKILL.md`。准备、提交与管理均通过 dev box；本机只放代码和 Markdown，不做模型推理、安装或完整测试。
4. 复用公开入口 `eval/agent_eval/run.py` 的 `--config`、`--execution-config`、`--sample-ids-file`、`--output`；保留接口。60 题清单替代 `--limit`，二者不能混用。准确率臂正常评分；仅生成一致性探针时才使用 `--inference-only`。闭式面板不加载 Judge。
5. 第一阶段以一次 **60 分钟活动工作检查点**为预算（不是 GPU 完成时限）：先产出 S 的首个完整模型单元；若排队或长题超时，记录真实阻塞/有效进度，减少尚未启动的可选臂，保留已选题和失败记录，不临时丢弃长题。沿用项目单一实验执行者规则，避免重复提交。
6. 所有原始/派生结果保存在 runs volume `wxu-evolve-agent-runs-20261006` 的新目录，例如 `devbox/pro6000_alignment_<实际日期>/`。至少保留 `selection.json`、每臂 `manifest.json`/冻结源、完整 rollout/请求日志、配对评分与审计；这些是交付内容约定，不要求另造一套评测框架。
7. 本地只保存 Markdown 报告：每臂有效样本、每模型/benchmark 主指标、可靠性计数、实际轨迹解释、限制及下一步。远端验证完成后按既有备份规则提交该工作项；不夹带其他会话代码。

**首个可执行动作：等主进程结束，冻结其直接回答基线与 60 题清单，仅替换 Global System，先跑 9B 完整 Agent 同题对照。** 不先回滚整个 src，不先更换 FlashInfer/精度/并发，也不先恢复独立回答器。

## 附：本次源码检查锚点

以下为本次检查时本地主目录内容的 SHA256，用于识别本文“当前”的含义；后续基线仍以主进程最终冻结 manifest 为准。

```text
d68f4cf2f2e1141619864e5c2118215474282ba57820d5356e756ed3503d47a7  src/mvagent/agents/global_agent/prompts.py
53bfcc82de6092ecf855004ea13c72fabdcc8f688bd68ca832bae0610bc0f6b8  src/mvagent/agents/global_agent/schema.py
7ea46825dc75b9cbaf45cb8b15031ca84dc495fb8b37f5118cbb7e20e696fb1d  src/mvagent/engine.py
d0c9d7b6f7a9904dfb20bad0ced4e4448891d3b2a73ccda4c5bfe8a2e1fe785d  src/mvagent/utils/media.py
cd96f9630bed9ca599370de8daf50830642f91efaf85f25f5be83208f225d931  src/models/vlm/api/providers/openai_compatible.py
30ec2146bba040c0db5ecb7b6ab3090aa1faec4b4f70ec12569bbe93dd5bd713  src/models/vlm/local/sync_server.py
```
