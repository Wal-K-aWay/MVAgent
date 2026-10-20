# 固定框架与实验记录

2026-10-20发布入口：默认分支`main`现同步固定框架，核心运行代码取自`f8a6a62`，结果说明沿用`ec3eb02`。
后文带日期的运行状态为历史记录，不代表任务当前状态；已有实验继续其冻结源码。
本次只同步源码、配置、测试和说明，不加入实验结果或外部方法的独立实验实现。
历史复现实验数据及旧媒体缓存已有用户授权清理，旧记录中的原件路径不保证仍可读取。


更新：2026-10-18。本文件是无 Skill 推理配置、回答协议和基础 Prompt 实验的唯一汇总。
运行方法见根 README、`configs/inference/README.md` 和两个 eval README；算法设计、Skill 进化和其他方法的独立项目文档不在本次清理范围。
历史结果不是正在运行的任务，也不是可切换的正式配置。

## 已固定的框架

采用“简洁 Global System + 原 VideoAgent”，对应完成 4500 条开发集评测的源码
`e0ace2739f13e2b01f8fcdf271f62a551e11f2b3`。本分支从共享代码备份 `d565790` 出发，
恢复该实验的 Global Prompt 和极短视频修复；保留后续结果导出、E2E 和其他方法实现。
不是整体回滚到 PRO 6000，也没有采用完整题目注入 VideoAgent 的实验。

- Global 主动 `answer` 直接携带 `parameters.answer`；耗尽步数时复用 `decide(answer_only=True)`，没有独立回答器。
- Global User 顺序：Question → Videos → Available actions → History。VideoAgent 只接收自己的 instruction 与历史，不额外接收完整原题。
- Global / Video 各最多 5 步，每次最多 512 帧、2048 输出 token；取证 reason 最多 1200 字符，终答 reason 无字符硬限。
- answer 保持开放、非空字符串，最多 2400 字符；不按 benchmark 枚举合法选项。
- FFmpeg 裁剪；极短视频进入补帧路径，正常完整视频可直接复用。OpenCV 仅在该判断中读取媒体元数据，不替换 FFmpeg 裁剪。
- Qwen3.5-9B / 27B / 35B-A3B 全部 BF16；8×H100，每卡独立 TP1/DP1、并发 1，整题固定副本。
- `qwen35-bf16-flashinfer-sync`，FlashInfer GDN、原生 GemmaRMSNorm、seed=0、temperature=0、thinking 关闭；prefix/MM processor cache 关闭，普通解码 KV 开启。
- 原始 rollout 先落盘；评分失败保留为错误。保留输入哈希、完整 token、服务身份和冻结源码。

唯一 Global System 原文：

> You are a coordinator for multi-video question answering. You cannot view videos directly. Your visual evidence consists only of successful single-video summaries and completed joint-watch results in History. Preserve video identities and choose one available action that either obtains missing evidence or returns the final answer.

### 已测主指标

每个模型每个 benchmark 500 题，共 4500 条有效轨迹；包含 306 条先导结果复用和 4194 条新轨迹。
均为开发题；CV/MVU 按 task 分层估计官方总分，CrossVid 十任务 macro（CCQA 按评分点加权）。
下表 E2E 与 Agent **同题对齐**，MVU E2E 使用指令移后版本；不把 500 题估计写作全集结果。

| 模型 | Benchmark | E2E | 原长 Global System | 固定简洁 System | 相对 E2E / pp |
|---|---|---:|---:|---:|---:|
| 9B | CVBench | 60.42 | 61.57 | 64.39 | +3.97 |
| 9B | MVU-Eval | 34.79 | 49.41 | 53.02 | +18.23 |
| 9B | CrossVid | 32.87 | 34.89 | 35.00 | +2.13 |
| 27B | CVBench | 69.17 | 70.01 | 70.22 | +1.05 |
| 27B | MVU-Eval | 43.21 | 60.23 | 59.62 | +16.41 |
| 27B | CrossVid | 40.99 | 46.62 | 47.71 | +6.72 |
| 35B-A3B | CVBench | 64.19 | 66.16 | 68.39 | +4.20 |
| 35B-A3B | MVU-Eval | 38.40 | 51.02 | 56.82 | +18.42 |
| 35B-A3B | CrossVid | 33.13 | 37.86 | 42.15 | +9.02 |

九格相对 E2E 点估计均正，但 CVBench 三格和 9B CrossVid 的配对 95% 区间跨零：
分别为 [−0.64,8.77]、[−3.10,5.24]、[−0.40,8.81]、[−2.78,7.39] pp。
不能声称已证明所有模型、所有 benchmark 稳定提升。
简洁 System 相对长 System 为 8 正 1 负；排除先导复用后，9B CrossVid 为 −0.62 pp，仍须报告。

4500 条最终空答案和单独 `}` 均为 0，基础设施/模型调用错误 0。
闭式答案格式错误从 79/4350 降到 62/4350：9B 28→30、27B 13→8、35B 38→24。
中间调用 `length` 从 178 增至 324，输出 token 从 6,515,793 增至 7,621,723；简洁 System 不等于更少推理。
9B/27B/35B 单题平均耗时分别 54.79/102.13/99.17 秒；这是该批次实测，不能直接作为任意机器的吞吐保证。

### 固定数值后端的补充证据与边界

三模型 E2E 各330题×4遍：3960正式响应、2970次完整token比较无差异；两个未跨卡题定向补测后每题都有跨卡比较。
两次独立视频准备的330题输入SHA一致；更早16-worker冷解码曾有两题输入不同，原因未定，不能外推到任意冷解码。
后端定位发现视觉输出和第0层输入相同、首个差异出现在第0层 GemmaRMSNorm；vLLM 0.19.1 的算子内部调用
`torch.compile`，外层 `enforce_eager=True` 没有关闭它。固定 `custom_ops=['all','-gemma_rms_norm']` 后的实际回归通过。
因此不能把问题概括为“FlashInfer 有问题”或只改 attention backend 就足够。
原E2E八卡面板吞吐9B/27B/35B为59.77/38.96/61.05题每分钟，不含帧预生成和权重加载，不是全benchmark工期。

CCQA Judge 与 Actor 验收分开：旧35B E2E曾发现两组相同Judge输入得到不同判定，缓存与原评分不一致。
历史 DeepSeek Judge 与本地 Qwen3-30B-A3B Judge 分数不能混算；后续配对沿用同一Judge、相同评分点规则和按答案缓存。

## 历次方法及结论

以下实验的输入、样本数与协议不同，不能横向拼接成同一消融。小规模成功只适用于已测范围。

| 方法 | 证据与结果 | 当前处理 |
|---|---|---|
| 早期 FP8、TP、原生 DP、批量与多进程数值实验 | 不同模型和内核路径的重复性不统一；未形成三模型共用且更快的已验收方案 | 删除实验驱动；使用统一 BF16 |
| FlashInfer GDN + 原生 GemmaRMSNorm + 同步独立副本 | 既有扩大 Agent 检查：888 条轨迹、11,544 次调用；666 次轨迹配对、9,125 次相同请求配对均无差异，含重启/换卡。正式 HTTP 接入另有 12 条轨迹、256 调用、128 调用配对无差异 | 保留固定后端；有限检查不保证任意输入 |
| TP8 + prefix cache + 16 题并发（35B） | 16/16 重复轨迹变化；24 次相同输入比较中 18 次变化。两轮 312.86/255.96 秒，TP1 对照 219.17/207.41 秒；总计 80 轨迹、754 调用，仅比较一致性/速度 | 不采用；prefix 关闭 |
| reason 字符放宽、总输出 4096 token | 28 次调用中仅提高 token 的 8 次答案不变；同时放宽字符限制仍有循环，CV712 调用 14→16，答案仍 C | 保留 2048；终答 reason 无字符上限 |
| reason 边界续写 | 23 条历史理由检查及 7 次续写显示“仍在推进”和“已经重复”同时存在；Counting88 到 4096 token 仍循环、未完整交付 JSON | 不以继续放宽预算作为统一解法 |
| 结果字段提前、短 reason、理由整理 | 32 次调用、4 题局部正确数 1→3，但出现标点答案、截断与事实漂移 | 不修改正式字段顺序，不加二次整理器 |
| 简洁理由＋最佳判断、多条通用决策规则 | 小型冻结证据试验可减少终答篇幅，但不稳定修复拒答；System 小测终答 580→338 token，仍仅 2/4 按题给选项；长规则在后续大面板逊于简洁角色 System | 只保留已测简洁 System |
| presence_penalty 与非零 temperature 等采样 | presence 0.5/1.5 小测 12 次配对 0 差异；后续 106 次响应、6 条全轨迹仍有拒答/标点/格式退步，未证明稳定净收益 | temperature=0，惩罚默认值 |
| 独立回答器与直接 answer（9B 固定相同证据） | 25 题：独立正确 6、格式合格 12；直接正确 15、格式合格 25；独立加上一轮 reason 正确 10、格式合格 17。单独 `}` 为 12/0/8 | 直接提交答案；这是节点诊断，非完整 Agent 准确率 |
| 直接回答完整小批与扩展 | 126 条：格式错误 38→2、空答案 12→0；900 条：格式错误 90→19、空答案 1→0，但准确率九格混合 | 扩到 4500 条后选择当前协议，不凭小批定论 |
| History 前置 + 主动直接答 + 独立兜底 | 三模型 6 条全轨迹及 6 条固定 History 兜底、144 调用、72 配对完全一致；9B 兜底两次均自然 stop 输出 `}` | 删除独立兜底；耗尽时复用决策接口 |
| PRO6000 9B 全 src + FFmpeg | 三模型各 330 题，27B 14 条媒体失败补跑后共 990 有效；27B CV −8.18 pp（区间 [−15.16,−1.41]），35B Cross 闭式 −6.34 pp；9B 部分增益但格式错误 7→15 | 不整体回滚；保留短视频修复 |
| 简洁 Global System | 上表 4500 条，相对长 System 8 正 1 负，格式错误总量下降；耗时、截断并非全面改善 | 当前固定基础 |
| Video 通用边界要求 + 视频 ID | 三模型共 306 题，小批结果混合，不能由 ID 单独归因，因为同时改 System | 不纳入正式基础 |
| Video 通用要求 + ID + 每轮完整原题 | 同面板再跑 306 题：相对原 Video 九格 6 正 3 负；相对只加边界/ID 为 3 正 6 负。35B Cross −18.49 pp，95% 区间 [−30.04,−6.79]；单题慢 12–28% | 拒绝该注入方式；恢复原 VideoAgent |

