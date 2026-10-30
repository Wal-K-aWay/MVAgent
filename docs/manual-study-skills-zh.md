# 手写机制卡完整中文镜像（2026-10-30）

英文权威资源位于 [manual-study-20261030](../src/mvagent/skills/skill_sets/manual-study-20261030/README.md)，逐文件身份见其 `manifest.json`。
**本批全部未测试。** 由 Codex 手工编写，不是人类领域专家独立卡片，未调用 optimizer API。8 个机制、每个机制 3 种排版，共 24 个单卡非空整库，不是 24 个独立策略，也不作为本轮自动进化的历史种子。
每个库只有一张 `meta={id:"1",role:对应角色,stages:["initial","evidence"]}` 的卡。
同一机制各排版的英文入口、meta、操作句及顺序完全相同：paragraph 以空格连接操作句；numbered 每句前增加 `N. ` 并换行；headings 每句前增加 `#### Step N`。
以下编号仅用于逐句对照，不代表所有英文 variant 都是编号正文；标题标记的差异没有新增操作语义，但会改变 token。
Global／Video 权限不扩大，工具、观察预算及有界终结协议不变；Actor 不自动看到 when_to_use，因此各正文包含执行所需的适用范围。

来源仅是历史合法 Train 公开轨迹的契约缺口；作者此前读过历史汇总，不宣称对历史分数盲法，未依据确认分区逐题材料制作本批卡。
历史卡只作近似机制参照，以下英文操作句为重新手写；未复制旧策略、未加入答案、题号、task 代号或样本固定映射。

## 1. 跨视频依赖闭合（`global_dependency_closure`）

角色：`global`。状态：未测试。

### when_to_use 完整镜像

问题需要先在一个视频中建立某项事实，才能解释另一个视频中的事件、身份或状态；题目可能明确给出视图、标签或同步约定。在发出依赖该事实的局部请求前先解决参考依赖；相互独立的逐视频判断不需要此流程。

### strategy 全部操作句镜像

1. 遇到跨视频依赖时，区分待建立的参考事实与目标结果，并保留当前问题明确给出的视图、标签、时间或同步约定，不虚构对应关系。
2. 复用公开 History 中充分的事实；若目标 instruction 仍依赖未知参考事实，先用 analyze_videos，通过 videoagent_request 指定参考 video_id，并用中立 instruction 请求该事实及其可见依据。
3. 参考报告返回后，仅将其中相关且有支持的描述、来源身份及必要时间约定放入目标 videoagent_request 的 instruction，同时写明尚未解决的局部问题；并发请求不能使用彼此尚未返回的报告。
4. 若对应关系仍会决定答案，且确实需要联合视觉证据，用 watch_videos：instruction 写明选中视频 ID 及待核关系，使用至少两个不同 video_id，每个视频只给一个起点小于终点且位于该视频时长内的 clip，不提供 fps 字段。
5. 把尚未解决的参考依赖，或假定了未提供跨视频事实的报告，视为剩余缺口而非证据；仅在澄清可能改变答案时发出聚焦请求。
6. 依赖关系及所求结果得到支持后，按问题要求的格式回答；到达运行时上限时提交证据最支持的非空答案，在 reason 中保留重要不确定性，不编造缺失参考事实。

### 研究依据与反例（离线说明，不注入 Actor）

待测假设：Closing explicit evidence dependencies reduces instructions that require a local agent to guess unseen cross-video facts.

反例／边界：Already supplied or adequately established anchors should be reused; independent requests should remain parallelizable.

与历史关系：Related to the unmeasured historical delegation candidate and temporal reference transfer; newly written, with dependency closure as the explicit hypothesis.

Train 依据：docs/skill-feedback-iteration-20261022.md: Global委派的约定与依赖诊断 (Train public view)。

英文库：[paragraph](../src/mvagent/skills/skill_sets/manual-study-20261030/a01f8b5e80aa73c4f5f8d74f6b3a87021fd4561b250b1144147d31f8be0c9619.json)、[numbered](../src/mvagent/skills/skill_sets/manual-study-20261030/c57521951888662030c358068f042f2eef494a6703f96a8e955dbc1b0df93446.json)、[headings](../src/mvagent/skills/skill_sets/manual-study-20261030/c051891d459bef0cd00ce6379d71160c8751ef1830d6c0ad555550e9ec103c7c.json)。

