# Global Skill 自进化算法设计

本目录已实现 `global-cluster-v2` 的主流程，完成小规模真实工程烟测；当前 optimizer Prompt 的后续修改尚未重新实测。原 `global-cluster-v1` 实验已按用户要求停止。实现参数、入口与缓存边界见 [README.md](../README.md)。本文第 1.1 节的embedding驱动迭代分组是待实现方案，其他流程按当前实现说明。
Skill 格式、Runtime、作者字段规范及评分沿用现有契约；本文只说明优化算法。

设计中的模块名表示算法职责，代码不要求每种职责各建一个文件。实际对应：scheduler/search_pool/state_store → `search.py`；rollout/cal_evaluator/gate → `evaluation.py`；四阶段调用与 candidate_builder → `optimizer.py`；evidence → `evidence.py`；question_groups → `question_groups.py`；主流程 → `trainer.py`。

主流程：**scheduler → rollout + evidence + analyzer + planner → generator / reviser + candidate_builder → cal_evaluator → search_pool → gate。**
对应六步：选择父版本 → 运行与诊断 → 单卡候选 → 完整 Cal → 更新搜索池 → 定期 Gate。

## 0. 由新流程确定模块边界

三种不同的判断：**轨迹暴露了什么问题、该对库做什么修改、修改内容怎么写**。

**四个 optimizer 模块**

### analyzer

**输入**

- 一个 batch 的轨迹（原始题目、选项、视频元信息，基于当前 parent 库的健康公开轨迹和结果评估）。
- 少量在当前父库下核实的相关成功／失败案例；不输入卡正文和用途目录。

**作用**

- 综合多条轨迹，定位失败现象、相关步骤和应保留的成功行为；本轮聚焦一个有证据支持的问题。
- 区分已发生的事实、可能原因和未确定项，不直接判断应修改哪张卡。例如，“将未报告事件当成不存在”是执行问题，是否属于卡正文缺陷还需 planner 核实。

**输出**

- issue：任务需求、失败现象、案例／步骤引用、相关成功行为、可能原因和未确定项。
- 无可分析问题时输出 no_issue。

### planner

**输入**

- analyzer 的 issue，以及相关原始题目、公开轨迹片段和案例引用。
- parent 库用途目录、相关完整卡、实际检索／选择／注入记录。

**作用**

- 将执行问题与现有 Skill 对应，检查指导是否存在、是否实际注入和被遵循，决定生成、修订或跳过。
- 根据原始案例核对 issue，不把分析摘要当作新的观察证据。生成前检查相关已有方法，不能因拒选或候选为空直接新建。
- 路由问题可发生在动作之前，不强制每个计划都引用执行步骤。

**输出**

- ready：单卡编辑计划，包含 WHEN／STRATEGY／NEW 操作、目标卡或 null、证据引用、修改目标、冻结字段、预期收益及应保留行为。
- skip：无法提出有依据的修改时，输出跳过及理由。

### generator

**输入**

- planner 确定的 NEW 编辑计划。
- 支持新方法的相关原始案例、必要对比卡和 CARD_CONTRACT。

**作用**

- 将计划中的新方法写成完整 Skill，保证用途与策略一致，并保留证据支持的通用范围。
- 不自行更换操作或扩大计划范围；ID、角色和阶段由程序分配。

**输出**

- 新卡的 when_to_use 和 strategy。
- 无法形成符合计划的有效内容时，输出 skip 及理由。

### reviser

**输入**

- planner 确定的 WHEN／STRATEGY 编辑计划，以及目标卡和冻结字段约束。
- 相关失败、成功和边界案例、必要对比卡和 CARD_CONTRACT。

**作用**

- 定向修订已有 Skill，保留有效内容与成功行为，不更换目标卡、操作或修改范围。
- WHEN 只修改用途；STRATEGY 只修改策略。冻结字段由 candidate_builder 从父卡复制，无需模型重复输出。

**输出**

- WHEN：新的 when_to_use；STRATEGY：新的 strategy；附修改摘要。
- 无法完成符合计划的修订时，输出 skip 及理由。

四个模块分别维护 Prompt 与 Schema，generator 和 reviser 共享 CARD_CONTRACT、模型调用与程序校验基础设施。
计划的证据和风险由程序关联保存，不要求作者重复归因。

典型轮次调用三个 optimizer 阶段：analyzer → planner → generator 或 reviser，不同时调用两个作者模块。
no_issue 时不调用后续阶段，skip 时不调用作者；每轮只调用一次 planner。
此拆分尚未证明更高效或更准确，需要比较同执行预算下的最终 QA 收益、有效候选比例和调用开销。

### 执行与控制模块

程序模块负责调度、证据构造、校验和接受规则。涉及 embedding、Actor、selector 或评分模型时复用现有服务。

