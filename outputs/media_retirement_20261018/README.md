# LensWalk / Video-RSI暂停与派生媒体清理（2026-10-18）

用户要求先停LensWalk与Video-RSI，清理可重建媒体，并评估未来每题现拼接的速度影响。不自动恢复实验，不压缩，不改当前Video背景对照。

## 暂停核验

02:20 UTC，两个已登记Sandbox均已退出（poll=0）：LensWalk `sb-kjUBHdKJc8CeFJYVzhn3h6`，RSI `sb-iv1GRi133eEtLmJv5L2Ze5`；host进程检查无LensWalk/RSI watcher，旧media-final watcher的PID记录已失效。本轮没有声称新释放两组GPU，也没有停止共享app。用户明确暂停记录写入devbox `paused-lenswalk-rsi-20261018.json`。

## 删除边界

仅下列runs/devbox根目录中`prepared/media/**/*.mp4`，包括最终拼接视频和中间分段：

- lenswalk_full_35b_20261016
- lenswalk_full_35b_recovery_20261017
- lenswalk_full_35b_audit_recovery_20261017
- rsi_full_35b_20261016
- rsi_full_35b_recovery_20261017

其他根的媒体cache/输入manifest/符号链接如果引用候选则先保护并核对来源。实查全部591份引用来自同两实验的废弃准备根：`rsi_full_35b_20261016_prepare_initial`（缺git导致准备失败）及`lenswalk_full_35b_audit_recovery_20261017_prepare_interrupted`（CPU被抢占）。两根均无正式progress/manifest；删除工具还要求没有新record.json或pool_verification。它们同样受用户暂停指令约束，因此保留元数据、明确缓存失效后释放原保护的564文件/157.28GB；原保护计划另存，不隐去此决策。保留timeline、源文件及输入/输出SHA、样本、原始回答/轨迹归档、评分、配置、冻结源码。assets和weights不删除；旧NC80等范围外共享媒体不删除。删除前确认原始输入仍在，记录每个候选的大小/mtime；删除后在新挂载核验路径和保留元数据SHA。

每个根写入USER_PAUSED.json和MEDIA_RETIRED.json，精确记录哪些旧路径已退役；不可按旧progress中的inference误判仍在运行。历史media_cache/items仍保留为证据，其中的video_path不保证继续存在。

## 后续按题生成的约束

当前驱动`prepare_item`本来就在cache未命中时生成；改变的是缓存寿命，而不是必须更换视频处理协议。未来在新目录和新冻结源中，沿用原assets/样本/帧时序/颜色/无损设置，每题只在本机临时磁盘保留输入，等该题所有工具/模型读取完成后再释放。一个题目内的多次观察仍复用同一文件；保留timeline、输入/输出校验、预处理耗时和原始结果到runs。可用有上限的小队列预处理下一题，不能再无限累积到volume。

不热改旧manifest或直接重启旧冻结驱动：其cache命中分支要求文件存在。恢复时继承正常模型结果，只处理剩余题/明确工程失败；旧负结果不能为了提高分数重跑。媒体目录释放不代表剩余实验完成。当前尚未接入/运行上述新按题临时存储实现。

## 历史预处理耗时

从保留的timeline读取`preprocessing_seconds`，按处理方式拆开，单位秒；这是历史实测，包含当时存储I/O、校验和并发资源条件，不是新临时磁盘实现的测量。

| 批次/方式 | 样本数 | 中位数 | P90 | 最大 |
|---|---:|---:|---:|---:|
| LensWalk audit recovery / stream copy | 946 | 4.64 | 13.65 | 36.47 |
| LensWalk audit recovery / lossless | 31 | 3039.38（50.66分钟） | 3601.41 | 3746.14 |
| RSI recovery / stream copy | 159 | 2.14 | 4.45 | 11.69 |
| RSI recovery / lossless | 11 | 1748.99（29.15分钟） | 2788.26 | 3019.04 |
| LensWalk最早全量 / lossless | 23 | 7145.15（119.09分钟） | 7707.00 | 7831.17 |
| RSI最早全量 / lossless | 20 | 6353.61（105.89分钟） | 7239.22 | 7530.40 |

因此不能保证每题现拼接对速度影响很小。普通直接拼接是几秒；需要无损转码的长题仍可能几十分钟。首次输入原本就会生成，失去的是缓存命中时的省时，尤其同题重试/多模型/跨方法复用。推荐按需生成＋本地临时磁盘＋有限预取，同题内以及两个方法短时间共享同一份输入，所有消费者完成后删除；不要每次观察工具调用都重新生成。改存储位置能减少volume读写，但不能消除转码/逐帧校验计算，不能据历史数据凭空给出新方案总吞吐百分比。

## 清理状态

2026-10-18 02:34:38 UTC删除完成：4071 MP4 / 2,055,451,167,921 B（2.055 TB），没有压缩。五根分别删除1281/855/984/776/175个文件，原始结果与元数据不在删除范围。独立新挂载已确认4071个计划路径全部不存在，11,734份保留记录/元数据SHA256全部一致。目录项余74,151/500,000（使用85.17%）；其他实验仍会写入。详细JSON仅保留在runs `devbox/media_retirement_20261018/`。

两批当前根中非基础设施失败的逐题记录也显示缓存复用的影响：LensWalk1257条，准备中位数3.59s/均值76.71s，推理中位数169.35s/均值192.73s；RSI1180条，准备中位数0.41s/均值19.71s，推理中位数97.09s/均值264.88s。其余已有记录由更早批次继承，不包含在这两个根的逐题统计中。缓存命中与视频组合不同，不能直接把这些均值相除当新策略的总耗时增幅。


执行证据：准备`ap-sGUHSEF8OsAL1n2qmPecdZ`；废弃准备引用核验`ap-hJ4gZZ3wwgXVeEjnwmpJSO`；删除`ap-B2yR9bGkHwppzPh0SFPXu4`；新挂载复核`ap-AwZJ0pbkdzDtjXIdDaK8BO`，均完成。边界断言和实际分阶段执行通过，未开展新模型调用或新按题临时存储性能测试。

按02:11容量快照减去本次逻辑删除量，runs约从2.417TB降至0.362TB；这是差额估算，不是删除后的全卷即时重扫，也不代表Modal底层计费已同步更新。assets、weights未清理。