## 2. 候选答案区别驱动取证（`global_option_discrimination`）

角色：`global`。状态：未测试。

### when_to_use 完整镜像

问题提供了多个候选答案，且可通过视频中的具体可见事实或关系区分它们的真伪。围绕候选之间的区别取证，而不是对每个视频作一般性叙述；排除未提供候选的开放问题，以及仅凭没有视觉支持的假设才能区分的候选。

### strategy 全部操作句镜像

1. 面对给定候选，找出能够区分尚有可能答案的可见事实或关系，保留问题中的全部限定和实体组合，不把选项标签当证据。
2. 若区别可在单个视频中独立观察，使用 analyze_videos，在每条 videoagent_request 的 instruction 中传入准确、中立的判据及必要上下文，不让局部 Agent 选择答案选项。
3. 若决定性区别是跨视频视觉关系，使用 watch_videos，在 instruction 中写明该关系，提供至少两个不同 video_id，每个视频一个合法的源视频秒数 clip，不给 fps 字段；选择窄片段前，通过局部请求定位未知时刻。
4. 将每项返回事实与它实际能够区分的候选对照，区分没有支持、受到反证和尚未解决的判断；仅有描述缺失不能排除某个候选。
5. 若多个候选仍有可能，用中立后续请求核查最可能改变答案的未决区别；若报告支持多个题目本应互斥的候选，重新核对问题的准确条件。
6. 有支持的区别足以确定所求答案时停止；或依照运行时有界终结机制，使用当前最强依据并在 reason 中简洁说明限制，同时保留要求的答案格式。

### 研究依据与反例（离线说明，不注入 Actor）

待测假设：Neutral acquisition of answer-discriminating facts avoids generic summaries and premature option-level verdicts.

反例／边界：A candidate containing several required conditions cannot be established by inspecting only one convenient difference.

与历史关系：Related to shared-predicate checking, but organized around differences among supplied alternatives rather than one predicate repeated across videos.

Train 依据：docs/skill-exploration-results.md: 已观察到的传递问题 (Train public reports support multiple nominally exclusive alternatives)；docs/manual-global-skills-zh.md: 设计依据与可检验预期 (Train public-view criteria drift)。

英文库：[paragraph](../src/mvagent/skills/skill_sets/manual-study-20261030/21266c1682095f496c3951c769471728dddeccac935c4035a5a4fa76bad66d5e.json)、[numbered](../src/mvagent/skills/skill_sets/manual-study-20261030/6255eeb992dc1f23a56ca843ba38aa5e702b33f98b48edbcb72cda4ec0730710.json)、[headings](../src/mvagent/skills/skill_sets/manual-study-20261030/05d5b3b751b3443b4e38ebcc8ceeeb11bfdcbdd2530af7e8c46072f3055a87b1.json)。

## 3. 跨视角身份候选消歧（`global_identity_candidates`）

角色：`global`。状态：未测试。

### when_to_use 完整镜像

问题的主要任务是判断某个特定人或物是否、或在何处跨视频对应，而不是判断物体是否属于相同类别或具有相似外观。根据题目给出的约定及可见区分证据建立身份候选，再比较未决候选；不从视频 ID 或时长假定对应关系。

### strategy 全部操作句镜像

1. 处理身份对应时，仅提取问题给出的目标描述、标签或视图约定；某视图中的标签不能初始化另一个视图中的同名标签，除非题目明确建立了该映射。
2. 用 analyze_videos 发送自包含局部 instruction，取得每个来源中的候选描述、区分特征、可见路径及相关锚点；缺少初始化证据时请求该证据，不猜测目标外观。
3. 在推理中保留所有与有支持证据相容的候选及其来源身份；仅有类别或颜色相似不能证明是同一个物理实体。
4. 若联合比较可解决某项区分特征，用 watch_videos，在 instruction 中写明候选及特征，使用至少两个不同 video_id，每个视频一个起点小于终点且位于时长内的 clip，不给 fps 字段，并复用已知锚点或先定位相关时刻。
5. 仅凭实际不相容的观察或明确约定排除候选；遮挡或未观察到的特征应保留为未决，不能转成不匹配。
6. 有支持的身份证据解决所求对应后回答；若歧义持续至运行时上限，按要求格式给出证据最支持的答案，并在 reason 中说明身份限制，不编造匹配关系。