| 模块 | 输入 | 输出 | 调用位置 |
|---|---|---|---|
| **question_groups** | Train／Cal 原始输入、冻结的 embedding 与图配置 | 固定分组及输入身份 | 初始化一次 |
| **scheduler** | 搜索池、分组、Train 错误索引、展开记录、预算与停止规则 | 父库、Train batch、Gate 触发与继续／停止决定 | 第 1 步及每轮结束 |
| **rollout** | 题目集、完整库、执行配置与 repeat 身份 | 原始结果、公开轨迹、实际路由与注入记录、逐题评分和健康状态 | Train、Cal、Gate、Test 的统一执行入口 |
| **evidence** | 当前父库 rollout、历史、父库、上下文预算及目标阶段 | 分阶段证据视图、相关卡引用、省略项、待核实历史 pending_refs | 第 1～3 步；analysis 视图不含卡文本，planning 视图含路由与相关卡，authoring 视图聚焦编辑计划 |
| **candidate_builder** | 父库、ready 计划、generator／reviser 输出、字段与总预算规则 | 作者调用前返回程序合法的计划或无效原因；调用后返回不可变候选库及修改记录；NEW 的 ID 由程序分配 | 第 3 步；验证目标存在、引用与单卡范围，构建时校验模式输出并复制冻结字段 |
| **cal_evaluator** | 固定完整 Cal、父库与候选库、父库已有结果、预定复测规则及评价预算 | 每个有效候选的完整 Cal 得分向量、实际路由、收益／退化和复测结果 | 第 4 步；执行复用 rollout |
| **search_pool** | 旧池、完整 Cal 候选、复测结果、K 与探索额度 | 更新后的完整库池、留存理由及分支额度 | 第 5 步，不修改正式库 |
| **gate** | 正式库、搜索池中已完成完整 Cal 的版本、Gate、固定验收协议与预算 | 更新或保持 L_best；仅接受／拒绝可进入 optimizer 输入，明细隔离 | 第 6 步及结束验收；执行复用 rollout |
| **state_store** | 冻结身份、任务预留与消耗、阶段产物、库版本、搜索池和缓存键 | 原子检查点、不可变快照、隔离产物与可恢复状态 | 贯穿全流程，不做优化决策 |

正常 rollout 内部使用 Runtime 检索、**selector**、GlobalAgent／VideoAgent 和评分。
selector 根据原始题目、选项、视频元信息及候选 id／when_to_use 选一张卡或拒选，Actor 只收到选定卡的 strategy。
离线分析不能替代在线选卡；所有 rollout 使用正常选择流程。

### 旧实现的复用边界

| 已有实现 | 复用内容 | 需要重新设计的部分 |
|---|---|---|
| cluster/evidence.py、infra/trajectory.py | 公开轨迹投影、实际注入核实、案例引用与媒体隐私边界 | 三种阶段视图、历史核实和上下文取舍；不原样传整个旧 reflect 输入 |
| cluster/prompts/reflect/ | 不把 GT 当观察、不把未遵循当缺失、区分误选与正文缺陷等分析原则 | 分别写入 analyzer 和 planner；不照搬旧 status 和单一 sample/step 锚点 Schema |
| cluster/prompts/generator/、reviser/、common.py | CARD_CONTRACT、成功规则保留、程序分配 ID、字段预算 | 保留独立作者 Prompt／Schema；对接 planner 计划，reviser 仅输出修改字段而非复制整卡 |
| cluster/stages.py、infra/bank.py、store.py | 模型调用持久化、Schema 校验、不可变库及原子写入 | 计划与作者输出绑定、单字段构建、搜索池／预算检查点；旧 candidate_bank 不能直接视为新契约实现 |
| infra/rollout.py、evaluation.py、benchmarks/ | 批量执行、原始结果先保存、评分缓存、官方聚合与健康检查 | 完整 Cal 和 Gate 调度；更细的请求缓存须另行实现验证 |
| cluster/question_groups.py、Runtime selector | 固定输入分组和正常选卡路径 | 保持算法组织与在线执行分离，不把簇或诊断结果变成选卡金标 |

上述是复用候选，不表示所有旧模块已充分验证。基础执行与存储沿用现有检查，新的阶段边界、Schema 和状态转移需独立验证。
模块间传递案例引用、库哈希与结果记录；state_store 隔离 Gate／Test，evidence 显式限制每个阶段可读取的范围。

## 1. 数据与优化状态

| 数据 | 用途 | optimizer 可读取 |
|---|---|---|
| Train | 运行、诊断、生成与修订 | 原始输入、健康公开轨迹和反馈 |
| Cal | 所有有效候选的全库评价与搜索分支比较 | 开发案例与逐题反馈 |
| Gate | 决定正式接受 | 仅接受／拒绝状态 |
| Test | 最终独立评价 | 不可读取，不参与版本选择 |

四个集合按题目 ID 隔离，另审计视频来源。Cal 和反复验收的 Gate 均属于开发过程。
目标是正常选卡下的官方总体回答得分；选卡率、成本和调用量仅用于诊断与报告。

维护两种状态：

