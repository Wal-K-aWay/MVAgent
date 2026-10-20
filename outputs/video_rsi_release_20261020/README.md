# Video-RSI 35B结果

[GitHub Release：video-rsi-results-20261020](https://github.com/Wal-K-aWay/MVAgent/releases/tag/video-rsi-results-20261020)

本批为Video-RSI已发布的final_harness与其skill策略接本地Qwen3.5-35B-A3B，三个benchmark共5321题：CVBench997、MVU-Eval1824、CrossVid Lite2500。239道CCQA已由原本地Qwen3-30B-A3B-Instruct-2507 Judge评分；本次仅整理保存结果，不重新推理或评分。

参照MVAgent、AgentCVR、LensWalk，包内仅五个文件：`cvbench.jsonl`、`mvu_eval.jsonl`、`crossvid.jsonl`、`ccqa_scores.jsonl`和纯统计表`statistics.md`。逐题字段为`id`、`gt`、`output`、`seconds`、`trajectory`；CCQA的`gt`同时含参考答案和评分点。原始答案及类型不变，未生成有效答案的null不改写为空字符串或选项。

文本轨迹包含原始决策及修复尝试、技能选择、工具观察、服务调用文本、调用耗时/token数量、终态/错误和源归档SHA256。去掉图片Base64、完整token ID数组、重复HTTP请求/响应体、重复memory副本及运行日志；不含视频、权重和冻结执行环境。完整原件保留Modal，此包用于结果分析，不是逐token重放包。

`seconds`为整题Agent执行用时，包含模型/工具/等待；`trajectory.prepared_seconds`为视频准备，`archive_seconds`为归档，均单列。不含服务启动或Judge时间，也不是并行任务的墙钟总工期。失败已消耗的时间保留。视频准备均值混合继承的缓存命中与后续临时拼接，不能直接用于比较预处理方案速度。

保留5196正常终答、86无效决策、39工程失败。主表工程失败计零，CVBench/MVU按题平均，CrossVid按十任务等权macro、其中CCQA按评分点加权；原始逐题score字段保持原值，工程失败仍为null，统计时才计零。无效决策也保留，不挑选最佳答案。统计表的“空答案”列专指`empty_answer`终态；本批125个null结果分属86无效决策和39工程失败，不归入该终态列。CVBench因损坏视频排除64–66；本面板包含此前开发/调试复用题，不能称为从未接触的独立Test。

模型两种角色均使用本地35B，保留已确认的多视频拼接与两位小数时间说明、通用答案适配、HTTP600秒、Modal Landlock不可用/seccomp保留的差异。其他继承的设置包括：8192输出token、温度0、seed0、11步/64服务调用/256帧、图像宽768、solver1800秒/整题7200秒；H100单卡TP1/C1、BF16、thinking关闭、prefix/MM缓存关闭。原项目的规划模型与视觉模型并非本地Qwen，不能把本批称作论文原模型成绩。

原始来源：runs `devbox/rsi_full_35b_parallel_media_20261018`及其恢复继承记录；导出来源：`devbox/rsi35_release_compact_20261020`。公开包只保存最终续跑结果，历史失败尝试与完整记录留原处。每份源归档/选用成员、答案/GT/耗时/调用计数和压缩包成员均核验。

| Benchmark | 题数 | 评分方式 | 得分（%） | 有最终答案 | 未收尾 | 空答案 | 无效决策 | 工程失败 | 平均Agent用时（秒） | 平均视频准备用时（秒） |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| cvbench | 997 | 官方逐题评分平均；工程失败计0 | 62.39 | 988 | 0 | 0 | 6 | 3 | 181.61 | 1.90 |
| mvu_eval | 1824 | 官方逐题评分平均；工程失败计0 | 51.43 | 1765 | 0 | 0 | 53 | 6 | 224.60 | 1.88 |
| crossvid | 2500 | 十任务等权macro；工程失败计0；CCQA评分点加权 | 33.47 | 2443 | 0 | 0 | 27 | 30 | 417.65 | 135.30 |

在Release的Assets下载 `video-rsi-35b-results-compact-20261020.tar.gz`；GitHub自动生成的Source code不是结果数据。

压缩包 140,697,956 字节（140.70 MB），五文件解压后合计 756,101,346 字节。SHA256：`6c28a2257865ef64fd021a550f219a07b5451a55a7015171d25ed6e85099b9c4`。

导出逻辑为`b438ca7`（前段同逻辑`1638719`，计数问题输入读取修复后保留完整已导出记录）；原始5321份归档、选用成员和五个打包成员的SHA已核验。全量验证核对5321题答案/标注/秒数与37,552次调用计数及token数量一致，无图片编码或完整token ID数组。原始summary、面板、标注、manifest及生效服务配置SHA保存在Modal的bundle.json，逐题源归档SHA在发布文件中。

本机仅在`outputs/video_rsi_release_20261020/`暂存发布包、元数据与核验回执；数据不入Git。工程实现和此说明在`codex/rsi35-results-release-20261020`，原始Modal记录及其他Release保留。

2026-10-20 01:03 UTC发布并验证：Release ID417898090，附件ID657881085；GitHub服务器大小/digest、本地暂存和Modal原件一致。经modal-gpu无凭据完整下载HTTP200，140,697,956字节及SHA256再次一致。原始数据与其他Release保留。
