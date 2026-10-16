# Video-RSI / VAM：本地 Qwen 评测

2026-10-15 用户最新确认：Video-RSI单次HTTP等待改为600秒，VAM保持原240秒。两方法保留原项目图像设置、多视频拼接、两位小数时间说明和通用答案适配；不因重复输出改动原提示词、采样或输出预算。MetaVideoAgent不测。65题RSI/3题VAM的原图像批次已完成，冻结结果目录devbox/external_original_images_20261015仍记录当时的1860秒；后续运行使用新目录。

VAM相同65题扩样已完成：新结果`devbox/external_vam65_20261015`，64题成功评分、TR1586一题因原模糊过滤后零帧而失败。Cross/CV/MVU官方口径子集分15.00/7.45/33.44%，RSI对应35.72/56.00/67.24%；失败独立列出，共同64题复核分数不变。RSI复用已评分65题并注明历史实际HTTP1860秒，所有历史RSI请求均低于600秒。评分、审计及资源释放已完成，详见[最终报告](../../outputs/external_vam65_20261015/README.md)。

## 原始设置与实际设置

`sources.json` 固定上游 commit，`upstream_settings.json` 保存原始配置、关键源文件 SHA256 和 VAM 各调用点的温度/token 上限。它是原始设置的审计基准，不能替代远端实际生效证据。

| 项目 | 当前约定 |
|---|---|
| RSI 规划 / 视觉输出上限 | 均直接读取原配置的 8192 |
| RSI 步数 / 服务调用 / 帧暴露上限 | 原版 11 / 64 / 256 |
| RSI 温度 / HTTP 超时 / provider 重试 | 0 / 600 秒 / 1 次重试；仅 HTTP 等待由用户批准从原版 240 秒延长 |
| RSI 抽帧 | 原版串行流程、宽度768、保持比例 |
| VAM 输出上限 | 原调用点的 220、300、500、700 等；不注入统一 2048 fallback |
| VAM 温度 | 原调用点的 0、0.1、0.2 |
| VAM HTTP 超时 | 原聊天请求240秒、连接60秒；Embedding请求60秒、连接10秒 |
| VAM 采样、过滤、记忆、检索 | 原版流程与默认参数；视频采样默认 0.5 fps |
| VAM 图像限制 | 原版1280×1280像素面积、5MB；没有额外448覆盖 |
| Actor | 两方法的语言/视觉角色均替换为本地 Qwen3.5-35B-A3B |
| Embedding | 本地Qwen3-VL-Embedding-8B（仓库默认；论文用Gemini Embedding 2）；原VAM请求结构与批次边界，官方默认1800×32×32像素上限 |

RSI 复用上游 `PinnedProvider.chat`，VAM 复用上游 `OpenRouterClient._chat_impl` 与 embedding 客户端。审计钩子只记录实际请求和耗时。RSI本地HTTP等待现为600秒；上游240秒记录仍保存在审计基准中，整题1800秒预算、服务端1800秒时限及1次重试不变。VAM的时限不变。HTTP等待缩短不意味着服务端会自动取消已经开始的生成。VAM embedding请求改为本地端点；当前仓库与论文的Embedding模型不同，不声称论文模型与本地向量等价。

VAM 使用原 TUI/WebSocket 的 `vam.agent.stream_agent_response`：先经顶层路由器选择检索、总结或直接回答，再执行原工具流程。视频帧ID前缀恢复原版 `v`，索引状态轮询恢复TUI的0.25秒。每题使用独立记忆库和空会话，避免跨题污染。

2026-10-15复核更正：旧3题实际Actor与Embedding均已启用448面积限制，之前“漏用448”的说明错误。旧适配器真正跳过的是顶层路由，直接调用了 `search_generator`；旧结果仅代表这一内部检索入口，不计为完整原版VAM。当前源码已修正，新复测另行冻结。

每题保存 `effective_config.json`、`service_card.json`、`requests.jsonl`、`result.json` 和 `execution.json`。模型服务另存模型/权重/数值配置与源码身份。原始输出先落盘，再由 `score.py` 调用共享官方评分协议。正常格式错误与运行故障分开报告。

`native_server.py` 是独立的外部方法入口：保留 BF16、单卡单请求、seed=0、thinking/prefix cache 关闭和原固定数值后端，但允许原方法指定非零温度，接受 RSI 的原生 `thinking=disabled` 请求字段。它使用单独的 `qwen35-bf16-external-upstream` 身份；不是既有只接受 temperature=0 的固定评测端点，不混用旧轨迹。

## 明确保留的适配

