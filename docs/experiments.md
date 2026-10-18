# 固定框架与实验记录

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

## 后续微调建议（尚未执行）

目标拆成三项：输出交付合格、同输入可重复、跨题/模型的准确率收益。已有数值配置只解决第二项，不能替代另外两项。
当前优先保留原 VideoAgent，不把完整原题或答案选项重新注入每轮报告。

1. **先测报告忠实性的一条 System 规则。** 候选：`Keep observations, inferences, and unknowns distinct; preserve uncertainty when summarizing evidence.`
   只加到 Video 报告所用 System，不加题目、示例、选项或额外调用。检查源观察中的“可能/未知”是否在报告中被变成肯定结论。
   是否有净收益须实测；不把负实验的机制分析直接当作有效修复。
2. **独立测简洁 Global 解释要求。** 候选：`Keep explanations brief and focus on evidence that changes the next decision.`
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

## 两项 System 微调小测（2026-10-18，进行中）

从冻结`f61946f`独立实验，不改变正式基线。入口`scripts/system_refinements.py`，结果仅写
`/runs/devbox/system_refinements_20261018`。V与G分别以基线为起点，不叠加：

- V：Video Planner System追加 `Keep observations, inferences, and unknowns distinct; preserve uncertainty when summarizing evidence.`；步数耗尽的Video总结原来System为空，现在仅使用同一句规则。正常finish同Planner决策生成，因此该规则也可能影响下一次观察，不能把变化仅归于摘要措辞。
- G：Global System追加 `Keep explanations brief and focus on evidence that changes the next decision.`，主动与强制终答自然沿用；Video完全不变。
- 两组User、视觉Observer、schema、参数预算、History、FFmpeg和数值profile不变。生成的候选源码及精确patch、源提交/哈希在新运行根冻结，不给正式配置增加实验开关。
- 三模型每组50题（CV15、MVU15、Cross20含2CCQA），共300新轨迹；同题基线150条来自已完成简洁Global面板。只按题型/人口权重和seed0选题，不按结果选题。CV每task只有1题，不能用本批声称普遍收益或可靠置信区间。
- 使用独立8×H100顺序加载三模型，同模型复用服务；两候选顺序跨模型轮换。身份/权重/固定profile与历史基线逐卡校验，整题单卡、每卡C1、prefix关闭。既有其他任务不变。
- 同模型两候选共享Judge缓存，并按完整评分Prompt预填入所选基线CCQA缓存；相同答案不因重新Judge引入分差。旧原始记录只读，基础设施失败与模型错误输出分开。
- 报告同题官方分（CV/MVU按task人口加权，Cross十task macro/CCQA评分点加权）、稳健提取、格式/空答、截断、修复、调用/token与耗时。小批通过后才考虑扩测；不自动替换基线。

准备已完成：冻结源码`65829c9`，源码包SHA256 `2b0f0454de5281ec693b88839804aa6cfc4eabbbf38bd6d9f615961eb20d9b9b`；
CPU `ap-A6V4tLs5TuXtLnP2hCCZFJ` prepare与System/抽样检查rc0，
`ap-EqphXprvu3zcIOmVhtIGHE`核对144闭式评分/格式和150条基线token/sticky/cache记录全部通过。
首次prepare因CPU镜像无git命令而终止，0模型调用，原记录在`system_refinements_20261018_prepare_initial`；改读冻结HEAD后完成。
05:43 UTC独立Sandbox `sb-EnHLS7BUGVf7Pebo8FgzAL`已申请，host PID3527878，
日志`~/wxu-evolve-agent/devbox/watch-system-refinements-20261018.log`。初始仍等待容器执行，尚无新轨迹；
按旧同题耗时估就绪后约1.6小时，排队另计。控制器依次执行三模型/两候选、Judge、释放本任务GPU、CPU汇总。
实际推理/评分尚未完成，不以提交成功声称测试通过。

06:00 UTC新Sandbox就绪（此前约17分钟等待），实查8×H10080GB。两候选决策接口检查通过。
9B实际8副本约204秒加载完成，startup_identity与历史权重/profile逐卡匹配；首16轨迹185调用
0模型错、token/cache0/sticky审计通过，V组未改动的首轮Global与基线16对完全一致（startup_audit.json）。
06:15 UTC两臂9B各50题均有效，0顶层工程错误，开始加载27B。9B初步闭式对照（不含2题CCQA）：
CV15题基线/V/G=80.90/75.80/75.80；MVU15题60.48/60.48/46.58；Cross九闭式18题39.68/45.24/29.76。
这是单模型小批、不含开放题的中间结果，不能作为完整九格结论。V截断0→2，G仍0；理由变短不等于准确率不下降。
CV774旧正确A也缺少明确证据、理由反复纠结，V改C、G改B；该翻转不能当作旧证据充分被新规则破坏的证明。
