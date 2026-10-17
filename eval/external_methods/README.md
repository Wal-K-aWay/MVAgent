# Video-RSI / LensWalk：本地 Qwen 评测

2026-10-16 用户明确退役 VAM，删除其活动适配器、独立视觉 embedding 服务/下载器、补丁及过时运行入口；保留历史原始答案、评分、报告和冻结实验快照。LensWalk 已完成本地 Qwen3.5-35B-A3B 的小规模接入验证，并按用户要求提交三 benchmark 完整评测（CV997/MVU1824/CrossVid2500）。AVP/AgentCVR 尚未接入，MetaVideoAgent 不测。

## VAM 清理

已从 Modal runs volume 删除 VAM 专用 `Qwen3-VL-Embedding-8B`（16,305,638,705 字节）及其独立客户端依赖目录（403,485,886 字节），合计 16,709,124,591 字节。删除前确认四个旧外部实验 Sandbox 全部退出；审计与下载/依赖 manifest 保留在 `devbox/vam_retirement_20261016`。本机和 modal-gpu 活动源目录的 Visual-Agentic-Memory/Qwen3-VL-Embedding 克隆也已清理。

共享 Qwen3.5 Actor、MVAgent 的文本 `Qwen3-Embedding-8B` 和 Judge 权重均保留。历史 VAM 结果见[65题报告](../../outputs/external_vam65_20261015/README.md)；历史结果分析脚本可以继续读取已保存数据，但不再有 VAM 推理入口。

## LensWalk 接入设置

上游固定为 release commit `c3cdf13a6ffc6b1ce21af3a0c7813178d17fac77`，见 `sources.json`。`lenswalk.py` 调用完整的原评测入口，Planner/Observer 的 System/User prompt、工具与采样逻辑保持原版；只增加 inference-only 评分开关，先保存答案，再交由本项目官方评分器处理。题面已经包含选项，不重复追加；参考答案不进入 LensWalk 推理文件。

| 项目 | 本轮设置 |
|---|---|
| 运行策略 | 仓库代码默认最多5轮，扫描次数限制关闭，subject registry关闭，字幕关闭，初始直接帧注入关闭；本轮逐题batch_size=1（上游15），workers=8保留 |
| 观察工具 | 原版 scan / segment / stitched；默认帧预算180 / 32 / 128，原版最长边512，无额外448限制 |
| 生成参数 | Observer显式temperature=0.2；Planner未指定温度；两者都未指定输出token上限。保留原请求，缺省值由标准vLLM API规则解析（默认temperature=1，输出最多剩余上下文），不套用MVAgent的2048或RSI的8192 |
| 本地模型 | Qwen3.5-35B-A3B，BF16/H100/TP1/C1，seed=0，thinking与prefix/MM cache关闭；同一题固定单个模型副本 |
| 工具接口 | 独立 `lenswalk_server.py`，复用固定数值后端及官方qwen3_coder工具解析器，仅解析时展开本地schema引用，模型看到的工具schema不变；完整原始文本、token、输入hash和实际生效采样参数落盘 |
| 时限 | 本地服务单请求600秒；冒烟执行器单题1800秒，超时单列，不改写为错误答案 |
| 客户端 | 按上游Python>=3.9,<3.12建立独立3.11环境；模型服务保留已验收的3.12环境，各自版本清单留档 |
| 输入 | 复用已验证的原视频拼接，不缩放、不补边、不改FPS；提示说明多视频任务和各视频起止位置，时间两位小数，终答使用原视频坐标 |

论文20次工具调用与公开代码默认5轮不是同一个设置。本次验证采用仓库默认，不声称复现论文的全部配置或分数。未指定的云API默认值无法证明与本地数值实现完全等价。

6题接入验证已完成：5个终答（4次finish、1次自然文本），1个未完成工具计划；138响应、0 HTTP错误、0token截断，2次互斥工具参数错误后自行恢复。累计整题18.34分钟，另模型启动44.03秒。覆盖选项、排序、时间定位和开放回答；不是完整benchmark成绩。

有效结果为`devbox/external_lenswalk_20261016_r3`，此前两轮接口失败原件保留。实验GPU已释放，开放题未启动Judge。逐题输出、分数、耗时、设置与局限见[完整报告](../../outputs/external_lenswalk_20261016/README.md)。

全量任务目录为 `devbox/lenswalk_full_35b_20261016`，使用8个独立H100副本及固定题目清单，自动续跑并在推理后评分。2026-10-16 08:24 UTC已处理216/5321，当前CV53.49%、MVU29.69%、Cross九类macro20.19%，8题CCQA待Judge；样本小且完成顺序有偏，不能视作全量成绩。长视频无损预处理正在拖慢进度；[运行说明与统计口径](../../outputs/lenswalk_full_35b_20261016/README.md)。

## Video-RSI 保留的设置

