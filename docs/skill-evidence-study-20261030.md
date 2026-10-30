# 无 Skill MVAgent 对比与手写 Skill 研究（2026-10-30）

本轮先做历史逐题配对分析与手写机制实验，为后续自动迭代提供依据。**研究进行中，已有小规模Train增损，完整机制、排版和步骤覆盖尚未完成，也没有Cal/Gate确认。**
本报告的系统对比属于隔离的评测分析，不向 Skill、optimizer、Meta 经验或检索索引传递评测题目、逐题反馈、轨迹及其诊断。
手写卡片仅依据历史合法 Train 的公开缺口重新编写，具体来源与已知继承关系见[资源目录](../src/mvagent/skills/skill_sets/manual-study-20261030/README.md)。

## 当前约定

以用户本机 `research/skill_evolution.md`（2026-10-30，文件 SHA256 `fc3a2b40d0ce532698e65a1d130afd6ca2cd62a92451b52d073a9196e977be76`）为本轮合同。
它取代 10 月 22 日的非空父库接续、H20 限制和旧配额；历史运行及其接受结果不改写。
本轮新库从两角色空库参照开始，9B Actor/Selector、冻结权重和 Runtime、seed=0、temperature=0、thinking 关闭、2048 输出 token、两角色各 5 步、每调用最多 512 帧。
视觉处理不额外施加最长边 448 上限；须记录实际路径，不能仅以配置文字证明生效。历史结果仅在身份匹配时复用，不重跑三基准主表或无反馈一次生成。
GPU 上限按 `America/Los_Angeles`：10:00–18:00 为 16 张 H100，其余时段 32 张，加载与闲置也计入。首个节点只申请 8 张，不依赖夜间额度。

当前用户要求包含手工格式、入口和步骤测试；它们是人工机制诊断，不冒充正式自动进化或研究合同中暂缓的正式消融。
最初 24 库仅改变机制和排版，尚未覆盖启动条件、步骤程序的全部独立干预，也不构成“充分测试完成”。

## 已完成：最终无 Skill 结果重新配对

CPU app `ap-6PyRI1ugnGOsGDA4Xr35CW` 已完成；以最终冻结协议的三模型各 5,321 条历史记录为输入，共重新核算 **15,963 个模型×题记录**。
这不是新增独立样本或新模型推理。每模型包括 CV997、MVU1824、Cross2500；1,500 题为历史开发复用，3,821 为补测题。
每模型 CCQA239、757 评分点；Cross 十任务等权，CCQA 内按评分点加权。CV/MVU 按全题平均。
三模型总分均逐一匹配原发布锚点；27B 固定原发布 Judge，不使用后续有变动的缓存。

| 模型 | CV：E2E → MVAgent | MVU：E2E → MVAgent | Cross：E2E → MVAgent |
|---|---:|---:|---:|
| 9B | 62.49 → 64.49（+2.01pp） | 37.72 → 50.55（+12.83pp） | 31.98 → 35.28（+3.31pp） |
| 27B | 68.51 → 70.51（+2.01pp） | 44.46 → 58.00（+13.54pp） | 42.13 → 48.10（+5.97pp） |
| 35B-A3B | 64.49 → 67.50（+3.01pp） | 36.62 → 54.28（+17.65pp） | 32.24 → 41.27（+9.03pp） |

官方分正差不等于等量视觉推理进步。使用原保存的保守终答提取口径后，MVU 的配对差分别为 **+2.30、+4.55、+5.54pp**，明显小于官方差。
9B 的 MVU 格式错误从 E2E 的 622/1824 降至 25/1824；该处理是评分敏感性分析，不是视觉能力的因果分解，也不替换官方主分。
CCQA 没有定义该 robust 指标，因此完整 Cross robust 留空，九个闭式任务另报，不补造开放题稳健分。

| 配对改善 / 退步 / 同分 | CV997 | MVU1824 | Cross2500 |
|---|---:|---:|---:|
| 9B | 162 / 142 / 693 | 467 / 233 / 1124 | 602 / 450 / 1448 |
| 27B | 137 / 117 / 743 | 440 / 193 / 1191 | 776 / 469 / 1255 |
| 35B-A3B | 166 / 136 / 695 | 487 / 165 / 1172 | 763 / 397 / 1340 |

