# LensWalk × Qwen3.5-35B-A3B 全量评测

用户已授权运行三个 benchmark：CVBench当前可测997题、MVU-Eval1824题、CrossVid既有Lite2500面板，共5321题。CVBench64–66的损坏视频题沿用既有排除清单；不重新抽取CrossVid样本。

## 当前状态

2026-10-16 05:58 UTC：已提交8×H100后台任务，Sandbox `sb-hMHJnYHAblIYvPh4revZ2t`尚未获得执行资源，当前新模型样本0/5321。准备、代码提交和实例ID均不代表推理完成。排队结束后会自动加载模型；预计推理约2–3天，排队及新增媒体准备时间另计。完整准确率、耗时和失败情况尚未产出。

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
- 新8卡服务的实际manifest、首批推理及本轮Judge尚待执行；没有重跑既有全部数值验收矩阵。

入口：[lenswalk_full.py](../../eval/external_methods/lenswalk_full.py)。关键产物为`progress.json`、`episodes/*/pool_verification.json`、逐题`record.json`与原始归档、`judge_cache/`及最终`summary.json`。会话内独立检查代理按15分钟只读巡检；它不等于离线常驻代理，真正持续运行的是modal-gpu上的后台管理进程。
