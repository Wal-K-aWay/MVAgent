# VAM扩大到与Video-RSI相同的65题

2026-10-15用户要求按当前设置后台继续：VAM扩为同一65题，汇总两个方法在三个benchmark上的分数、耗时和失败。新结果仅在Modal runs volume `devbox/external_vam65_20261015`。

## 最终结果（2026-10-16核实）

本轮于2026-10-15 21:19:34北京时间完成。Video-RSI复用65条成功结果；VAM65题全部尝试，64条成功返回并评分、1条无有效索引而失败。没有运行中或待评分题。原GPU Sandbox已正常退出（poll=0）。

| 方法 | Benchmark | 已评分 / 计划 | 官方口径子集分 | 成功题平均 / 中位耗时（秒） | 运行失败 |
|---|---|---:|---:|---:|---:|
| Video-RSI | CrossVid | 19 / 19 | 35.72% | 371.84 / 222.29 | 0 |
| Video-RSI | CVBench | 30 / 30 | 56.00% | 171.92 / 112.19 | 0 |
| Video-RSI | MVU-Eval | 16 / 16 | 67.24% | 192.29 / 90.53 | 0 |
| VAM | CrossVid | 19 / 19 | 15.00% | 463.59 / 231.71 | 0 |
| VAM | CVBench | 30 / 30 | 7.45% | 531.16 / 383.90 | 0 |
| VAM | MVU-Eval | 15 / 16 | 33.44% | 160.58 / 88.23 | 1 |

分数按已评分样本计算，未将失败题填零。CrossVid为十类macro，CVBench/MVU为按任务全集题量加权的子集估计，不等于本面板的简单答对比例。按双方共同有评分的64题（Cross19/CV30/MVU15）复核，三项分数均不变。

RSI推理批次墙钟48.63分钟；VAM75.81分钟。VAM连同模型启动、Judge和收尾共约83.78分钟，其中模型启动285.35秒、Judge启动155.10秒、评分4.50秒。两批分别用6/7个Actor，不能当作等资源吞吐对照。逐题平均/中位数只统计正常返回题，所有尝试累计耗时及失败耗时保留在原始JSON。

唯一失败为`mvu_eval:TR:1586`：原VAM按0.5 fps从约10秒视频抽取5帧，时刻为0/2/4/6/8秒；5帧均被原模糊过滤器丢弃，保留帧数为0。当前评测入口据此将空索引判为失败，在4.36秒退出，尚未开始答题；不是HTTP超时，也不据此称视频损坏。按用户要求保持原阈值，不降低过滤强度或重新抽帧补跑。两方法均未记录聊天模型HTTP请求错误。

本批VAM的主要时间消耗在索引/记忆构建：CrossVid平均332.33秒建库、127.23秒查询；CVBench473.63/54.49秒；MVU113.92/43.47秒。最慢NC80总2646.62秒，其中建库2582.27秒；CV722总2330.80秒，其中建库2284.74秒。建库包含抽帧、Embedding和记忆文本生成，不能把这部分都解释为CPU预处理或纯token解码。

VAM的CVBench30题只有16条最终答案是单个选项字母；原RSI为30/30。自然语言回答会受官方提取规则影响，同时原记录中也有明确的选项错误。因此分差同时包含任务判断与答案交付因素，未做语义重判，不能量化两者各自贡献，也不能外推为原论文模型下的方法排名。所有原提示词、生成预算、温度、过滤器及评分结果保持不变。

复核仅使用已有输出，未新增推理或Judge。`result_review.json`保留阶段耗时、答案形式描述、共同64题复核与例子；对应分析脚本为`eval/external_methods/experiments/20261015/review_vam65.py`。原始rollout、模型/源码/输入hash和逐题评分仍在Modal。

## 与旧版 MVAgent 的同题比较（2026-10-16）

只读取已有答案，在 Modal CPU 上复算。MVAgent 来源为 `devbox/mvagent_full_35b_parallel_20261015/35B-A3B`，使用历史独立回答器；不是当前直接回答协议。两者均为本地 Qwen3.5-35B-A3B，题目原文、原始视频路径及参考答案逐条一致，各方法保留自身提示、视觉输入设置与调用预算。

| Benchmark | 共同已评分题数 | Video-RSI | 旧版 MVAgent | RSI 平均秒/题 | MVAgent 平均秒/题 |
|---|---:|---:|---:|---:|---:|
| CrossVid 九类闭式任务 | 17 | 37.83% | 33.92% | 407.67 | 94.63 |
| CVBench | 30 | 56.00% | 64.85% | 171.92 | 65.93 |
| MVU-Eval | 16 | 67.24% | 67.11% | 192.29 | 85.21 |

65题中只有两题CCQA（73、725）的旧MVAgent答案尚未Judge评分，因此双方比较均排除这两题；不填零、不新增Judge，也不把本表的Cross九类分与上方十类分直接比较。CV/MVU仍采用同一task人口加权。得分改善题数（MVAgent/RSI）分别为2/4、6/4、2/2，其余相等。结论是旧版同题准确率各有胜负、MVU近似持平；RSI本批平均耗时约为旧MVAgent的2.3–4.3倍。这不是等帧数/等token预算、独立控制服务负载的性能实验。

