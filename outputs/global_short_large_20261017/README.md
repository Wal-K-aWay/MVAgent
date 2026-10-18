# 简洁Global System：原1500题同题扩样

## 最终结果

2026-10-18 00:56 UTC核验：全部4500/4500有效，三模型各1500题、每benchmark500题；306条候选原结果复用、4194条新增，0缺失、0整题工程失败、0模型请求错误。新增105份CCQA Judge全部完成，加旧45份共150份评分。最后GPU于10月17日19:56 UTC释放，CPU于20:35:33完成汇总，host已退出；从申请开始约7小时28分。当前无本实验GPU或巡检继续运行。

下表为同题官方分（百分制），括号为简洁Global相对原MVAgent的百分点变化。CV/MVU按task人口权重估计，Cross为十task macro、CCQA按点评分。E2E的MVU沿用官方指令移后版本。

| 模型 | Benchmark | 原MVAgent | 简洁Global | 同题E2E |
|---|---|---:|---:|---:|
| 9B | CVBench | 61.57 | 64.39（+2.82） | 60.42 |
| 9B | MVU | 49.41 | 53.02（+3.60） | 34.79 |
| 9B | CrossVid | 34.89 | 35.00（+0.12） | 32.87 |
| 27B | CVBench | 70.01 | 70.22（+0.22） | 69.17 |
| 27B | MVU | 60.23 | 59.62（−0.61） | 43.21 |
| 27B | CrossVid | 46.62 | 47.71（+1.09） | 40.99 |
| 35B-A3B | CVBench | 66.16 | 68.39（+2.23） | 64.19 |
| 35B-A3B | MVU | 51.02 | 56.82（+5.80） | 38.40 |
| 35B-A3B | CrossVid | 37.86 | 42.15（+4.29） | 33.13 |

相对原MVAgent八格正、一格负；相对E2E九格点估计均正。35B收益最明显，27B基本持平；9B/Cross在102题筛选中的+10.27pp没有在扩样中维持，只剩+0.12pp。小面板35B/CV、MVU的负方向在扩样后反转，不能按102题结果为模型选择不同prompt。

每task内2000次配对bootstrap（seed0）：只有35B/MVU和35B/Cross相对原MVAgent的95%区间严格高于0，分别[+1.59,+9.81]和[+0.12,+8.62]pp；其他七格均跨0。未做共享视频聚类、多重比较或反复开发校正。这里是已复用开发集上的结果，不能证明每个模型、benchmark或所有输入都不会退步。

排除参与筛选的102题/模型，只看本轮新增1398题（CV470/MVU470/Cross458），相对原MVAgent的CV/MVU/Cross变化：9B为+2.50/+2.76/−0.62pp，27B为+0.19/−0.44/+0.94pp，35B为+3.02/+6.36/+4.50pp。35B/MVU、Cross的未校正区间仍正；其收益没有仅依赖旧102题，但新增部分也不是独立Test。

### 格式和运行成本

| 模型 | 闭式格式错误 原→短（各1450题） | 中间输出触顶调用 原→短 | 平均整题秒 原→短 |
|---|---:|---:|---:|
| 9B | 28→30 | 46→89 | 55.24→54.79 |
| 27B | 13→8 | 68→83 | 108.71→102.13 |
| 35B-A3B | 38→24 | 64→152 | 92.09→99.17 |

三模型均0空答案、0仅右花括号。总闭式格式错误79/4350→62/4350，改善主要来自27B/35B，9B略差。保留同一官方格式口径，包括原题面缺陷；没有新增答案枚举或纠错后改分。

中间length响应总计178→324，简洁Global的structured_invalid为88/82/151次，repair为84/70/126次。最终能交答案、格式错误减少，不表示中间截断消失。总调用50394→55288，输出token6515793→7621723（约+17.0%）；System缩短并未让生成输出缩短。耗时为历史同题与本轮实测比较，非控制所有缓存/机器状态的纯吞吐对照。

每模型50个CCQA中，新旧答案逐字相同的数量均为0，因此没有可用的同文判分对照；这不能证明Judge不存在波动。完整评分与原答案保留，不重新Judge或静默改分。

### 证据和后续

