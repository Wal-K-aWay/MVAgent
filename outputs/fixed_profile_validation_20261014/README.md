# 恢复固定配置方案（2026-10-14）

**数值配置已验证。** 当前统一名称为 `qwen35-bf16-flashinfer-sync`，关闭prefix cache，保留正常解码KV。
8独立TP1/DP1/C1、BF16、seed0/temperature0、FlashInfer GDN、native GemmaRMSNorm以及原有Prompt/预算保持不变。

已同步共享服务、六个YAML入口（三模型inference、两个Agent默认配置、35B skill进化runtime）、两个相关契约测试，
以及AGENTS、inference/Agent/E2E说明、环境skill和status。
保留`cached_tokens`和`cache_hit_rate`观测字段，不因此启用缓存；prefix关闭时实际应为0。
已删除本地退役的TP8/prefix cache 实验控制器，其原始源码与结果仍保留在旧实验的runs冻结目录。

## 验证

- 恢复参数时，`PROFILE`、`ENGINE_CONFIG`、`ENVIRONMENT`、`VERSIONS`与原全量任务冻结源码逐项相同。后续仅去掉 profile 名称中的版本后缀；历史 manifest 不改写。
- 远端完整compileall与13项相关契约测试通过（prefix计数2、E2E接口9、终答reason2）。
- 本地仅AST、引用路径和git diff检查，没有安装依赖或运行模型。
- 独立H100单卡9B冒烟已完成：mvu_eval:SU:587的E2E两次响应/一次比较0差异，完整MVAgent两条轨迹/一次比较0差异。
  Agent共8次模型调用、4次对应调用比较0差异；8次实际cached_tokens和cache_hit_rate均为0。没有模型/结构化错误，不评分/Judge。
- 实际输出：E2E两遍输出同一段分析、均以`C`结束；Agent两遍最终答案均为`C`，每遍4次调用。
  E2E墙钟21.688/13.854秒，Agent19.044/15.522秒，属于接口冒烟而非吞吐评测。
- 远端phase=completed，输出配置实际为固定配置/prefix=false、H100、TP1/DP1/C1、seed0、native RMSNorm。
  单卡测试实例已释放，显式down返回terminated；原完整评测实例未修改。

首次`devbox/v2_restore_20261014`已通过参数/契约核查并正常启动服务，但冒烟驱动误将未选benchmark传为空ID列表，
被正式入口拒绝，未进入题目推理。已修为显式`--benchmarks mvu_eval`，原错误与源码保留；不改变正式CLI。
修正后的源码快照、manifest、配置和原始记录在runs目录`devbox/v2_restore_20261014_r2`。

运行中的三模型完整评测本来就是冻结固定配置，未同步新源码进去，也未重启其服务或改动结果。
这次是恢复既有数值配置的接口冒烟，不重跑三模型一致性矩阵；prefix cache 实验结果保留为历史证据。