### 研究依据与反例（离线说明，不注入 Actor）

待测假设：Maintaining compatible identity candidates makes cross-view comparison depend on discriminating evidence rather than label or appearance guesses.

反例／边界：Category similarity questions need no physical-identity search; no correct candidate is guaranteed to be visible in every source.

与历史关系：Related to joint comparison and convention transfer; the candidate-preservation and elimination procedure was not separately established by the historical tests.

Train 依据：docs/skill-feedback-iteration-20261022.md: Global委派的约定与依赖诊断 (Train view-specific object conventions)。

英文库：[paragraph](../src/mvagent/skills/skill_sets/manual-study-20261030/b08090d7d125fd18eeafb0b7c372e64d34afbd0d124db6181837735822bd1436.json)、[numbered](../src/mvagent/skills/skill_sets/manual-study-20261030/bb6f6f04cdc5c42b9662458740b3d4b3a2d2e11c357835c71ae76b5706be50c1.json)、[headings](../src/mvagent/skills/skill_sets/manual-study-20261030/6d298d3fdf16eaa9756fe2756e43cb5dff3e399863db1908dc40341d5be4f0ed.json)。

## 4. 量词答案上下界与停止（`global_quantifier_bounds`）

角色：`global`。状态：未测试。

### when_to_use 完整镜像

问题需要把可逐视频独立观察的条件，合成为全部、任意、恰好某数、计数或符合条件的子集答案。追踪哪些尚未解决的局部判断仍可能改变答案；排除统计单视频内重复事件的任务，以及无法逐视频独立决定的身份匹配。

### strategy 全部操作句镜像

1. 处理逐视频量词时，保留准确谓词、限定、被计数实体，以及所求结果究竟是真值、数量还是完整子集。
2. 用 analyze_videos，在每个相关 videoagent_request 的 instruction 中提供相同的中立局部判据及必要定义，请求决定性可见依据和尚未解决的限制，而不是缺少依据的笼统判决。
3. 在推理中按来源区分有支持的符合项、有支持的排除项和未知项；计数时，已支持符合项给出下界，加入未知项给出上界，不新增输出字段，也不把遗漏当排除。
4. 检查未知判断的不同结果是否仍会改变所求答案，并注意：即使某个是非量词已经确定，准确子集通常仍需解决每个可能被纳入的成员。
5. 仅针对可能改变答案的缺口发出聚焦局部后续请求；使用报告收紧上下界前，先解决谓词被替换或报告冲突的问题。
6. 当所有与有支持证据相容的结果都给出相同所求结果时回答；若运行时更早结束，按要求格式给出证据最支持的非空答案，并在 reason 中披露未决边界。

### 研究依据与反例（离线说明，不注入 Actor）

待测假设：Answer bounds focus follow-ups on consequential unknowns and support stopping without demanding complete evidence for an already decided quantifier.

反例／边界：A resolved yes-or-no question does not imply that an exact count or complete membership list is resolved.

与历史关系：Builds on shared-predicate semantics but introduces explicit answer bounds and answer-dependent stopping, not a cost or step-count acceptance objective.

Train 依据：docs/manual-global-skills-zh.md: 设计依据与可检验预期 (Train quantifier and predicate drift)；docs/manual-skill-results.md: Global简短库的已有轨迹核对 (Train unknown treated as exclusion)。

英文库：[paragraph](../src/mvagent/skills/skill_sets/manual-study-20261030/7434f8397ebc70bdcf0c6a105698e4e1d7872b876fd98f738d686d87d3c08f9d.json)、[numbered](../src/mvagent/skills/skill_sets/manual-study-20261030/3e7cf263204f1d412a86bffe89ebc633c04970bb9abbae030550ceaf49542b80.json)、[headings](../src/mvagent/skills/skill_sets/manual-study-20261030/b2bdabccc161b9a3bf6f080e6fb4ed61a80c903b88fabfd91a32d00979d636ee.json)。

## 5. 否定判断与覆盖证据（`video_negative_coverage`）