- `L_best`：经过 Gate 接受的正式库。
- `P`：最多 K 个完整库版本组成的搜索池，允许保留尚未正式接受的分支。

初始化时，`cal_evaluator` 和 `gate` 通过 `rollout` 评价初始库的完整 Cal 与 Gate，`state_store` 保存结果，令 `P = {L₀}`、`L_best = L₀`。

`question_groups` 将 Train 与 Cal 按完整问题、原顺序选项、视频 ID/时长一次性 embedding + Louvain 分组。
簇只组织取样和参考，不规定用哪张卡，也不规定每簇必须生成一张卡。
混合簇按原始输入中的方法需求拆分诊断，不把少数真实任务差异默认视为聚类错误。


### 1.1 embedding驱动的迭代分组（待实现）

**聚类目的：将可复用核心方法的题目组织在一起，便于从多条案例提炼适配范围清晰、可迁移的Skill。** 杂乱方法互相干扰，单一题材又可能使用途窄化。因此分组应逐步突出任务和方法关系，保留不确定小组，不以减少簇数为目标。

本提案不增加analyzer/planner的分类职责，不要求LLM输出成员划分、簇描述、分组操作或新的结构字段。四optimizer继续只做当前轨迹诊断、编辑计划和卡片生成／修订。`question_groups`通过embedding与数值迭代更新成员，`scheduler`按更新后的组取样；在线selector及Cal/Gate规则保持。

**算法基础与新增信息**

