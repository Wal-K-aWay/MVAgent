# 简洁Global System：原1500题同题扩样

2026-10-17用户要求扩大简洁Global测试，其他地方不变，题目保持与前一批一致。本轮使用已完成4500条基线的原selection：每模型CVBench500、MVU500、CrossVid500，三模型共4500结果。原题目ID及分片顺序不重抽；102题筛选中的全部结果（含负结果）直接复用，共306条；只新增4194条。

只测上一轮的`global_short`候选。Global System、Video System/User、所有schema、媒体处理、步数/输出预算、模型和数值设置与上轮简洁Global候选完全一致。准备时将`src/`、`configs/`、`eval/`、requirements和demo逐文件SHA与已冻结`system_ablation_20261017/source.tar.gz`核对；新增修改仅是实验编排及文档。普通Video不加入新通用要求、视频ID或完整原题。

Global System仍为：

> You are a coordinator for multi-video question answering. You cannot view videos directly. Your visual evidence consists only of successful single-video summaries and completed joint-watch results in History. Preserve video identities and choose one available action that either obtains missing evidence or returns the final answer.

两组各8×H100执行互不重叠的原分片，三模型依次9B→27B→35B-A3B。BF16、每卡独立TP1/DP1、并发1、整题sticky、seed0/temperature0、thinking关闭、FlashInfer GDN/native GemmaRMSNorm、prefix/MM cache关闭；每次2048token、512帧、Global/Video各5步。正式接口和评分不变；新增CCQA105份使用原本地Qwen3-30B-A3B-Instruct-2507 Judge，旧45份评分复用。其他任务不重启、不热更新。

结果只保存在runs volume `devbox/global_short_large_20261017`。`selection.json`记录全部1500 ID、原分片和102继承ID；新结果在`shard{0,1}/global_short/{model}/`，两分片真实状态分别查看`shard{0,1}/global_short/progress.json`。旧结果原件仍在`devbox/system_ablation_20261017/global_short/`，不复制或修改；配对表保存来源路径和SHA。

每个Sandbox最长12小时，host控制器11.5小时封顶，完成/失败释放本实验GPU，随后CPU汇总。失败和缺失明确保留，不把失败当0分，也不将不完整覆盖写成全量。基于历史同题耗时乘本轮102题时间比例估时，正式估计见manifest；不是两小时规模。主执行者是唯一作业控制者，独立Luna仅在活跃会话内每15分钟只读检查，退出会话时停止检查；后台运行由host控制器负责。

最终按模型×benchmark比较原MVAgent、简洁Global与E2E，Cross报十task macro；另报本轮新增1398题/模型（排除筛选102题）的结果、格式/空答案/右花括号、中间截断修复及调用耗时。固定开发集多次使用，102题已参与候选筛选；新增部分也不是未触碰的独立Test，不用扩样自动宣称稳定普遍收益。已验收的数值一致性范围直接复用，保留逐请求token/hash/cache审计，不额外做双遍矩阵。

当前状态：编排实现完成，尚待远端编译、自检、原题目/源码核验和实际GPU启动。原已验收基线标签`baseline/mvagent-direct-20261017`、共享代码冻结分支及此前所有结果不改写。实验分支`codex/global-short-large-20261017`，最终提交与远端运行身份以下续记录为准。
