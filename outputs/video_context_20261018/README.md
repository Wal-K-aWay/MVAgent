# VideoAgent 原题背景小批量对照

2026-10-18 01:32 UTC：准备与源码冻结完成，B/C两个8×H100均进入9B加载；尚无新模型成绩。依据[用户确认的计划](../global_short_large_20261017/video_context_plan.md)实现；独立分支和冻结目录，不更新既有任务。

## 对照与样本

三组的 Global System 均为已测简洁版本，User 与行动/答案协议不改。

| 组 | Video 输入 | 运行 |
|---|---|---|
| A | 原 Video System 与 User | 复用同题简洁 Global 的306条结果 |
| B | 新职责边界 System、视频 ID、原题字段 `(not provided)` | 新测306条 |
| C | 与 B 完全相同，原题字段换为完整实际题目（含选项与定义） | 新测306条 |

每模型102题：CVBench30、MVU-Eval30、CrossVid42（含15CCQA）；沿用已有固定 manifest，不重新抽样。三个模型为9B、27B、35B-A3B。B/C各用一个8×H100实例，依次加载三个模型及既有CCQA Judge。共612条新结果；C−B衡量背景信息贡献，C−A衡量整体改动。分层官方分数、同题净变化、格式/空答案、截断、调用与耗时均报告，保留负结果。

## 改动边界

Runtime仅修改`engine.py`与Video的`agent.py/prompts.py`：传递完整原题和绑定视频ID，普通决策和强制总结均使用计划中的Video System与背景。原题不写入Memory；instruction不改；Observer提示与接口逐字/AST核对不变。B通过冻结源码中唯一一行背景赋值与C区分。

保持BF16、seed=0、temperature=0、thinking关闭、2048输出token、512帧、Global/Video各5步；每卡独立TP1/DP1、并发1、FlashInfer GDN与原生GemmaRMSNorm，prefix/MM processor cache关闭，整题固定副本。不额外做双遍一致性测试。

## 保存与验证

结果只在Modal runs卷`devbox/video_context_20261018/`：冻结源码/manifest、A来源及哈希、B/C逐题轨迹与评分、配对分析。Lightsail仅保存代码和本报告。Volume inode配额耗尽是启动前实际阻塞；仅核验并清理有既存完整冻结源码可恢复的重复模型src副本，保留所有原始回答、评分和共享源码。

已通过：远端完整compileall、2个Video上下文单测、13个Global直接回答回归、B/C唯一差异检查和控制器生命周期自检。冻结源码`bcf3da82db90174e82cb067e58791d449baca68f`，归档SHA256 `1eb35cf16dc6a678c15757d24e23caa78e5b08ca7e339b5d41a336b9dd177bd9`，样本manifest SHA256 `1ba54b1d8d7cfc6e2f7628febf14c4ddb6246b24359b7e04bfc717fb701bbba2`。逐文件核对仅三个预定runtime文件改变，Observer保持原样。按同题历史耗时预计两组并行约1.6小时（实际预留1.5–2小时）。

待完成：模型调用冒烟及完整小面板；Judge与配对分析。开发面板用于筛选，不能据此声称全集或独立测试集普遍收益。

## 既有结果的无损存储整理

原runs卷达到500000 inode上限。18个已完成模型目录中的重复`src`（共5976目录项）逐文件核对SHA、类型、权限、链接后去重：完整来源仍在`global_short_large_20261017/source.tar.gz`、`system_ablation_20261017/source.tar.gz`及各arm的code覆盖文件、`direct_answer_large_20261016/frozen_repo/src`。

已完成的简洁Global扩样两shard×三模型目录，另外无损归档到`devbox/video_context_storage_20261018/global_short_shard{0,1}_{9B,27B,35B-A3B}.tar`。六份合计3,364,935,680字节，8966目录项；每份JSON清单记录相对路径、原mtime/权限、文件SHA与整包SHA。先核验归档并Volume落盘，再在独立CPU任务复核源不变后移除散文件；最终状态见同目录`summary.json`。恢复时解压到原模型目录的父目录即可。完整分析表、分片progress、总冻结源码和本轮复用的pilot原始记录仍留原处。未改动任何答案或评分字节；其他活跃实验不在整理范围内。

## 当前任务身份

- 唯一host控制器PID `3439035`，日志`~/wxu-evolve-agent/devbox/watch-video_context_20261018.log`。
- B：`sb-1kfzoZIe6mqE6bGWX7BeSa`；C：`sb-97xvb2p2MnNJYIk7YhzXHX`。均于01:30:43 UTC创建，实查每组8×H100 80GB。
- 每组progress为`devbox/video_context_20261018/{boundary_only,with_question}/progress.json`。控制器依次完成三模型推理、CCQA Judge，释放自己的两组GPU，再运行CPU配对分析；3小时实例期限、2小时45分控制器上限。不接触其他任务。
- 存储整理最终`summary.phase=completed`，六份归档均外部读取校验后才删除散树；末次可用inode31726（共享卷会继续变化）。
