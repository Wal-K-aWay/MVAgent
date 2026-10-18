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

其他根的媒体cache/输入manifest/符号链接如果引用候选则保护。保留timeline、源文件及输入/输出SHA、样本、原始回答/轨迹归档、评分、配置、冻结源码。assets和weights不删除；旧NC80等范围外共享媒体不删除。删除前确认原始输入仍在，记录每个候选的大小/mtime；删除后在新挂载核验路径和保留元数据SHA。

每个根写入USER_PAUSED.json和MEDIA_RETIRED.json，精确记录哪些旧路径已退役；不可按旧progress中的inference误判仍在运行。历史media_cache/items仍保留为证据，其中的video_path不保证继续存在。

## 后续按题生成的约束

当前驱动`prepare_item`本来就在cache未命中时生成；改变的是缓存寿命，而不是必须更换视频处理协议。未来在新目录和新冻结源中，沿用原assets/样本/帧时序/颜色/无损设置，每题只在本机临时磁盘保留输入，等该题所有工具/模型读取完成后再释放。一个题目内的多次观察仍复用同一文件；保留timeline、输入/输出校验、预处理耗时和原始结果到runs。可用有上限的小队列预处理下一题，不能再无限累积到volume。

不热改旧manifest或直接重启旧冻结驱动：其cache命中分支要求文件存在。恢复时继承正常模型结果，只处理剩余题/明确工程失败；旧负结果不能为了提高分数重跑。媒体目录释放不代表剩余实验完成。当前尚未接入/运行上述新按题临时存储实现。

速度分析与实际清理结果待本轮核验后补记。详细JSON审计仅保留在runs `devbox/media_retirement_20261018/`。