- 多视频按题目顺序拼接为一个视频，prompt 开头明确说明多视频任务及拼接方式；各视频起止时间保留两位小数，内部记录保留完整精度。题目及最终回答的时间指向原视频坐标。
- RSI 原版只接受单个选项；用户明确保留非空字符串的通用答案适配，以支持多选、排序、定位、数字和自然语言。没有改变工具策略或技能库。
- RSI抽帧Services恢复上游原文件，宽度768；VAM读取原版1280²/5MB图像设置，Embedding也不覆盖官方默认。外部方法模型服务移除共享MVAgent的448宽高提示；共享MVAgent服务文件和其他实验不变。
- RSI仅将HTTP等待改为600秒。历史240/1860秒批次保持各自冻结配置；已完成的65题结果不改写为600秒测量。
- 本地模型端点、Python/OCR 路径、VAM 临时文件路径按 Modal 环境调整。Modal 缺少 Landlock，RSI 保留 candidate seccomp 与外层 Sandbox，但不具备上游相同的文件系统 fence。
- VAM 的原始缺失 `re` 导入补丁保留。这些运行环境修正均列入有效配置，不能称为逐字未改的上游代码。

65题RSI和3题VAM已完成原图像协议重跑、评分和审计，复用已校验的拼接媒体（含修复NC80），未复用448协议答案；结果为final_summary.json及report.md。当前调用检查与600秒最小冒烟使用独立目录devbox/external_call_audit_20261015_r2；首次诊断脚本初始化错误及其CPU证据保留在不带r2的目录。

600秒验证已完成：CV764返回B、83.38秒、3调用；另重放CV722不合格视觉请求，其输入与244个输出token逐一匹配旧记录，仍未遵循JSON要求。共4次实际响应审计通过，0请求错误；未发现模板、thinking开关、上下文截断或EOS漏停问题。按用户要求保留原提示词与生成参数，不以改善格式为由加约束或惩罚。[检查详情](../../outputs/external_original_images_20261015/call_settings_audit.md)。

## 客户端依赖

两方法使用独立依赖目录：`/runs/devbox/external_methods_20261014/support/upstream_clients_20261015/{rsi,vam}`。RSI逐项匹配原`requirements-lock.txt`的22项固定版本；VAM满足原`pyproject.toml`的13项适用要求，包括NumPy 1.26.4和OpenCV 4.10.0.84。`run_batch.py`仅为客户端子进程设置相应目录，并保存`client_environment.json`；模型服务继续使用固定Qwen环境，不向其注入两套互相冲突的客户端库。旧环境13/22项不匹配RSI锁文件，且NumPy/OpenCV不满足VAM约束，不能称为原环境复现。

## 视频准备

拼接不缩放、不补边、不改 FPS。相同 H.264 或 MPEG-4 编码走 stream copy；混合/其他编码走逐片段无损 H.264 统一，像素格式不支持时直接报错。原始音频不提供给这次视觉理解评测。

2026-10-15 扩样发现，部分 H.264 视频在串流完整、PTS 正确的情况下，拼接后随机 seek 仍会用错后续片段的解码参数。当前准备器在每段的每个关键帧重复 SPS/PPS，再拼接；CVBench432 的实际失败位置及另外五个位置已解码成功。旧 `prepared_r2` 媒体不能因包数/PTS 校验通过就当作任意 seek 已验收。

每帧 PTS 仍须匹配到 2 微秒；旧 FFmpeg 的 MP4 movie 时钟导致末尾时长元数据可以有小于 1 毫秒的舍入，单独记录，不放宽帧数或 PTS 检查。混合编码或含隐藏解码预滚帧时，以同一 PyAV 解码器逐帧无损转为 H.264，再拼接；不改变显示帧、尺寸或帧时间。5 类合成输入共 353 帧及 15 个 seek 已通过像素、尺寸、格式和时间检查。NC80 的实际长视频另行修复验证，原输入的推理结果不进入最终汇总。

`prepare.py --selection <selection.json>` 保持原抽样。原始 33 题为各原生任务一题，seed=0；扩大面板原定 66，首轮因 NC808 混合编码准备超时排除该新增题后为 65（CrossVid19/CVBench30/MVU16），不补抽。开发面板不能当作独立 Test 或全量 benchmark 成绩。

## 耗时与执行

- 媒体 metadata 记录 `preprocessing_seconds`。
- `requests.jsonl` 记录每次模型请求的实际输入/输出和 HTTP 耗时；服务审计记录处理耗时与完整 token。
- `result.json` 记录 Agent 内部耗时；VAM 另记录索引与查询耗时。
- `execution.json` 记录整题墙钟；`progress.json` 记录整批墙钟、逐题均值/中位数/最大值。
- 模型启动单独计时，不混入逐题推理时间；完整评测还应单列评分时间。HTTP 请求有重叠时，不把耗时之和当作墙钟。