### PRO6000 为什么看起来更稳

历史同题四方复算中，旧 PRO Agent 的 CV/MVU/Cross 闭式相对旧 E2E 增益：
9B 为 +4.41/+7.13/+4.57 pp；27B 为 +4.93/−1.71/+10.06 pp；35B 为 +8.21/+4.10/+12.71 pp。
其中 27B/35B 当时仅对齐运行中子集（4195/1375 闭式题），9B 为 5081 题；Cross 不含 CCQA。
旧版本来也不是九格全部提升。硬件、帧采样、E2E 输出预算、分辨率和 Judge 同时变过，不能将全部差异归于单一 Prompt。

旧独立回答器阶段 9B 的 905 个 `}` 全部是合法 JSON、自然 stop，输出中位数 120 token；
其中 MVU Comparison:1232 在决策与终答理由里都明确选择 A，却在 answer 字段交付 `}`。
这不是解析丢字，也不是普遍超过 token 预算；可重复地生成错误格式仍然是错误。
CV712 则是回答器重新解释“提到或展示”，推翻前一步判断并拒绝给选项，属于协议引入的二次判断。

### Video 完整原题实验的实际差异

306 题首轮 Global 输入/输出相同；663 对完全相同请求的 token 无差异，因此没有发现数值重复性退化。
新增原题改变了 208 题首次观察描述和 78 题 FPS 计划；首次时间段均不变。
58 题首次视觉输入/输出相同，但 Video 报告改变，得分 1 胜 4 负；全部 25 个失分中 23 个没有 C 组 length。
主要风险是报告把问题中的假设写成视觉事实，不能主要归咎于截断。

- 35B NC360：相同四次视觉输出，“可能涉及背叛”被总结为“围绕 FBI 背叛”，Global 错误加深。
- 9B TR1476：相同三次视觉输出，报告新增未观察到的“中后段/高潮”排序，后续联合观看走偏。
- 35B CC250：询问颜色变为询问材料类别，不确定透明液体被称为白色糊状物，错误匹配选项。
- 35B PEA784：原本正确也是证据不足时猜中，改后猜错；不能把每个翻转都解释为理解能力下降。

## 评分口径与格式收益

MVU 官方规则是 `str(output).strip().upper()[:1] == ground_truth`。
`B. explanation` 可以得分；`The answer is B` 首字符为 T，不能得分。
不应笼统声称所有“格式不规范”一律零分，也不应为放大增益临时换弱基线。

同 500 题面板（task 分层估计）：

| 模型 | E2E 原位置官方 | E2E 指令移后官方 | E2E 指令移后稳健提取 | Agent 官方/稳健 |
|---|---:|---:|---:|---:|
| 9B | 16.98 | 34.79 | 47.00 | 53.02 |
| 27B | 47.80 | 43.21 | 53.00 | 59.62 |
| 35B-A3B | 26.40 | 38.40 | 51.62 | 56.82 |

Agent 相对稳健提取仍为 +6.01/+6.61/+5.20 pp，95% 区间分别 [0.80,11.59]/[2.02,11.42]/[0.59,10.00]。
因此已测 MVU 收益不只来自格式，但这不证明其他所有任务都有内容收益。
原位置也并非统一更弱：27B 原位置官方 E2E 分数更高。论文主表固定官方规则，同时报告稳健提取与格式率。
不得只替换 E2E 的规则，或从 Agent reason 提取答案给一方补分。

## 来源与恢复

原始数据原则上留在 Modal `wxu-evolve-agent-runs-20261006`；路径均相对此 Volume。
本次只删除 Git 工作树里的过时脚本/重复报告，不删除远端运行、数据、权重或历史 Git 提交。