Cross 含连续分，改善题数减退步题数不能直接转换成总分差。9B CV 补测497题双方均64.59%，总体小正差主要来自此前复用题，不能只报全量而省略开发接触。

### 已测到的优势与弱势

下表是最终全量系统层面的描述，不据此改写卡片，也不将每个任务差都视作统计显著或纯架构因果。

| 任务（MVAgent − E2E，pp） | 9B | 27B | 35B-A3B |
|---|---:|---:|---:|
| Cross PSS | +21.98 | +47.25 | +37.91 |
| Cross FSA | +4.95 | +21.69 | +15.08 |
| Cross MSR | +4.91 | +22.09 | +22.09 |
| Cross CCQA | −33.09 | −33.42 | −5.88 |
| Cross PI | −15.00 | −3.00 | −17.00 |
| CV Multi-video Temporal Reasoning | +24.32 | +35.14 | +25.68 |
| CV Cross-video Procedural Transfer | −10.00 | −6.00 | −6.00 |
| CV Video Difference Caption | −14.55 | −1.82 | −23.64 |

优势集中在这些已测时间关系、步骤排序、定位和空间题；弱势集中在部分开放细节、情节推断、过程迁移和视频差异描述。
仅凭终答不能判定弱势发生在观察、Video 报告压缩、委派还是 Global 使用阶段；机制定位还需要合法 Train 的完整证据链。
9B 每题平均模型调用为 CV10.21、MVU17.70、Cross12.45，平均整题秒为46.53、57.57、66.30；同题 E2E 约20.96、12.25、25.40秒。
这不是等计算预算比较，秒数也不包含服务加载、Judge 或并行墙钟成本。27/35配对文件没有 E2E 秒数，本次明确留空。

### 与其他 Agent 的系统参照

以下为原发布统计；其后另列本轮已完成的五组逐题配对。保留方法各自的预算、工具及基础设施失败口径，不能把原表视作同一计算预算的架构比较。

| 方法 / 骨干 | CV997 | MVU1824 | Cross2500 |
|---|---:|---:|---:|
| Video-RSI / 9B | 57.97 | 46.66 | 29.47 |
| Video-RSI / 27B | 68.20 | 58.77 | 43.18 |
| Video-RSI / 35B | 62.39 | 51.43 | 33.47 |
| LensWalk / 9B | 56.27 | 36.35 | 25.05 |
| LensWalk / 27B | 62.09 | 36.62 | 33.29 |
| LensWalk / 35B | 55.37 | 33.72 | 21.77 |
| AgentCVR / 作者公开8B系统 | 56.87 | 44.02 | 37.20 |