原版8192规划/视觉输出token、11步、64次服务调用、256帧、temperature=0、串行抽帧宽768保持比例、provider重试1次；仅本地HTTP等待为用户确认的600秒。保留通用非空答案适配、原生多视频拼接及两位小数时间说明；Modal没有Landlock，candidate seccomp与外层Sandbox保留。完整原始配置/源文件哈希见 `upstream_settings.json`。

客户端复用 `support/upstream_clients_20261015/rsi`；22项依赖与上游锁文件一致。Actor服务是单独的 `native_server.py`，不连接 LensWalk 工具服务；历史65题实际HTTP上限1860秒，所有468次请求低于600秒，不能把历史测量改写成新600秒批次。

## 入口与数据

- `freeze.py`：冻结源码、源版本与补丁。旧结果的恢复只使用旧冻结源码。
- `prepare.py --selection ...`：使用已有选择清单，拼接媒体并生成题目和时间轴。
- `run_batch.py rsi|lenswalk ...`：一题固定一个副本；LensWalk通过 `--client-python` 指定独立3.11客户端。
- `lenswalk_full.py`：完整5321题、媒体复用、逐题原始归档、断点续跑和官方评分；结果类型单列未收尾与基础设施失败。
- `score.py`：原始答案落盘后使用官方评分；缺少Judge的开放题显式待评，运行失败单列。
- `experiments/20261016/lenswalk_smoke.py`：本轮CPU准备及GPU小测；`test_lenswalk_transport.py`检查原生工具参数、开放答案和API缺省规则。

模型推理、依赖安装与完整检查经modal-gpu放在Modal。原始结果只保存在runs volume；本机保留代码与Markdown。当前备份分支 `codex/lenswalk-20261016`；其他会话改动不属于本工作项。

## 基线选择调研历史（2026-10-16，执行范围以上方最新决定为准）

