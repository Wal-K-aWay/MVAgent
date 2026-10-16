# LensWalk × Qwen3.5-35B-A3B 全量评测

用户已授权运行三个 benchmark：CVBench当前可测997题、MVU-Eval1824题、CrossVid既有Lite2500面板，共5321题。CVBench64–66的损坏视频题沿用既有排除清单；不重新抽取CrossVid样本。

## 当前状态

2026-10-16 08:24 UTC快照：已处理216/5321题（4.06%），其中143题终答、53题未收尾规划、19题空答案、1题基础设施失败。Sandbox `sb-hMHJnYHAblIYvPh4revZ2t`于06:14开始执行，约06:19开始推理，后台管理器仍在运行。当前主要耗时是CrossVid长片段的无损转码与完整逐帧校验，5个worker在准备媒体；其他worker继续产出。此前2–3天只估算推理，不能作为含这些媒体准备的总工期。

| Benchmark | 已处理 / 目标 | 当前已评分结果 | 单题平均推理时间 |
|---|---:|---:|---:|
| CVBench | 86 / 997 | 46/86，53.49% | 232.81秒 |
| MVU-Eval | 65 / 1824 | 19/64，29.69%；1题基础设施失败 | 153.01秒 |
| CrossVid | 65 / 2500 | 已评分57题，九类任务macro 20.19%；8题CCQA待Judge | 224.57秒 |

按目标题库各任务占比重加权，CVBench与MVU-Eval当前估计分别51.54%和31.71%。这仅校正任务比例，不能消除先使用现成媒体、短题先完成带来的选择偏差；若干任务只有2–5题。CrossVid必须等CCQA评分才能报十类官方macro，九类得分不冒充完整成绩。空答案和未收尾输出仍按原评分器计分，没有通过筛选终答提高分数。表中推理时间包含故障题，不包含媒体准备、模型加载和排队；尚未完成的长准备不能由已完成题均值代表。

3722次模型调用中5次HTTP错误集中于`mvu_eval:Counting:11`：首个请求600秒超时，随后4次连接失败；该题记录为基础设施失败，副本重启后继续。另记录76次视觉工具错误、0次输出token长度截断，工具错误不等于76题失败。原始分析仅存runs：`analysis/progress_20261016_0825.json`。

08:25诊断确认NC870/77/926/62/889在媒体准备，部分已超过1小时；4段约7分钟电影片段无损归一化后，单个拼接文件达到8–9GB。文件仍在增长，先完成的拼接进入逐帧校验，并非已经确认的死锁。当前冻结运行代码与模型参数未修改，也没有重提任务。

- DEVBOX_NAME：`mvagent-lenswalk-full-35b-20261016`。
- modal-gpu后台管理进程：PID `2584926`，`~/wxu-evolve-agent/devbox/watch-lenswalk_full_35b_20261016.log`。
- 固定结果根：runs volume的`devbox/lenswalk_full_35b_20261016`。
- 固定题目清单SHA256：`4287d2221aac79865d24016dbd0d0a34d137a5b42745856d55f62aecf1915bd2`。
- 新控制器代码提交：`4d405b6`；底层方法和模型服务复用此前验证的冻结源码，来源及全部文件哈希在`manifest.json`。

## 设置与运行方式

沿用[六题接入验证](../external_lenswalk_20261016/README.md)的LensWalk release `c3cdf13`：原提示词和工具、默认5轮、原版512最长边、scan/segment/stitched默认180/32/128帧；不增加448限制。Planner未显式设温度，本地标准API缺省为1；Observer为0.2；没有额外输出token上限，实际最多剩余上下文。seed=0、thinking及prefix/MM cache关闭、BF16、FlashInfer GDN/原生GemmaRMSNorm。

8个独立H100副本分别TP1/C1，一道题固定在一个副本上；每题仍调用完整上游评测入口，batch_size=1、workers=8。单请求600秒、单题1800秒。模型正常输出的格式偏差、未收尾规划及工具参数错误不进行答案修补。

5321题含4298个不同的有序视频组合；优先使用65组已验证的拼接媒体，其他组合按需准备并缓存。拼接沿用原尺寸、原帧时间、无音频；题面保留多视频任务说明和两位小数时间轴，题目与参考答案分开。每题记录媒体准备时间、推理时间、调用和token数。

原始请求、响应、轨迹先落盘并核验token/input hash、实际worker和cache=0，再逐文件SHA256校验后打成tar.gz。`lenswalk/<sample>/record.json`保存归档路径及文件哈希；归档保留全部原始内容。此措施针对当前runs volume已使用约84%的文件数，避免全量散文件耗尽inode。媒体、模型权重和结果都留在Modal，未下载到Lightsail或devbox磁盘。

## 续跑与评分

复用现有`watch_full_mvagent.py`管理生命周期：约23小时换实例，读取同一冻结源码与题目清单，跳过已有逐题记录，未完成题另存新attempt；完成或明确失败后释放资源。异常恢复有次数上限，不无限重启。服务器失效时记录当前题故障、重启该副本处理下一题；连续基础设施错误过多则停止并保留错误。

Actor结束后释放其显存，在同一8卡实例加载已有Qwen3-30B-A3B-Instruct-2507 Judge，对CCQA按官方提示和评分点打分，成功缓存可续用；Judge最终失败直接报错，不计零分。

CVBench、MVU-Eval按有效题平均；CrossVid按十任务macro，CCQA任务内按评分点加权。原模型输出直接交给官方评分器；未收尾规划单列，不能因包装器返回码为0就算作有效终答。基础设施失败单列并披露有效分母，不混成模型答错。

## 已完成验证

- CPU准备app `ap-7fyXKwhLpWZQSvxF0gwJx9` rc0：固定5321题、缓存顺序与题目隔离、六条真实历史轨迹分类及138响应审计、归档字节一致性通过。
- CPU评分检查app `ap-cxKo4mQ604pCgE2KeszWWV` rc0：样本均分、十任务macro、CCQA评分点加权、基础设施失败与未收尾分离通过。
- 复用的后台管理器通过生命周期自检，源码SHA与备份一致。
- 新8卡服务启动时实际manifest、硬件、源码及cache设置检查已通过，首批推理已落盘；本轮CCQA Judge尚未执行，没有重跑既有全部数值验收矩阵。

入口：[lenswalk_full.py](../../eval/external_methods/lenswalk_full.py)。关键产物为`progress.json`、`episodes/*/pool_verification.json`、逐题`record.json`与原始归档、`judge_cache/`及最终`summary.json`。会话内独立检查代理按15分钟只读巡检；它不等于离线常驻代理，真正持续运行的是modal-gpu上的后台管理进程。
