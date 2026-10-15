# VAM扩大到与Video-RSI相同的65题

2026-10-15用户要求按当前设置后台继续：VAM扩为同一65题，汇总两个方法在三个benchmark上的分数、耗时和失败。新结果仅在Modal runs volume `devbox/external_vam65_20261015`。

| Benchmark | Video-RSI题数 | 本轮VAM题数 |
|---|---:|---:|
| CrossVid | 19 | 19 |
| CVBench | 30 | 30 |
| MVU-Eval | 16 | 16 |

复用已验证的拼接媒体和题目，不重新抽样、缩放或转换FPS。输入items.json SHA256为`c5df7e2771afc5138f9fa4955ac11b66c58a5f9b9f9808cf94485409344ffce0`，与RSI批次逐字一致。视频总时长20660.90秒，中位153.36秒，最大1680.60秒。原媒体准备时排除的NC808仍不在本面板。

VAM本轮65题全部新跑，不将旧3题的耗时混入本批。仍为Qwen3.5-35B-A3B、BF16、单卡单请求、seed0、thinking与prefix cache关闭；原VAM温度、输出预算、图像上限、索引/记忆/检索流程及HTTP240秒不变。Embedding为当前仓库默认Qwen3-VL-Embedding-8B，官方图像默认，不是论文的Gemini Embedding 2。每题独立进程/记忆库、整题固定Actor副本。

Video-RSI复用已完成的`external_original_images_20261015/rsi`结果与评分，不再次推理或Judge。该批实际HTTP等待1860秒，所有468次请求都在600秒内完成、无请求错误；当前源码默认600秒已经另行验证。报告明确标注历史实际配置，不能把旧测量写成新600秒运行。原始记录不修改，汇总目录仅复制progress/scores并记录来源。

资源为独立8×H100：7个VAM Actor副本与1个Embedding服务。RSI历史批次为6个Actor副本，整批墙钟不能直接当作等资源吞吐对照；报告同时给逐题平均/中位耗时、全部尝试累计时间及各批墙钟。启动、Judge和评分耗时另记。

后台启动入口`eval/external_methods/experiments/20261015/launch_vam_expanded.py`运行在modal-gpu；CPU准备与报告检查通过后启动唯一GPU控制器。DEVBOX_NAME=`mvagent-external-vam65-20261015`，Sandbox=`sb-cxESrSjwJQniJVV2d3VIUD`，控制器PID41。host launcher PID2236680提交成功后退出。11:55:47 UTC（19:55:47北京时间）进入模型启动阶段；尚未产生本轮VAM最终分数。初估1–2小时，长视频与重试可能延长。

控制器完成推理后自动停止Actor/Embedding，必要时启动本地Qwen3-30B-A3B-Instruct-2507给开放题评分，然后审计token与输入哈希并汇总。完成或异常均关闭模型，Sandbox在任务退出后由idle watchdog释放；不配置持续通知或巡检。

产物：

- `progress.json`、`vam/progress.json`：阶段与逐题完成/失败状态。
- `vam/<sample_id>/`：原始输出、HTTP记录、实际配置、逐题耗时、索引进度及失败日志。
- `vam/scores.json`、`analysis.json`：官方逐题评分、请求错误和token/耗时审计。
- `final_summary.json`、`report.md`：两个方法×三个benchmark的分数、有效题数、覆盖任务、平均/中位耗时、累计耗时、批次墙钟与失败明细。
- `ready.json`、`frozen_repo/source_manifest.json`：输入/源码hash与执行范围。

CrossVid为十类任务macro，CVBench/MVU按任务全集题量加权估计官方平均分。运行失败独立列出，不悄悄当作模型答错；正常返回但格式不合要求仍按官方规则评分。结果只代表这个开发面板，不是全量benchmark成绩。

验证：CPU对新控制器语法检查通过，复用已完成数据实际执行报告生成并核验样本数；媒体manifest、VAM/Actor/Embedding实现SHA与已验收版本一致。新七路并行的实际启动与首批结果另行记录。
