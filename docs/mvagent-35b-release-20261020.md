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

Modal CPU任务`ap-ptm0IAFlUN6ZDwt4a5d2y5`于2026-10-20 08:28:08 UTC完成，rc0。
全项目语法、媒体文本清理及Judge复用检查通过；不完整Judge报告会被拒绝。
5321份原件SHA与输出/轨迹对应关系、239条评分、五个归档成员大小/SHA与题数均通过；
导出分数与最终分析逐项完全一致。导出源码提交`75d909c`。

发布包：`mvagent-35b-a3b-results-with-trajectories-20261020.tar.gz`。
大小173,059,464字节，五文件解压合计1,047,201,850字节。
SHA256：`21930f8c318b6d57b2b3ccde767ce493a6dfb2f097a64729fd9e82b7f0204bf0`。
Modal到devbox及Lightsail暂存均已核对大小与SHA一致。

2026-10-20 08:30:03 UTC发布核验完成：
[下载35B完整包](https://github.com/Wal-K-aWay/MVAgent/releases/download/mvagent-results-20261019/mvagent-35b-a3b-results-with-trajectories-20261020.tar.gz)。
GitHub附件状态、大小及服务端SHA一致；无需登录完整下载HTTP200，实收字节与SHA再次一致。
更新后的`SHA256SUMS.txt`覆盖三个模型，公开下载内容已核对；原9B/27B附件ID、大小和SHA均未改变。
核验回执保存在本地暂存目录的`github_verified.json`与`release_after.json`。

本次未重跑Actor或Judge、未分配GPU。发布数据不进入Git历史；本地状态笔记及其他会话未提交工作未纳入本工作项备份。