当前直接回答35B的300题面板只与RSI面板重合`cvbench:39`一题，无法据此判断当前版本总体优劣。此前MVAgent 66题pilot、当前300题面板和RSI65题面板不是同一批题，不能横向拼表排名。

派生结果及分析源码仅在runs volume `devbox/baseline_survey_20261016/{summary.json,paired.json,compare_saved_baselines.py}`；CPU app `ap-gX5aKljdZk3GeUPLjajuyy`完成，rc0。检查复算的RSI全65题聚合与原报告完全一致、共同63题身份/题面/视频路径/参考一致、仅两题CCQA被排除。没有修改原始结果或运行设置。代码备份为`eval/external_methods/experiments/20261016/compare_saved_baselines.py`；后续基线选择调研见[评测说明](../../eval/external_methods/README.md#后续基线选择调研2026-10-16)。

## 运行范围与历史启动记录

| Benchmark | Video-RSI题数 | 本轮VAM题数 |
|---|---:|---:|
| CrossVid | 19 | 19 |
| CVBench | 30 | 30 |
| MVU-Eval | 16 | 16 |

复用已验证的拼接媒体和题目，不重新抽样、缩放或转换FPS。输入items.json SHA256为`c5df7e2771afc5138f9fa4955ac11b66c58a5f9b9f9808cf94485409344ffce0`，与RSI批次逐字一致。视频总时长20660.90秒，中位153.36秒，最大1680.60秒。原媒体准备时排除的NC808仍不在本面板。

VAM本轮65题全部新跑，不将旧3题的耗时混入本批。仍为Qwen3.5-35B-A3B、BF16、单卡单请求、seed0、thinking与prefix cache关闭；原VAM温度、输出预算、图像上限、索引/记忆/检索流程及HTTP240秒不变。Embedding为当前仓库默认Qwen3-VL-Embedding-8B，官方图像默认，不是论文的Gemini Embedding 2。每题独立进程/记忆库、整题固定Actor副本。

Video-RSI复用已完成的`external_original_images_20261015/rsi`结果与评分，不再次推理或Judge。该批实际HTTP等待1860秒，所有468次请求都在600秒内完成、无请求错误；当前源码默认600秒已经另行验证。报告明确标注历史实际配置，不能把旧测量写成新600秒运行。原始记录不修改，汇总目录仅复制progress/scores并记录来源。

资源为独立8×H100：7个VAM Actor副本与1个Embedding服务。RSI历史批次为6个Actor副本，整批墙钟不能直接当作等资源吞吐对照；报告同时给逐题平均/中位耗时、全部尝试累计时间及各批墙钟。启动、Judge和评分耗时另记。

后台启动入口`eval/external_methods/experiments/20261015/launch_vam_expanded.py`运行在modal-gpu；CPU准备与报告检查通过后启动唯一GPU控制器。DEVBOX_NAME=`mvagent-external-vam65-20261015`，Sandbox=`sb-cxESrSjwJQniJVV2d3VIUD`，原控制器PID41。host launcher PID2236680提交成功后退出。11:55:47 UTC（19:55:47北京时间）进入模型启动阶段，13:19:34 UTC（21:19:34北京时间）完成。

控制器完成推理后自动停止Actor/Embedding，必要时启动本地Qwen3-30B-A3B-Instruct-2507给开放题评分，然后审计token与输入哈希并汇总。完成或异常均关闭模型，Sandbox在任务退出后由idle watchdog释放；不配置持续通知或巡检。

产物：

- `progress.json`、`vam/progress.json`：阶段与逐题完成/失败状态。
- `vam/<sample_id>/`：原始输出、HTTP记录、实际配置、逐题耗时、索引进度及失败日志。
- `vam/scores.json`、`analysis.json`：官方逐题评分、请求错误和token/耗时审计。
- `final_summary.json`、`report.md`：两个方法×三个benchmark的分数、有效题数、覆盖任务、平均/中位耗时、累计耗时、批次墙钟与失败明细。
- `ready.json`、`frozen_repo/source_manifest.json`：输入/源码hash与执行范围。

CrossVid为十类任务macro，CVBench/MVU按任务全集题量加权估计官方平均分。运行失败独立列出，不悄悄当作模型答错；正常返回但格式不合要求仍按官方规则评分。结果只代表这个开发面板，不是全量benchmark成绩。

验证：CPU对新控制器语法检查通过，复用已完成数据实际执行报告生成并核验样本数；媒体manifest、VAM/Actor/Embedding实现SHA与已验收版本一致。七路并行已完成全批，成功响应均通过输入hash与完整token审计。

启动确认历史：模型加载285.35秒，20:00:33北京时间进入推理。7个Actor均为不同H100、固定TP1/C1且prefix cache关闭，Embedding默认像素上限1843200。当时VAM已4/65成功、0运行失败；首题MVU TR1585返回B、46.80秒，3条实际响应的输入hash与完整token审计通过。`startup_verification.json`保存证据；`code_backup.json`记录源码备份commit a1c39e8及9个相关源码SHA的逐一核对。最终状态以上方结果及远端final_summary.json为准。