角色：`video`。状态：未测试。

### when_to_use 完整镜像

instruction 询问指定事件或物体是否不存在、是否只出现所列项目，或本地清单是否完整。在作否定或穷尽性断言前，先判断同视频观察覆盖了什么；只请求一个正例的任务不需要此流程。

### strategy 全部操作句镜像

1. 作本地否定或穷尽性判断时，仅用本视频的 instruction 及保留 Memory，确定准确事件或物体，以及 instruction 要求的时间和可见范围。
2. 检查相关保留观察中的正向证据、相反证据及可见性限制；某项未被提及，或曾广泛采样一个区间，本身不能证明不存在。
3. 遇到会影响判断的覆盖缺口时，使用 observe：中立的 what 请求目标证据及可见性限制，where 为实际时长内有序、互不重叠且起点小于终点的区间，fps 遵循当前动作 schema。
4. 区分未观察到与受到可见证据反驳，保留由遮挡、身份不清或采样造成的不确定性，不根据熟悉活动补全清单。
5. 仅核查仍可能改变局部报告的可见区别；要求的断言得到支持，或运行时内没有可用观察可能解决其重要限制时，停止继续取证。
6. 仅在已有可用同视频证据且 finish 可用时，用 summary 报告有支持的本地判断及覆盖限制，不输出内部区间、fps、工具细节、跨视频结论或编造的观察；否则遵守既有有界终结协议。

### 研究依据与反例（离线说明，不注入 Actor）

待测假设：Making coverage relevant to negative claims prevents omitted descriptions from becoming certain absence or complete-list conclusions.

反例／边界：A positive example can resolve an existence question without exhaustive coverage; sparse observation cannot certify universal absence.

与历史关系：Narrows the earlier criterion-evidence warning about omission versus absence into a coverage procedure; this concept is not claimed as wholly new.

Train 依据：docs/manual-video-skills-zh.md: Train局部轨迹中的多判据与笼统结论缺口；docs/skill-exploration-results.md: 已观察到的传递问题 (Train evidence scope narrowing)。

英文库：[paragraph](../src/mvagent/skills/skill_sets/manual-study-20261030/886af9a3e61a6d48c2cf06b6d8e97957df7586246d212fbdf753564d740cbd56.json)、[numbered](../src/mvagent/skills/skill_sets/manual-study-20261030/7c7d61c23dc76da6bbae6aa8a6c466740e438a82ed048ffddbd4b118b2baf651.json)、[headings](../src/mvagent/skills/skill_sets/manual-study-20261030/d6779ab6c568630ab844ccb040c5e000ae67d11456224bf8a8dbfcbf4971067b.json)。

## 6. 事件边界双侧状态夹逼（`video_boundary_bracketing`）

角色：`video`。状态：未测试。

### when_to_use 完整镜像

instruction 要求本视频中事件的开始、完成、持续区间，或对边界敏感的顺序。先确认事件，再用周围状态变化界定要求的端点；排除不需要边界定位的一般性描述和粗顺序任务。

### strategy 全部操作句镜像

1. 处理所求事件边界时，保留准确动作和物体条件，确定 instruction 实际需要哪些端点，仅复用同视频 Memory 支持的锚点。
2. 若事件尚未得到确认，先用 observe：what 请求其可见身份及相关状态变化，where 为时长内合法、有序且互不重叠的区间，fps 合法并适合所求细节。
3. 对未决起点，寻找此前非事件状态及事件开始的证据；对未决终点，寻找事件持续及其后完成或变化状态的证据，不把采样中的首次出现或裁剪边缘当成边界。
4. 保留足够周边上下文，把下一次 observe 聚焦于可信锚点尚无支持的一侧；若事件身份或锚点本身可疑，则扩大搜索，不反复细化同一未经核实的位置。
5. 若事件在可见材料之前已开始、在其后仍继续或仍有歧义，将缺失一侧或端点保留为未决；instruction 要求的时间区别得到支持后停止细化。
6. 已有可用同视频证据且 finish 可用时，在 summary 中报告有支持的源视频事件时间、端点精度及缺失边界，不输出内部观察区间或 fps，并遵守既有运行时上限，不编造完整区间。

