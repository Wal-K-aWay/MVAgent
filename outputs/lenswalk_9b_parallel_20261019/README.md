# LensWalk 9B 两组 8×H100 并行续跑

用户要求在原 8×H100 外再增加 8×H100，并避免相同题目重复计算。

本次只改变任务分配：原 5,321 题按 benchmark 分别交替分配到两个互斥清单，已保存结果（包括空答案、未完成规划和基础设施失败）原样继承。每组仍为 8 个 TP1/C1 单卡副本、8 路临时视频准备，沿用原模型身份、数值配置、Prompt、工具、图像、输出和超时预算。CrossVid 为 Lite2500；另含 CVBench 997、MVU 1,824。

旧执行器没有 drain 接口。一次性迁移脚本暂停它的派题父进程，让已独立启动的客户端按原 1,800 秒预算完成；使用原 inspector、评分器和原始归档器保存结果，再关闭旧执行器。尚未推理的媒体准备可重新执行。迁移题的耗时从客户端进程起点与结果文件结束时间重建，并单独标明；其原始 adapter 耗时同时保留。旧已落盘记录逐 SHA 验证不变。新分片须看到旧 Sandbox 已退出的回执才能初始化。

每个题号只有一个静态 owner；本组续跑仅执行尚无保存记录的题。两组分别完成自己负责题目的 CCQA Judge，自动释放 GPU 后由 CPU 汇总，并断言题号无重复、并集等于原面板。沿用原看门狗的 23 小时续接；基础设施中断时，尚未落盘的在途题仍可能需要恢复计算，这是容错重试，不是双组同时派发。

- 原结果：`/runs/devbox/lenswalk_full_9b_20261019`
- 新总根：`/runs/devbox/lenswalk_9b_parallel_20261019`
- 执行分片：同总根名称后加 `-shard0`、`-shard1`；实时状态读两者各自的 `progress.json`。
- 源码：`eval/external_methods/lenswalk_partition.py`、`drain_lenswalk.py`；后台主控 `scripts/watch_lenswalk_partition.py`。
- 回归：`eval/external_methods/test_lenswalk_partition.py` 在 Modal CPU 上运行，验证互斥、完整覆盖、负结果不重算、原推理代码不变和客户端进程计时。

2026-10-19 16:15 UTC 实查：交接完成，1,131 条旧记录逐 SHA 不变，7 道在途题自然收尾并在新 CPU 挂载验证原始归档，合计继承 1,138 条。整题推理重跑 0；只有 `crossvid:NC:766` 的未完成视频准备需要重建。原 Sandbox 已正常退出，停止回执和持久化证明均保存在原结果根目录。

| 分片 | 完整题数 | 继承 | 本次待测 | 16:15 状态 |
|---|---:|---:|---:|---|
| shard0 | 2661 | 569 | 2092 | 8×H100 已申请，资源排队 |
| shard1 | 2660 | 569 | 2091 | 实际 8×H100，已推理 |

两个完整清单的交集为 0，并集为原 5,321 题；源代码冻结 `f94342b`。分片1已有7道新题、135次调用审计通过、0新增基础设施失败。例如 `cvbench:74` 返回原值 `C`，推理72.11秒；`crossvid:BU:246` 返回 `BC`，106.13秒。实际8个服务的权重及 execution 与原9B预期完全匹配，BF16、TP1/C1、seed0、prefix/MM cache关闭。证据位于分片1的 `startup_audit.json`。

唯一后台主控 PID 105628；子控制器 105635/105636。日志在 modal-gpu 的 `/tmp/lenswalk-9b-parallel-20261019/controller.log` 和 `~/wxu-evolve-agent/devbox/watch-lenswalk_9b_parallel_20261019-shard{0,1}.log`。分片0 Sandbox `sb-4qe94AmaHDzv7R0jkUDLPX`，分片1 `sb-5l6NR4b1qHBDOTFUjashGP`。排队分片会自动启动，无需再提交；不应恢复原已停止的完整队列。

只读启动核验 PID 109144 等两组各有新结果后，自动检查16个不同GPU UUID、清单和活跃题号互斥，并保存总根 `startup_audit.json`。该文件成功出现前，不应把“已申请两组”写成“已实证16卡同时推理”。两组完成后的合并由主控自动执行。

远端分片回归、项目语法检查通过。另用历史35B已评分的5,321条结果验证新合并路径：准确率、题数、失败清单和耗时保持一致（浮点容差1e-12），重复/缺失题号会拒绝；此检查没有重推理或调用Judge。迁移时 gVisor 的进程退出码字段不可靠，7道迁移题的 returncode 标记为未知，仍由原请求/结果审计判定工程失败和答案，不伪造退出码。

现阶段尚未测到16卡稳定吞吐；资源排队是当前唯一启动阻塞。原 LensWalk 27B、Video-RSI 和其他 MVAgent 作业未改动。原始结果仍只在 Modal；本地仅代码、说明和状态笔记。