可采用DP-means式原型分配：反复分配题目、更新簇中心，题目离所有中心超过阈值时自动新建簇，不指定K。原论文使用平方欧氏距离和簇数惩罚，证明其原始目标局部收敛；见[DP-means原论文，ICML2012](https://icml.cc/2012/papers/291.pdf)。本项目拟使用归一化embedding的cosine距离，并加入Skill辅助原型，属于需要验证的改造，不继承论文的收敛或精度保证。

同一批固定向量只重复计算中心，会收敛到某个局部划分，不能保证逐轮修正语义边界。外层新增信息来自正常优化产出的Skill：方法归纳后的when_to_use可能弱化题材、突出任务，为下一次embedding分配提供辅助方向。它可能也写窄或写错，必须与真实题目几何关系共同约束。

**表示与原型**

- `x_i`：Train原始题目、选项和视频元信息的冻结embedding，初始化计算一次。
- `c_j`：组内题目向量的归一化平均中心，不因卡片是否被选中而定义成员。
- `s_a`：当前父库中新生成／用途已修订卡的when_to_use embedding，按卡文本hash缓存。首版不编码整段strategy，避免执行步骤和长文主导任务匹配。
- `p_j`：分配使用的原型。有相关Skill时，以有界权重将`c_j`与辅助`s_a`组合；没有Skill的组仍以`c_j`工作。

一种待测实现是`p_j = normalize((1-beta)*c_j + beta*s_a)`。beta限制Skill影响，不预设哪种权重已经有效。question与when_to_use文本类型不同，embedding相似度和阈值须校准，不能直接沿用Runtime初筛分数或此前Louvain阈值。

Skill与组可多对多关联。一个组可无Skill，一张卡可辅助多个同方法小组，多个相似卡也不要求产生同数量的簇。所有关联由文本embedding、生成轮次出处和程序规则提出，不要求作者新增分类输出；生成出处只是种子线索，不表示整批题都适用。

**初始化与一次更新**

1. 保留初始分组及题目向量。可用现有Louvain作warm start，并与直接从无固定K原型开始对照；初始成员允许重新分配，不冻结方法边界。
2. 当前候选完成完整Cal并被search_pool留存后，为新增或变更的when_to_use计算embedding。未经有效评价、已丢弃的卡不进入该版本的分组原型。
3. 更新已有相关原型。新卡若只对应混合组的一部分，作为额外原型种子参与竞争，保留原组作为剩余材料的候选；不能用它直接替换整个混合组中心。种子附近的支持题由embedding检索与题目相容条件筛选，不把整个生成batch自动视为正例。
4. 对Train题重新分配：选择满足半径条件的最相近原型；若全部不满足，自动新建小组或独立组。接近多个原型、差异不足的题保留现有位置或待定状态，不能因库中已有卡就强制归入其组。
5. 根据新成员重新计算`c_j`，再得到`p_j`，继续数值迭代。固定本次Skill辅助信息，设置确定顺序、最大迭代数及成员变化停止条件；收敛后下一轮正常优化使用新组。
6. 空组自动移除。首版不按簇数强制合并；组数量可因新组出生和空组消失变化。若以后支持非空组合并，应检验合并后的成员半径或紧致性，而非仅看两个中心接近。

题目归属同时受数据中心相容性约束，不能只因Skill原型相似就吸收与组内题目不相近的成员。对换组使用改善幅度／近似并列保留规则，减少微小向量变化导致的抖动。这些是待校准数值参数，不是大模型分析任务。阈值控制分组颗粒度，自动K并不意味着没有参数或已能自动识别所有方法。

**与六步主流程和搜索分支衔接**

`scheduler → rollout + evidence + analyzer + planner → generator/reviser → 完整Cal → search_pool → 定期Gate`保持。仅在被留存的新库版本上运行数值分组更新，并让之后的scheduler读取该版本的分组引用。

不同搜索分支可能有不同Skill原型，不能用一个候选的卡更新所有父库共用分组。分组快照以库hash、Skill文本hash和分组版本绑定；原始题目向量跨版本共享。正式库仍只由Gate决定，分组更新不构成部署。没有卡变化或成员变化时复用已有结果，不每轮无条件重算全量。

Train成员参与自适应分配；Cal保持固定题集及完整评价，不因新组改变成员或权重。Cal已有结果只决定候选库留存并提供当前允许的开发参考，不按其逐题GT把题目硬归到某张卡。Gate明细与Test不参与原型或阈值更新。生成的卡有总体收益也不能证明逐题分类正确。

**运行示例（虚构）**

初始G1主要是烹饪片段排序并混入功能匹配，G2主要是组装视频并混入质量排名。正常优化生成“用于将同一流程的打乱视频片段按发生顺序排列”的卡后，编码该用途作为新方法原型。embedding重新比较题目与各原型：相容的烹饪／组装排序题可能聚拢；功能匹配和质量排名若离该原型过远，则保留原组或自动形成其他小组。

下一轮从更一致的排序材料优化Skill，其用途可能进一步准确，更新embedding原型再分配。分配是否真的改善须用具体成员检查；用途本身仍写成“烹饪排序”时，不能宣称embedding反馈必然修复题材偏差。保留题目中心约束、无Skill组和独立题，是防止错误卡循环影响分类的必要措施。

```text
X ← embed(Train原始输入)                      # 一次计算，固定题目向量
G0 ← initial_groups(X)                        # 无预设K；保留初始快照
P ← {(L0, G0)}
每轮：
    parent, Gparent, batch ← scheduler(P)
    candidate ← 当前四optimizer及正常rollout流程
    report ← 完整Cal(candidate)               # 题集、评分与预算保持
    如果search_pool留存candidate：
        S ← embed_changed_when_to_use(candidate)
        Gcandidate ← prototype_update(X, Gparent, S)
        # 分配→新组出生→更新中心；半径/并列规则；保留无Skill组
        保存(candidate_hash, Gcandidate, 原型文本hash与变更统计)
    定期Gate；正式接受规则保持
```

伪代码仅说明分组插入位置，no_issue/skip、历史核实、预算与缓存仍按正文。当前实现没有辅助原型或动态成员状态，不修改四optimizer的Prompt/Schema，也不增加专门补测分支。

**分阶段验证**

A为当前固定分组；B为仅题目embedding的无固定K迭代分组；C在B上加入正常产出的Skill原型。B检验数值重分配本身，C检验Skill归纳是否带来额外信息，避免把普通聚类收敛误称为自进化收益。使用相同样本、初始库、模型与优化预算；新增embedding成本单独记录。

检查方法级正负题目对、跨题材同方法连接、混合组、独立题、簇数与成员迁移稳定性，并比较卡片质量、正常选卡／拒选及QA。不追求簇数持续下降，不把原任务类别纯度或内循环收敛当作语义精度证明。需覆盖不同规模、输入顺序和Skill范围写偏的情况；阈值及辅助权重在开发阶段固定，不能看Gate/Test调参。


## 2. 每轮流程

### 2.1 scheduler → rollout → evidence：父版本与案例

`scheduler` 从 P 中优先选择展开次数少的版本，同次数优先完整 Cal 总分高者，再按创建顺序。
按簇轮换抽取 Train batch；定期从全局错误池抽样。小簇不足时使用较小 batch，不复制题目。

`rollout` 使用父库正常选卡并运行；`evidence` 保留健康公开轨迹，补充少量相关成功／失败历史案例，允许跨簇。
历史记录必须带库版本；旧版本的缺陷不能直接当作当前版本仍存在的问题。
优先使用当前父库案例；历史案例只提供线索，若成为修改的关键依据，先在当前父库下核实。
参考包包含目标失败、相关成功和易混淆边界，保留完整问题、选项及视频元信息。
按案例组织相关公开步骤和卡内容，限制总上下文并记录省略项；不把整个历史池或全库正文一次性塞给模型。
本轮聚焦一种有证据支持的失败模式。

### 2.2 analyzer → planner：分析与计划

`analyzer` 先根据原始输入与健康公开轨迹定位失败现象，关联成功／失败案例，输出有引用的 issue。
`planner` 再检查实际检索候选、最终选择、实际注入的正文，以及相关卡的范围和方法。
它区分未进入候选、LLM 误选／漏选、已注入但未遵循、正文缺陷和观察证据不足；回答错误本身不能决定操作类型。
事实、修改假设和未确定项分别记录，事实须指向输入或轨迹记录。
planner 有明确修改依据时返回 ready；依据不足或无法提出有支持的改进时返回 skip，不调用作者。

| planner 判断依据 | ready 操作 → 作者模块 | 字段约束 |
|---|---|---|
| 不适用卡造成损失，用途过宽或有歧义 | `WHEN` → reviser：修订误选卡 | strategy 不变 |
| 已有卡被漏选，存在明确用途表达缺陷 | `WHEN` → reviser：修订造成混淆的卡 | strategy 不变 |
| 方法适用，但存在可定位的执行规则缺陷 | `STRATEGY` → reviser：修订正文 | when_to_use 不变 |
| 有新方法需求，检查过的已有卡不能合理复用 | `NEW` → generator：生成完整新卡 | 两字段均生成 |
| 证据不足、偶发未遵循、效果相当或 Skill 无法修复 | `SKIP` → 无作者调用 | 不生成候选 |

每次处理一个证据最明确的问题，每个候选只改一张卡；同轮可有少量实质不同的备选。
用途修订同时考虑误选、漏选和应保留的正确案例，遵守 CARD_CONTRACT，不为命中题目夸大能力。
用途围绕原始输入可识别的必要关系、主要操作和答案内容概括；仅写区分方法所需的信息，不累加逐题排除条款。
缺卡误选时重点检查仍在库中的吸引卡，而非只改缺失卡。相关卡之间可分轮修复，每轮仍只改一张卡。
若区别依赖选卡时不可见的视觉事实，记录这一限制，不能假设用途文字能预先识别逐题最优卡。

### 2.3 generator / reviser → candidate_builder：单卡候选

planner 返回 NEW 时调用 generator，返回 WHEN／STRATEGY 时调用 reviser；二者接收 ready 计划及 evidence.authoring 案例包，使用各自的 Prompt 和 Schema。
调用前，candidate_builder 校验操作、目标、证据引用和字段范围；不合法计划不会送给作者。
`candidate_builder` 先校验计划与作者输出绑定，再检查字段、总预算、修改范围、空内容、无变化和完全重复；字段合法不等于用途可选或正文有效，语义效果由后续正常运行验证。
不额外增加语义审查模型。无有效候选则记录原因并推进轮次和停止计数。

已有卡的两字段不能在一个候选中同时改写：WHEN 不改变方法能力，STRATEGY 保持原用途范围。
确需引入不同能力范围时走 NEW；可独立成立的用途与正文改进分轮进行，不让字段相互矛盾的中间版本进入搜索池。
所有候选从本轮父库产生新快照，正式库此时不变。

### 2.4 cal_evaluator → rollout：完整 Cal

`cal_evaluator.evaluate` 通过 rollout，在同一个固定完整 Cal 上评价父库和所有有效候选。
父库已有身份一致的完整结果可以复用；每个候选均保存官方总体分数、逐题结果和实际路由。
Cal 在实验开始前冻结，不含 Train 题，不能根据候选表现增删题目。

用途改变后重新执行真实初筛与 selector，保存候选 ID、分数、呈现顺序和最终选择。
同时检查目标收益与非目标退化；局部改善不能替代正常全库收益。
同题比较沿用官方评分与聚合协议，不以答对题数替代加权总分。执行或 Judge 故障记录并处理，不删掉失败题后比较成绩。
关键收益按预定规则配对复测，结果交给 search_pool 决定留存；Cal 持平或下降不自动淘汰有互补收益的候选。

scheduler 在调用作者前按候选上限预留完整 Cal 评价预算和最终 Gate 预算；不足时减少候选数或结束搜索。
未完成完整 Cal 的候选不能进入搜索池。

### 2.5 search_pool：搜索池留存

所有有效候选完成同一个完整 Cal 后，`search_pool` 从旧池与这些候选中保留至多 K 个版本：

| 位置 | 留存依据 |
|---|---|
| 总体最优 | 完整 Cal 官方总分最高 |
| 互补分支 | 相对已保留版本，在足够多题上提供未覆盖的收益 |
| 限次探索 | 非重复、有明确修改依据，仍有后续展开额度 |

互补性按逐题得分及官方聚合权重比较，分簇均分只作辅助。逐题取已保留版本最高分仅用于多样性记账，不是可部署成绩。
记录收益与损失的来源集中度，近重复题的多个收益不能被解释为多个独立证据。
关键收益按预定规则对父库和候选配对复测，重复次数和汇总方式预先固定，不复测到出现改善才停止。
支持题数阈值只是搜索留存规则，不等于统计显著性或正式接受。

纯探索分支允许暂时退化，但只能展开有限次数；后代继承剩余额度，不能靠生成新版本重置期限。
成为高分或合格互补版本后可按普通分支留存。没有合格分支时，池不必填满。
为探索预留固定的评价／展开预算，并限制其总占比；额度不足时优先保住最优分支的正常评价与最终 Gate。
正式库独立保存，不因离开搜索池而丢失。

### 2.6 scheduler → gate：正式验收与结束

`scheduler` 按预定节点触发 gate；`gate` 从池中选择少量完整 Cal 有竞争力、尚未验收的版本，通过 rollout 运行完整 Gate。
只有 `GateScore(candidate) > GateScore(L_best)` 才更新正式库；持平或下降保持原库。
未接受的候选仍可依据 Cal 留在搜索池继续展开。

相同内容和执行配置不重复 Gate。预留最终验收预算；结束时只交付经过 Gate 的 `L_best`，不直接输出 Cal 最高的未验收版本。
如采用重复评测，运行前固定重复次数、配对条件和汇总协议，父库与候选对称执行；不在看到 Gate 结果后临时追加复测。
Gate 明细与分数只供验收程序和最终报告，optimizer 不据此定位题目或修改卡。反复使用 Gate 仍可能造成开发过拟合，最终收益需 Test 确认。
`state_store` 每轮原子保存状态。`scheduler` 在达到总轮数、候选数、执行预算或预设停滞条件后结束；之后通过 rollout 在 Test 上评价最终库。

## 3. 缓存与恢复

`state_store` 管理缓存与恢复记录，`rollout` 按实际请求身份查询／写入缓存。完整评价必须覆盖全体题目并重新聚合，但执行身份一致时可以复用结果。

| 改动 | 路由 | 执行 |
|---|---|---|
| 只改 strategy，selector 实际输入不变 | 可复用 | 重跑实际执行输入变化的题 |
| 改 when_to_use、新增或删除卡 | 对完整评价集重算 | 实际执行输入相同才可复用 |
| 模型、prompt、工具、采样或预算变化 | 按变化失效 | 按变化失效 |

缓存键覆盖题目、视频、实际序列化上下文、模型、工具、采样、预算和 repeat 标识；不能只按 Skill ID 命中。
以实际请求判断复用，包括候选呈现顺序和注入正文，不能只依据“strategy-only”等修改标签。
缓存是已有抽样，不是新的独立复测。

恢复需要保存：正式库与搜索池、父子关系、展开次数和探索额度、固定分组与完整 Cal 身份、候选修改记录、带版本轨迹、完整 Cal 得分向量、隔离的 Gate 记录、缓存身份和已消耗预算。
恢复不重新分组，不重复扣预算；构造 optimizer 输入时显式排除 Gate/Test，而不是只依靠目录区分。
执行前持久化任务身份与预算预留，完成后提交结果和实际消耗；中断恢复核对未完成任务，避免重复提交候选、验收或消耗探索额度。

## 4. 起始参数与实现顺序

以下是未验证的起始建议；模型、Skill 格式、整卡 word 预算和评分沿用当前配置。

| 参数 | 起始建议 |
|---|---|
| Train batch／历史参考 | 最多 8 题／4 条，参考优先包含成功与失败 |
| 全局错误 batch | 每 4 轮一次；池空时恢复簇取样 |
| 替代卡／候选 | 最多 2 张替代卡，另含实际选择与不用卡／最多 2 个候选 |
| 搜索池／互补支持 | 最多 3 个版本／至少 2 道收益题并复测关键差异 |
| 探索额度 | 每条纯探索分支最多 2 次后续展开 |
| 探索预算 | 启动前固定总占比上限，同时预留一次完整 Cal 和最终 Gate |
| Gate | 每 2 轮至多验收 1 个竞争版本，预留结束验收额度 |
| 停止 | 固定总轮数、候选和执行预算，可附加池停滞上限 |

实施顺序：

1. 用 mock 评分验证父版选择、字段锁定、Cal 留存与 Gate 接受。
2. 接入现有执行与评分，构造三种 evidence 视图；核对 issue 引用与计划／作者输出绑定。
3. 接入 analyzer、planner、generator、reviser；与旧阶段划分比较同预算收益，再接入完整 Cal、互补与限次探索。
4. 最后细化路由／执行缓存，先保证结果正确，再验证节省调用量。

不需要重写现有模型或 Runtime，也不在第一版加入自动合并、多卡重组和动态重聚类。

设计依据：此前[极简拒选规则测试](../../../../../../../analysis/skill_evolution/selector_minimal_rules_20261005.md)出现召回损失，
[按簇归纳用途测试](../../../../../../../analysis/skill_evolution/selector_cluster_scopes_20261005.md)改善总体拒选却仍有局部退化。
因此优化围绕案例证据、用途与方法一致性及全库评价展开，不预设“更保守的 prompt”或“更详细的用途”必然有效。
这些是复用开发样例的 selector 证据，尚不证明自动生成质量、真实检索或最终回答收益。

## 5. 验收重点

- 同簇可用不同卡、跨簇可共用卡或拒选；不因拒选直接新建。
- WHEN／STRATEGY 的冻结字段不变；局部收益不冒充部署收益。
- 历史关键缺陷经当前父库核实；issue 的假设须由 planner 核对，无依据计划可 SKIP，不把运行故障归因于 Skill。
- 固定完整 Cal 不含 Train 题；真实检索／选择覆盖跨卡干扰，保留目标外退化记录。
- 所有有效候选均完成同一个固定 Cal；搜索池依据总体得分、互补收益或限次探索规则留存版本。
- 搜索池留存不代表正式接受；只有完整 Gate 总分严格提高才更新正式库。
- 探索额度不能无限续期；结束预算覆盖最后的 Gate 验收。
- 缓存不命中过期正文；中断后分组、版本和预算保持一致。
- 报告完整 Cal/Gate 曲线、逐题收益与退化、候选去留及实际调用量；独立 Test 不参与任何搜索。

## 6. 主伪代码

模块调用与第 0 节一致；rollout 使用正常选卡。
`.analysis / .planning / .authoring` 是同一 evidence 模块的三种视图，均由程序构造，不额外调用模型。

```text
输入：Train、Cal、Gate、初始库 L0、搜索及评测预算
输出：通过 Gate 的正式库 L_best

state ← state_store.initialize_or_resume(输入与冻结配置)
if 首次初始化:
    groups ← question_groups(Train 与 Cal 的原始输入)
    baseline_cal ← cal_evaluator.baseline(Cal, L0)   # 调用 rollout
    baseline_gate ← gate.baseline(Gate, L0)         # 调用 rollout
    L_best ← L0; P ← {L0}
    state_store.commit(groups, baseline_cal, baseline_gate, L_best, P)
else:
    groups, L_best, P ← 从 state 恢复

while scheduler.can_continue(state):
    verdicts ← 空集
    # 1. 父版本、Train batch 与当前证据
    L_parent, B ← scheduler.select(P, groups, Train 错误索引, state)
    results ← rollout(B, L_parent, mode=normal)
    cases ← evidence.collect(results, 历史, L_parent)
    if cases.pending_refs 非空:
        verified ← rollout(cases.pending_refs 对应 Train/Cal 题, L_parent, mode=normal)
        cases ← evidence.collect(results, 历史, L_parent, verified)

    # 2. 先分析轨迹，再规划库修改；无问题则 SKIP
    issue ← analyzer(evidence.analysis(cases))
    plan ← {status=skip}
    if issue != no_issue:
        context ← evidence.planning(issue, cases, L_parent)
        plan ← planner(issue, context)
    plan ← candidate_builder.validate_plan(L_parent, plan, cases)
    if plan.status == ready:
        scheduler.reserve_evaluation_budget(候选上限, 完整 Cal, 最终 Gate)
        若预算不足，减少候选上限或结束搜索
        author_context ← evidence.authoring(plan, cases)
        if plan.operation == NEW:
            edits ← generator(plan, author_context, CARD_CONTRACT)
        else:                     # WHEN / STRATEGY
            edits ← reviser(plan, author_context, CARD_CONTRACT)
        candidates ← candidate_builder(L_parent, plan, edits)

        # 4. 所有有效候选直接评价完整 Cal，按预定规则配对复测
        cal_results ← cal_evaluator.evaluate(Cal, L_parent, candidates, 预定复测规则, 预算)

        # 5. 完整 Cal 评价后决定版本留存；不改正式库
        P ← search_pool.update(P, cal_results, 互补规则, 探索额度)

    # 6. 定期验收；no_issue / skip / 无效候选也执行收尾
    if scheduler.gate_due(state) 且 有验收预算:
        L_best, verdicts ← gate.evaluate(P, L_best, Gate, 固定验收协议)
    state ← scheduler.finish_round(state, 展开记录, 实际消耗, verdicts)
    state_store.commit(state, P, L_best, 本轮产物)

L_best ← gate.finalize(P, L_best, Gate, 预留预算)
state_store.commit(最终状态, L_best)
return L_best                    # Test 评价在搜索结束后独立调用 rollout
```

每次实际调用前，state_store 保存任务身份和预算预留，完成后登记实际消耗；伪代码省略重复记账调用。
缓存复用、跳过或作者无效均返回显式结果，不绕过 scheduler 的轮次和预算更新。

## 7. 模拟运行：失败候选如何继续修复

以下数据全部虚构，用于演示算法和检查状态转移，不是实验成绩。
每题得分为 0 或 1；Cal 共 12 题，Gate 共 20 题。
正常运行确定性固定，因此模拟中的互补收益不需要额外随机复测。

### 7.1 题目与固定分组

| 簇 | 题目 | 方法需求 |
|---|---|---|
| C1 | Q1片段排序、Q4事件次数、Q7位置比较、Q10画面清晰度 | 多种任务 |
| C2 | Q2片段排序、Q3遮挡下排序、Q5事件次数、Q8属性比较、Q11拍摄稳定性 | 多种任务 |
| C3 | Q6事实识别、Q9属性比较、Q12画面亮度 | 多种任务 |

排序卡可服务 C1/C2，计数卡也可服务 C1/C2；Q10–Q12 无适合卡时应拒选。
同簇并不指定同一张卡。这里的方法需求只用于解释模拟，不作为算法标签。

### 7.2 五轮过程

每轮所有有效候选均评价同一个完整 Cal（Q1–Q12）。
第五轮根据 Train 中遮挡案例 T3 提出正文修订，用 Cal 中的 Q3 验证同类问题。
T3 与 Q3 是不同题；模拟假定来源隔离，不能直接把 T3 放入 Cal。
每两轮验收一次 Gate，第五轮使用预留的最终验收额度。

| 轮次 | 父库 → 候选 | planner 操作 → 作者模块及修改 | 完整 Cal | 搜索池 | Gate 与正式库 |
|---|---|---|---:|---|---|
| 初始 | L0 | 空库 | 6/12 | {L0} | 10/20；正式L0 |
| 1 | L0 → L1 | NEW → generator：状态衔接排序卡，修复Q1 | 7/12 | {L1} | 未验收；仍L0 |
| 2 | L1 → L2 | NEW → generator：统一属性比较卡，修复Q8 | 8/12 | {L2} | 13/20；接受L2 |
| 3 | L2 → L3 | NEW → generator：计数卡，修复Q4/Q5，但用途过宽使Q10–Q12误选 | 7/12 | {L2,L3} | 未验收；仍L2 |
| 4 | L3 → L4 | WHEN → reviser：只修计数卡用途，Q10–Q12恢复拒选 | 10/12 | {L4} | 17/20；接受L4 |
| 5 | L4 → L5 | STRATEGY → reviser：排序卡区分“未观察到”和“不存在”，修复Q3 | 11/12 | {L5} | 18/20；接受L5 |


**search_pool 第三轮为何留存 L3？** Q4/Q5 提供两道父库没有的收益，满足模拟中至少两题的互补条件；
Q10–Q12 的三道损失使总分下降，L3 因此不部署。搜索继续展开 L3，正式库仍使用 L2。

**planner 第四轮为何选择 WHEN？** 当前父库 L3 的开发轨迹显示，Q4/Q5 的计数问题能从计数卡获益，
而 Q10–Q12 被不适用的计数方法引导。analyzer 定位误用现象；planner 检查原始问题、实际选卡及注入记录，
确认正文支持计数任务，但用途表达覆盖了非计数任务，因此提出 WHEN。
reviser 只收窄用途，正文保持不变；完整 Cal 同时检查计数收益是否保留、非计数损失是否恢复。
这是一项基于现有开发证据的修改假设，只有正常选卡运行后的完整评分才能验证收益。

**planner 第五轮为何选择 STRATEGY？** Q3 已选到排序卡，但把遮挡造成的未报告细节当成不存在。
缺陷属于证据处理；只修 strategy，when_to_use 保持。
analyzer 在当前父库 T3 轨迹中定位错误证据处理；planner 对照实际排序卡正文，确认规则缺陷后提出 STRATEGY 计划。
reviser 按 STRATEGY 计划只改正文，在固定完整 Cal 中用 Q3 验证同类问题；Q3 从实验开始即在评价集中，不因本轮诊断新增。不能从回答错误直接推导正文有缺陷。
第五轮完整 Cal 从父库的10/12提高到候选的11/12，确认Q3修复，再做最终 Gate 验收。

### 7.3 可核对的逐题数据

| 题目 | L0 | L1 | L2 | L3 | L4 | L5 |
|---|---:|---:|---:|---:|---:|---:|
| Q1 | 0 | 1 | 1 | 1 | 1 | 1 |
| Q2 | 1 | 1 | 1 | 1 | 1 | 1 |
| Q3 | 0 | 0 | 0 | 0 | 0 | 1 |
| Q4 | 0 | 0 | 0 | 1 | 1 | 1 |
| Q5 | 0 | 0 | 0 | 1 | 1 | 1 |
| Q6 | 1 | 1 | 1 | 1 | 1 | 1 |
| Q7 | 1 | 1 | 1 | 1 | 1 | 1 |
| Q8 | 0 | 0 | 1 | 1 | 1 | 1 |
| Q9 | 0 | 0 | 0 | 0 | 0 | 0 |
| Q10 | 1 | 1 | 1 | 0 | 1 | 1 |
| Q11 | 1 | 1 | 1 | 0 | 1 | 1 |
| Q12 | 1 | 1 | 1 | 0 | 1 | 1 |
| 合计 | 6 | 7 | 8 | 7 | 10 | 11 |

此表就是模拟评分 fixture：按固定题序读取每列即可复现完整 Cal 分数，无需再维护重复 JSON。
Q9 最终仍错；算法不假定所有问题都被解决。

```text
正式库：L0 ─────→ L2 ─────────────→ L4 → L5
搜索线：L0 → L1 → L2 → L3（下降）→ L4 → L5
```

应验收的关键行为：所有有效候选评价完整 Cal、两题互补使降分版本留存、父库可取未接受分支、
WHEN/STRATEGY 单字段修改，以及未通过 Gate 的 L3 始终不替换正式库。
