# MVAgent skill 研究交接：本轮思路、实验证据与下一轮执行指南

本文件是2026-10-21至22日这轮探索的统一入口。目标是让接手者无需重读会话，就能知道为什么做这些实验、哪些结果可信、哪些假设已被削弱，以及接下来应运行什么。

**当前状态：本轮已结束，全部模型评测和配对分析完成，GPU已释放。下一轮尚未启动。** 研究代码与最终原报告的基点为 [`e96d2fd4f27efdbe9e939c1289a427154384ac73`](https://github.com/Wal-K-aWay/MVAgent/commit/e96d2fd4f27efdbe9e939c1289a427154384ac73)，位于 `codex/skill-exploration-20261021`，不是已经合并到main的方法版本。

阅读顺序：先读本文第1–6节理解结论，再按第8–10节准备下一轮。所有数值的详细区间、逐项审计范围和来源见[完整实验结果](skill-exploration-results.md)；方法契约见[设计说明](skill-evolution-design.md)，文献及历史转向见[探索方案](skill-exploration-study.md)。本文整理没有新增模型、API或Judge调用。

后续只读复核见[optimizer输入与搜索完成度审查](skill-optimizer-input-audit-20261022.md)：八份真实提案重建一致，64个案例位置仅覆盖29道不同Train题，两个Video请求完全相同；正式轨迹截断11/95、八次响应均正常结束。该审查没有新增准确率实验，也没有改写原始结果。

## 1. 本轮最终回答了什么

**Skill有值得确认的正信号，但当前自进化尚未证明优于强一次生成。** 实验也没有支持“机制肯定有效，剩下只是生成器写得不够好”这个前提。

同一9B、同一开发清单，官方CrossVid十任务macro：

| 方法 | Train80 | Cal40 | Gate176 |
|---|---:|---:|---:|
| 复用的空库 | 25.2885% | 32.6186% | 32.4078% |
| GLM无反馈一次生成，单Global卡 | 31.5648% | 25.7246% | **38.9940%** |
| 正式8候选后保留的Global库 | 27.7885% | **35.0000%** | 35.0869% |

一次生成在Gate相对空库为 **+6.5862pp**，未校正的逐题95%区间 `[+0.7359,+12.6467]pp`，来源组敏感区间 `[+0.5417,+12.4449]pp`。这份正证据必须保留。一次生成相对正式库为 `+3.9071pp`，区间 `[-2.0046,+9.9591]pp`，没有证明两种方法的稳定优劣。

这里同时出现了Cal和Gate排序反转。一张一次生成卡不代表其生成分布；相同GLM配置也没有对齐Prompt、信息量和累计搜索预算。全部都是开发数据，不能据Gate分数追认该卡通过原Cal门槛，或宣布一次生成普遍优于反馈优化。

本轮约8小时46分钟内完成模型测量和配对分析，总GPU上限64张H100。最终账本为：

| 类别 | 完整评估量 | 计数说明 |
|---|---:|---|
| 9B受控/单候选实验 | 5555题次、44单元 | `21×80 + 11×40 + 5×176 + 7×365` |
| 正式Global→Video轮换 | 1136题次 | `8×(80+40)+176`，不另计复用空库 |
| 27B/35B固定策略及自然库迁移 | 2190题次 | 两模型各3个完整365题臂 |
| 合计 | **8881评分题次** | **661个不同题号**，不是8881个独立样本 |
| 强Selector诊断 | 960次纯文本选择 | 不计为新的端到端问答 |

原先并行的DeepSeek全量库测试共15963题次，属于另一项冻结实验，未计入8881，也不是本轮进化结果。原始轨迹的只读审计不增加问答数量。

## 2. 冻结架构决定了哪些方法可行

任务是根据多个视频共同回答一个问题。模型权重、基础Prompt、工具、评分均冻结；本研究只改变skill文本。

| 角色/位置 | 可见内容 | 对skill的约束 |
|---|---|---|
| Global首次Selector | 问题、视频ID与时长、候选ID/when_to_use | 入口不能要求尚未产生的冲突报告或未来History |
| Video每次请求Selector | 当前instruction、候选入口 | 不见Memory、源时长、Global原题或其他Video内容 |
| Global Actor | 问题、视频信息、公开action/history、返回报告、选中strategy | 不能查看Video内部观察轨迹 |
| Video Actor | instruction、源时长、自己的Memory、选中strategy | 只能处理本视频；复用此前本视频的内部轨迹 |
| 优化器 | Train中目标角色公开轨迹、得分反馈、库和契约 | 不给GT、Judge评分点、task/题号、Cal/Gate细节或其他角色私有轨迹 |

Global使用 `analyze_videos / watch_videos / answer`；Video使用 `observe / finish`。Global联合观看至少两个不同视频，片段共享单次帧预算，不接收FPS参数；Video observe给出what、时间范围和FPS。正常finish至少要有一次成功观察。

运行时每个Global问题、每次Video请求最多选一张，也可none，之后沿用该选择。卡片为schema v3：`meta={id, role, stages}`、`when_to_use`、`strategy`；两个文本字段合计最多1200 words，渲染正文另有1200 words上限。只有strategy进入Actor，when只用于检索与选择。

因此：

- 观察后才知道的条件应写进strategy，由Actor在后续步骤判断；不能要求初始Selector提前知道。
- strategy执行所需的前提和例外要自包含，不能只留在when里。
- Observer不会自动收到skill，要求必须经Global instruction、Video observe.what等现有消息传下去；Video耗尽步数的强制总结也不会自动收到规划skill。
- none是原MVAgent继续运行，不是拒答。高弃选率或一句“否则按原流程”都不是整体不退化保证。
- 本轮每角色不超过8张，候选直接呈现；没有验证大库的BM25/embedding召回瓶颈。检索query含history也不代表Selector实际messages含history。

完整接口以[运行时说明](../src/mvagent/skills/README.md)、[卡片规范](../src/skill_evolution/skill_specification.md)和实际请求记录为准。

## 3. 数据、配置与统计口径

### 3.1 数据分区与污染边界

| 清单 | 用途 | 重要限制 |
|---|---|---|
| Train80 | 唯一optimizer逐题反馈来源 | 十任务各8题；多轮重复使用 |
| Cal40 | 候选打分/筛选 | 十任务各4题，分数较粗，不能视作稳定排名 |
| Gate176 | 正式接受判定或预声明的只报告对照 | 已有开发历史，不是最终独立Test |
| 补充365 | 冻结策略的扩大确认 | 8任务各40、PI14、PSS31；96声明来源组，排除上述296及其声明来源组，但不抹去更早历史接触 |

80/40/176的manifest文件SHA：`794a66996f1e12fceea9e6c7f12fcd6416fb4704c6a96e573e715ae7a35b1a21`。
365准备manifest SHA：`7a8a83c1f5a3d205131b3a537d4e9c1ac7758f4df18de1bc66e1c5120d9e8b69`。这两个哈希标识实际保存文件；不要把它们当成代码重新序列化后的语义哈希。

**365主对照是主动注入的terminal一句skill，不是none。** 该卡只保留“Answer from supported evidence in the requested format.”。历史365空库有两处短片媒体处理差异，只作次参考。本轮按用户要求不重跑空库，因此不能把“低于terminal”写成“相对同协议none被skill损害”。

### 3.2 实际推理和优化预算

| 项目 | 本轮设置 |
|---|---|
| 主Actor/Selector/Observer | Qwen3.5-9B，同一部署模型；迁移另用27B和35B-A3B |
| 服务 | `qwen35-bf16-flashinfer-sync`，H100、BF16、TP1、单副本并发1、整题固定副本 |
| 采样与预算 | seed=0、temperature=0、thinking关闭、2048输出token、Global/Video最多5步、每次512帧、最长边448 |
| 缓存 | prefix及MM processor cache关闭，正常解码KV开启；保留实际token与输入哈希 |
| 单节点分工 | 8张H100中7个Actor副本、1个固定本地CCQA Judge；总分配及预留均纳入64上限 |
| Judge | Qwen3-30B-A3B-Instruct-2507，沿用既有评分Prompt和配置；不是优化器 |
| 本地optimizer | 9B纯文本，复用已有模型池，最多4096输出token；不另建小池限制Actor吞吐 |
| GLM optimizer | glm-5.3、thinking/high、temperature=1、top_p=.95、最多16384 token；凭据只读环境或Secret |
| 正式搜索 | 4个总角色轮次×每轮2候选，Global→Video→Global→Video；每次8例、每例最多12000字符、每角色最多8卡 |

公开 `configs/skill_evolution/evolution.yaml` 默认是 **2轮×2候选**，不能拿它替代本轮冻结的4轮配置。API配置的`max_retries: 1`在既有客户端中表示首次请求后最多一次瞬时错误重试；正常成功提案实际只调用一次，不等于所有异常情形严格单次HTTP。

### 3.3 分数和区间怎么解释

主指标是十task等权macro；CCQA在task内部按评分点加权，不能用所有题的普通平均替代。分母必须是完整面板；按选中/弃选分组时报告对完整面板的贡献，不能把缺少任务的子集macro当总分。

主要后续比较采用同题、按task分层配对bootstrap，10000次、seed0，并报告声明来源组敏感区间；首波表使用2000次，具体以原报告为准。所有区间未校正多重探索，来源组方法也依赖分组假设。跨零不证明等效；Gate按规则接受不代表统计显著或稳定泛化。

保留原始评分。只有同题、同完整Judge身份和相同请求才做canonical敏感性分析；不重新Judge、不覆写主分数、不改变历史接受。Judge/基础设施失败不记零分，模型错误答案、无效动作和正常工具拒绝另行记录。

## 4. 思路如何随证据变化

| 阶段 | 当时的问题 | 做的干预 | 得到的证据与决定 |
|---|---|---|---|
| 先测正文上限 | 小库无效是否因为根本不选卡？ | 手写短/步骤卡；固定注入与自然路由分别测 | Train80固定temporal/joint有正差，允许继续查选择损失；不先调用强API堆卡 |
| 分离路由 | 是否只是Selector弱？ | 补齐三卡+none同题表、Codex分配、入口/编号与更强Selector | 语义选择仍不及最佳常量；事后最优不能直接当可学空间 |
| 排除普通提示效应 | 时间程序是否真有额外价值？ | 同时测完整temporal、步骤版及只留终答一句；扩大365 | 一句控制也能提高小面板分数，完整程序未显示稳定额外收益 |
| 检查角色和传递 | Video报告压缩、组合能否改善？ | Video scope、Global×Video组合、Video自然/强选 | 组合不呈加性；有零激活，也有真实注入后仍无净收益 |
| 本地闭环 | 当前信息是否足以写可用卡？ | 9B提案、同题Train反馈、自然Cal/Gate | 有未来History入口违约；Cal上涨但Gate不通过，保留原提案不手修 |
| 强优化模型 | 换GLM及角色轮换是否改善？ | 同逻辑案例对照；正式4轮×2候选 | 首Global接受，后续未超父Cal；三模型365未确认增量 |
| 分离正文作用 | 复核流程是否导致得失？ | 固定入口，删除Stage2–3，完整296 | 选择完全相同但动作改变；Train/Cal/Gate方向分化，不能只归因长度或单分支 |
| 补强简单基线 | 反馈是否优于直接写？ | 同GLM零样例单卡，完整296只报告 | Gate正信号、Cal排序反转；不能预设进化必需 |
| 补实际效用反馈 | 语义Selector没见收益，入口是否仍可学？ | 正文/meta全固定，8组四臂Train反馈，只改三个when | Train略升、匹配Cal下降；停止同题近义改写，不否定理论可学性 |

旧“强制watch恢复约47%”来自E2E答对而MVAgent答错的筛选子集。本轮没有同清单、同协议精确复现；不能将它作为总体预期增益。多次提案失败也没有证明已经陷入局部最优，可能仍受正文效用、可见信息、反馈覆盖和筛选噪声限制。

## 5. 实验账本与关键结果

下表数值为原官方macro（%）；`—`表示该条件没有对应完整测量。每行Train为同一80题；未测条件不能用另一行补值。来源、区间和评分噪声详见[完整结果](skill-exploration-results.md)。

### 5.1 21个Train条件及其后续

| 条件 | 部署方式 | Train80 | Cal40 | Gate176 | 补充365 |
|---|---|---:|---:|---:|---:|
| Global concise temporal | 固定诊断 | 36.4750 | — | — | 34.7732 |
| Global三卡 broad入口 | 自然 | 24.9365 | — | — | — |
| Video两卡 broad入口 | 自然 | 27.8420 | — | — | — |
| watch-first | 固定诊断 | 30.7192 | — | — | 30.9523 |
| Global concise joint_compare | 固定诊断 | 34.2848 | — | — | 35.4555 |
| Global concise shared_predicate | 固定诊断 | 28.7960 | — | — | — |
| Global步骤版temporal | 固定诊断 | 33.3333 | — | — | — |
| terminal一句 | 固定诊断 | 31.9504 | — | — | 36.4594 |
| Global temporal＋Video broad | Global固定/Video自然 | 31.3830 | — | — | — |
| Video scope保留指令范围 | 自然 | 28.1653 | 35.1186 | 33.2535 | 35.4926 |
| temporal单卡泛化入口 | 自然 | 28.8462 | 30.1186 | — | — |
| 本地9B首Global提案 | 自然 | 23.8584 | 35.6250 | 31.9190 | — |
| 本地9B配对反馈第二版 | 自然 | 25.0962 | 32.6186 | — | — |
| GLM四例首Global提案 | 自然 | 26.8890 | 37.5000 | 33.9085 | 34.7288 |
| 同一GLM首提案 | 固定诊断 | 29.3890 | — | — | — |
| GLM八例反馈第二版 | 自然 | 28.9820 | 30.5000 | — | — |
| 本地9B首Video提案 | 自然 | 25.0962 | 32.6186 | — | — |
| 同一Video提案 | 固定诊断 | 25.0192 | — | — | — |
| 首接受Global删除Stage2–3 | 自然、只报告 | 30.9689 | 27.5000 | 34.9997 | — |
| GLM零反馈一次生成单卡 | 自然、只报告 | 31.5648 | 25.7246 | 38.9940 | — |
| GLM只改when效用反馈 | 自然、只报告 | 27.4038 | 25.1186 | — | — |

另外补了原三卡relation入口完全不变的自然Cal40=30.0000%，作为when改写的匹配控制；其Train24.7442%来自既有测量，没有重新算成新增Train臂。第七个365臂是下节的正式首接受Global库。以上合计44个单元，不能把各列相加当作不同题目数。

### 5.2 正式8候选：从空库开始，最终只有一张Global卡

| 轮次/角色 | 库短SHA | Train80 | Cal40 | 处理 |
|---|---|---:|---:|---|
| 0 / Global | 4765323a | 27.7885 | 35.0000 | Gate35.0869，接受 |
| 0 / Global | 78950967 | 31.5593 | 35.0000 | Cal同分，稳定次序未选中 |
| 1 / Video | 6acc681a | 29.0385 | 32.5000 | 拒绝 |
| 1 / Video | 5a1df9a2 | 28.0243 | 35.0000 | 未严格超过父库，拒绝 |
| 2 / Global | 27cc2c13 | 30.5208 | 30.0000 | 拒绝 |
| 2 / Global | 9dcbadbc | 23.7342 | 30.9722 | 拒绝 |
| 3 / Video | 68cfb31b | 24.9011 | 27.5000 | 拒绝 |
| 3 / Video | 134b4aa3 | 26.7885 | 33.0769 | 拒绝 |

Video最终为空；只有首轮候选进入正式Gate。首接受库对空库Gate增量 `+2.6791pp`，95%区间 `[-1.6797,+7.1329]pp`。接受规则是整库官方分严格正差，不临时改成显著性、成本或步数门。

### 5.3 三模型365：自然接受库和固定程序分开比较

| 模型 | terminal控制 | 固定temporal | 自然首接受库 | 自然库减terminal pp（95%逐题区间） |
|---|---:|---:|---:|---|
| 9B | 36.4594 | 34.7732 | 34.0246 | −2.4349 `[-8.0677,+3.2209]` |
| 27B | 51.6696 | 50.0520 | 48.3803 | −3.2893 `[-8.2993,+1.6684]` |
| 35B-A3B | 43.0428 | 43.4703 | 42.7994 | −0.2434 `[-5.5222,+5.0244]` |

固定temporal的三模型差值区间也均跨零。迁移时Actor和Selector同时换模型，不能当作只换Actor的单因素实验；27B与35B-A3B架构也不同，不能用这三格拟合简单的参数量规律。

### 5.4 哪些机制已经核实

| 检验 | 实际证据 | 不能推出什么 |
|---|---|---|
| 9B路由查表 | 最佳常量temporal36.4750%；broad自然24.9365%，其频率匹配随机期望31.4490%；Codex标准31.1865%；事后最优56.0337% | 随机是保存结果表的期望，不是随机路由新E2E；事后最优不是可实现Selector |
| 更强Selector | 27B/35B各80×3入口×2编号=480，全部有效；12种查表值均低于最佳常量及各自频率匹配随机期望 | 只选卡后查9B结果，不是大模型Actor或混合系统的新准确率 |
| 只改when | P38/T15/none27/J0；80对实际预测和非Selector输入/输出token哈希多重集等于所选旧固定臂；122次实际注入 | 当次输入/输出多重集一致不等于全部事件顺序、视觉真伪或普遍确定性 |
| when效用 | 原Train27.4038 vs旧24.7442；Cal25.1186 vs旧30，差−4.8814pp、CI跨零；查表27.0192低于频率匹配随机29.0520 | 一次八例且有截断的失败不证明初始信息理论上不可学 |
| 一次生成激活 | Train选中69/80，172/172 Global调用注入；11弃选答案/分数同空库；首接受库既有选中28/80 | 更多激活不代表更正确；入口宽度未与其他措辞隔离，整体成绩还混合正文变化 |
| Stage2–3删除 | 296对Selector输入/输出与选择相同；191共同none答案/动作相同；105选中题动作均变、76答案变 | 删除同时改变长度与内容，不能定位某分支的纯因果作用；Gate近零不等于没影响行为 |
| 角色组合 | Global与Video单独点增益+11.1865/+2.5536pp，组合+6.0945pp，描述性差中差−7.6456pp | 角色收益不可预设相加，但一次组合不证明所有组合有害 |
| Video首卡 | 自然239请求全none；强选480规划调用全部注入，47答案变化，整体未测到正差 | 零激活不证明正文无效，强选负差也不能排除适用子集有益 |
| watch-first | Train77/80首步watch，75/78多视频题首watch全覆盖；365仍未胜terminal | 成功调用/改变动作不等于正确视觉证据；这不是47%筛选集合复现 |

只改when的原分比查表高0.3846pp来自一题同完整请求、同身份Judge异分；canonical后Train27.0192%，Cal不变。另有早期0.1923pp同请求异分。正文生效与评分噪声必须分开。

本地Video在一段0.92秒视频上重复产生零长度时间范围，即使Memory已有工具错误也继续重复；正常工具拒绝不是基础设施故障，该题各臂都0分，不能把它算作新增掉分原因。推理失败解释也需实际证据。

## 6. 什么样的skill值得下一轮研究

当前尚无经过来源外确认的“最佳风格”。能够给出的约束是：

1. **可选性：** when描述首次输入可判断的操作需求，明确范围；不要求未来报告或Video Selector不可见的Memory。入口最好能说明方法如何覆盖问题的主要操作，不能只有模糊的“需要更多观察”。
2. **可执行性：** strategy把目标变成合法action/参数和报告判据。跨消息传递要明确，不能假设Observer已经看到skill或完整原题。
3. **相对效用：** 正文与当前Actor、伙伴库、诱发的观察链共同决定收益；文字合理、选中、注入、动作变化均不是总分提升的替代指标。
4. **可验证性：** 能提出一个可区分的行为假设并保留失败；用完整自然库评估接受，固定/人工路由仅作诊断。

静态比较中，强一次生成卡与首接受卡正文分别509/513词，长度接近；两者when都不依赖未来History。一次生成卡更明确按缺失事实分流、把已知事实嵌入后续instruction、在证据齐时停止；首接受卡更强调中立首轮和异常后的复核。这些是**待检验的解释**，不是Gate正差的已证明原因。

更深的问题可写成：给定初始可见输入X，能否预测某正文相对none或固定强比较器的条件净收益？最佳常量 `max_s E[R_s]`、可实现路由 `E_X[max_s E[R_s|X]]` 与事后最优 `E[max_s R_s]` 不相同。本轮只能测其中部分值，不能将事后差额全部当作可学空间。实际计算仍用官方task/CCQA权重。

## 7. 文献怎样转化为本项目的实验

本表整理本轮已调研的一手工作，详细摘取与限制见[探索方案](skill-exploration-study.md)。它们不是已经在MVAgent完整复现的算法结果。

| 工作 | 借鉴的问题 | 本轮对应或后续边界 |
|---|---|---|
| [SkillOpt](https://arxiv.org/html/2605.23904v1)、[GEPA](https://arxiv.org/abs/2507.19457) | 用执行反馈编辑程序性文本、验证候选 | 已有rolewise透明基线；完整同预算适配尚未做，不能把“反思改Prompt”当新贡献 |
| [Skill Consumption](https://arxiv.org/html/2605.23899v1)、[Skill Usage](https://arxiv.org/html/2604.04323v1) | 提取、选择、使用是不同能力 | 自然/固定路由、注入与轨迹分别测；不额外加入在线refiner |
| [ExpeL](https://arxiv.org/abs/2305.14794)、[ReasoningBank](https://arxiv.org/abs/2509.25140)、[ACE](https://arxiv.org/abs/2510.04618) | 成功/失败经验、增量规则更新 | 只用Train角色公开视图；不把幸运答对当正确策略，不部署答案记忆 |
| [Dynamic LLM Routers](https://arxiv.org/html/2610.02762v1)、[RouteLLM](https://arxiv.org/html/2406.18665v4)、[Learning to Defer](https://proceedings.mlr.press/v119/mozannar20b.html) | 相对效用而非主题匹配，弃选也有机会成本 | 常量、频率匹配随机、none与自然选择分别诊断；不训练参数化router |
| [COBRA-Skills](https://arxiv.org/html/2609.11682v1) | 优化期候选评估预算 | 不能当部署query→skill路由解法；目前不新增surrogate/bandit |
| [SPARO](https://arxiv.org/html/2609.32492v1)、[AgentGrad](https://arxiv.org/html/2609.08572v1) | 通过干预定位激活/执行/下游问题 | 采用受控比较；GT-derived提示违反本项目optimizer边界，不照搬 |
| [MASPO](https://arxiv.org/html/2605.06623v1)、[MIPRO](https://arxiv.org/html/2406.11695v2) | 多模块与搭档之间存在交互 | Global×Video组合和交替更新；完整系统重跑，不拼接旧局部报告 |
| [Video-RSI](https://arxiv.org/html/2609.37950v1)、[LensWalk](https://arxiv.org/abs/2603.24558)、[AgentCVR](https://arxiv.org/abs/2605.29643) | 主动观察、新证据和跨视频关联 | 借现有action参数控制；不改harness、不让optimizer越权看片或增加成本目标 |
| [SICA](https://arxiv.org/html/2504.15228v2)、[DGM](https://arxiv.org/html/2505.22954v2)、[ADAS](https://arxiv.org/html/2408.08435v1)、[Self-Refine](https://arxiv.org/html/2303.17651v2) | 自改进、归档分支和可操作反馈 | 多父搜索未实现；固定GLM写卡没有证明优化器自身的改进能力递归增强 |

论文下一阶段仍需要强一次生成、一次Train蒸馏、现有rolewise、GEPA/SkillOpt适配的公平比较。至少对齐模型、信息权限、最大库容量、提案/完整rollout/验证预算，并报告所有拒绝和无效提案、token/GPU小时及重复运行。人类手写正式基线不纳入当前计划；已做手工卡与Codex分配作为机制干预单列。

## 8. 接手后的第一项实验：冻结两库的新来源确认

这是**下一阶段建议，尚未运行**，不需要新的优化器调用。

| 项目 | 事前固定内容 |
|---|---|
| 问题 | 强一次生成卡与正式首接受库的差异能否在新声明来源上保持？ |
| Arm A | 原样冻结的GLM一次生成库87c43278…，Global自然选择，Video空 |
| Arm B | 原样冻结的正式首接受库4765323a…，Global自然选择，Video空 |
| 消费模型 | 同一9B Actor/Selector/Observer与固定Judge；基础Prompt、预处理、预算不改 |
| 样本 | 十任务齐全、有序、seed0；排除本轮296和365及其声明来源组，披露更早历史接触 |
| 主比较 | A减B的完整官方macro；不是A相对none的效果，不追认旧Gate接受 |
| 规模 | 先约定最小实际增益，再按已有配对方差和来源相关性确定；不再次任意选40题 |
| 停止/报告 | 两臂完整评分后比较；不按前缀准确率换卡、换清单、补第三赢家臂 |
| 资源 | 建议先各8H100并行，共16；分配、加载和等待资源均记账，总上限仍64 |

### 8.1 必须先完成的清单工作

当前仓库**没有一条已经验收的命令**能直接生成上述“十任务＋排除所有既用来源”的新确认集。`prepare_crossvid_train_cal_gate_split.py`实际只为九个closed任务分配样本，并只按Lite2500题号排除；choice脚本也不是十任务确认入口。不要将它们换个输出文件名就称独立确认。

需要交付以下小型数据准备单元，之后立即运行上述两臂：

1. 从固定版本的完整QA元数据提取真实来源标识，按共享来源的传递连通关系分组。可复用 `eval.data.group_by_media`；UAV源序列等不能仅按派生片段文件名区分。
2. 在同一个完整来源图中映射历史面板，排除本轮296/365及其来源。不要在不同子集分别生成group_id后只比较字符串；代表ID可能变化而视频来源仍相同。
3. 先报告每任务可用题数/来源数。如果严格排除后某任务无足够来源，如实记录；不能悄悄放宽后仍称来源隔离。可补充合法数据，或明确转为较弱的开发确认。
4. 冻结 `sample_ids.json`（有序JSON数组）、`source_groups.json`、`panel_manifest.json`：包含样本与来源、任务配额、seed、排除清单哈希、源QA/媒体版本、输入文件SHA及协议。task仅供分层抽样/统计，不能进入optimizer。
5. 在读候选新面板成绩之前冻结比较计划、规模和分析器。样本数不足时报告能力边界，不通过反复改变面板找正差。

已有来源分组是声明口径，不等于已经证明视觉来源绝对独立。原365以及复用Cal不能重新命名为盲Test。

### 8.2 完成后怎样决定

| 观测 | 后续决定 |
|---|---|
| 一方在来源外呈现有实际意义的稳定净收益 | 把它冻结为强比较器，再在新的合法Train上检验一个明确正文行为假设 |
| 差值区间较宽或方向反转 | 先解决覆盖/方差问题或报告机制边界，不立即扩大库和搜索轮次 |
| 希望解释one-shot与首库差异 | 可在Train固定one-shot入口/meta，仅交换两份原正文；先核选择相同，再比较行为和整题得分；这是正文整体干预，不是单组件归因 |
| 固定正文有效、自然选择损失可复现 | 再研究when对可见相对效用的描述；不能仅优化激活率 |

当前rolewise不支持以任意父库初始化新run。后续“从强比较器上做一次正文干预”可用完整库的独立诊断评估；若要做可恢复的父库搜索入口，需要另行设计/实现，不能假装已有`--initial-bank`。

## 9. 可执行入口：哪些现在可用，哪些尚缺

### 9.1 环境与源码

使用上述研究分支或精确源码提交，不在共享旧工作区直接reset。公开代码可在普通GPU服务器运行，环境和本地数据布局见[根README](../README.md)、[固定推理配置](../configs/inference/README.md)；这里只给接续实验命令，不提供数据下载指导。

本项目维护环境：Modal访问必须先经过 `ssh modal-gpu`，在该devbox读取 `~/.agents/skills/modal/SKILL.md` 并按本机环境说明分配GPU；Lightsail只编辑、Git和日志查看。以下推理命令在**已分配的远端计算环境**执行，命令本身不会申请GPU。原始记录留runs volume；凭据通过Secret/环境提供，不写进命令、库或Git。

### 9.2 冻结原库，生成自然运行配置

以下模板核对了当前源码接口，但本次文档整理未执行。前提是新来源清单已经完成，且计算环境已挂载原runs、assets和weights。`/runs/new-skill-confirmation`必须是一个新的目录；模型权重路径需匹配现有配置或按根README单独设置并记录身份。

```bash
export PYTHONPATH=src:.
export STUDY_ROOT=/runs/new-skill-confirmation
```

将下面Python保存为计算环境中的`/tmp/prepare_skill_confirmation.py`，再执行`python /tmp/prepare_skill_confirmation.py`。它只准备配置，且因新目录保护只能对该目录执行一次；恢复已有评测时不要重新运行此准备步骤。

```python
import json
import os
from pathlib import Path
import yaml
from skill_evolution.infra.banks import BankSnapshot, runtime_with_bank

study = Path(os.environ['STUDY_ROOT'])
study.mkdir(parents=True, exist_ok=False)
previous = Path('/runs/devbox/skill_exploration_20261021')
banks = {
    'one_shot': (
        previous / 'one_shot_glm/generation/banks',
        '87c43278775a495f2d163356c8cefe73fce233b6f943c3734d1ae5d319345472'),
    'accepted': (
        previous / 'rolewise_glm/evolution/banks',
        '4765323a0d13b5df3402a00b29fe242f0543dd6f82dc30377595e83668f2ad55'),
}
base = yaml.safe_load(Path('configs/inference/modal_qwen35_9b_no_skill.yaml').read_text())
for name, (directory, digest) in banks.items():
    snapshot = BankSnapshot(directory / (digest + '.json'), digest)
    runtime = runtime_with_bank(base, snapshot)  # 校验原始字节SHA/schema，启用自然task选卡
    (study / f'runtime-{name}.json').write_text(
        json.dumps(runtime, ensure_ascii=False, indent=2))

execution = yaml.safe_load(
    Path('configs/inference/execution/modal_h200x8_qwen35_9b.yaml').read_text())
replicas = execution['model_pools']['qwen3_5_9b_local']['replicas']
assert [r['gpus'] for r in replicas] == [[i] for i in range(8)]
execution['model_pools']['qwen3_5_9b_local']['replicas'] = replicas[:7]
(study / 'execution.json').write_text(json.dumps(execution, indent=2))
```

这样每节点Actor使用GPU0–6及端口8100–8106，GPU7留给Judge。文件名里的h200是历史命名，硬件必须以真实分配和启动manifest为准。`runtime_with_bank`关闭空Video库，不是强制选卡。将审定清单原样复制到 `$STUDY_ROOT/sample_ids.json`，保留其来源审计文件和文件哈希；不要用`--limit`近似替代。

### 9.3 两臂完整自然运行、评分与收尾

同节点可以依次执行；若并行，应为两臂分别分配节点并保持相同服务配置。不要在同一个模型池上同时启动两个独立批处理器。下例先在专用GPU7启动一次Judge，再依次运行两臂：

```bash
export JUDGE_WEIGHTS=/weights/Qwen3-30B-A3B-Instruct-2507
export JUDGE_LOG_DIR="$STUDY_ROOT/judge-logs"
bash eval/agent_eval/serve_ccqa_judge.sh 7 8207 || exit 1

for arm in one_shot accepted; do
  python eval/agent_eval/run.py \
    --config "$STUDY_ROOT/runtime-$arm.json" \
    --execution-config "$STUDY_ROOT/execution.json" \
    --dataset-root /assets --benchmarks crossvid \
    --sample-ids-file "$STUDY_ROOT/sample_ids.json" \
    --defer-open-qa-judge \
    --output "$STUDY_ROOT/arm-$arm" || exit 1

  python eval/agent_eval/score_crossvid_ccqa.py \
    --output "$STUDY_ROOT/arm-$arm" \
    --qa-path /assets/crossvid/QA/CCQA.json \
    --endpoints http://127.0.0.1:8207/v1 || exit 1

  python eval/agent_eval/finalize_results.py \
    --output "$STUDY_ROOT/arm-$arm" || exit 1
done
```

运行前保存源码commit、依赖/模型身份、两库SHA、实际execution、清单和预处理哈希；native runner会保存其源码和输入配置。所有中断恢复使用本次冻结入口和原参数加`--resume`，不能改已完成输出目录中的实验身份。本轮历史任务已经完成，不要对旧目录盲目resume。

**最终主分读取 `summary_scored.json` 的 `datasets.crossvid.official_task_macro`，并确认十任务齐全、`score_complete`和题号覆盖。** 原`summary.json`仍可能是deferred；普通`accuracy`是题目平均，不能替代十任务macro。当前`finalize_results.py`的Markdown标题仍带No-Skill，并按配置文本的`enabled: false`推测禁用状态；Global有卡/Video关闭时会误导。该标题不是skill身份依据，以实际`input_config.yaml`、库SHA和选卡事件为准，后续正式报告可单独修正文案。

新面板的配对bootstrap/来源组分析没有现成通用公开CLI。本轮分析器在第10节的私有代码归档中，可复用算法并为新manifest做薄适配；不要改原路径后覆盖旧报告。完整分析要同时给官方差值、改善/退步/同分、十任务分数、来源组区间、Judge一致性、采样和调用成本。结束后释放自己的Actor/Judge及GPU分配；进程退出不自动等于所有服务释放。

### 9.4 生成与进化入口的正确用法

重新生成只是新候选，不会复现保存的87c43278…卡。以下配置读取`BIGMODEL_API_KEY`环境变量，应由Secret注入，不能将实际密钥写进命令或文档：

```bash
python scripts/generate_skills.py \
  --config configs/skill_evolution/glm_optimizer.yaml \
  --runtime-config configs/inference/modal_qwen35_9b_no_skill.yaml \
  --role global --max-cards 1 \
  --output-dir /runs/a-new-generation
```

该入口没有`--resume`，输出目录必须不存在，`--max-cards`是上限，不是配额；它不读取样本或成绩，也不分配Actor。一次生成入口没有rolewise的本地优化器池注册，不要直接套用`local_optimizer.yaml`。

正式进化入口是 `scripts/evolve_skills.py`，参数见[方法README](../src/skill_evolution/README.md)与[中文Prompt镜像](skill-evolution-prompts.md)。默认会从两空库请求完整Train/Cal/Gate基线；**当前没有 `--initial-bank / --bank / --reuse-baseline / --rounds` CLI**。本轮合法空库复用由私有冻结驱动接入并核验，不是任意复制`evaluation.json`即可命中缓存。下一项两库确认不应重新启动rolewise，避免重跑用户排除的无skill条件。

只有真正未完成的旧进化run才用下面的恢复形式，且不能再附模型、split或execution参数：

```bash
python scripts/evolve_skills.py --output /runs/an-existing-evolution --resume
```

`manifest.json`、`configs/`、`frozen/src`与`frozen/eval`为恢复权威。完成的API响应和评估可复用；只有请求没有响应的中断提案不自动重放。

## 10. 文件、库与证据如何找回

### 10.1 GitHub和Modal各保存什么

GitHub包含公开方法、配置、人工诊断定义、测试和报告；**不包含本轮所有生成库、原始结果、媒体、权重、私有控制器或环境凭据**。因此clone仓库能继续开发，不能单凭它精确复现本轮全部原始记录。

```text
src/skill_evolution/configs/          配置解析、人工诊断定义
src/skill_evolution/infra/            库编辑/冻结、角色公开投影、调用留存、角色契约
src/skill_evolution/algorithms/
  one_shot/                         无反馈一次生成
  rolewise/                         单角色单卡编辑及整库Cal/Gate闭环
src/mvagent/skills/                  检索、Selector与注入；不依赖optimizer
eval/skill_eval/                     与原生运行器、数据、官方评分的适配
eval/agent_eval/                     正式问答、CCQA评分与最终汇总
configs/skill_evolution/             YAML；不是全部实际实验冻结配置
```

不存在独立动态换卡器、Video局部真值奖励、多父候选搜索或训练router。现有rolewise已经有同题反馈、角色投影和条件策略Prompt，后续不要把这些已实现部分重新命名为新贡献。

本轮结果volume：`wxu-evolve-agent-runs-20261006`，环境`zheng-dev`。下文`ROOT`均指 `/runs/devbox/skill_exploration_20261021`；SDK文件名不带`/runs/`前缀。完整原件继续在Modal读取，勿把媒体、raw JSON或凭据迁入Lightsail/Git。

### 10.2 必须固定的身份

| 对象 | 位置或提交 | SHA256 |
|---|---|---|
| 诊断/迁移源码 | commit `2d3085f0582c47918893a0c5dc9d73854e19d72c`，`ROOT/source/source.tar.gz` | `dc338acd403a8e7522c05a8f05d88a968e4d6b9f1d132d938416eb252b321a8e` |
| 优化器/正式源码 | commit `ff81a3606151ab2b03fbd68455e33775bc8f46e2`，`ROOT/local_optimizer_pool_fix_source/source.tar.gz` | `4e9354463a82bafb6005fab4c989274749f8f1a17a6740e31775a1e271c7b9f0` |
| 强一次生成库A | `ROOT/one_shot_glm/generation/banks/<SHA>.json` | `87c43278775a495f2d163356c8cefe73fce233b6f943c3734d1ae5d319345472` |
| 正式最终库B | `ROOT/rolewise_glm/evolution/banks/<SHA>.json` | `4765323a0d13b5df3402a00b29fe242f0543dd6f82dc30377595e83668f2ad55` |
| 手工三正文源库 | `ROOT/confirmations/joint_compare_forced365/source_bank.json` | `7c3f0aa4f4b2e3e1d6f0bbf07778a3aa462fcc67f9c7837983abfa4b756d4fcd` |
| when-only候选 | 路径由`ROOT/utility_when_only/generation_manifest.json`给出 | `f14ba6f7a439f45a72657254698da91ee5b6c4ebc9bf69957e8e66616381f0e1` |
| 正式谱系与拒绝记录 | `ROOT/rolewise_glm/evolution/summary.json` | `7f8e03e96e36d8f829be4dd3d87d6e631db183225c56078aca341f500e1b4360` |
| 私有代码/MD最终归档 | `ROOT/control_backups/final-controls-20261022-0150.tar.gz` | `361fe4e70a9218d38d500aa53ae67266d824d3ccf334a75b0937aa9e092e24b2` |

私有归档485255 bytes、204个Python/Markdown文件，配套`.manifest.json`记录成员哈希；保存后完整SDK回读已核验。它包含一次性分析/控制代码，**不包含原始结果或模型环境**。恢复到隔离私有目录供查阅；里面旧controller带过期截止和旧job状态，不能解压后直接全量启动。部分已完成任务的重复冻结src/eval散文件已无损归档，旧run复查应遵循原归档索引恢复，不把缺散文件误认成raw丢失。

旧run的实际 `runtime_source.json`、`execution.json`、`startup_identity.json`、native `run_manifest.json`、正式`configs/*.json`以及模型权重身份都须一并读取。只匹配模型名、Git提交或YAML文件名不足以证明同协议。

### 10.3 主要分析报告索引

下列目录均在ROOT下，内含`summary.json`及可读报告；完整SHA和核验范围见[结果报告](skill-exploration-results.md)。

| 要复核的结论 | 目录 |
|---|---|
| 三卡/none同题表与实际路由 | `counterfactual-saved-20261021-180819` |
| 路由置换、频率/题型分配 | `routing-permutation-20261021-184835` |
| 更强Selector查表 | `strong_selector/{27B,35B-A3B}/lookup` |
| 首Global正文删减 | `conditional-ablation-audit-20261021-233312` |
| Video强选及无效observe | `local-video-forced-audit-20261021-224617` |
| 一次生成296三方配对 | `one_shot_glm/paired-20261022-004758` |
| 一次生成Train实际激活 | `one-shot-train-selection-20261022-011054` |
| when-only及匹配原Cal | `utility-when-only-audit-20261022-005220` |
| 首Global自然9B365 | `confirm365-paired-rolewise_global_first_natural365-20261021-225703` |
| 首Global自然27B/35B365 | `accepted_transfer/paired-27B-20261022-011753`、`paired-35B-A3B-20261022-011754` |
| joint_compare365 | `confirm365-paired-joint_compare_forced365-20261022-014431` |
| joint完成与旧raw保持 | `joint_recovery/launch-002/completion_reconciliation.json` |

原始答案通常位于各臂 `evaluations/<variant>/<partition>/rollouts/records/crossvid/<id>/result.json`；自然库variant为库SHA，固定诊断是另算的variant，不能用源库SHA猜路径。先读`tasks.json`和`evaluation.json`。正式候选的`rounds/`保存提案、反馈与接受谱系，`judge_cache/`及逐臂`judge/`保存判分来源。补充365目录中`partition=gate`是运行器字段，不等于正式接受Gate176。

仅复查文档来源时，可在已认证的modal-gpu devbox上用SDK读一个小文件到内存，不下载raw：

```python
import hashlib
import modal

volume = modal.Volume.from_name('wxu-evolve-agent-runs-20261006', environment_name='zheng-dev')
relative = 'devbox/skill_exploration_20261021/one_shot_glm/paired-20261022-004758/summary.json'
data = b''.join(volume.read_file(relative))
assert hashlib.sha256(data).hexdigest() == '46e68fc079bedf1d10d00e8b71e6ead1c758bf46439a5afff988bfa2979530f3'
print('Verified saved analysis:', relative)
```

本文引用的是本轮已保存和核验的身份，不代表此文档整理重新遍历了全部远端raw。获得结果volume权限、原始数据及权重仍是精确复核的前提。

## 11. 故障、恢复与避免重复工作的规则

| 已发生问题 | 本轮处理 | 后续应保留的约束 |
|---|---|---|
| 文件条目达到500000上限 | 已完成重复src/eval归档，逐成员核验并独立读回后才移除散文件 | 不删除raw/Judge；不对活跃服务reload volume；按实际容量安排新任务 |
| 正式Video候选ENOSPC | 沿原冻结源码恢复，55份已保存raw及7份旧evaluation保持哈希 | 基础设施失败不记零；不能用当前源码覆盖旧run |
| joint控制连接中断 | 保留114份raw，仅续251题；首次恢复目录初始化失败在模型前，第二次成功 | 旧driver状态保留；用新的完成回执判终态，失联不等于模型失败 |
| CPU分析旧元数据不一致 | 精确确认空记录评分保护差异、源库/规范化库双身份后窄修正 | 不直接删身份断言，不重Actor/Judge掩盖解析错误 |
| 同请求Judge异分 | 保留原分，做canonical补充 | 不把评分噪声当skill因果效应，不悄悄回写接受结果 |

joint-only基础设施恢复截止从01:29延至01:50，事先声明且未改变题目、库、Actor或预算；实际01:43完成评分、01:44释放。完成回执SHA `6e31c2aac76bd64c2ecd3a48d4abc9f4a1c298c2bde9b11a5910e4502117ce45`核实114份旧raw未变。所有模型任务已结束，15分钟独立检查也已停止，不存在会话外自动研究循环。

下一轮一个人/控制器负责提交与释放，检查代理只读；每15分钟检查实际新增完整样本，不以不随每题刷新的phase时间判断停滞。资源计入已分配、加载和等待替换的槽位，确认旧节点实际释放后再重用。排队时推进独立分析，不重复提交。每个实验单元保留新目录、配置与来源，避免按日期更换推理seed。

## 12. 下一轮交付清单

- [ ] 冻结一个研究问题、两库SHA、同一模型与完整对照，不把当前开发赢家改称盲测赢家。
- [ ] 新十任务有序清单、完整来源图排除审计及样本规模依据落盘；不满足隔离时先说明范围。
- [ ] 按第9节完成两臂自然完整问答、原始答案先落盘、Judge成功、官方macro与同题分析齐全。
- [ ] 保存所有失败、原评分与必要canonical敏感性；未完整的实验不写成零分或完成。
- [ ] 报告来源覆盖、配对区间、多重比较/复用限制，以及提案、调用、token和GPU时间；不将成本加入准确率接受目标。
- [ ] 据第8.2节只选择一个后续方向；正文、入口、伙伴、库大小不要同时任意扩展。
- [ ] 更新本交接文档、结果报告与实验清单，提交并推送代码/配置/MD；原始数据和凭据不入Git。

这份交接的目标是继续产生可检验的结果，包括负结果。完整SkillOpt/GEPA适配、多次独立生成/搜索、新来源确认及最终Test均尚未完成，不能在论文或后续交接中写成已有证据。
