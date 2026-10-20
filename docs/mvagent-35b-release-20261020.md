# MVAgent 35B最终结果发布

用户授权将35B按9B/27B的格式整理，并追加至现有
[MVAgent Results Release](https://github.com/Wal-K-aWay/MVAgent/releases/tag/mvagent-results-20261019)。
本次只导出既有结果，不重新推理或Judge；原始Modal记录及现有两个公开模型包保留。

来源：`devbox/frozen_full_35b_finish_20261020`；导出根：
`devbox/frozen_35b-a3b_results_20261020`。
运行及恢复说明见[35B完成报告](mvagent-35b-recovery-20261020.md)。

包内五文件与前两个模型一致：

- `cvbench.jsonl`、`mvu_eval.jsonl`、`crossvid.jsonl`：id、原始GT、最终答案原值、耗时、文本轨迹。
- `ccqa_scores.jsonl`：239条评分、coverage/correctness及评分点数。
- `statistics.md`：主指标、同题E2E比较、平均耗时、协议与来源说明。

保留模型响应、动作、解析和修复事件；媒体Base64替换为哈希，省略完整token ID数组及重复传输日志。
5321题，CVBench67.50%、MVU-Eval54.28%、CrossVid十任务macro41.27%；
包括1500条复用开发题，不是独立Test。完整原件、视频、权重和冻结环境留Modal。

使用现有`finalize_frozen_results.py`导出与逐原件SHA校验，增加35B来源与已完成Judge复用入口。
导出时断言主指标与已完成分析完全一致；验证归档五成员的大小/SHA、题数及答案/轨迹结构。
本地仅暂存发布包与核验回执于`outputs/mvagent_35b_release_20261020/`，不进入Git数据历史。

当前阶段：导出与验证准备中，尚未上传35B附件。