所有重负载经 `mvagent-environment` skill 和 `modal-gpu` dev box 放到 Modal。`freeze.py` 保存不可变源码、配置与适配补丁；`run_batch.py rsi|vam` 必须连接上述外部方法专用服务。模型与数据、原始请求和结果只保存在 runs volume；Lightsail 仅保存源码和 Markdown 报告。

此前 2048 对照 `devbox/rsi_budget_20261015_r2` 已因随机 seek 故障及错误路径进入 prompt 被标记无效并停止，未完成准确率评测；随后用户又明确恢复原项目预算。该目录与历史速度实验保留为证据，不能混入本次按原参数测试的结果。

代码备份分支为 `codex/external-methods-prompts-20261014`。共享工作区其他推理/runtime 改动不属于此分支；精确恢复实验以 Modal 冻结快照为准。

## 后续基线选择调研（2026-10-16）

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

LensWalk实读release=`c3cdf13a6ffc6b1ce21af3a0c7813178d17fac77`；`finish.answer`为string，批处理支持开放题分支。论文描述20次工具调用，当前发布入口默认5轮并限制scan次数，subject registry可选；部署前必须区分论文配置与公开代码默认，冻结采用的版本，不能声称二者逐项相同。[论文](https://arxiv.org/html/2603.24558v1)、[工具schema](https://github.com/likanchuan09171/LensWalk/blob/release/tool_configs/vcs_standard.yaml)、[评测入口](https://github.com/likanchuan09171/LensWalk/blob/release/eval/infer_bench_summ_vcs.py)

多视频优先考虑[AgentCVR](https://github.com/wang-jh24/AgentCVR)（实读main=`568b402c51254a04149d49d0bc4ad7c9d2fcf2f1`）：Master调用视觉与Whisper音频工具，支持CrossVid十类，Master经脚本模拟GRPO训练；4B/8B是论文训练模型规模，不是Python框架只能使用这些规模。代码端点可配置，也允许off-the-shelf Master。统一Qwen3.5对比应标记为AgentCVR architecture / w/o RL；完整训练版需使用原checkpoint。仓库README、releases及Hugging Face模型检索本次未找到可下载的官方AgentCVR训练权重，不把“论文有4B/8B”写成“权重已发布”。论文8B架构未RL 37.20%、完整RL 42.03%的CrossVid结果说明两者不能混称；不同模型/音频配置下的论文分数不可与本项目小样本直接比较。[论文及消融](https://arxiv.org/html/2605.29643v1)、[运行文档](https://github.com/wang-jh24/AgentCVR/blob/main/agent_system/README.md)

[AdSeek](https://arxiv.org/html/2610.03099v1)是多视频电商比较Agent，Qwen3-VL-8B策略＋4B视觉工具＋Whisper，使用RL→轨迹修正SFT→RL。可作为领域训练系统的补充，但本次未核实到官方代码/权重下载入口；混合训练明确使用MVU-Eval视频和AgentCVR脚本，不能直接把该checkpoint的MVU-Eval成绩当作独立测试。若可获得AdsCVR-only checkpoint与训练清单，才优先考虑无重合子集。论文CrossVid 31.55与其AgentCVR复现28.24，和AgentCVR原论文42.03来自不同实验，不作跨论文排名。

AgentCVR现成评测入口针对CrossVid十类，各自读取`master_BU.prompt`、`master_FSA.prompt`等专用提示；默认构造器引用的`master_autonomous.prompt`未在当前源码树中提供。扩展到CVBench/MVU-Eval需要明确的数据入口和提示适配，不能称三个benchmark原生开箱即用。原版音频工具与本项目视觉输入权限不同：主表如禁用音频须标记vision-only消融，保留原版音频的系统成绩单列。

推荐主比较统一Qwen3.5及官方评分，保留各方法原策略/预算并披露适配：E2E原多视频、E2E拼接、RSI拼接、AVP拼接、MVAgent空库/skill库；资源允许时加入LensWalk和AgentCVR w/o RL。完整AgentCVR或AdSeek使用独立的原模型系统表，注明训练数据、额外视觉模型及音频权限。对原生多视频方法保留独立视频和各自时间轴，不强制拼接。费用同时报逐题耗时、GPU资源、模型调用、输入/输出token、视觉帧数和运行/格式失败；冷启动索引与可复用索引分别计时。该建议未自动转成新的实验任务。