MVAgent 在这些同模型大多数格更高，但 RSI27 的 MVU 更高；AgentCVR 的 Cross 高于 MVAgent9B，骨干不同。
工具、预算、音频、模型训练和基础设施失败口径有差别，不能据此宣称架构本身全面更优。
来源：[MVAgent](https://github.com/Wal-K-aWay/MVAgent/releases/tag/mvagent-results-20261019)、[Video-RSI](https://github.com/Wal-K-aWay/MVAgent/releases/tag/video-rsi-results-20261020)、[LensWalk](https://github.com/Wal-K-aWay/MVAgent/releases/tag/lenswalk-results-20261019)、[AgentCVR](https://github.com/Wal-K-aWay/MVAgent/releases/tag/agentcvr-results-20261018)。

CPU `ap-hrqpE1rFQuha4LuGlcoT9a` 已按保留索引逐流核验7组×5文件的大小、SHA与行数，复用原239条CCQA缓存，0新Actor/Judge。五组通过发布总分、当前官方闭题评分及完整5321题ID配对；产物为新卷`skill_evidence_20261030/other-agent-comparison-20261030-200829/`。这是历史结果分析，不是新增独立测量。

| MVAgent − 同骨干方法（pp） | CV997 | MVU1824 | Cross2500 | Cross已记录Agent秒：MVAgent / 对方 |
|---|---:|---:|---:|---:|
| LensWalk9B | +8.22 | +14.20 | +10.23 | 66.30 / 193.94 |
| LensWalk27B | +8.43 | +21.38 | +14.81 | 126.84 / 302.64 |
| Video-RSI9B | +6.52 | +3.89 | +5.81 | 66.30 / 157.91 |
| Video-RSI27B | +2.31 | −0.77 | +4.92 | 126.84 / 384.67 |
| Video-RSI35B | +5.12 | +2.85 | +7.80 | 130.43 / 417.65 |

比较对象会改变强弱结论：相对这五组，CV多视频时间推理均为正（+12.16至+25.68pp），Cross MSR/PSS/CC/NC也均为正；但相对三种Video-RSI，MVU Comparison/KIR/RAG与Cross PEA均为负。相对Lens9B/27B，Cross CCQA为−6.27/−5.28pp、FSA为−15.88/−6.23pp。因而前面FSA相对E2E的优势不能外推为相对其他Agent的普遍优势；这些都是系统描述，不能回流卡片或Meta设计。
排除对方明确标记的工程失败后，五组CV/Cross差仍为正；RSI27的MVU差从−0.77变为−1.84pp。该敏感性改变了题目子集，不是新的全量成绩或因果分解。秒数不含加载、Judge和视频准备，也不是总墙钟/重试成本；例如外部方法Cross视频准备均秒另约154–160，不能把表中Agent秒当完整等成本评测。
两组保留未对齐：Lens35B有1条已存闭题分与当前CPU评分不一致；AgentCVR按当前CPU评分器得到CV56.97091%、Cross34.95377%，不同于原发布56.87/37.20，MVU仍44.02412%。旧代码确有CV映射、Cross答案parser及终态计分规则差异，完整差异归因另核；不替换原发布分，也不冒称已完成统一口径下这两组的能力配对。

## 手写机制与测试顺序

### 只读重审历史合法Train轨迹

CPU `ap-DW9TD3g8Sn2YeVaKCkqOzx` 完成旧9B无skill Train80的80份raw SHA核验，**没有读取Cal/Gate，也没有新增推理或Judge**。
原始根为历史卷`devbox/manual_skill_diagnostics_20261021/nineb/node0/evaluations/1dea07ba6d17ff67eb714db06082a162f76012a28d2c8ecc5ad832ab33f1c184/train/`；
新审读产物在新卷`skill_evidence_20261030/historical_train_audit/`，保留脚本、原件hash和6个按原清单顺序取的Global公开摘录，没有按成绩挑例。

| 可观察行为 | 数量与分母 | 可支持的解释 |
|---|---:|---|
| Global analyze / watch / answer | 88 / 36 / 80次 | 存在多轮和联合观看，但调用本身不是有效证据证明 |
| Global强制终答 | 2/80题 | 这批多数题主动终答；不能把主要缺口一概归于步数耗尽 |
| Video调用 | 239次 | 与题数分开计 |
| observe成功 / error | 259 / 15次，共274次 | 不将工具失败当视觉证据 |
| 同一request完全相同observe参数重复 | 32次，涉及12/239个request | 需要审读是否有新增信息；重复不自动等于无效 |
| request无新增observe、复用此前观察 | 18/239次 | 合法Memory复用，不是缺少观察的失败 |
| finish缺少同视频累计可用观察 | 0/236次finish | 不支持“每次调用都必须重看”的通用规则 |

两个公开证据链示例不依赖视觉GT：

- 一题要求某条件在三个视频均成立；第一份报告并未支持该条件，Global仍在终答理由中声称三者共同满足。它暴露的是**报告到量词结论之间的支持缺口**，不据此判断原视频事实。
- 另一题的一个Video反复返回“达到步数上限且没有观察”；Global重复同一委派后，将该未知视频当作可排除项，并称现有证据足够。它暴露**失败后的行动恢复与未知项处理**，不把失败本身当作否定观察。

字面时间检查只覆盖9个含显式时间表达的Video instruction，其中7次observe比较未发现数字从`what`遗漏；这是狭窄负证据，不能据此判定语义、时间对应或边界正确，也不能默认“重复更多时间字样”就是主要修复。
整题分数不作为每份Video报告的正确性标签；本轮尚未用局部视觉GT证明观察、报告或Global哪一层是主因。

第一批为 4 Global / 4 Video 新编程序，每个程序 3 种排版，共24个非空单卡整库，详见[英文库与索引](../src/mvagent/skills/skill_sets/manual-study-20261030/README.md)、[完整中文镜像](manual-study-skills-zh.md)。
每种排版固定相同的 `meta`、`when_to_use`、操作句和句序，只改变连接、编号、小标题；这种构造仍会改变 token 与注意力，不保证执行输出相同。
Selector只看到`when_to_use`而看不到`strategy`，因此同输入下三种正文排版不能直接改变它的偏好；排版测试测的是Actor执行效用。Video后续instruction变化引起的选卡变化须另行归因。
它们不作为自动进化种子；人工诊断与后续正式空库进化谱系分开记录。

先测新合法 Train 的空库和单个候选自然 rollout，产出第一份完整父子对照，再扩大程序与样本覆盖。
首测10题或40题只用于启动与开发，不承担主要能力判断；主要样本池目标仍为 Train2000 / Cal400 / Gate400，须先验证来源可行性。
不按刚得到的分数重新选题，不把自然 Selector 的 none 当作运行故障。启动条件和步骤干预在排版之外单独冻结，不能将多因素改动称为纯格式结果。

每个实验单元分别报告：有效题数、自然选择次数（Global按题、Video按调用）、真实注入、预期操作变化、官方配对增损，以及误触发与反例。
阶段接受仍需预声明的完整 Cal、阶段冻结后唯一 Gate；选中率、成本、步数和局部自评不加入官方接受目标。

## 远端资产与状态

### 首个新父子对照：完成，净收益接近零

恢复节点于19:09 UTC完整完成，controller exit0并释放8H100。CPU `ap-XGmCfcgzO9ukST5LCUsZhK` 完成80份raw逐SHA核验、官方加权总分复算及真实注入检查。
产物为新卷`skill_evidence_20261030/first-pair-analysis-20261030-191102/`，含分析脚本、全部输入hash及汇总；没有新Judge或修改原分。

| 新Train40条件 | 有效评分题次 | 官方总分 |
|---|---:|---:|
| 空库 | 40 | 39.45055% |
| 候选区别取证，段落版，自然选择 | 40 | 39.64286% |
| 配对差 | 40个不同题的配对 | **+0.19231pp** |

逐题 **1改善 / 2退步 / 37同分**。NC的一个改善贡献总分+2.50pp，两个CCQA退步合计−2.30769pp；连续分和点评价权重使净题数与净总分不同。
这是小Train开发信号，**不能称为稳定有效、Cal接受或泛化提升**。还没有比较本程序的三种排版，也没有测试其他七个程序。

- 自然选中17/40题，23题none；none的23个终答全部与空库相同。
- 选中后的40次Global决策请求确实含策略；17题取证参数变化、8题动作名序列变化、10题终答变化。变化本身不证明证据更真实。
- Global决策调用109→106；analyze42→41、watch27→25；全部记录模型响应508→527（包含新增Selector开销）。
- 1035个实际Actor/Selector响应全部为`qwen3_5_9b_local`；缓存计数完整且cached_tokens全0。80个成功raw的`attempt`原值均为0，不将原值自行解释成累计尝试成本。
- 实际视觉传输为video_url：153→145个视频请求、190→179个video项目，image_url均0。不能据此声称零视频帧；逐请求解码帧数未由这份分析器测量。

### 新发现：实际视频路径限制了FPS干预的含义

已在运行中的7个Actor进程只读核对vLLM0.19.1、Transformers4.57.6与真实环境，未修改服务。
`ApiVLMClient.chat_on_videos`发送video_url和fps，不调用前述图片编码函数；**517×292图片探针不能代表本轮视频实际输入尺寸**。

安装库`vllm/multimodal/media/video.py:42–72`默认`num_frames=32`；默认OpenCV loader在`vllm/multimodal/video.py:358–388`取32、源帧数、duration×fps的较小值。
7个Actor均没有VLLM_VIDEO环境覆盖，默认后端opencv。当前watch最多4视频，解码层上限因此比外层512计划更严格，通常至多128帧；Qwen后处理与temporal padding由下面的原请求重放另行核对。
**提高请求fps不一定增加实际帧数**，故不能将fps字段增加直接计为更密的有效取证。缩短目标窗口、改观察问题等仍需整题结果和实际采样检查。

权重`video_preprocessor_config.json`的shortest_edge4096/longest_edge25165824用于视频总像素预算；安装库`transformers/models/qwen3_vl/video_processing_qwen3_vl.py`按时间×高×宽及32倍数resize，未施加最长边448。
CPU `ap-tyDPnTBT0SmRVuyocAwoXj` 已对首个单视频及首个联合视频Train请求完成原生重放。使用同冻结裁剪/编码函数重建，3个data URL的SHA/长度和2个完整HTTP请求SHA全部与原记录一致后，才调用同版本MediaConnector和视频processor；没有加载Actor、生成回答或改变配置。

| 原请求内的视频项目 | 解码帧×高×宽 | Qwen处理后含padding的帧×高×宽 |
|---|---|---|
| 单视频 | 32×270×480 | 32×256×480 |
| 联合第1视频 | 21×720×1280 | 22×704×1280 |
| 联合第2视频 | 32×1080×1920 | 32×640×1152 |

联合第1项目原计划27帧，OpenCV跳过6个不可读帧，实际21帧后补至偶数22；padding不是新增独立证据。它们是原请求字节一致的CPU处理重放，不能冒称所有在途请求均记录了tensor尺寸或所有视频均可完整解码。
这些尺寸验证了本次样例没有额外448最长边限制，也显示512外层预算不等于实际输入512帧。产物在新卷`skill_evidence_20261030/video_rebuild_cpu/`，summary SHA `bbeae96c465c8e56fc250a93a89e50828aa622a155c95d413a9229927f380bed`。

- 历史卷 `wxu-evolve-agent-runs-20261006` 的 inode 已达499614/500000（99.9%）；本轮不删旧 raw、评分、Judge、卡库或冻结源码。
- 新研究卷 `wxu-evolve-agent-runs-20261030` 保存本轮结果，历史卷后续只读。首个聚合产物：`skill_evidence_20261030/baseline_comparison/summary.json`，包含分析脚本、自检和输入SHA，不含新推理。
- 输入 SHA：9B `4ea9c503490970b2d64c744010db966926355ad407f1b0ebe4fdc12f387e8b1a`；27B `889bc349cf41bd55efc9d45822237703f50ee2e828cae81861bfda6f3cbb9b1e`；35B `63f8ecbbbaa65ff61ba569ed7e80b385c47676be68706642b4f49b038df05432`。
- 数据容量检查CPU `ap-WCVmH3XZ3bwyua3NwaqcHG` 完成：9015−2500=6515；PI151题/22来源组、NC887题/18来源组，是分区容量约束。这里只是声明来源键的连通组，不把它当作完整实体来源真值。
- 首次聚合脚本通过自检，但旧文件缺 `task_population` 导致正式统计停止；已改为直接从冻结全量题集推导分层权重后完成。原件未改，无Actor或Judge重跑。

CPU `ap-c9Yd3AMpqoAnlM7EkarfWN` 已验证24库的runtime parser、渲染、字节SHA及同句同序构造；实际预处理函数的1600×900图片得到517×292，面积上限151200像素，没有最长边448硬截断。该CPU证据尚不替代模型实际请求审计。
首个来源分配未填满PI16题、NC14题，未写可运行manifest；改为先分配最大剩余来源组，保留首次不足审计，未按分数改题或放宽隔离。
CPU `ap-TiTdJDivoBTJvQxyKlpCiX` 已完成修正后的自检与真实分配，冻结 Train2000 / Cal400 / Gate400：
`prepared_v2/manifest.json` SHA `7bcdaae229e6c540f221d0bff5ef6d52727ee78a640a0b8bab3482b39fa0f69e`；
首Train40 SHA `14037e3378243d04c86fc76dabe8b3fff6a7dec8d93d0681afea184efd3f67d8`。
三个分区在声明视频/UAV来源键的连通组上互斥；其中与Lite来源共享题数为Train1665、Cal292、Gate294。
完整2800题中1902/560题分别与旧296/365面板共享来源；两数可重叠。这里是**历史来源有接触的开发条件**，不是对所有历史或潜在实体关联的来源外确认。

首个GPU单元预声明：单节点8H100、仅新Train40；空库40＋`global_option_discrimination`段落版40，共最多80题次、40不同题。
自然选卡，伙伴角色为空，不查询Cal/Gate；最大4小时分配（含启动与收尾，最多32GPU·小时），首次父子单元完成立即分析。
候选文件SHA `21266c1682095f496c3951c769471728dddeccac935c4035a5a4fa76bad66d5e`；冻结Runtime代码67a6d15，卡片来源54159c5。
每库仅1张卡，未触发embedding检索，不把未参与运行的embedding模型更换解释为收益。
首Train40与旧296清单有2个题号交集（其中旧Train1题），与旧365题号无交集；不能称为40个历史未接触题。
旧Train80原manifest的Runtime snapshot SHA为`d1686258737d5649926128d898cb6863f10e04a945d4bfdd8451cdff3a9affca`，本轮冻结树为`e6fc095e8b62db776684058ca89195b4b613da35ac8995900829aaa08647b591`。
未建立两者完整可复用身份，因此不导入或伪造旧缓存；本次是新合同允许的新开发分区初始参照，不是三基准旧主表回补。
首请求app `ap-JpU84Q3eIfHW8zZvU9JlrF`、sandbox `sb-OGA6ZOLwUO45onXrrP9Ppw` 已创建，18:27 UTC仍无容器任务，`poll=None`且主控制器存活，未得到新rollout。
节点获取阶段预算15分钟；若仍未启动，先确认终止该排队请求，再缩至4H100保留同一80题及单副本协议，另记尝试，不并发重复提交。
18:29:26 UTC核对时原8卡已获得task，因此取消分支没有执行、4卡方案没有提交。7个Actor约236秒启动成功，实际profile、BF16、seed0、关闭prefix/MM cache和7个独立H100身份均已核验，Judge也成功就绪。
首尝试随后在原生CLI导入阶段失败：私有启动器未将`PYTHONPATH`传给评测子进程，报`ModuleNotFoundError: models`，没有进入问题推理。
该节点已由控制器释放，退出137是收尾终止结果；不能将0样本当成Skill负收益，也不能继续报告其运行中。
已修复私有启动器的环境继承；CPU `ap-ZD6VP0saUnKwDchdOAtqNE` 在实际devbox镜像上跑通40题`_prepare_output`新建及resume，0 Actor/Judge调用。
恢复尝试保留原Runtime、数据、库和7+1配置；原失败状态、日志和source脚本保留，恢复状态另存`node0/driver_status_attempt2.json`，控制文件在`attempt2_envfix/`。
当前已完成：历史聚合与Train80原件重审、24库机械验收、新面板冻结、首80个新有效评分题次（40个不同题）及完整配对。8H100已释放。
进一步只读核验3个有分差Train的Global公开输入/终答：两个退步输入明确为open-ended比较、没有Options列表，仅有Video A/B源标签；唯一改善输入有显式A/B/C/D选项并要求单字母。
该观察定位到一个具体入口适用性错误，不依据视觉GT判断过程真假。新入口只改`when_to_use`，明确要求问题有带标签的候选答案列表，区分视频标签和答案选项；meta和全部strategy逐字不变。
新库SHA `35fbe7b62f2fb0ba9dd1e20915289f46b7e5f4669f81816cdb68cd26e7f49b77`，见[谱系](../src/mvagent/skills/skill_sets/manual-study-20261030/entry_refinement.json)及[中文镜像](manual-study-skills-zh.md)。首Train40结果如下，其他覆盖仍待测。

### when-only修订：首40题开发信号

CPU `ap-zqQGGWJrSFGzbyUv6hbvN8` 通过自检、120份raw逐SHA、完整运行/评分身份及官方分复算；结果为新卷`skill_evidence_20261030/phase2-analysis-20261030-195314/`。

| 同一Train40条件 | 官方总分 | 相对空库 |
|---|---:|---:|
| 空库（复用） | 39.45055% | — |
| 原G2 paragraph（复用） | 39.64286% | +0.19231pp |
| 只改when，strategy/meta不变 | 41.95055% | +2.50000pp |

新when对原入口为2改善/0退步/38同分，+2.30769pp；对空库为1改善/0退步/39同分，+2.50pp。题内分层配对bootstrap（seed0，1000次）的探索区间分别为[0,5.00]和[0,7.50]pp。40题中35个声明来源组，但PI仅1组；来源组bootstrap只有554/1000次包含全部十任务，因此不报告有误导性的来源区间。
新入口自然选中20/40，原入口17/40；**把必要前提写得更明确不保证选中率单调下降**。新入口确实注入51次Global决策；相对原入口8题取证参数变化、3题动作序列变化、4题终答变化。具体路由与同请求响应核对如下，不能将全部变化仅归为排除两个已知误选。
后续CPU `ap-rd3buMV7nL2xHoeFSVXVC8` 核实：旧→新有6题none→selected、3题selected→none、14题仍selected、17题仍none。9个路由变化输入中，新增6题都有显式候选答案列表，退出3题为无列表开放比较。共同14个selected和17个none的取证参数与终答全部一致；两条件86个相同Global Actor请求body SHA对应的响应文本均一致。参数/答案变化均落在路由改变的9题内，支持本次入口通过路由起作用的解释，仍不等于已证明局部视觉取证正确或所有适用性错误均已修复。
这是从同一Train40诊断后修订再测的结果，不是未接触数据的确认。小样本、适应性选择、区间含0及来源覆盖限制都保留；不称Cal接受、稳定提升或自动进化成功。

### 首个程序与等句排版对照：保留负结果

CPU `ap-AOGlmHzDyTJC8AcgNVpmii` 完成首个匹配排版单元核验，产物`formats-analysis-20261030-200748/`。同Train40的依赖闭合paragraph为32.43678%，numbered为32.30769%，空库39.45055%。paragraph对空库2改善/5退步，−7.01377pp；numbered对空库0改善/4退步，−7.14286pp。
numbered对paragraph为1改善/3退步/36同分，−0.12908pp，探索95%题分层区间[−7.62908,7.38889]pp；不能据此判断排版优劣。两者40个完整Selector输入全部相同、选卡全部相同（11题选中、29题none），但10题取证参数、8题动作序列、6题终答变化。这是正文执行差异，不是Selector对排版的偏好。该程序首测负向，不筛掉预定其他排版或程序；其适用性与执行原因仍需合法Train轨迹诊断。

下一批预声明：冻结Train轮换前120个不同题，3批各40，每批空库＋8个原段落程序＋1个新入口，共最多1200评估题次。
其中首80严格按身份与rawSHA复用，计划新增最多1120；CPU `ap-2fMCvejIZPHGNxRqsD2qHh` 已直接调用现有Evaluator的缓存分支验证80复用、0新rollout/0Judge，并校验新卡仅when不同。
第一批先核两缓存，再测新when，随后其余7个程序；后两批10库均自然评估，不按Train高低筛。伙伴角色固定空库，不查询Cal/Gate。
单节点8H100，最多4小时，2小时后停止派发新40题单元、保留收尾；未完成标unfinished，不填零分。120题有历史接触及来源相关，不称统计独立。
本批已于19:26 UTC提交，节点`sb-ixcudMa83Y9DvDLj6ePJkO`；7个Actor约225秒就绪，实际模型、profile与缓存关闭已核验。19:51新入口40题完整评分，开始跨视频依赖程序；截至该单元共有120有效评分题次、40不同题，不能把题次称为独立样本。
状态写入新卷`skill_evidence_20261030/phase2/driver_status.json`；只有完整40题的`evaluation.json`计入机制比较，半成前缀另报进度。
直接媒体重放的两个早期探针失败：先误读旧失败状态，后发现`_safe_event`把data URL脱敏为SHA和长度，不能把对象当Base64。后续按冻结函数重建并通过URL与完整请求双重SHA门禁后完成上表CPU处理；早期失败产物保留，不用猜测路径替代原请求。
排版诊断先冻结范围：沿用前120个Train题及原24库，3批分别评估空库与8机制×3排版，共3000评估题次；所有已完成且身份一致的结果直接复用，部分raw继续恢复，不重跑首80。新when修订单独分析，不混入等句排版比较。
19:48 UTC按实测吞吐调整执行依赖：当前新入口40题在约4分钟得到22份raw，原2小时派发窗口可能不能完成机制矩阵，逐节点串行也会延后排版数据。由同一主执行者准备独立8H100排版节点，只运行全部numbered与headings，共1920新增题次；empty/paragraph仍只读复用机制节点，不重新提交。两个节点、各自Judge及待分配资源合计最多16H100，符合当前日间上限；分配前核已知节点和所有本项目GPU app，拒绝未知占用。
排版节点使用独立`format/batch0..2`结果与Judge缓存，避免并行改写相同文件；split内容、Runtime、源码、执行设置与研究身份保持原样。每批固定先全部numbered，再全部headings，不按Train得分挑程序。仅在同机制、同题、同入口的完整共同单元上比较，伙伴为空。
排版CPU `ap-XwBEkTyD7z0NexWwAyvyyq` 已核48个单元的样本顺序、库与评估身份，0 Actor/Judge调用。节点于19:50 UTC启动，`sb-z8nM7ciTzCmTCRW4ekjhXz`，与机制节点合计16H100；截至19:55加载Judge。计划4小时新单元派发窗口、6小时分配上限；已完成参考若仍缺测则明确保留missing，不据此前缀宣称完整比较。它是用户要求的手工开发诊断，尚无排版优劣结论。
后续启动条件、步骤、排版与充分覆盖仍未完成，整体研究目标继续进行。
步骤写法另预登记8个compact候选：[谱系与资源](../src/mvagent/skills/skill_sets/manual-study-20261030/step_refinement.json)、[完整中文镜像](manual-compact-skills-zh.md)。它们仅改strategy，继承原meta/when，以paragraph保留核心程序及边界，缩减重复工具字段说明；原strategy193–224词，新129–149词。长度与步骤展开共同变化，不作为纯排版对照或完全语义等价改写。
全部8个子库在相同前120题逐批自然评估，最多960新题次；所有对照直接复用同身份空库/原paragraph。CPU `ap-eVMNo2RbjArmR9pBCGSWKO` 已通过原生parser/render/word计数、SHA、仅strategy变更与120题计划检查，0 Actor/Judge/GPU；描述文件SHA `4c27e4ad09e8920faafe7a02012190b69377199f9671afe0c5ea09e6cb6721e5`，资源已存新卷`cards/`，`compact/preflight.json`为prepared_not_submitted。待现有节点释放并核资源上限后再分配，预算为单8H100、3小时新单元派发/4小时分配，未完记缺测。目前未提交，不按已测Train分数筛掉任何子库。
单卡试验尚未测库内竞争与两角色耦合，另冻结3个八卡组合：原8paragraph、仅替换G2新when、原when的8compact。所有执行文字均按来源复制，只按机制顺序把引用ID唯一重编号1–8；每角色4候选，不触发embedding。来源与中文映射见[组合说明](manual-combined-skills-zh.md)及[谱系](../src/mvagent/skills/skill_sets/manual-study-20261030/combination_manifest.json)。三库全测同120题，最多360新题次，预备单8H100、2小时派发/3小时分配；尚未原生parser验收或提交。它们不是单卡内容干预，也不作为正式空库进化的种子。

### 手工整库确认约定（Cal/Gate尚未执行）

最初单卡资源从一开始就是Train机制诊断，不追认为自动搜索提案或接受结果；其排版、入口和步骤归纳保留Train范围。另冻结的三份完整双角色库A/B/C是本手工阶段的确认候选，**三者全部进入完整Cal400**，不根据Train成绩筛选，也不把确认结果用于改写卡片或Meta。

| 本手工包 | 最大问题rollout题次 |
|---|---:|
| 33单卡诊断＋3整库＋共享空库，各同120题 | 4440 |
| 三整库＋空库，各完整Cal400 | 1600 |
| 条件性Gate：唯一冻结库＋空库，各400 | 800 |
| 总计上限 | **6840** |

上述题次含首80的严格缓存复用，实际新派发扣除已成功结果；历史系统重分析和CPU媒体重放不新增模型回答。不同条件重复同题不算新增独立样本。这个手工包不是8轮自动进化的执行，optimizer API仍0；题次上限没有超出研究文件8560题次的预算量级。
Cal仅以完整官方总分选择：A/B/C最高者必须严格高于空库才保留，同分候选按冻结A→B→C顺序唯一选定。若无严格提升，保留空库，不为生成结果重复运行Gate。选定后冻结唯一库，再比较其与同协议空库的完整Gate；失败不换候选试Gate、不按Gate错题改卡。报告配对不确定性和来源限制，微小正差不称稳定泛化；目前没有确认通过。
Cal节点准备采用两组8H100，各负责固定两个400题单元；维持总占用不超过16，启动前核所有已知节点已释放及当前本项目占用，未知占用直接停止分配。原预算、自然none、固定模型/媒体/评分与结果留Modal规则保持。
完整模型回答、媒体、权重和生成结果不进入Git或Lightsail；本机保留源码、Markdown与私有控制脚本。研究目标尚未完成。