本次只调研论文/官方源码并分析既有结果，没有替换方法或启动新推理。旧版MVAgent同题63条与RSI的比较见[结果报告](../../outputs/external_vam65_20261015/README.md#与旧版-mvagent-的同题比较2026-10-16)：准确率各有胜负，RSI耗时更高；当前直接回答协议只有一题交集，不能据异题分数排名。

建议保留RSI，以AVP替换VAM作为主要单视频主动理解对照；若能增加一个方法，优先LensWalk。VAM的定位是持续在线索引、层级记忆与回溯检索，论文评测OVO-Bench及月尺度MM-Lifelong；当前每题独立建库的一次性离线QA不体现其记忆复用价值，低分本身不是排除基线的依据。[VAM论文](https://arxiv.org/html/2605.16481v1)

| 候选 | 核心设计 / 当前公开状态 | 对本项目的建议 |
|---|---|---|
| [AVP](https://github.com/SalesforceAIResearch/ActiveVideoPerception) | 免训练的plan–observe–reflect；3轮、阈值0.7；官方提供并行评测与错误重试 | 优先替代VAM；保留多视频拼接。需适配Gemini原生视频/分辨率接口及通用答案 |
| [LensWalk](https://github.com/likanchuan09171/LensWalk/tree/release) | 免训练reason–plan–observe；扫描、局部精看、非连续片段拼接复核；现成兼容API接口与并行入口 | 最值得增加的第二个主动单视频基线；终答工具接收开放字符串，接口迁移比AVP直接 |
| [DVD](https://github.com/microsoft/DeepVideoDiscovery) | 多粒度描述数据库＋迭代工具检索；有正式复现材料 | 可作为不同机制的检索型补充，但建库耗时要计入；公开版明确有别于论文的global_browse实现 |
| [VideoTree](https://github.com/Ziyang412/VideoTree) / [VideoAgent](https://github.com/wxh1996/VideoAgent) | 公开的经典自适应树表示 / LLM主动检索框架 | 可作历史参考；已有RSI后，新增优先级低于AVP、LensWalk |
| [PACE](https://github.com/HKUST-KnowComp/PACE) | 问题条件索引＋利用选项差异检索验证；有Qwen3-VL实验 | 较新的强选择题候选，但依赖候选答案，不适合作为覆盖CrossVid开放题/排序/定位的唯一基线 |
| [VCA](https://arxiv.org/abs/2412.10471) | 好奇心驱动树搜索、模型自评奖励 | 方向合适，本次未找到可确认的作者官方实现，不优先自写复现 |
| [LongVideoAgent](https://github.com/longvideoagent/LongVideoAgent) | RL训练Master，字幕定位＋视觉观察；代码/权重已公开 | 更偏影视/字幕场景，替换训练Master不能代表完整方法，不是当前视觉主表首选 |
| [VideoExplorer](https://github.com/RUC-NLPIR/VideoDeepResearch) | 规划、定位、感知循环，SFT＋轨迹偏好优化 | 属于训练过的Agent，不能把任意Qwen接入当作原版；还需权重与数据核对 |
| [VideoXAgent](https://github.com/go-agent-x/VideoXAgent) | 按问题即时探索，43个MCP服务覆盖视觉/音频/OCR等 | 比较通用，但工具依赖重、模态不同，示例配置自称不等于论文配置；暂不作为最小主矩阵 |
| [LongVU](https://github.com/Vision-CAIR/LongVU) / [LongVILA](https://github.com/NVlabs/VILA/tree/main/longvila) | 原生长视频压缩 / 长上下文模型，提供权重与评测入口 | 可作异模型系统补充；其视觉结构和训练权重是方法的一部分，无法直接换成Qwen3.5而保留原方法 |

AVP实读main=`a2b6f2854ee4232be5ce49fe07a02691e413a8df`。论文默认Gemini-2.5-Pro，也报告Qwen3-VL-8B；low/medium的66/258视觉token每帧属于Gemini语义，不能直接当作Qwen像素大小。当前代码给low 512帧、medium/high 128帧；多数调用依赖SDK生成默认值，并非所有参数均可与本地服务一一等价。另`MCQ_SCHEMA.selected_option`枚举A–F，`extract_answer`优先提取该字段；README称可不提供options，但覆盖多选/排序/时间定位/开放QA仍需明确的通用答案适配。[论文](https://arxiv.org/html/2512.05774v2)、[schema](https://github.com/SalesforceAIResearch/ActiveVideoPerception/blob/main/avp/prompt.py)、[提取器](https://github.com/SalesforceAIResearch/ActiveVideoPerception/blob/main/avp/eval_dataset.py)

LensWalk实读release=`c3cdf13a6ffc6b1ce21af3a0c7813178d17fac77`；`finish.answer`为string，批处理支持开放题分支。论文描述20次工具调用，当前发布入口默认5轮，scan次数限制默认关闭（启用后默认1次），subject registry可选；部署前必须区分论文配置与公开代码默认，冻结采用的版本，不能声称二者逐项相同。[论文](https://arxiv.org/html/2603.24558v1)、[工具schema](https://github.com/likanchuan09171/LensWalk/blob/release/tool_configs/vcs_standard.yaml)、[评测入口](https://github.com/likanchuan09171/LensWalk/blob/release/eval/infer_bench_summ_vcs.py)

多视频优先考虑[AgentCVR](https://github.com/wang-jh24/AgentCVR)（实读main=`568b402c51254a04149d49d0bc4ad7c9d2fcf2f1`）：Master调用视觉与Whisper音频工具，支持CrossVid十类，Master经脚本模拟GRPO训练；4B/8B是论文训练模型规模，不是Python框架只能使用这些规模。代码端点可配置，也允许off-the-shelf Master。统一Qwen3.5对比应标记为AgentCVR architecture / w/o RL；完整训练版需使用原checkpoint。仓库README、releases及Hugging Face模型检索本次未找到可下载的官方AgentCVR训练权重，不把“论文有4B/8B”写成“权重已发布”。论文8B架构未RL 37.20%、完整RL 42.03%的CrossVid结果说明两者不能混称；不同模型/音频配置下的论文分数不可与本项目小样本直接比较。[论文及消融](https://arxiv.org/html/2605.29643v1)、[运行文档](https://github.com/wang-jh24/AgentCVR/blob/main/agent_system/README.md)

[AdSeek](https://arxiv.org/html/2610.03099v1)是多视频电商比较Agent，Qwen3-VL-8B策略＋4B视觉工具＋Whisper，使用RL→轨迹修正SFT→RL。可作为领域训练系统的补充，但本次未核实到官方代码/权重下载入口；混合训练明确使用MVU-Eval视频和AgentCVR脚本，不能直接把该checkpoint的MVU-Eval成绩当作独立测试。若可获得AdsCVR-only checkpoint与训练清单，才优先考虑无重合子集。论文CrossVid 31.55与其AgentCVR复现28.24，和AgentCVR原论文42.03来自不同实验，不作跨论文排名。

AgentCVR现成评测入口针对CrossVid十类，各自读取`master_BU.prompt`、`master_FSA.prompt`等专用提示；默认构造器引用的`master_autonomous.prompt`未在当前源码树中提供。扩展到CVBench/MVU-Eval需要明确的数据入口和提示适配，不能称三个benchmark原生开箱即用。原版音频工具与本项目视觉输入权限不同：主表如禁用音频须标记vision-only消融，保留原版音频的系统成绩单列。

推荐主比较统一Qwen3.5及官方评分，保留各方法原策略/预算并披露适配：E2E原多视频、E2E拼接、RSI拼接、AVP拼接、MVAgent空库/skill库；资源允许时加入LensWalk和AgentCVR w/o RL。完整AgentCVR或AdSeek使用独立的原模型系统表，注明训练数据、额外视觉模型及音频权限。对原生多视频方法保留独立视频和各自时间轴，不强制拼接。费用同时报逐题耗时、GPU资源、模型调用、输入/输出token、视觉帧数和运行/格式失败；冷启动索引与可复用索引分别计时。该建议未自动转成新的实验任务。
