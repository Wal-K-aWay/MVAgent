# 简洁Global System：原1500题同题扩样

2026-10-17用户要求扩大简洁Global测试，其他地方不变，题目保持与前一批一致。本轮使用已完成4500条基线的原selection：每模型CVBench500、MVU500、CrossVid500，三模型共4500结果。原题目ID及分片顺序不重抽；102题筛选中的全部结果（含负结果）直接复用，共306条；只新增4194条。

只测上一轮的`global_short`候选。Global System、Video System/User、所有schema、媒体处理、步数/输出预算、模型和数值设置与上轮简洁Global候选完全一致。准备时将`src/`、`configs/`、`eval/`、requirements和demo逐文件SHA与已冻结`system_ablation_20261017/source.tar.gz`核对；新增修改仅是实验编排及文档。普通Video不加入新通用要求、视频ID或完整原题。

Global System仍为：

> You are a coordinator for multi-video question answering. You cannot view videos directly. Your visual evidence consists only of successful single-video summaries and completed joint-watch results in History. Preserve video identities and choose one available action that either obtains missing evidence or returns the final answer.

两组各8×H100执行互不重叠的原分片，三模型依次9B→27B→35B-A3B。BF16、每卡独立TP1/DP1、并发1、整题sticky、seed0/temperature0、thinking关闭、FlashInfer GDN/native GemmaRMSNorm、prefix/MM cache关闭；每次2048token、512帧、Global/Video各5步。正式接口和评分不变；新增CCQA105份使用原本地Qwen3-30B-A3B-Instruct-2507 Judge，旧45份评分复用。其他任务不重启、不热更新。

结果只保存在runs volume `devbox/global_short_large_20261017`。`selection.json`记录全部1500 ID、原分片和102继承ID；新结果在`shard{0,1}/global_short/{model}/`，两分片真实状态分别查看`shard{0,1}/global_short/progress.json`。旧结果原件仍在`devbox/system_ablation_20261017/global_short/`，不复制或修改；配对表保存来源路径和SHA。

每个Sandbox最长12小时，host控制器11.5小时封顶，完成/失败释放本实验GPU，随后CPU汇总。失败和缺失明确保留，不把失败当0分，也不将不完整覆盖写成全量。基于历史同题耗时乘本轮102题时间比例估时，正式估计见manifest；不是两小时规模。主执行者是唯一作业控制者，独立Luna仅在活跃会话内每15分钟只读检查，退出会话时停止检查；后台运行由host控制器负责。

最终按模型×benchmark比较原MVAgent、简洁Global与E2E，Cross报十task macro；另报本轮新增1398题/模型（排除筛选102题）的结果、格式/空答案/右花括号、中间截断修复及调用耗时。固定开发集多次使用，102题已参与候选筛选；新增部分也不是未触碰的独立Test，不用扩样自动宣称稳定普遍收益。已验收的数值一致性范围直接复用，保留逐请求token/hash/cache审计，不额外做双遍矩阵。

## 启动与验证（2026-10-17）

实际冻结源码commit `e0ace2739f13e2b01f8fcdf271f62a551e11f2b3`，归档SHA256 `0ba98684eea2c2c666cc5f235d8bd7da1ff9cf11465f1ad29b66e76c325130db`。422个运行相关文件与已测简洁Global归档逐字相同，原题目及306份继承记录SHA验证通过；原分片排除102继承题后分别为657/741题每模型。准备时可用inode24985；只读核查上轮306条候选共1927个inode（含三套src快照），本轮未删除任何旧结果。

CPU `ap-eAU59cOMdLeYyFl8ojsZZb`完整compileall与固定题目自检通过，随后将host控制器自检放在无Modal SDK的CPU子环境执行而退出，prepare未执行。控制器改在其真实devhost SDK环境自检通过；CPU `ap-Xc4aCBL2pD5uhmFNKJumEt`实际prepare成功rc0，manifest已从外部Volume SDK复读核验。没有改运行源码来绕过检查。

两组Sandbox于13:07:41 UTC创建：

| 分片 | Sandbox | DEVBOX_NAME | 新推理目标 |
|---|---|---|---:|
| 0 | sb-hBaSzhFNpRDNMihnJH75oq | mvagent-global-short-large-20261017-shard0 | 1971 |
| 1 | sb-t3sT45HTV5xIDDwdsagRL2 | mvagent-global-short-large-20261017-shard1 | 2223 |

host控制器PID3183066，路径`~/wxu-evolve-agent/devbox/global-short-large-control/watch_global_short_large.py`，日志`~/wxu-evolve-agent/devbox/watch-global_short_large_20261017.log`。两个分片分别在13:16和13:13进入9B真实推理。每组八个实际H100 worker均通过服务身份/profile核验；已有其他任务不改动。

根据全部待测同题旧耗时乘本候选102题的模型耗时比（9B0.897、27B0.857、35B1.018），并为波动加25%和加载/评分/汇总预留45分钟，预计总计8.42小时，暂按另8–9小时安排。不是只用首批短题估计；后续时长仍取决于长尾与故障。

13:15–13:18请求审计完成：shard1前8条结果/75响应、shard0前8条/81响应，共156响应；33次Global和79次普通Video Planner请求与预期System精确一致，seed0/T0/2048、token长度/hash、cache0、整题单worker均通过。实际输出例：CV334→C、CV450→B、CC597→B；FSA1804→`200,260`（原评分0）也保留，未按正确性筛选。证据位于各9B目录`startup_audit.json`；没有追加重复推理。13:17两组记录至少4+40条新增，health近5分钟0Traceback；进度持续增长，最终以实际progress为准。

启动验证通过后按用户既有偏好交给后台host控制器继续；结束会话时停止独立Luna检查，不承诺会话外仍有AI巡检。长期阶段是9B推理，后续27B/35B、Judge及CPU汇总由上述控制器按冻结源码执行。

13:19两分片逐条只读统计为18+58=76份新增结果，全部status=ok，模型请求错误0（开放题仍待后续Judge），加306继承共382/4500已有推理结果。各9B目录`startup_status.json`保留该时点；不是完整模型准确率。独立Luna末检确认两组inference、host存活、近10分钟0Traceback后停止，只停止检查会话，未操作GPU或host控制器。

原已验收基线标签`baseline/mvagent-direct-20261017`、共享代码冻结分支及此前所有结果不改写。实验分支`codex/global-short-large-20261017`。当前已开始新增推理，27B/35B及最终评分尚未完成，不能把启动验证写成整批结果。

后续待办：[VideoAgent 题目背景与职责边界实验计划](video_context_plan.md)。等本批推理、Judge 和汇总完成后再开展，目前仅保存设计，未启动该对照。
