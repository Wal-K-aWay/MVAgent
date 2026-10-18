# VideoAgent 原题背景小批量对照

2026-10-18启动准备，尚无新模型结果。依据[用户确认的计划](../global_short_large_20261017/video_context_plan.md)实现；独立分支和冻结目录，不更新既有任务。

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

待完成：远端CPU单测与语法检查；冻结；模型调用冒烟及完整小面板；Judge与配对分析。开发面板用于筛选，不能据此声称全集或独立测试集普遍收益。
