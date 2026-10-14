# 三模型完整 MVAgent 与 E2E 同题比较（2026-10-13）

> 2026-10-14 13:30北京时间核实：任务已停止，9B 5220条成功、100条失败、1条未完成；27B/35B尚未启动。以下启动记录保留历史背景，不能据此认为任务仍在运行。

**运行中，尚无三模型最终成绩。** 本地仅保存说明与巡检；原始结果和自动生成的比较表全部保存在Modal runs volume。

## 固定范围

| Benchmark | 每模型实际执行 | 所选范围 |
|---|---:|---|
| CVBench | 997 | 全部1000题中，64–66使用已知损坏视频；与E2E相同，3题单独记录 |
| MVU-Eval | 1824 | 全部 |
| CrossVid | 2500 | 与E2E完全相同的Lite2500清单，包含239条CCQA |
| 合计 | 5321 | 三模型合计15963条可测轨迹 |

Actor依次为Qwen3.5-9B、27B、35B-A3B，均BF16。总共8×H100，每卡独立TP1/DP1、并发1，整题固定副本。
使用固定配置同步后端、FlashInfer GDN、native GemmaRMSNorm、seed0、temperature0、thinking关闭、默认零惩罚。
本任务及其跨实例续跑始终使用启动时冻结的固定配置源码；后续本地开启 prefix cache 的实验配置/prefix cache改动不进入这一批结果。
无skill；当前refined System、每次2048输出token/512帧、Global/Video各5步、决策reason1200字符、终答reason无字符硬上限均不变。
按seed0只打乱执行顺序；没有重抽CrossVid清单，也不重跑一致性矩阵。

## 执行与后台管理

- 主控制器：[run_full_mvagent.py](../../scripts/run_full_mvagent.py)，复用正式`eval/agent_eval/run.py`、冻结源码与`--resume`。
- 外部看守：[watch_full_mvagent.py](../../scripts/watch_full_mvagent.py)，仅在`modal-gpu`运行。它接管现有任务，不重复提交；
  每23小时保存进度并重新分配8卡Sandbox，从原冻结源码继续未完成题目，以避开24小时上限。
- 非预期实例退出最多自动恢复两次；控制器明确报failed时释放GPU并停止，不无限重试错误。完成后释放GPU。
- 固定DEVBOX_NAME：`mvagent-full-20261013`；任务名：`mvagent_full_20261013`。
- 初始Sandbox：`sb-n1pMjpocWFh8lU2zFxZr2b`；初始正式控制器PID78，host watcher PID1381015。后续换实例/PID以实时状态为准。
- host watcher日志：`~/wxu-evolve-agent/devbox/watch-mvagent_full_20261013.log`；PID文件同目录`watch-mvagent_full_20261013.pid`。
- 查看任务：经环境skill工具读取`devbox/mvagent_full_20261013/progress.json`；查看单模型完整记录计数：`9B/progress.json`等。
  不因为同步服务的短HTTP探针超时而认定它退出。
- 停止整批任务时，先在modal-gpu停止watcher PID（SIGTERM会结束它拥有的Sandbox），再确认该名称的devbox已释放；仅停止GPU可能被看守视为中断而续跑。

看守已通过状态转移小测试与实际只读接管检查。真实跨23小时续跑尚未发生；不把逻辑测试写成已完成的时限续跑验收。
长期运行的独立只读检查见[progress_checks.md](progress_checks.md)。

## 结果位置和口径

runs volume：`wxu-evolve-agent-runs-20261006`，根目录`devbox/mvagent_full_20261013/`：

- `frozen_repo/`、`manifest.json`、`configs/`、`samples.json`、`selection.json`：源码、配置、模型/版本、来源哈希与固定ID。
- `known_unavailable.json`：CVBench3条源视频故障；不混入997道可比较题。
- `<模型>/records/<benchmark>/<sample_id>/result.json`：原始轨迹、每次模型请求/响应、token/输入哈希、最终答案、状态和逐题评分。
- `<模型>/summary.json`：闭式题评分和CCQA待评分状态；`score/ccqa_scores_official_qwen3_30b_a3b.json`、`ccqa_judge_cache/`保留Judge原始结果。
- `<模型>/summary_scored.json`、`benchmark_results.md`：使用现有汇总器合并延后评分的CCQA；原始记录保留deferred状态。
- `comparison/<模型>.json`：每题MVAgent/E2E答案、分数、差异、耗时、调用数和token；CCQA最终分数看`agent_score`，原始`scoring_status`仍反映原记录。
- `comparison.md`：本次同题比较的主表；未满样本数时明确为已配对题的暂定结果。
- `first_results/comparison/9B.json`：首批27题的配对程序实测产物，独立于正式全量比较，不能当作最终成绩。
- `lifecycle_controller.py`：实际后台看守代码副本；其作用只是在实例时限/退出后继续原冻结推理。

闭式题先保存轨迹再评分。三个Actor都完成后，切换到与E2E相同的Qwen3-30B-A3B-Instruct-2507，使用相同官方Prompt/参数评CCQA；Judge失败报错，不记零分。
比较表中CVBench/MVU为相同ID的逐题均分；CrossVid为十类task等权macro，CCQA按评分点加权。
`progress.json`里的`scored_mean`仅是已评分部分的进度统计，不是CrossVid正式总分。
Agent原始汇总器还提供按task总体规模加权的子集指标；与E2E比较以`comparison.md`为准，避免将997题均分与子集加权指标混用。

E2E来源：9B为`devbox/e2e_full_20261012/9B`，27B/35B为`devbox/e2e_full_20261013_timeout/<模型>`。
模型、题目集合和Actor后端一致，但Agent动态取证/多轮调用与E2E的整段固定抽帧、单次预算不同；这是系统级比较，不是等计算预算消融。
既有E2E的Judge曾出现相同文本评分差异，因此保留两侧原判定与缓存，不宣称Judge通用确定性。

## 启动验证

- 首次启动因`/runs`实际挂载路径被resolve后与逻辑路径比较而误拒，尚未推理；已修复并在实际挂载环境检查。
  原错误保存为`startup_path_validation_failure.log`，复用同一8卡实例重新启动，未重做任何模型结果。
- 控制器小测试覆盖固定ID/执行顺序、未评分结果不记零、CCQA评分点加权及评分更新后的记录缓存刷新。
- 远端compileall与两项现有契约测试通过；9B八个副本全部ready，约223秒。
- 16:28 UTC已产生27条正常完整轨迹、274次模型调用，三个benchmark均有结果，0整题错误。
  其中25条闭式题已评分，2条CCQA等待Judge。首批真实配对代码已成功运行；CV9/MVU6的指标只是局部数据，CrossVid总分暂不计算。
- 实际输出示例：`mvu_eval:SU:587`返回`B`，4调用/342输出token/25.96秒；`crossvid:FSA:1374`返回`137.0,147.0`，8调用/702输出token/36.95秒。
  两者当时官方得分均为0，运行成功不等于答对。
- 16:41:52 UTC已完成149条轨迹、1792次模型调用，CV36/MVU46/Cross67，0整题错误，10条CCQA待Judge。
  16:42再次确认外部看守进程及状态日志正常；整题状态正常不等于没有中间修复或答案格式偏差。

正在运行，不把提交成功、首批验证或暂定指标写成全量评测完成。首批速度仍含预热/长题尚未返回的偏差，整体粗估约2–3天，后续按实际完成速率更新。