### 研究依据与反例（离线说明，不注入 Actor）

待测假设：Flanking state evidence improves endpoint grounding and prevents repeated refinement around an unsupported anchor.

反例／边界：A boundary outside the supplied visible material may remain unknown; coarse event order should not trigger unnecessary endpoint refinement.

与历史关系：Related to event-boundaries and temporal-anchor cards, but explicitly tests two-sided state bracketing and anchor rejection; not a novel concept claim.

Train 依据：docs/manual-video-skills-zh.md: Train时间要求未传入观察及终点缺失；docs/skill-exploration-results.md: 已观察到的传递问题 (Train crop edges used as event endpoints)。

英文库：[paragraph](../src/mvagent/skills/skill_sets/manual-study-20261030/3e46018cb2341818e3f4231d58c151809d427a706841cf3e35238e88f6adee30.json)、[numbered](../src/mvagent/skills/skill_sets/manual-study-20261030/ae5b224dd497e1e78749b91cd090a0ad6eb69125bade55de1e528c48189560d2.json)、[headings](../src/mvagent/skills/skill_sets/manual-study-20261030/e524cf72dd595f7c858e629fb66c725332677abcd08309a9ae9b2c932eec7747.json)。

## 7. 遮挡后身份重新确认（`video_occlusion_identity`）

角色：`video`。状态：未测试。

### when_to_use 完整镜像

instruction 要求在本视频中追踪特定人或物、判断该实体的后续行为，或区分它的重复出现与不同实体。维持本地身份连续性，并明确解决再次出现时的身份；排除不依赖身份的静态类别或属性检查。

### strategy 全部操作句镜像

1. 处理本地追踪请求时，仅根据当前 instruction 的明确约定和保留同视频证据初始化目标；缺少可见身份依据时请求该依据，不从任意标签指定身份。
2. 使用 observe：what 请求目标的可见区分特征、运动及邻近地标，where 为实际时长内合法、有序且互不重叠的区间，fps 遵循动作 schema。
3. 仅在可见连续性或区分证据支持时延续身份；遮挡、离画或无法区分的交会后，保留相容本地候选，不假定最近的再次出现就是目标。
4. 若未决身份可能改变所求行为或计数，检查中断两侧的证据，并询问哪些特征区分返回候选，不根据常见运动模式补全隐藏路径。
5. 仅在保留证据支持时区分不同实体与重复出现；身份相关结果得到支持，或剩余歧义无法在有界请求内解决时停止。
6. 已有可用同视频证据且 finish 可用时，总结有支持的本地身份、相关行为及尚未解决的重识别，不输出内部区间、fps、跨视频匹配断言或虚构轨迹，并保留运行时终结行为。

### 研究依据与反例（离线说明，不注入 Actor）

待测假设：Explicit reidentification avoids transferring later behavior or counts to an entity selected only by appearance or proximity.

反例／边界：A static attribute can be answered without continuous tracking; complete disappearance can leave identity genuinely unresolved.

与历史关系：A new local procedure hypothesis adjacent to historical identity/convention concerns; no historical local tracking benefit is claimed.

Train 依据：docs/skill-feedback-iteration-20261022.md: Train身份约定传递诊断为相关线索，未证明局部遮挡错误频率。

英文库：[paragraph](../src/mvagent/skills/skill_sets/manual-study-20261030/bc0c8bcb27056899178445dd8c307f5ac62620e391054e5c2e7f7ec1169931b4.json)、[numbered](../src/mvagent/skills/skill_sets/manual-study-20261030/d5ff269276d009c36a75933b306064fbc81a9f685720895262e5d46d221cad42.json)、[headings](../src/mvagent/skills/skill_sets/manual-study-20261030/721129e2b06000b0f52c23b84a001a69904c1da0fca54f244291f8e01efa491b.json)。

## 8. 观察工具反馈驱动恢复（`video_observe_recovery`）

角色：`video`。状态：未测试。

### when_to_use 完整镜像

instruction 要求细粒度动作细节、短暂局部事件，或依赖可执行观察计划的事件区间。根据实际时长及可用反馈调整同视频观察；先前报错或隐藏 Memory 不是选中本卡的前提。

### strategy 全部操作句镜像

