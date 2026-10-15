# MVAgent 全量测试：两组8×H100并行

用户授权新增8张H100。原组继续27B，并在完成后为9B/27B补CCQA评分；新组独立执行35B-A3B和自己的评分。
每个模型均使用原冻结runtime和相同5321题（CV997/MVU1824/CrossVid2500），8个独立TP1/DP1/C1、BF16、seed0、temperature0。
改变的是跨模型调度，Actor/Prompt/schema/推理配置不变，不重跑一致性矩阵。

- 原目录：devbox/mvagent_full_20261014_transport，最终scope只含9B/27B。
- 35B目录：devbox/mvagent_full_35b_parallel_20261015，独立runtime/media cache和日志。
- 合并目录：devbox/mvagent_parallel_20261015。plan.json明确唯一模型所有者；全部推理和评分完成后由最后完成组的host watcher生成progress.json与comparison.md。
- 调度代码run_mvagent_partition.py只调用原冻结runner、服务启动器、Judge与比较函数，独立保存自己的代码SHA和模型分工。
- 原组通过校验PID、完整命令、输出目录和进程组后接管运行中的27B CLI；替换原父控制器，不中断这条CLI。此后原组不会启动35B。
- 两个host watcher各自负责23小时续接、有限异常恢复及释放自己所属的GPU实例；不同时写另一个模型的结果目录。

预备CPU检查：新脚本语法、进程接管/拒绝错误归属和完成后合并等2项测试、原生命周期自检已通过。
当前阶段仍为部署；尚待新实例就绪、实际接管和35B首条完整输出，不把申请成功当作推理完成。
