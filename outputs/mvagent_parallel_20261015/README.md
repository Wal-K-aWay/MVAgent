# MVAgent 全量测试：两组8×H100并行

用户授权新增8张H100。原组继续27B，并在完成后为9B/27B补CCQA评分；新组独立执行35B-A3B和自己的评分。
每个模型均使用原冻结runtime和相同5321题（CV997/MVU1824/CrossVid2500），8个独立TP1/DP1/C1、BF16、seed0、temperature0。
改变的是跨模型调度，Actor/Prompt/schema/推理配置不变，不重跑一致性矩阵。

- 原目录：devbox/mvagent_full_20261014_transport，最终scope只含9B/27B。
- 35B目录：devbox/mvagent_full_35b_parallel_20261015，独立runtime/media cache和日志。
- 合并目录：devbox/mvagent_parallel_20261015。plan.json明确唯一模型所有者；全部推理和评分完成后由最后完成组的host watcher生成progress.json与comparison.md。
- 调度代码run_mvagent_partition.py只调用原冻结runner、服务启动器、Judge与比较函数，独立保存自己的代码SHA和模型分工。
- 原组通过校验PID、Agent CLI命令和输出目录后接管运行中的27B CLI；原父控制器暂停到Sandbox释放，不中断这条CLI。此后原组不会启动35B。
- 两个host watcher各自负责23小时续接、有限异常恢复及释放自己所属的GPU实例；不同时写另一个模型的结果目录。

远端CPU检查：脚本语法、进程接管/拒绝错误归属、完成后合并、GPU分配等待共3项测试，以及原生命周期自检已通过。

## 2026-10-15 11:09 北京时间部署状态

- 原组Sandbox `sb-avRFplVDedzMxeQh67o88z`：原27B CLI PID5950保持运行，新partition控制器38454、host watcher2047322；只读检查alive/job_alive均为true。
- 9B推理5321/5321完成，27B已完成3743/5321，运行错误均为0；CCQA最终评分待本组推理结束后进行。
- 新组Sandbox `sb-XfN8flgJKz3hyX3j6Fj3nU`已申请H100!:8，但尚未分配execution container，不能称为16卡已经运行。
- 新组host watcher2050602使用`--start-existing`等待已申请实例，03:08:37 UTC记录queued；获卡后自动启动35B。此前等待中的一次提交客户端已取消，Sandbox申请保留，没有重复提交。
- 两组watcher的tag分别为`mvagent_full_20261014_transport`和`mvagent_full_35b_parallel_20261015`，日志在modal-gpu的`~/wxu-evolve-agent/devbox/watch-<tag>.log`。停止某组须先SIGTERM其watcher，watcher会释放该组Sandbox。

分配等待是当前唯一启动阻塞。尚未验证新增组的8卡服务manifest和首条35B输出；获得GPU后应检查，不能把CPU控制器测试当模型运行成功。沿用历史35B整题吞吐预估约26小时推理，另留加载/评分时间；排队时长未知，新组实测后再更新。原冻结E2E比较来源未改为后来的MVU提示位置复测。