1. 处理依赖细节的本地请求时，规划 observe 前检查给定时长及保留同视频证据，保留 instruction 的实际目标，不将它替换成宽泛总结。
2. what 使用中立、可通过视觉回答的问题，where 采用实际时长内有序、互不重叠且起点严格小于终点的区间，fps 遵循当前 schema，并保留小数秒，不把短区间取整成零长度。
3. 若 observe 被拒绝或失败，把反馈当作诊断而非视觉证据，找出所述原因，仅在可用反馈支持修正时，更改导致问题的合法参数或取证请求。
4. 若成功观察没有新增决定性证据，更改 what、where 或许可 fps 前，先区分问题不相关、时间覆盖不足和视觉细节仍未解决，不再次发出同一无效请求。
5. 保留证据已支持所求本地结果，或剩余运行时内没有有依据的修正能改善结果时，停止重试；不延长循环、不绕过校验、不增加帧预算，也不调用不可用动作。
6. 仅在已有可用同视频观察且 finish 可用时使用它，在 summary 中写入有支持的事实和剩余不确定性，不输出内部工具失败、区间或 fps；若 finish 不可用，则遵循可用动作及既有有界终结协议，不声称观察已经成功。

### 研究依据与反例（离线说明，不注入 Actor）

待测假设：Feedback-specific changes prevent repeated invalid or uninformative observations without modifying the tool or loop contract.

反例／边界：Successful and sufficient observations require no recovery; unsupported infrastructure explanations must not replace evidence.

与历史关系：Targets an observed Train execution failure with a newly authored recovery procedure; historical cards did not separately establish its utility.

Train 依据：docs/skill-exploration-results.md: Train local-video invalid observe at 0.92 seconds (all compared arms scored zero; no attributed new score loss)；docs/skill-research-handoff-20261022.md: 5.4 Video invalid observe description。

英文库：[paragraph](../src/mvagent/skills/skill_sets/manual-study-20261030/1ccaf9f469aa727f310bd6e5fbde9bb084ba52ab6a1d9138075aa5148d089888.json)、[numbered](../src/mvagent/skills/skill_sets/manual-study-20261030/271050b5f087248275009451148ca31a59c61bcfbd0067b5804a5bce3a3a6641.json)、[headings](../src/mvagent/skills/skill_sets/manual-study-20261030/861c76dc1763dc6347f227dcd5f679d96b7c088da7cc27e05eaed471545b698e.json)。

## Train 修订：候选答案列表须明确存在（未测试）

英文权威新库：[35fbe7b62f2fb0ba9dd1e20915289f46b7e5f4669f81816cdb68cd26e7f49b77](../src/mvagent/skills/skill_sets/manual-study-20261030/35fbe7b62f2fb0ba9dd1e20915289f46b7e5f4669f81816cdb68cd26e7f49b77.json)。父库为 `21266c1682095f496c3951c769471728dddeccac935c4035a5a4fa76bad66d5e`，对应第 2 张 `global_option_discrimination` 的 paragraph 排版。

### 新 when_to_use 完整中文镜像

仅当问题明确提供带标签的候选答案列表，并要求从该列表中选择答案，且能够通过视频中的可见事实或关系区分这些候选时使用。围绕这些候选答案之间的区别获取中立证据。输入视频列表、源视频标签、对象标记或比较两个视频本身，都不构成答案选项列表。不要用于开放式描述、解释，或没有明确候选答案列表的比较问题。

### strategy 与 meta

新库 `meta` 与父库完全相同；`strategy` 逐字节等于父库的 paragraph 正文，完整中文镜像仍为本文件第 2 节的全部 6 个操作句，没有增加或删除执行条件。本次仅将必需的“明确答案选项列表且要求从中选择”前提写入入口，排除源视频标签等近邻误解。

### Train 依据与状态

只审读首批发生变化的 3 个 Train Global 公开问题输入及终答；其中可见开放式比较没有答案列表，另有带标签候选列表并要求选择的问题。该观察支持检验入口条件，尚未证明改写能改善最终准确率。本候选未测试，没有读取确认分区案例用于修订；离线谱系与证据范围保存在 `entry_refinement.json`。原 24 库及 `manifest.json` 不变，本修订不计为第 9 个独立机制。
