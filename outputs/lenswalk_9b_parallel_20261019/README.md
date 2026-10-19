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

当前处于部署验证；实际 GPU 分配、继承数量及首批推理证据将在完成切换后补充。原 LensWalk 27B、Video-RSI 和其他 MVAgent 作业不属于此改动范围。
