# Video-RSI / VAM：恢复原图像设置（2026-10-15）

用户最新指令：取消额外448限制；保留多视频拼接、两位小数时间说明、通用答案适配和已确认的超时。RSI与VAM仍使用本地Qwen3.5-35B-A3B。

本轮已于2026-10-15 15:07北京时间完成推理、评分及token审计，RSI65/65、VAM3/3正常结束，0运行失败、0待评分。GPU Sandbox已退出。后续日志分析见[耗时、重复输出与超时建议](latency_analysis.md)，没有新增推理或更改本轮1860秒设置。

| 方法 | benchmark | 评分题数 | 官方口径子集分 | 成功题平均 / 中位耗时 |
|---|---|---:|---:|---:|
| RSI | CrossVid | 19 | 35.72% | 371.84 / 222.29秒 |
| RSI | CVBench | 30 | 56.00% | 171.92 / 112.19秒 |
| RSI | MVU-Eval | 16 | 67.24% | 192.29 / 90.53秒 |
| VAM | CrossVid | 1 | 0.00% | 108.57秒 |
| VAM | CVBench | 1 | 100.00% | 129.32秒 |
| VAM | MVU-Eval | 1 | 100.00% | 37.57秒 |

CrossVid按十类任务macro；CVBench/MVU按任务全集题量加权估计官方平均分。这里是开发子集，尤其VAM每benchmark仅一题，不能代表全量准确率。方法运行成功与题目答案正确分开记录。RSI6副本批次墙钟2917.81秒，VAM1副本275.48秒（两个方法同时运行）；模型启动281.64秒、Judge启动155.13秒与评分3.85秒另计。原数据在该目录对应的Modal`final_summary.json`、`report.md`。

模型来源说明：VAM的Qwen3-VL-Embedding-8B是当前仓库默认，不是论文实验使用的Gemini Embedding 2；本轮属于本地Qwen适配评测。论文生成模型为Gemini 3 Flash；RSI论文为DeepSeek-V4-Pro推理/进化和Qwen3.6-Plus视觉观察。

| 设置 | 本轮 |
|---|---|
| RSI图像 | 上游Services原文件，抽帧宽度768、保持比例；与原源码SHA一致才允许启动 |
| VAM图像 | 原1280×1280像素面积和5MB上限，不额外覆盖 |
| Embedding图像 | 官方Qwen3VLEmbedder默认1800×32×32像素上限，不额外覆盖 |
| 本地模型服务 | 移除共享MVAgent的448宽高提示，保留512 image / 8 video数量限额；不改共享MVAgent源码 |
| RSI预算 | 两角色8192token、温度0、11步、64服务调用、256帧、1800秒整题、HTTP1860秒、原1次重试 |
| VAM流程与预算 | 原stream_agent_response顶层路由及原索引/记忆/检索流程；原调用点的token/温度/时限 |
| 客户端依赖 | 独立环境；RSI22项锁定版本，VAM13项适用要求与SciPy1.14.1兼容环境 |

本轮RSI65题（CrossVid19、CVBench30、MVU16），VAM三个benchmark各一题。保留原selection，不重新抽样；原NC808仍属预处理排除题。复用已校验的拼接媒体，NC80使用去除隐藏解码预滚后的版本。拼接阶段不缩放、不改FPS，不复用448协议的模型答案。

新目录：runs volume `devbox/external_original_images_20261015`。`frozen_repo/source_manifest.json`、`ready.json`、每题`effective_config.json`、服务manifest、客户端环境版本、实际HTTP请求与完整token均保存。原448目录`external_upstream_nc80_20261015`已终止/被替代，保留原件；其独立收尾脚本曾因子进程缺少Modal SDK退出，该故障不解释为评测成功。

本轮由同一GPU控制器完成推理、官方评分、token/输入审计及汇总，不再另起需要Modal SDK的收尾子进程。最终输出`final_summary.json`、`report.md`、逐方法`scores.json`和`analysis.json`。报告包含各benchmark官方聚合分、已评分题数、覆盖任务、成功题平均/中位耗时、所有尝试累计耗时、失败清单及批次墙钟；模型启动与Judge评分单独计时。并行请求累计时间不当作墙钟。

资源为独立8×H100：RSI六副本、VAM一副本、原Embedding一张卡，整题固定副本，单卡单请求。任务结束停止服务并由idle watchdog释放。Sandbox=`sb-FheMotX5Sn5j6N8tN6crwM`，控制器PID41；DEVBOX_NAME=`mvagent-external-native-images-20261015`；host入口`launch-original-images-20261015`。不配置持续通知或独立巡检。

14:18北京时间首批检查：模型启动281.64秒，RSI已5/65成功、VAM已1/3成功，均0运行失败。CV764的RSI实际图像768×1364，答案B，整题墙钟95.29秒（内部94.36秒）；VAM TR1585实际图像1280×720，答案B，墙钟37.57秒（内部29.99秒）。7个Actor副本的manifest均已移除448宽高提示，Embedding实际max_pixels=1843200。两题共6次实际响应的完整token与输入SHA审计通过；证据startup_verification.json。尚无完整准确率/吞吐结论。原云服务未公开的处理/数值默认值仍不能认证完全相同；VAM每benchmark仅一题属于冒烟，不代表全量准确率。