- runs `devbox/global_short_large_20261017/analysis/summary.json`与三模型`*_paired.json`为完整汇总；根`progress.json`为completed/4500。两分片模型有效数657/741，CCQA分别18/17题每模型；旧102题/模型的来源与SHA保留。
- 实际冻结源仍为`e0ace27`；所有运行参数和Video提示保持原样。此次仅读取结果、更新报告，无新Actor或Judge。CPU只读补算的成本与同文Judge统计来自相同配对表。
- 附加审计最初尝试写新文件时遇到`No space left on device`，随后改为纯只读CPU统计成功。完整主结果已于20:35落盘并从外部SDK读回，不受此次附加写入失败影响；未删除旧数据。后续新实验前需处理存储写入余量。
- [VideoAgent题目背景计划](video_context_plan.md)的Global扩样前置已完成，但Video实验尚未实施或自动排队。后续三组须使用同一个明确冻结的Global配置，不能一边加入背景、一边更换Global。

下面保留原设计与启动记录，其中的预计时间和“运行中”均为历史状态。

## 原设计

2026-10-17用户要求扩大简洁Global测试，其他地方不变，题目保持与前一批一致。本轮使用已完成4500条基线的原selection：每模型CVBench500、MVU500、CrossVid500，三模型共4500结果。原题目ID及分片顺序不重抽；102题筛选中的全部结果（含负结果）直接复用，共306条；只新增4194条。

只测上一轮的`global_short`候选。Global System、Video System/User、所有schema、媒体处理、步数/输出预算、模型和数值设置与上轮简洁Global候选完全一致。准备时将`src/`、`configs/`、`eval/`、requirements和demo逐文件SHA与已冻结`system_ablation_20261017/source.tar.gz`核对；新增修改仅是实验编排及文档。普通Video不加入新通用要求、视频ID或完整原题。

Global System仍为：

> You are a coordinator for multi-video question answering. You cannot view videos directly. Your visual evidence consists only of successful single-video summaries and completed joint-watch results in History. Preserve video identities and choose one available action that either obtains missing evidence or returns the final answer.

两组各8×H100执行互不重叠的原分片，三模型依次9B→27B→35B-A3B。BF16、每卡独立TP1/DP1、并发1、整题sticky、seed0/temperature0、thinking关闭、FlashInfer GDN/native GemmaRMSNorm、prefix/MM cache关闭；每次2048token、512帧、Global/Video各5步。正式接口和评分不变；新增CCQA105份使用原本地Qwen3-30B-A3B-Instruct-2507 Judge，旧45份评分复用。其他任务不重启、不热更新。

结果只保存在runs volume `devbox/global_short_large_20261017`。`selection.json`记录全部1500 ID、原分片和102继承ID；新结果在`shard{0,1}/global_short/{model}/`，两分片真实状态分别查看`shard{0,1}/global_short/progress.json`。旧结果原件仍在`devbox/system_ablation_20261017/global_short/`，不复制或修改；配对表保存来源路径和SHA。

每个Sandbox最长12小时，host控制器11.5小时封顶，完成/失败释放本实验GPU，随后CPU汇总。失败和缺失明确保留，不把失败当0分，也不将不完整覆盖写成全量。基于历史同题耗时乘本轮102题时间比例估时，正式估计见manifest；不是两小时规模。主执行者是唯一作业控制者，独立Luna仅在活跃会话内每15分钟只读检查，退出会话时停止检查；后台运行由host控制器负责。

最终按模型×benchmark比较原MVAgent、简洁Global与E2E，Cross报十task macro；另报本轮新增1398题/模型（排除筛选102题）的结果、格式/空答案/右花括号、中间截断修复及调用耗时。固定开发集多次使用，102题已参与候选筛选；新增部分也不是未触碰的独立Test，不用扩样自动宣称稳定普遍收益。已验收的数值一致性范围直接复用，保留逐请求token/hash/cache审计，不额外做双遍矩阵。

## 启动与验证记录（2026-10-17）

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

原已验收基线标签`baseline/mvagent-direct-20261017`、共享代码冻结分支及此前所有结果不改写。实验分支`codex/global-short-large-20261017`。以上启动记录当时尚未完成27B/35B及最终评分，现以文首完整结果为准。

后续待办：[VideoAgent 题目背景与职责边界实验计划](video_context_plan.md)。等本批推理、Judge 和汇总完成后再开展，目前仅保存设计，未启动该对照。

## 2026-10-18 存储归档

为下一轮Video实验恢复runs文件配额，已完成的两shard×三模型目录无损归档至`devbox/video_context_storage_20261018/global_short_shard{0,1}_{model}.tar`及逐文件SHA清单。原始答案与评分字节保持不变，分析表/总冻结源码/分片progress仍在原处；历史分析表中的散文件路径需通过对应tar读取或恢复后访问。模型`src`重复副本从总冻结源码恢复。详见[存储清单](../video_context_20261018/README.md#既有结果的无损存储整理)，没有重新推理或评分。