| 实验 | 来源 |
|---|---|
| 早期数值、reason、采样、独立回答器与 PRO 对齐 | [清理前完整报告](https://github.com/Wal-K-aWay/MVAgent/tree/d565790/outputs)，其中 `validation_history.md` 汇总更早报告 |
| 早期固定 Prompt B0/D/S | [旧分析入口与协议索引](https://github.com/Wal-K-aWay/MVAgent/blob/d565790/scripts/analysis/README.md)；3600 条轨迹的旧驱动已退役，不作为当前配置 |
| 固定数值/正式接入 | `devbox/repro_expanded_session_20261012_r2/stress/35B-A3B`、`devbox/repro_expanded_session_20261012_r3/`；面板 `devbox/repro_expanded_panel_20261012_r2`，正式接入子路径见旧验收报告 |
| 直接回答节点对照 | `devbox/answer_ablation_20261015` |
| History 前置/独立兜底 | `devbox/terminal_answer_smoke_20261016_r2`，代码 `aad5fad` |
| 原长 System 4500 条 | `devbox/direct_answer_large_20261016`、`devbox/direct_answer_large_recovery_20261017`、`devbox/direct_answer_large_diagnostics_20261017`；代码 `1b711bf` |
| 简洁 System 4500 条 | `devbox/global_short_large_20261017`，代码 `e0ace27`；源码包 SHA256 `0ba98684eea2c2c666cc5f235d8bd7da1ff9cf11465f1ad29b66e76c325130db` |
| 简洁 System 原始分片归档 | `devbox/video_context_storage_20261018/global_short_shard{0,1}_{model}.tar` 及逐包 SHA 清单；原路径需先恢复归档，不能误判为数据丢失 |
| Video 背景对照与轨迹诊断 | `devbox/video_context_20261018`；实验源码 `bcf3da8`、诊断 `0b35401`、汇总 `9641990` |
| 官方/稳健评分敏感性 | `devbox/global_short_scoring_20261018/{summary.json,mvu_paired.json,analysis_source.py}`；没有新推理/Judge |
| 最新详细报告的历史版本 | [简洁 System](https://github.com/Wal-K-aWay/MVAgent/blob/9641990/outputs/global_short_large_20261017/README.md)、[Video 实验](https://github.com/Wal-K-aWay/MVAgent/blob/9641990/outputs/video_context_20261018/README.md) |
| 三模型最终 E2E 原始回答/评分/Judge | [公开 Release](https://github.com/Wal-K-aWay/MVAgent/releases/tag/qwen35-e2e-results-20261017)，不是 Git 文件；本地授权副本在 `outputs/e2e/` |

2026-10-18 本次之前另有用户授权的 Volume 清理：7 类退役实验、26 根目录、34,002 文件、
2,365,413,255 字节已删；涉及 TP8/cache、预算/顺序/惩罚、终答兜底及 PRO9 回滚实验。
它们的原始文件不能承诺仍可恢复，方法与负结果保留在本表及历史 Git 文档；当前接受配置的归档不在该删除范围。

## 本次代码清理与验证

清理范围：63 个旧数值/协议/Prompt实验脚本，34份分散历史报告和旧快照说明；保留正式
`eval/e2e_eval/run.py`、`eval/agent_eval/run.py`、数据准备、当前契约测试、Skill进化与其他方法代码。
历史完整驱动仍可从上述Git提交取回；不要在当前分支重新引入已退役配置开关。

当前 `src/mvagent/`、`src/models/`、`configs/inference/` 的68个Python/YAML文件与已测`e0ace27`逐字节一致。
独立Modal CPU任务 `ap-mfFvzR5pfBvZXwodudWK8V` 已完成：完整compileall、27项unittest、
E2E分片/合并自检、demo/E2E/Agent/Skill进化四个CLI help均通过（rc=0）。
独立token审计自检在 `ap-MewGiQnsH7P8DhjPI8pFdW` 通过，覆盖完整ID/哈希和缺失、截断、非法token拒绝。
短视频测试实际生成5帧视频，经FFmpeg处理和vLLM视频解码后由1个采样帧变为至少2帧，重复文件哈希一致；
正常90帧完整视频继续直接复用。没有启动GPU、Actor或Judge；模型调用路径与已验收源码相同，复用原有GPU实测。
删除模块的Python导入与文档引用已检查，`git diff --check`通过；本地环境Skill链接可解析但不入Git。

共享根工作区和其他worktree未切换/覆盖；本分支是清理后的独立恢复入口，历史运行继续自己的冻结源码。

## 微调候选与筛选原则

目标拆成三项：输出交付合格、同输入可重复、跨题/模型的准确率收益。已有数值配置只解决第二项，不能替代另外两项。
当前保留原 VideoAgent，不把完整原题或答案选项重新注入每轮报告。
以下两条 System 候选已完成首轮小测，结果见文末；均未纳入正式配置。第 3 条为后续筛选原则。

1. **报告忠实性的一条 System 规则。** 候选：`Keep observations, inferences, and unknowns distinct; preserve uncertainty when summarizing evidence.`
   只加到 Video 报告所用 System，不加题目、示例、选项或额外调用。检查源观察中的“可能/未知”是否在报告中被变成肯定结论。
   是否有净收益须实测；不把负实验的机制分析直接当作有效修复。
2. **独立的简洁 Global 解释要求。** 候选：`Keep explanations brief and focus on evidence that changes the next decision.`
   不叠加多条冲突策略，不更改 User、schema、reason 顺序或 2048 预算。观察 length、重复段、完整答案与准确率；不能只用输出更短判胜。
3. **按同题、小步筛选，再用未参与调参的题确认。** 开发筛选优先覆盖三模型九格和已见失败类型，并保留正常题作保护组。
   复用固定 baseline，不重跑无关一致性矩阵；只新跑一个候选，初步有收益再扩展。抽样 seed=0，已有面板保持原 manifest。
   官方分、稳健提取、格式错误/空答、length、异常与耗时一起报告；CrossVid 用十任务 macro，CCQA 用相同 Judge 与评分点规则。
   预先约定可接受的退步界限，配对区间不能排除明显退步时不替换基线；“样本中九格为正”不等于保证未来九格为正。

优先级低：扩大 token、非零采样、恢复独立回答器、多条通用策略一起加入 System。这些已有负结果或混合结果。
更复杂的取证策略留给 Skill 自进化；基础 Prompt 只维护角色、证据边界和清晰交付。

## 外部研究线索（历史核查）

以下为2026-10-10已归档的来源记录，本次整理未重新核对这些项目的最新状态。

以下是官方脚本实际指定的设置，不代表这些团队承诺任意batch、rank或机器间逐token相同：

| 团队或基准 | 源码中的设置 | 本项目应借鉴或补齐的部分 |
|---|---|---|
| OpenGVLab InternVL / MVBench | 每卡固定数据分片；强制batch=1；temperature=0、num_beams=1；默认16帧 | 固定分片和逐题推理便于控制调度；仍要做重启、冷/热缓存验收。[源码](https://github.com/OpenGVLab/InternVL/blob/2410d1dbf208f0e799459aff9376e5747dbf41a2/internvl_chat/eval/mvbench/evaluate_mvbench.py) |
| CVBench / lmms-eval | 启动示例batch=1；任务温度0；Qwen adapter关闭采样并硬编码max_new_tokens=128（task YAML虽写16，实际调用以adapter为准） | 核对最终generate调用，不能只抄YAML；短答案检查不能覆盖长rollout。[启动说明](https://github.com/Hokhim2/CVBench/blob/f8dc8f752fb8e7a3a05ac90e9ff9b3a9e90d79ed/README.md)、[adapter](https://github.com/Hokhim2/CVBench/blob/f8dc8f752fb8e7a3a05ac90e9ff9b3a9e90d79ed/lmms-eval/lmms_eval/models/qwen2_5_vl.py) |
| CrossVid（以BU为例） | 共128帧、最长边360；temperature=0、top_p=0.95、max_tokens=8192；20个客户端进程 | 贪心解码没有锁定服务器实际batch/TP；本项目每副本C1是额外约束。[源码](https://github.com/chuntianli666/CrossVid/blob/b53ada63551f9ac4a726b381b627d17ece066281/eval/BU.py) |
| NJU-LINK MVU-Eval | 每视频均匀抽32帧、最长边720；逐题API请求；定义了--temp但调用未传temperature或seed | 不能依赖后端默认参数；本项目已显式设温度0等生成参数。[源码](https://github.com/NJU-LINK/MVU-Eval/blob/a5937adea78e9649af53cd9a4e30a91ed7fd3df2/inference/main.py) |
| Qwen / Qwen3-VL VideoMME | 离线vLLM `LLM.generate`批处理；seed=3407；Instruct示例temperature=0.7、top_p=0.8、top_k=20；2fps、最多512帧，传视频metadata | 这是带采样的评测协议，不是本项目逐token验收配方；冻结帧、时间戳、预处理与prompt的做法可以复用。[推理代码](https://github.com/QwenLM/Qwen3-VL/blob/96588727e44c78b25ba03ea03b8e12f7e64fd0da/evaluation/VideoMME/run_videomme.py)、[启动参数](https://github.com/QwenLM/Qwen3-VL/blob/96588727e44c78b25ba03ea03b8e12f7e64fd0da/evaluation/VideoMME/infer_instruct.sh) |

vLLM 0.19.1官方说明默认不保证重复一致：离线可关闭V1多进程来固定调度，或使用batch-invariant内核；
在线的官方确定性路径是batch invariance，且限相同硬件与版本。该版本验证模型名单没有Qwen3.5，
不能因为开关被接受就认为视觉、GDN和MoE全路径均已覆盖。
[版本固定的可复现性说明](https://docs.vllm.ai/en/v0.19.1/usage/reproducibility/)、
[batch invariance范围](https://docs.vllm.ai/en/v0.19.1/features/batch_invariance/)。

Thinking Machines的研究将固定浮点规约顺序、batch形状和attention分块作为确定性条件，
在其Qwen3文本测试中将1000次生成从80种结果变为完全相同；这不是Qwen3.5视频的直接验证。
[研究原文](https://thinkingmachines.ai/blog/defeating-nondeterminism-in-llm-inference/)。
SkyRL的IsoExec也在8×H100上研究了Qwen3.5-35B-A3B的GDN及并行规约，但属于训练/推理对齐研究，
报告的端到端logprob误差小于1e-6并不等于本项目视频输出的逐token保证。
[研究原文](https://github.com/vllm-project/vllm-project.github.io/blob/main/_posts/2026-08-21-isoexec.md)。

截至2026-10-10，Qwen GDN修复[PR49827](https://github.com/vllm-project/vllm/pull/49827)仍未合并，
声明的在线验证是H100/0.8B/TP1、无量化、prefix关闭；TP/EP、量化和prefix不在其验证范围。
后续[PR60033](https://github.com/vllm-project/vllm/pull/60033)仍为Draft，明确尚未完成该提交的完整服务验证。
这些是针对GDN数值路径的研究线索，不是当前0.19.1反例的根因证明，也不是三个视频模型已可直接使用的修复。

本项目按上述固定评测配置验收，固定权重、镜像、硬件、媒体字节、processor/tokenizer、prompt、
生成参数和调度配置；比较完整 token、输入哈希与 Agent 轨迹，并覆盖重启与换卡。
上述外部研究记录核对于2026-10-10，仅作为方法来源；本项目实测以本文件固定配置记录为准。

## 两项 System 微调小测（2026-10-18，已完成）

**结论：保留当前固定基线，两条候选都不统一采用。** Video 证据保真规则收益零散且截断增多；
Global 简洁解释规则在 27B、35B 部分任务有收益，但 9B 三个 benchmark 均下降。
没有发现同输入数值重复性退化，Prompt 改动本身改变了观察、总结或决策路径。

### 改动与对照

以冻结 `f61946f` 为基线，V 与 G 分别独立添加一句 System，不叠加：

- **V（Video 证据保真）**：`Keep observations, inferences, and unknowns distinct; preserve uncertainty when summarizing evidence.`
  加到 Video Planner System；步数耗尽时 Video 总结原来 System 为空，现在仅使用同一句。
  正常 finish 与 Planner 决策共用 System，因此也可能改变下一次观察，不能视作纯粹的报告润色。
- **G（Global 简洁解释）**：`Keep explanations brief and focus on evidence that changes the next decision.`
  只加到 Global System，主动与强制终答沿用；Video 不变。
- 两组 User、视觉 Observer、schema、History、FFmpeg、步数与输出预算不变。使用固定 BF16、
  8×H100、每卡 TP1/DP1/C1、seed=0、temperature=0、prefix/MM processor cache 关闭与整题固定副本。
  逐卡检查实际权重、profile 与服务身份。同模型两组共用服务，顺序跨模型轮换。
- 每模型每组 50 题：CVBench 15、MVU 15、CrossVid 20（十任务各 2 题，含 2 CCQA）。
  **300 条新轨迹全部有效，复用 150 条同题基线。** 来自此前 102 题开发面板，按 task/总体数量权重、seed=0 抽取，未按得分筛题。
  CV 每 task 仅 1 题，本批不能提供可靠的总体置信区间。
- CCQA 使用相同 Qwen3-30B-A3B-Instruct-2507 Judge、评分点规则与按完整评分 Prompt 的缓存。
  两候选共享同模型缓存并预填旧同题缓存；12 个新答案均未命中旧缓存，全部完成新评分、无失败。
  不能把共享缓存机制写成实际命中，也不能据此保证不同答案的 Judge 判定绝对稳定。

### 同题官方分

单位 %；括号为相对**当前固定 MVAgent 基线**的百分点变化，不是相对 E2E。
CV/MVU 按 task 总体数量加权估计官方分；CrossVid 为完整十任务 macro，CCQA 按评分点计分。
本批官方与稳健答案提取两种口径的分数完全一致。

| 模型 | Benchmark | 基线 | V：Video 保真 | G：Global 简洁 |
|---|---|---:|---:|---:|
| 9B | CVBench | 80.90 | 75.80（−5.10） | 75.80（−5.10） |
| 9B | MVU-Eval | 60.48 | 60.48（0） | 46.58（−13.90） |
| 9B | CrossVid | 35.99 | 40.99（+5.00） | 30.12（−5.87） |
| 27B | CVBench | 75.80 | 80.90（+5.10） | 85.10（+9.30） |
| 27B | MVU-Eval | 61.10 | 61.10（0） | 61.10（0） |
| 27B | CrossVid | 44.07 | 44.33（+0.26） | 50.94（+6.87） |
| 35B-A3B | CVBench | 70.60 | 67.30（−3.30） | 80.00（+9.40） |
| 35B-A3B | MVU-Eval | 48.06 | 48.06（0） | 48.06（0） |
| 35B-A3B | CrossVid | 49.06 | 45.44（−3.61） | 49.35（+0.29） |

V 为 3 正 / 3 平 / 3 负，G 为 4 正 / 2 平 / 3 负。
单题翻转足以改变小批分数，不能据此选择模型专属的正式默认规则。

### 交付、截断与成本

每组各 150 条轨迹，闭式答案格式统计各 144 条；格式错误与中间结构错误分别计数。

| 指标 | 基线 | V | G |
|---|---:|---:|---:|
| 最终闭式格式错误 | 1/144 | 1/144 | 0/144 |
| 最终空答案 / 单独右花括号 | 0 / 0 | 0 / 0 | 0 / 0 |
| 服务 / 模型调用错误 | 0 | 0 | 0 |
| 模型调用数 | 1,845 | 1,860 | 1,892 |
| 达输出 token 上限的调用数（length） | 4 | 10 | 6 |
| 出现 length 的题目数 | 3 | 8 | 6 |
| 结构无效调用数（structured_invalid） | 4 | 11 | 6 |
| 修复请求数 | 3 | 9 | 6 |
| 输出 token 总数 | 249,351 | 261,337 | 242,789 |
| 逐题耗时总和 / 秒 | 11,843.89 | 11,292.71 | 10,412.82 |

新实验 3,752 次模型调用无服务故障，但有 16 次 Global 决策达到 2048 token 上限，长 reason 后 JSON 未完整闭合。
另有 V/9B/CC317 的 Video 参数把结束时间写为 133 秒，超过视频时长 132.97 秒；既有校验拒绝后重试成功。
这些是模型生成或参数边界问题；既有恢复流程最终交付了全部答案，但不能声称每次无效输出都在第一次修复中成功。
V 输出 token 比基线多 4.81%，G 少 2.63%；G 最终理由总体变短仍未减少中间截断。
耗时未控制物理 H100、缓存冷热和先后顺序，以上仅描述实测，不作为因果提速结论。

复用既有 token 日志的离线审计完成 **782 次相同请求比较，完整输出 token、文本与结束原因 0 差异**；
其中 V 与基线的首轮 Global 共 150 对全部相同，已包含在 782 次中。新轨迹 token 完整、cache=0、sticky 校验通过。
没有额外进行双遍全矩阵推理；有限共享请求通过不等于任意输入的绝对保证。

### 具体轨迹说明

- **CVBench 774**：9B 基线 A 正确，V 改 C、G 改 B，均错；27B 基线 C 错，两候选均改 A 正确。
  同一句规则对不同模型方向相反。9B 旧正确理由也在反复说未找到医疗建议并猜选项，不能断言新规则破坏了原本充分的正确证据。
- **CrossVid PEA784**：9B 原答 `None of the above`，两候选变成选项字母但仍错；这是格式改善而非准确率改善。
  27B 的 V 反而从选项变成“没有选项得到证据支持”的长答案，新增格式错误，原、新评分均为 0。
  保留不确定性的通用要求可能影响最终按题交付，不能只凭措辞合理就认定有效。
- **35B-A3B/FSA1175**：基线区间 `22,37`，IoU 为 0.5556；V 改成 `0,10`，IoU 为 0。
  **35B-A3B/CCQA188** 的 V 将原先切片面包描述改为面团整形烘烤，Judge 从 1/6 降至 0。
  本次未人工重看原视频，不把这一 Judge 判定直接写成已核实幻觉。

后续维持“简洁 Global + 原 Video”统一基线。若继续 Prompt 研究，应先在这些已知失分轨迹中区分
取证改变、证据总结改变与证据不足时猜选项，再用未参与本轮调参的题确认候选。
本轮不继续放宽预算、不新增格式枚举或二次回答器，也不把不同模型的小样本收益拼成统一成功结论。

### 完成记录与恢复

实验代码位于独立分支 `codex/system-refinements-20261018`，入口 `scripts/system_refinements.py`，
实际运行冻结提交 `65829c9e545fb6824bc6b673ff26dc910b80ef2e`。
候选只在新运行目录生成不可变源码；正式分支 `codex/frozen-framework-20261018` 只同步本报告，
不引入候选 Prompt 或实验开关。共享根工作区及其他任务未切换或覆盖。

原始结果仅在 `wxu-evolve-agent-runs-20261006` 的 `devbox/system_refinements_20261018/`：

- `manifest.json`、`source.tar.gz`、`samples.json`、`baseline.json`、`baseline_services.json`；
  源码包 SHA256：`2b0f0454de5281ec693b88839804aa6cfc4eabbbf38bd6d9f615961eb20d9b9b`。
- 两候选各自的源码、`system.patch`、逐题 records、12 条 CCQA 评分与原始 Judge 响应。
- `services/<model>/startup_identity.json`、`startup_audit.json`；
  `analysis/summary.json`（`complete=true`）、三个 `<model>_paired.json`、`output_audit.json`、`output_audit.py`、`early_failures.json`。
- 基线配对来自 `devbox/global_short_large_20261017/analysis/`；所选原始先导轨迹来自
  `devbox/system_ablation_20261017/global_short/`，原始数据未改写。

远端 compileall、两候选各 13 项决策接口检查通过；prepare 与基线评分/token/sticky/cache 契约检查通过。
最终 CPU 审计 `ap-jX08sfLSg1abv21KWfnj3B` 返回 0。首次 prepare 因 CPU 镜像无 git CLI 退出，
0 模型调用；修复后重建，初始失败记录保留在 `devbox/system_refinements_20261018_prepare_initial`。

05:43 UTC 申请、06:00 容器就绪，06:59 完成 300 条 Actor 轨迹；07:03:49 Judge 后释放本任务 GPU，
07:04:22 完成最终分析。Sandbox `sb-EnHLS7BUGVf7Pebo8FgzAL` 已退出，host PID3527878 已退出、state 已清理；
只释放本任务的 Sandbox，没有停止共享 Modal app。15 分钟独立巡检已结束，本轮无遗留推理任务。

## Global 判定标准传递小测（2026-10-18，已完成）

**结论：保留原固定方案，不把本候选加入统一默认。** 相对当前 MVAgent 基线，九格为 5 正 / 4 负：
CVBench 三模型均提升，MVU 的 9B/27B 提升、35B 下降，CrossVid 三模型均下降。
本批没有服务故障或最终空答案；性能收益不统一，不能概括为后端输出不确定。

### 唯一改动与样本

Global System 末尾只追加以下一句，分别作用于普通决策和既有 answer-only 终止决策：

> When delegating, preserve the question's definitions, qualifiers, and decision criteria relevant to that video's requested observations.

User、VideoAgent、schema、History、空 skill 库、FFmpeg、步数和输出预算不变；不自动透传完整原题，
不增加工具或回答器。沿用 BF16、8×H100、每卡 TP1/DP1/C1、seed=0、temperature=0、thinking 关闭、
FlashInfer GDN/原生 GemmaRMSNorm、prefix/MM processor cache 关闭和整题固定副本。
新增 System 虽针对分派任务，也可能影响整体动作选择与终答，不能声称只改变 instruction 措辞。

三模型使用相同 90 道题，每个 benchmark 30 道，**270 条新轨迹全部有效，复用 270 条同题基线**。
从此前 1500 题面板中排除前几轮 System/Video 筛选的 102 题；seed=0，按 task 分层、不按成绩选择。
CV 每 task 2 题；MVU 每 task 至少 2 题，剩余按总体数量分配；CrossVid 十任务各 3 题，含 3 CCQA。
这些仍是开发数据，不是独立 Test。小分层不能支撑可靠的总体置信区间或普遍无损承诺。
基线来自已有简洁 Global 结果；所需原始文件从归档提取到本次目录并逐文件校验 SHA256，原件不改写。

### 完整同题分数

单位 %；差值为百分点。CV/MVU 按 task 总体数量加权，CrossVid 为完整十任务 macro、CCQA 按评分点加权。
9 个新 CCQA 答案均成功评分，使用相同 Qwen3-30B-A3B-Instruct-2507 Judge；已预填同题基线缓存，
本次实际缓存命中为 0。下表官方与稳健答案提取两种口径的分数完全一致。

| 模型 | Benchmark | 固定 MVAgent 基线 | 判定标准传递 | 差值 / pp |
|---|---|---:|---:|---:|
| 9B | CVBench | 48.35 | 68.40 | +20.05 |
| 9B | MVU-Eval | 52.89 | 61.43 | +8.53 |
| 9B | CrossVid | 35.30 | 23.41 | −11.88 |
| 27B | CVBench | 66.85 | 74.30 | +7.45 |
| 27B | MVU-Eval | 60.14 | 64.07 | +3.93 |
| 27B | CrossVid | 54.25 | 50.53 | −3.72 |
| 35B-A3B | CVBench | 59.00 | 66.10 | +7.10 |
| 35B-A3B | MVU-Eval | 66.79 | 53.33 | −13.46 |
| 35B-A3B | CrossVid | 38.75 | 35.71 | −3.03 |

为对齐最终的 E2E 对比目标，另外复用**这同一批题**的既有 E2E 官方评分；MVU 沿用指令移后口径，未新跑 E2E：

| 模型 | 同题 E2E：CV / MVU / Cross | 候选相对 E2E：CV / MVU / Cross（pp） |
|---|---|---|
| 9B | 56.55 / 23.71 / 40.00 | +11.85 / +37.71 / −16.59 |
| 27B | 70.95 / 44.06 / 41.75 | +3.35 / +20.01 / +8.79 |
| 35B-A3B | 57.30 / 35.66 / 45.00 | +8.80 / +17.67 / −9.29 |

候选相对 E2E 为 7 正 / 2 负，仍未达到九格全正。原固定方案在这个小面板上也只有 5 正 / 4 负，
与前述 4500 条面板九格点估计全正不同；这是不同抽样面板，不能混用分数或据此改写大面板结论。
本批支持 CVBench 上进一步验证该候选，尚不支持跨 benchmark 的统一替换。

### 输出交付与成本

各组 270 条轨迹、261 条闭式答案；最终格式错误与中间 JSON 结构失败分开统计。

| 指标 | 固定基线 | 候选 |
|---|---:|---:|
| 最终闭式格式错误 | 5/261 | 4/261 |
| 最终空答案 / 单独右花括号 | 0 / 0 | 0 / 0 |
| 服务 / 模型调用错误 | 0 | 0 |
| 模型调用数 | 3,169 | 3,212 |
| 达输出 token 上限的调用数 | 19 | 21 |
| 发生截断的轨迹数 | 18 | 18 |
| 结构无效调用数 | 19 | 21 |
| 修复请求数 | 18 | 19 |
| 输出 token 总数 | 452,407 | 464,527 |
| 逐题耗时总和 / 秒 | 22,987.94 | 24,987.99 |

格式错误净少 1 条，实际是**修好 3 条、保留 2 条、新增 2 条**，没有单调改善：
9B KIR187 从拒选改为 B 但仍错，同时 KIR350 从 B 改为“没有选项符合”的长回答，新增格式错误；
35B 的 CV532、CC202 从拒答改为正确选项，但 BU560 新增 `None`。27B BU560 和 35B FSA235 的格式问题仍在。
三模型格式错误分别 1→1、1→1、3→2；截断分别 9→7、2→6、8→8。
所有结构无效事件都在 Global 决策中；最终均交付了非空答案，不意味着每次中间输出都成功。
候选输出 token 增加约 2.68%，没有证明更高效率；耗时受不同物理 GPU、缓存与时序影响，只作实测描述。

离线审计核对 **270 条首轮 Global 请求**：去掉新增句子后，整个消息列表与同题基线完全一致。
新输出共 3,212 次调用；**298 次自然重复请求比较，完整 token、文本、结束原因 0 差异，输入 token 哈希 0 差异**。
三模型分别 125/95/78 次比较；没有额外重跑双遍矩阵。有限日志比较不构成任意输入的确定性保证。

### 实际轨迹及解释边界

- **CVBench 140：判定侧重点也改变。** 9B A 错→B 对，35B 同向，27B 则 B 对→A 错。
  旧 9B 报告本来就包含手冲和速溶的信息，Global 却选择“艺术性/实用性”；候选更明确询问手工/速溶，
  最终理由优先采用事实上的制作方式差异。收益不能只解释为补回遗失信息，也不能用一个模型代表其他模型。
- **27B/PSS65：格式正常仍然退步。** 原答案 `2->4->5->1->3` 正确，新答案 `1->2->4->5->3` 错。
  原轨迹完成两次联合观察，新轨迹在一次联合观察后结合已有装盘报告终答；调用 21→19、token 4104→3267，
  两边均无截断、结构错误或服务错误。更少调用没有保证正确排序。27B 的 PSS343/65/79 三题原全对、新全错。
  不能把未在一次联合调用中覆盖全部五段本身视为根因：新轨迹已从单视频报告中知道 segment_3 是装盘，错误在其余片段排序。
- **9B/NC450：观察报告与后续判断均变化。** 旧 Video 2 报告认为有父子牺牲情节，新报告称未观察到；
  Global 随后在证据冲突中从正确 A 改为 D。未人工重看原视频，不能直接认定哪份视觉报告忠实。
- **9B/ICL710：正确标签不等于可靠推理。** 旧 C 答案虽对，但理由用单人跳水推测数值约 3.3，再选最接近选项；
  新 D 答案错，理由仍在计划继续取证却提交了 answer。这个翻转不能全部归因为破坏了原本充分的正确证据。

本轮没有测试另两个提案（未报告不等于不存在、修复调用保留原 System），没有加入 benchmark 专用规则、
修改答案合法值枚举、放宽输出预算或改数值后端。后续若研究本候选，应保留跨模型和 CrossVid 回归保护，
在未参与设计的数据上确认收益；不通过去掉退步题或换评分口径获得九格全正。

### 源码、数据与完成记录

- 正式分支 `codex/frozen-framework-20261018` 运行时不变，只同步本报告。
  实验分支 `codex/criteria-transfer-20261018` 的入口为 `scripts/criteria_transfer.py`；
  实际 Actor 冻结提交 `d147e02a9c4cab6eada9bc368ed2a809d86a39e1`，候选源码与精确 patch 单独保存。
- 结果仅在 runs volume `wxu-evolve-agent-runs-20261006` 的 `devbox/criteria_transfer_20261018/`：
  `manifest.json`、`samples.json`、`source.tar.gz`、`baseline.json`、`baseline_restore.json`、
  `baseline_files/`、`baseline_services.json`、`services/<model>/startup_identity.json`、
  `criteria_transfer/<model>/records/` 及 `score/ccqa_scores_official_qwen3_30b_a3b.json`。
- 最终汇总为 `analysis/summary.json`（complete=true）与三个 `<model>_paired.json`；
  `output_audit.json`、`diagnostics.json` 及同名 Python 源码保存输入/token、E2E 参考和格式诊断。
  其他 `*_closed_interim.json` 不含 CCQA，只是中间结果；案例在 `early_9b_cases.json`、
  `9B_selected_trajectories.json`、`27B_pss65_case.json`，原始轨迹不改写。
- 源码包 SHA256：`994743d35a46b95a375755252171487fea71338e460dabbecb4410d69d9dd82d`；
  抽样清单 SHA256：`5e2458e728a37b1c523c9fb039e8736e420b035e8c1b1c4fbeb753771f345aae`；
  被动审计源码 SHA256：`cbc160170de18f7719968b0cc2ed0bac0d644197a1c0b5502f0a79c947e700ff`。
- 远端 compileall、System-only/抽样自检、13 项决策接口测试、所选归档文件 SHA 和 token/cache/sticky 核验通过；
  首批真实 9 轨迹/123 调用审计通过，最终全量日志审计和诊断 CPU 任务返回 0。
- 07:48:41 UTC 创建唯一 Sandbox，08:53:49 完成 270 条 Actor 轨迹，08:57:49 完成 9 个 CCQA 评分；
  **08:57:59 释放 GPU，08:58:22 完成最终分析**。
  Sandbox `sb-Bn53Xcl4T8xMXXVCcKwInJ` 已以 0 退出，host PID3579522 已退出、state 已清理。
  独立 15 分钟巡检已停止；没有停止共享 app 或影响其他任务，本轮无遗留推理作业。

## 冻结版本完整补测（2026-10-18，后台运行中）

用户授权沿用已验收实现补齐完整范围。基线运行时仍为 `e0ace27` 对应的简洁 Global System＋原 VideoAgent；
`src/`、推理 YAML、Agent 调用与评分入口不改。新增 `scripts/run_full_mvagent.py` 只负责复用、缺题分片、服务生命周期和结果汇总。

- 每模型 CVBench 997 可测题（64–66 媒体损坏另列）、MVU-Eval 1824、原 CrossVid Lite2500；共 5321 题。
- 三模型各复用 1500 条，合 4500；每模型只补 3821，合 11463；最终目标 15963。
- 复用不看答案或得分；逐文件验证归档大小/SHA、完整 token、cache=0 和整题固定 worker，保留原始评分及来源。
- 剩余题按 seed=0 固定打乱、分成 1911/1910 两组，每组依次运行 9B、27B、35B-A3B；两组各 8×H100，均 TP1/DP1/C1。
- 固定 BF16、seed/temperature=0、FlashInfer GDN、原生 GemmaRMSNorm、prefix/MM cache 关闭；每次加载逐卡核对 profile/权重/8 个独立 worker。
- 复用原 `eval/agent_eval/run.py` 和 `--resume`；23 小时续接新 Sandbox，非预期退出最多恢复两次，明确运行错误停止并保留证据，不无限重试。
- 原始记录先落盘，新增 CCQA 用原 Qwen3-30B-A3B-Instruct-2507 Judge；旧分不重新 Judge。两组完成自动释放 GPU，再 CPU 汇总。
- 结果仅 runs volume：`devbox/frozen_full_20261018`。每组 `shard{0,1}/progress.json`、`<model>/records/` 和 `score/`；最终 `analysis/summary.json` 与三模型逐题配对表。
- 完整表与新增题子集分别报告；CV/MVU 按题平均，CrossVid 十任务 macro/CCQA 按评分点加权。E2E 对照沿用 MVU 官方指令移后版本。
- 这是完整可测范围，包含已使用的开发题，不称为独立 Test。工程失败、未完成及 Judge 失败单列，不当零分或正常负结果重跑。

13:53 UTC，Modal CPU `ap-Cox9ZIa7iv6Kivlocy8aXj` 返回0：分片/评分自检、完整 compileall、相关推理/配置/评分文件与已验收源码的逐文件核对、4500条原始记录 SHA/token/cache/sticky 审计全部通过。源码冻结 `677444b`；源码包 SHA256 `755acec352c176443cd298f1ff9f7104ef6d3fce1ff58f61f0d9d7325f1d714e`，selection SHA256 `7d44fda30efdf5fc310e985e7a4bd05cf1fe05a7e8dc63c56d93393bb400996d`。准备完成时 runs 余55908目录项；不展开旧轨迹，新增记录预计约23000项。两组唯一后台控制器已提交，首批实际推理尚待确认。按旧批平均题时及30%余量，预计约23小时（含加载/评分余量），实际依新批吞吐和平台排队更新。

后台主控制器 PID `3683732`，日志 `~/wxu-evolve-agent/devbox/watch-frozen_full_20261018.log`；
分片0/1分别拥有 `sb-6mL4G9D1gNw9XRkeBqllpT` / `sb-NAuJ2rA0X1k5J5YfmPRrOU`。
13:57 UTC分片1在8张实际H100上加载9B，分片0等待执行，未重复申请。
按剩余CV497/MVU1324/Cross2000分别加权历史题时：16卡理想17.60小时，加30%余量及加载/评分约23.88小时。
这是运行前估计，不包含异常平台排队；后台控制器支持跨23小时边界继续同一冻结输入。

14:04 UTC两分片均已进入真实9B推理；每组8张H10080GB、8个单卡服务，实际profile/权重与旧批逐卡相同，prefix关闭。
启动审计仅读取生产轨迹，不额外推理：分片1首16题/208调用覆盖8个worker；分片0首1题/8调用，
均status=ok，完整token/hash/cache0/sticky检查通过，模型错误、结构错误和length均0，实际Global源码SHA匹配。
例如 `cvbench:483 -> A`、`mvu_eval:OR:1177 -> C`、`crossvid:FSA:711 -> 227.0,236.0`；这些是运行证据，不作小样本准确率结论。
证据为各分片 `startup_audit.json` 和根 `startup_audit_source.py`。后续27B/35B仍由相同冻结driver自动切换并逐卡校验。

运行期间以 `shard0/progress.json` 和 `shard1/progress.json` 为准；根progress只记录准备和最终汇总，不实时汇总。
两组主/子控制器继续后台，无需当前会话保持在线。本轮会话内Luna检查结束后不宣称仍有AI定时巡检；
后台控制器仍轮询进度、处理已约定的续接、完成Judge与CPU汇总并释放资源。
代码与本报告在 `codex/frozen-full-20261018`，生产源码冻结始终为677444b；后续文档提交不热更新运行。
目前尚未完成11463条补测和新Judge，也未实际触发23小时续接；完整统计与工程失败须等最终汇总。

### 2026-10-19 中断诊断与恢复

06:24 UTC检查发现原两分片均已停止，未完成补测。分片1的9B在全部1910题落盘后因
`mvu_eval:TR:1416`服务失败退出；原progress最后1909为滞后快照。该题有一段1帧、8 FPS、0.125秒视频，
规划采样FPS高于源FPS，旧补帧公式 `ceil(2 * source_fps / sampling_fps)` 得到1，未真正补足2帧，
Qwen3VLProcessor随后报错并关闭固定副本。这不是模型答案格式错误。

分片0在27B约1044题时，dev box `/home` 写满，host打印进度触发Errno28，finally释放GPU；
并非Modal runs volume满。当前dev box `/home`余约9.3GB、根文件系统`/tmp`余约112GB。
控制日志改放`/tmp/mvagent-frozen-full-recovery-20261019`，不清理其他项目数据。

- 分片0继续原`677444b`冻结源码和结果目录，主host恢复为4127147，仅日志位置变化。
- 分片1在新runs `devbox/frozen_full_recovery_20261019`恢复，原始失败和1909成功结果不改写；仅对status=ok做SHA核验后引用，正常模型负结果也保留。
- 唯一推理实现修复：编码帧数下限取 `max(2, ceil(2 * source_fps / sampling_fps))`，仍采用原FFmpeg重复末帧路径。
  普通片段原公式已≥2时不改变输出；单帧输入会改变，须单独记录，不宣称旧失败输入与修复后完全相同。
- Prompt、模型/精度、数值后端、seed、采样、总token和步数预算不改。新首题将完整重跑TR1416，随后继续27B/35B；成功旧题不重测。
- 新汇总引用原分片0与恢复分片1，补齐未Judge的CCQA，再统计15963条；每份源快照和原失败记录保留。

当前修复已写入隔离工作树，合成/真实单帧CPU回归及恢复GPU首题尚待验证。旧的24小时估计已经失效，恢复后重估。

06:37 UTC恢复CPU检查返回0：新增1帧/8FPS回归通过（此前的5帧/30FPS及普通90帧路径也通过）、
完整compileall与分片/评分自检通过；1909条成功原始结果SHA/token/cache0/sticky核验后以引用继承，
唯一失败TR1416保留在原目录。恢复源码冻结`a0150f7`，源码包SHA256
`7cd134bbe0deed652dda9925ff666c26e59516a4ba3dd6dc44b3ab5b49a7a63f`；selection与baseline SHA仍同原批。
恢复manifest的原始容量/ETA字段明确标为parent历史值，不作为当前余量/耗时证明。
新分片1的唯一控制器已启动；实际失败题的GPU恢复仍待确认。分片0原源码续跑已拿到`sb-eiSumhObPP38RHbSKX6nO4`，正在加载27B。

06:53 UTC实际恢复验证通过：TR1416在新分片1返回`B`、status=ok、52.7秒，10次调用/1365输出token，
模型错误/结构错误/length均0。实际媒体事件为源8FPS、请求16.7FPS、选中1帧并复制末帧1次；
旧失败原件SHA未变，6个修复前后完全相同的请求其完整输出token均一致。
这仅验证本次受影响路径，不是任意输入的重复性证明。证据为新root `analysis/recovery_smoke.json` 和 `recovery_audit.py`。

原分片0也已正常续跑27B：06:52实读1053条结果，最新CV7返回B（85.2秒）、CV814返回A（110.06秒）、
CCQA60正常非空（108.18秒），时间戳均为恢复后。两个8H100的真实服务身份/profile已通过各自driver校验。
因此9B全部5321题推理已齐；27B继续，35B补测与本批CCQA Judge/总汇总尚未完成。
新master PID4132279、shard1 child4132281，旧分片0 host4127147，均后台运行；恢复后估计仍需18–22小时，35B尚未有本批吞吐实测。
本轮Luna只读检查在退出会话时停止；后台控制器继续，不能将此描述为AI仍每15分钟巡检。

已修复并验证的是单帧输入与控制日志存储路径；原始失败保留，未重测已有成功题，未修改Prompt/精度/seed/推理预算。
恢复后新分片1使用a0150f7冻结源，原分片0仍用677444b，元数据明确记录两者，不能声称所有记录来自同一份源码快照。

### 2026-10-19 分片0的不可读裁剪末帧修复

12:35 UTC在CPU复现`crossvid:MOC:552`：27B规划观看view_B的[4,5]秒，实际采样2FPS。
FFmpeg流拷贝输出标称14帧/10FPS，顺序只能解码10帧；vLLM OpenCV均匀取[0,13]，末帧读取失败，
只剩1帧传给Qwen3VLProcessor，服务退出。这与TR1416的原始单帧视频不同，先前编码帧下限修复不覆盖它。

共享`cut_video_segment`现在在返回前按均匀采样位置确认至少2帧可读，读足即停止；不足时沿用FFmpeg
转码路径精确裁剪，必要时复制末帧。正常流拷贝文件不改，Global和Video两个调用方共用修复。
只改变无法组成有效时序输入的片段，不修改Prompt、数值后端、采样规划或预算；修复后像素可能变化，
不能称为原失败输入的逐字节复现。若转码后仍不足，明确报媒体错误，不把异常输入送入模型服务。

12:41 UTC远端CPU检查通过：真实MOC552短片旧路径仅1帧，新路径2帧；同视频[4,8]秒正常片段
与原流拷贝逐字节一致；重复裁剪SHA一致；之前1帧/8FPS、5帧/30FPS补帧及90帧直传回归通过。
分片/评分自检与完整compileall通过。未全量重扫媒体，GPU整题恢复待验证。

恢复源码`5884f4a`位于`codex/frozen-shard0-recovery-20261019`。
新的runs根`devbox/frozen_full_final_20261019`计划继承原分片0全部成功结果，失败原件保留，
仅重跑MOC552再继续35B。分片1继续`frozen_full_recovery_20261019/shard1`原冻结a0150f7，
新汇总根引用该分片；既有master不热改，新master负责两组完成后的最终汇总。

12:48 UTC新root准备完成：3821条成功轨迹逐SHA/token/cache0/sticky核验后继承，
原27B的MOC552失败原件保留，未改写旧输出。源码包SHA256为
`9be4a026452f6f3ea7748ada67ec7dcfdabd820b205e224a7b6062b1579ed773`；selection/baseline仍与原批一致。
12:49 UTC唯一新master PID40568提交，日志位于devbox `/tmp/mvagent-frozen-full-final-20261019/`；
将先验证27B失败整题，然后35B、三模型CCQA Judge，并等待另一分片完成后做总分析。
旧master仍维持其healthy shard1，不作为新的最终汇总owner。

13:02 UTC GPU整题恢复通过：`crossvid:MOC:552`返回`A`、status=ok、73.65秒，9调用/693输出token；
模型错误、structured_invalid、repair和length均0。实际[4,5]秒片段使用`decode_repair_transcode`，
10编码帧/2FPS，未添加额外时间段。旧失败SHA仍为
`6d235dd9b63d0253c47f90d18a073881477fc9bd0affcb24700d7d7637af82e1`，
新结果SHA为`43ef51e261d6d9e3ef9e31cf06dc74f431a36f73b8420c67cb339a6015d2054c`；
修复前后6个完全相同request的完整输出token均一致。证据为新root的`recovery_audit.py`与
`analysis/recovery_smoke.json`。这验证本次故障路径，不构成任意视频或任意输入的绝对保证。

原有成功结果继续复用，后台控制器继续35B、Judge及汇总，尚未得到完整三模型评分。
按当前27B尾段与35B历史同配置题时、错峰启动和长尾估计，13:03 UTC起全部仍约12–15小时；
35B本批尚无稳定吞吐实测。会话末检后停止Luna检查，仅后台控制器继续，不宣称会话外AI巡检。

### 2026-10-19 9B完整推理与E2E同题比较（CCQA待判）

13:15 UTC完成纯CPU分析，无新Actor/Judge调用，不改变在途27B/35B或其冻结源码。
9B5321条均有正常推理结果：CVBench997、MVU1824、CrossVid2500；含1500条复用开发题、3821条补测。
原始回答、compact、逐题对齐表、统计脚本和报告仅保存在runs
`devbox/frozen_full_9b_comparison_raw_20261019/{source.py,compact.json,paired.json,report.json}`。
分析源码SHA256 `cc518a09b45b2bdd660548415cd91a838b989d23c620655950e2e580e5810312`。
原始E2E文本及其文件SHA写在report中；不是以评分文件里已解析的prediction替代原始输出。
首轮中间分析`frozen_full_9b_comparison_20261019`因此标记superseded，禁止引用其格式/稳健/空答统计。

| 同题范围 | 数量 | E2E | 当前MVAgent | 差值(pp) | 未校正配对95%区间(pp) |
|---|---:|---:|---:|---:|---:|
| CVBench | 997 | 62.49 | 64.49 | +2.01 | [-1.30,+5.52] |
| MVU-Eval | 1824 | 37.72 | 50.55 | +12.83 | [+10.20,+15.57] |
| CrossVid九类非CCQA宏平均 | 2261 | 29.65 | 37.00 | +7.35 | [+4.51,+10.05] |

CV/MVU按完整可测题平均，Cross九类等权，不将九类宏平均冒充完整十类总分。
MVU使用官方指令移后的E2E1824题，原位置15.84仅留历史。CV双方统一已有YES/NO选项映射，
使E2E的26/455/464/899四题从0到1，故本次62.49不同于旧发布表62.09；不改原始评分文件。
CV共643 vs623正确（162题改善、142题退步）；MVU922 vs688正确（467改善、233退步）。
区间用seed0、2000次按task分层的逐题配对bootstrap；未按共享视频聚类、未做多重比较或开发集复用校正。

CrossVid239条CCQA中仅旧50条有Judge，新189待自动评分。已有50条按评分点加权Agent24.53、同题E2E55.28。
固定已判分数，待判点的合法得分范围为[0,1]，故完整十类Agent总分数学范围为[33.82,41.70]，
E2E完整总分31.98。下界也比E2E高1.85pp；这是未判部分的数学界，**不是把未判题正式记零，也不是最终完整成绩**。
正式完整score保持null，最终数值仍须等待189条Judge。

| 原始输出指标 | CVBench | MVU-Eval | CrossVid非CCQA |
|---|---:|---:|---:|
| 格式错误 E2E→Agent | 27→5 /997 | 622→25 /1824 | 15→109 /2261 |
| 同规则稳健分 E2E→Agent | 62.19→64.49 | 48.25→50.55 | 29.91→37.00 |

双方所有5321条原始输出均0空答案；Agent0仅右花括号。MVU官方收益12.83pp在稳健提取后只剩2.30pp，
该稳健差的区间[-0.33,+5.04]跨零，不能把全部改善解释为推理能力提升。Cross稳健优势仍7.09pp，
区间[+4.23,+9.77]；其格式反而更差，存在超出格式规范化的得分改善，但不证明各题型普遍提高。
Cross109个格式问题主要在FSA58、BU14、NC14、PEA13；没有新增合法答案枚举或模型输出后修正。

主要变化：Cross步骤排序PSS+21.98pp、行为理解BU+21.55、叙事理解NC+18.86；
情节推断PI−15.00、多视角计数MOC−1.29。MVU Counting+37.00、TR+20.91、Comparison+16.30，RAG−3.24。
这些是任务分项相关性，未做新的因果对照。只看本次补测：CV497题正确数持平（分层估计−0.09pp），
MVU1324题分层官方+10.79/稳健+0.90pp，Cross1811非开放题macro官方+8.02/稳健+7.75pp。
因此CV的全量小幅增益主要来自原500题；不能称新题上已稳定提升。

Agent共73595调用，0模型调用错误，381次structured_invalid、348次repair、382次length；
最终有答案不表示中间从不截断。历史日志平均整题秒：CV Agent46.53/E2E20.96，
MVU57.57/12.25，Cross66.30/25.40；这是不同批次日志，非控制缓存/负载的纯吞吐实验，也非并行墙钟耗时。
独立只读检查确认两GPU分片继续运行并复核CCQA数学界后停止；没有会话外AI巡检。

### 2026-10-19 9B开放题Judge与结果整理

用户要求完成9B开放题Judge后，参考AgentCVR最终包整理结果和轨迹。
新增独立Judge任务`devbox/frozen_9b_results_20261019`，只评新增189条CCQA，旧50条判定及其coverage/correctness原样复用。
使用现有`serve_ccqa_judge.sh`和`score_crossvid_ccqa.py`，Qwen3-30B-A3B-Instruct-2507、原官方Prompt和生成设置不改。
新评分写入两个已完成9B分片的既有score/cache目录，再复制到整理根；后续全量控制器会复用缓存，不重判同一答案。
不重启或热改27B/35B的Actor、配置与源码，不修改9B原始回答。

独立4H100 Judge的owner为devbox PID54961，Sandbox `sb-6ohNFneCYRh9rOGCNGn0pi`，
日志`/tmp/mvagent-9b-results-20261019/controller.log`。13:34 UTC仍排队（execution_ready=false），尚无新增判分。
Judge源码冻结90b7dbe；整理实现f3e4306在`codex/frozen-9b-results-20261019`，未改正式推理入口。
CPU检查通过文本/媒体脱敏自检与脚本语法，并核对旧15+18+17=50条判定所在报告完整、failed_ids为空。

计划交付五个同布局文件：`cvbench.jsonl`、`mvu_eval.jsonl`、`crossvid.jsonl`、`ccqa_scores.jsonl`、`statistics.md`。
前三个每行`id/gt/output/seconds/trajectory`；GT保留原数据类型，CCQA为参考答案及评分点；
output直接取Engine最终answer字段原字符串，保留空白与格式偏差，不做答案纠正。
trajectory保留Engine完整动作轨迹、Global/Video文本输入输出、模型响应、结构解析/修复与媒体区间，
只剔除图片/视频Base64、完整token数组及重复传输调度日志；原始完整记录仍在Modal。
每份原始轨迹在导出时与既有baseline/inheritance SHA对齐，旧归档直接按成员读取。
评分齐全后生成一个压缩包，逐成员验证题号覆盖、字段、字节数和SHA；来源映射与manifest在同一Modal根。
本任务只要求整理格式，未将新增MVAgent原始结果移出Modal或自行公开发布。

13:47:55 UTC Judge完成：新增189条（107+82）全部成功，failed_ids为空；复用旧50条，
完整239条CCQA、757个评分点，按点加权得分19.81506%。原4H100 Judge由owner正常释放，
其Sandbox末检poll=137表示已退出；未重启或修改Actor。以下取代上文待判数学区间：

| 9B完整同题范围 | 题数 | E2E (%) | MVAgent (%) | 差值(pp) |
|---|---:|---:|---:|---:|
| CVBench | 997 | 62.49 | 64.49 | +2.01 |
| MVU-Eval | 1824 | 37.72 | 50.55 | +12.83 |
| CrossVid十类宏平均（含全部CCQA） | 2500 | 31.98 | 35.28 | +3.31 |

E2E输入、CV答案映射、MVU指令移后及开发题复用限制同上，不改变旧发布原文件。
首轮导出因TR1416历史审计字段名应为`new_result_sha256`而停止；当时仅建立空目录，
无结果写入。修复237b952后仅重跑CPU导出与核验，没有重跑Actor或Judge；失败说明保留在
`export_failure.json`。最终导出脚本SHA256为
`e64497ae4b1ea36c240baaff43ec9560a1c56f309775cb5be704ed436e5f9b46`。

13:56:24 UTC五文件核验完成，13:56:26记录`PACKAGE_VERIFIED`，CPU owner62744成功退出。
已核对5321条来源原件SHA、题号覆盖、唯一性、字段、各文件字节数/SHA及压缩包成员；
`manifest.json`保留逐题来源、Judge与导出源码身份，`verified.json`记录完成证据。
独立检查者复核完成标记、239条Judge、总分及归档摘要后停止，没有会话外AI巡检。

用户明确要求“先保留在modal，后续再处理”。数据仅保留在runs volume
`wxu-evolve-agent-runs-20261006`（环境`zheng-dev`）的
`/runs/devbox/frozen_9b_results_20261019/`：

- `files/{cvbench,mvu_eval,crossvid}.jsonl`：997/1824/2500条原值答案、GT、逐题秒数和文本轨迹。
- `files/ccqa_scores.jsonl`：239条，字段与AgentCVR一致。
- `files/statistics.md`：评分、耗时、格式及来源说明。
- `mvagent-9b-results-with-trajectories-20261019.tar.gz`：以上五文件，185,582,658字节；
  SHA256 `0af9dbda447386f0a13109ad93559a5a52bc2d990245d4f5d3448f41503aa5a3`。

未下载本机或发布Release；源码与本文按项目规则推送Git。包内保留文本轨迹，不包含媒体Base64或
完整token ID数组；未删改原始Modal记录。27B/35B结果不在本9B包内，仍由原全量任务负责。

### 2026-10-19 27B结果整理与35B单组GPU调度

用户要求27B推理齐后立即Judge并按9B布局整理，撤回原27B卡组对35B的并行投入。
27B为5321题（1500复用、3821新增），两分片1911/1910均完成且顶层工程错误为空。
正式Actor、Prompt、数值配置和评分规则不变；通用整理入口改为
`MVAGENT_EXPORT_MODEL=27B python scripts/finalize_frozen_results.py prepare|judge|export|verify`，
9B已完成包及其冻结脚本保留原件。

15:18 UTC主动停止旧shard1的35B，保留121条完成记录及在途目录；原progress最后采样120，
不拿采样计数覆盖实存结果。审计在runs `devbox/frozen_27b_results_20261019/{reallocation,retained_35b}.json`。
只停止worker后，旧Sandbox退出触发看守器自动续接；再次停止看守器4132281与新worker，
15:22确认新Sandbox `sb-Y0XVuj0BJZZs6VARWeEcBg` poll137，旧master/host退出。
续接仅到加载阶段，没有新增回答；这次中断是用户调度要求，不是新的模型故障。

独立4H100 Judge owner87293 / `sb-ImKSHBMcKPLPQHoWYrBAqS` 于15:23开始加载；
仅补189条CCQA，旧50保留，缓存写回两分片供后续复用。
完成后自动释放4卡，再用CPU冻结输入、导出和核验五文件；数据继续只留Modal，不发布Release。
GPU冻结整理脚本对应7e8d4d3；CPU导出126482e按实际27B恢复审计的`new_sha256`键读取，
不改9B历史审计的`new_result_sha256`，也不改变原始回答。

另一组35B `sb-vgVxKqWaY20PaHrNRgZ5SO`保持原冻结任务。
串行owner88348及`scripts/continue_frozen_35b_serial.py`只在该组completed、GPU已退出且状态文件移除后，
才使用原shard1冻结源码续跑1789条剩余题；所以35B同时最多一个8卡池。
旧原master40568在第一组结束后可能因旧shard1 owner已撤回而退出，其最终汇总职责转交串行owner。
串行owner等待两组均完成后执行原CPU总分析，不把暂停分片标记为完成。
资源门禁self-check通过；实际串行续跑仍待第一组结束，不能声称已完成。
控制日志在devbox `/tmp/mvagent-27b-results-20261019/{controller,serial-35b,serial-35b-worker}.log`。

15:27:53 UTC新增189条Judge全部完成（107+82，failed_ids均空），旧50条原判定通过来源与分数核对。
Judge专用4H100已释放，末检poll137；CPU owner87293于15:32:11完成五文件与压缩包核验后退出。
原始5321题来源SHA、答案原值、覆盖与唯一性、文件字节数/SHA和包内成员均通过；未重跑Actor。

| 27B完整同题范围 | 题数 | E2E (%) | MVAgent (%) | 差值(pp) | Agent平均秒/题 |
|---|---:|---:|---:|---:|---:|
| CVBench | 997 | 68.51 | 70.51 | +2.01 | 99.78 |
| MVU-Eval | 1824 | 44.46 | 58.00 | +13.54 | 126.91 |
| CrossVid十类宏平均 | 2500 | 42.13 | 48.10 | +5.97 | 126.84 |

所有5321题正常返回，最终空答案0、仅右花括号0；这里没有声称中间调用从不截断或所有题型均提升。
包含1500复用开发题；MVU E2E用官方指令移后，CV统一原有YES/NO映射，原E2E发布文件不改。
本轮未新增统计显著性分析，逐题耗时也不等于并行墙钟时间。

成品仅在runs volume `wxu-evolve-agent-runs-20261006`、环境`zheng-dev`的
`/runs/devbox/frozen_27b_results_20261019/`，与9B同布局：

- `files/{cvbench,mvu_eval,crossvid}.jsonl`：原值GT/答案、逐题用时与文本轨迹。
- `files/ccqa_scores.jsonl`、`files/statistics.md`：239条开放题判定与统计说明。
- `mvagent-27b-results-with-trajectories-20261019.tar.gz`：180,055,502字节；
  SHA256 `27d76656d65272e8925417832dd172d10ab1e325565e0dcaa35a136951d3e9ad`。

`input_manifest.json`保存5321题输入快照与原始E2E文件哈希，`manifest.json`含逐题来源和文件哈希，
`verified.json`记录完成证据；导出源码SHA256为
`eca09230f885688eb1d3708f43b46799d523515015519f8e970b4e5ce21c8ee7`，与126482e一致。
包不含媒体Base64、完整token ID数组或重复传输日志，完整原件留Modal；不下载本机、不发布Release。
35B串行owner仍等待第一分片，不因27B包完成而重新扩为16卡；未来续测尚未执行，不冒充全量完成。

### 2026-10-19 9B与27B结果公开发布

用户追加要求将两个已核验成品上传GitHub，取代此前“仅留Modal”的交付限制。
沿用原包，不重新打包、推理或Judge；每模型5321题、239条CCQA、五个成员文件及答案原值/文本轨迹均不变。
Release为[`mvagent-results-20261019`](https://github.com/Wal-K-aWay/MVAgent/releases/tag/mvagent-results-20261019)，
目标源码提交9cf198b。发布包与核验回执暂存`outputs/mvagent_release_20261019/`，数据不进入Git历史，Modal原件保留。

| 附件 | 字节数 | SHA256 |
|---|---:|---|
| `mvagent-9b-results-with-trajectories-20261019.tar.gz` | 185582658 | `0af9dbda447386f0a13109ad93559a5a52bc2d990245d4f5d3448f41503aa5a3` |
| `mvagent-27b-results-with-trajectories-20261019.tar.gz` | 180055502 | `27d76656d65272e8925417832dd172d10ab1e325565e0dcaa35a136951d3e9ad` |

另附`SHA256SUMS.txt`；两个包的成员文件名相同，下载后分别解压到9B与27B目录。
只分发已约定的文本轨迹，媒体Base64、完整token ID数组、权重与冻结环境不进包。
35B不在本次Release中，现有推理和单组8卡串行调度不变。

发布完成后，GitHub三个附件的`state=uploaded`、大小及服务器SHA256均与本地/Modal一致，
两个压缩包和校验文本的无需登录完整下载也逐字节数/SHA通过。
Release ID为417467742，公开tag解析到9cf198b；核验回执为本地
`outputs/mvagent_release_20261019/verification.json`。只提交说明和授权规则，不提交结果数据，
未重跑推理或Judge，未操作其他Release或在途GPU任务。

### 2026-10-20 三模型逐题耗时与配置核验

只读审计已发布9B、27B与35B-A3B包的全部15,963题及201,928次模型响应，未新增Actor/Judge/GPU，
不修改正式配置或Release。原始分析只在runs `devbox/mvagent_timing_audit_20261020`，
以`final_report.json`为最终报告；`settings.json`保留服务身份与冻结源码，`final_source.py`保留分析实现。
初版`report.json`和逐题表中的`global_steps`实际指轨迹条目数，最终报告改名`trajectory_entries`，
不可将它解读为Global决策步数。实测处理脚本为`scripts/audit_mvagent_timing.py`，语法和均值/分位数自检通过。

| 模型 | CVBench 997题(s/题) | MVU-Eval 1824题(s/题) | CrossVid 2500题(s/题) | 全5321题加权均值(s/题) | 全题中位数(s) | 全题P95(s) |
|---|---:|---:|---:|---:|---:|---:|
| 9B | 46.53 | 57.57 | 66.30 | 59.60 | 50.40 | 127.60 |
| 27B | 99.78 | 126.91 | 126.84 | 121.79 | 100.78 | 268.91 |
| 35B-A3B | 103.06 | 122.04 | 130.43 | 122.43 | 102.93 | 272.71 |

三模型题号集合完全相同，每题`seconds`均等于`trajectory.result.time`；无重复/漏题、非有限值或非正耗时。
重算9个benchmark均值与发布包`comparison.json`差异均小于1e-8秒；均值不是已四舍五入的表格数再平均。
全部题目seconds之和分别317131.04、648068.17、651427.54秒，除以5321得到上表加权均值。
CrossVid耗时按2500题平均，与其准确率采用十任务macro不同；不以GPU数再次除逐题时间。

`MVAgentEngine.answer()`在`_preprocess()`之前记录`perf_counter()`，在`_postprocess()`中
计算差值并存为两位小数秒数。计入视频元信息检查、题内预处理/裁剪、Agent调用、视觉输入处理、
推理、题内等待及发生于这段区间的日志开销；**不计**最初等待副本租约、模型加载/Engine初始化、
结束后的cache清理、结果序列化/落盘、评分/Judge、归档和历史失败/被中断尝试。
因此建议论文称“成功整题Agent执行耗时”，不是总任务墙钟除题数，也不是纯GPU解码时间。

实际请求和运行配置核验：

- 73,595 / 65,037 / 63,296次响应全部来自H100 80GB HBM3；每题固定同一个worker，prefix命中数全部0。
- 201,928份请求均为temperature=0、top_p=1、max_tokens=2048、seed=0；未传thinking字段时，
  固定服务验证器及renderer仍强制`enable_thinking=False`，不是启用了默认thinking。
- 224份服务card引用（含重复引用，不是224张卡）仅一套profile：BF16、TP1、max_num_seqs=1、
  max_model_len=131072、max_num_batched_tokens=32768、显存比例0.94、FlashInfer GDN、原生GemmaRMSNorm、
  enforce_eager=True、prefix/MM processor cache关闭；vLLM/torch/transformers等版本一致。
- 15组来源的`input_config.yaml`齐全，剔除模型名/权重路径和输出/cache目录后完全一致：
  每次最多512帧、2048输出token、Global/Video各5步、video_concurrency=2、空skill库。
  实际batch_prepared均8个question workers、16个预处理slot、8个单卡C1副本；16个slot不是每卡16并发。
- 继承9B旧分片从result符号链接解析回原运行配置；旧1500题的归档配置也纳入检查。
  六份生产/恢复/旧面板源码归档中Engine与Batch代码各只有一个SHA，计时起止位置没有模型特例。
  媒体修复、恢复批次、GPU UUID及历史同时运行的池数存在差异，不能称所有执行环境条件完全受控一致。

服务器计时采用每次响应的`inference_seconds`；它包含renderer/视觉处理、prefill与生成，
不是纯GPU kernel时间。固定整题单副本使各请求的服务器区间串行，求和没有多VideoAgent并行重复计时。
全部题目服务器累计时间及事件时间跨度均未超过Engine时间（容差0.02/0.05秒）。

| 模型 | 平均调用数/题 | 平均输出token/题 | 服务器累计秒/题 | Engine减服务器秒/题 |
|---|---:|---:|---:|---:|
| 9B | 13.83 | 1646 | 55.54 | 4.06 |
| 27B | 12.22 | 1941 | 118.39 | 3.41 |
| 35B-A3B | 11.90 | 1631 | 118.20 | 4.23 |

服务器部分占整题93.19%/97.20%/96.55%，27B/35B相对9B的主要时间增量在这里；
不是35B因调用次数更多或客户端排队多了约一分钟。27B和35B全题均值仅差0.63秒（约0.52%），
这些跨批次轨迹不足以对两者做严格速度排名。

按角色分解的服务器平均秒/题：Global决策9B19.15、27B36.60、35B47.58；
Video行动规划13.73/36.09/34.53；视觉观察19.61/42.47/33.03。
35B相对27B在Global决策多10.98秒，在视觉观察少9.44秒、Video规划少1.56秒，整体大体抵消。
这是实际轨迹的耗时分解，不是固定完全相同请求后证明某种架构/内核的因果收益。

旧1500开发题均值54.79/102.13/99.17秒，新增3821题为61.49/129.51/131.56秒；
问题构成、实际观察范围/FPS、输出轨迹和运行批次均会影响总耗时。
未新增同输入性能对照、GPU kernel profiler或吞吐实验；无需更正已发布seconds与均值。
CPU审计完成，独立检查只读核对全部主指标与配置分组后停止，不宣称后台持续AI巡检。
