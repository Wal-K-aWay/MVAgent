最新：2026-10-16已完成三模型717条Judge与评分汇总，仍保留已知Actor失败，详见[最终评分](../mvagent_final_score_20261016/README.md)。下文为启动时的历史快照。

# MVAgent 全量测试：两组8×H100并行

后续分析：[PRO 6000 与当前四方同题、轨迹及协议比较](pro6000_aligned_comparison_20261015.md)（2026-10-15 15:35快照）；[12条空答案根因](empty_answers_20261015.md)。下文保留启动时快照，实时状态以远端progress为准。

2026-10-15 11:19北京时间已验证两组实际并行推理。新增组11:11获卡、11:16开始正式35B推理；原27B推理和模型服务没有中断。两组均沿用同一冻结runtime和固定评测方案，只改变跨模型调度。

| 模型 | 已完成推理 | 运行错误 | 负责组 |
|---|---:|---:|---|
| 9B | 5321/5321 | 0 | 原组，待CCQA最终评分 |
| 27B | 3769/5321（11:18） | 0 | 原8张H100 |
| 35B-A3B | 7/5321（11:18） | 0 | 新增8张H100 |

三模型各CVBench997可测题、MVU1824题、CrossVid2500题；不重跑已完成9B。
原组27B完成后补9B/27B评分，新组负责35B及其评分，最后完成的组汇总全部三模型。历史35B吞吐估计剩余约26–30小时含加载/评分余量；首批太少，不据此重估稳定吞吐。

## 协议与实测验证

- BF16、8个独立TP1/DP1副本、每卡并发1、seed0、temperature0、thinking关闭；FlashInfer GDN、原生GemmaRMSNorm，prefix/MM processor cache关闭。Actor、Prompt、schema和输入预算不变。
- 两组冻结源码均为`/runs/devbox/mvagent_full_20261014_transport/frozen_repo`。现有任务保留该快照的历史profile标识；没有改名或连接另一版服务。
- 两组samples.json SHA256相同：`1267acf601cd4488b68135c41cc42e8737c6bcd94bc9a5b835875ae3a0328c05`。
- 独立调度脚本`/runs/devbox/mvagent_parallel_20261015/run_mvagent_partition.py`的SHA256：`13d9d1cd570ad5c01e757f4c990753dcc97312fa1ddec2ea9ab4550fffeb8af2`。它复用原冻结runner、服务启动器、Judge和比较函数，不改推理实现。
- 新组8个manifest已核对：8张独立UUID的H10080GB、8个独立单卡worker、模型身份/缓存设置/seed/数值配置和冻结sync_server源码哈希一致。证据在新组`startup_validation.json`及runtime_cache中。
- 首批7条完整记录均成功，实际token ID长度等于completion_tokens且forward_calls大于0；不是仅启动或健康检查。样例：`cvbench:215`最终答案`C`，4次模型调用/318输出token；`cvbench:246`最终答案`B`，15次调用/1297输出token；`crossvid:FSA:1374`答案`137,147`，4次调用/205输出token。这些只是运行证据，不作准确率或全局确定性结论。
- 远端3项CPU测试通过：合法进程接管/错误归属拒绝、完成后合并、分配等待；生命周期自检和相关脚本语法检查通过。没有重新运行一致性矩阵。

## 后台任务与结果路径

所有原始结果保留在Modal runs volume `wxu-evolve-agent-runs-20261006`。

| 组 | DEVBOX_NAME | Sandbox | 结果tag | 分工 |
|---|---|---|---|---|
| 原组 | mvagent-full-20261013 | sb-avRFplVDedzMxeQh67o88z | mvagent_full_20261014_transport | 9B、27B |
| 新组 | mvagent-full-35b-20261015 | sb-XfN8flgJKz3hyX3j6Fj3nU | mvagent_full_35b_parallel_20261015 | 35B-A3B |

原27B CLI PID5950保持运行，新partition控制器38454接管；原父控制器3079暂停到Sandbox释放，避免它再启动35B。新组partition PID36。两个host watcher初始PID为2047322和2050602，只读检查alive/job_alive均为true；PID会在恢复时变化。

host watcher在modal-gpu运行，日志为`~/wxu-evolve-agent/devbox/watch-<tag>.log`，各自处理23小时续跑、有限异常恢复及所属组完成后释放GPU。新组先以`--start-existing`等待同一申请，随后自动启动；等待中的旧提交客户端已取消，没有重复提交。停止某组须先SIGTERM其watcher，watcher会释放对应Sandbox。

合并目录`devbox/mvagent_parallel_20261015`中plan.json记录唯一模型所有者；两组推理和评分全部完成后生成三模型progress.json与comparison.md。原目录最终model_scope只有9B/27B，不能把该组completed当作三模型全完。原冻结E2E比较来源保持不变，没有改用后来的MVU提示位置复测。

代码与本说明备份在`codex/parallel-full-mvagent-20261015`。状态笔记和环境skill仅本机保存。会话期间Luna独立终检确认两组进展；会话结束后由host控制器持续管理，不宣称代理仍有无人值守的15分钟巡检。
