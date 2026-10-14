# 当前输入协议的 RSI / VAM 冒烟

用户重新授权实际测试：验证两个方法在当前拼接与提示设置下能否完成，并检查批量评测与提速路径。Meta 不参与，不运行 Judge 或报告小样本准确率。

## 范围与环境

- 从既有33题开发面板按视频时长选每个benchmark最短一题，不重新随机抽样：`crossvid:MSR:361`、`cvbench:764`、`mvu_eval:TR:1585`，两方法共6个组合。
- Qwen3.5-35B-A3B，固定BF16、seed=0、temperature=0、thinking关闭、prefix关闭，每题独占TP1/C1副本；VAM视觉embedding沿用Qwen3-VL-Embedding-8B。
- 申请8×H100，六个Actor副本供两方法各三题并行，另一卡运行embedding；不在同一副本上提高请求并发。
- 原生尺寸/帧时间拼接，混合编码逐段H.264无损转码；prompt先说明多视频任务与拼接方式，时间显示两位小数。模型侧448限制沿用。
- 源码、媒体、逐请求日志及结果仅保存在Modal runs volume，实验目录`devbox/external_methods_current_20261014_r2`；独立Sandbox名称`mvagent-external-current-20261014`。

## 已测到的

首轮CPU检查发现镜像FFmpeg不支持`-fps_mode`；已改为该环境支持的`-vsync 0`，保持时间戳透传语义。失败日志留在`devbox/external_methods_current_20261014`。

R2的四种组合均通过：同H.264、同MPEG-4、混合编码、混合编码加可变帧间隔；共93帧和8次随机跳转，解码RGB像素、尺寸及时间与原片段一致。适配协议检查、远端完整compileall及三道真实题媒体准备通过。

模型运行结果待补充；上述CPU验证不代表两个Agent已完成。

## 批量与提速

- Video-RSI上游提供`run_batch.py`、`execution.concurrency`线程池与独立评分入口，默认需显式指定发布的final_harness。
- 当前固定版本VAM提供索引/持久化记忆/检索及TUI/server入口，没有公开benchmark批量评测脚本。项目的`eval/external_methods/run_batch.py`为其逐题分配独立进程、存储与模型端点。
- 当前已支持跨题并行。优先保持每题sticky、副本内串行，靠增加独立副本扩展吞吐。
- VAM可考虑复用完全相同视频序列及索引配置的基础记忆；必须隔离各题检索/总结写入，不能共享被题目改写的数据库。当前每题仍独立建索引，未实现此缓存。
- 缩减帧率、步数或token预算会改变方法；本轮不通过这些方式提速。实际耗时与瓶颈待本轮分阶段计时。
