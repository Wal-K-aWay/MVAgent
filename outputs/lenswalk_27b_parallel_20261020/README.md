# LensWalk 27B 增加至两组8×H100

用户授权再增加8张H100，完成同一批CVBench997、MVU-Eval1824、CrossVid Lite2500，共5321题。已完成结果和负结果保留；模型、Prompt、工具预算、图像设置、超时、BF16/seed0/TP1/C1/prefix关闭沿用原27B冻结源。

从`devbox/lenswalk_full_27b_20261019`交接到`devbox/lenswalk_27b_parallel_20261020`，实际执行根为同名`-shard0`和`-shard1`。新8卡资源排队时原任务继续。新增资源实际就绪后，暂停旧调度器，等待已启动客户端按原1800秒整题预算结束，保存结果并逐原件/在途归档SHA验证；随后退出旧执行者，再启动两组互斥题号的任务。已开始的推理不重做；尚未开始推理的临时视频准备可能重建。

待测题按已完成LensWalk35B的逐题准备、推理和归档耗时分配，均衡两组预计工作量；仅耗时用于调度，历史答案不进入新模型输入。原始面板顺序在组内保留。每组独立处理所属CCQA Judge并释放GPU；唯一主控在两组完成后CPU合并，核验5321题唯一且完整，原结果文件不变。

入口：

- `eval/external_methods/lenswalk_partition.py initialize|merge`：复用既有分片/汇总，仅扩展27B身份和历史耗时分配。
- `eval/external_methods/drain_lenswalk.py`：复用已验交接器；不改原推理源码。
- `scripts/expand_lenswalk_27b.py`：在modal-gpu运行一次，等额外资源、交接、核验、准备两片并启动主控。
- `scripts/watch_lenswalk_partition.py`：唯一新主控，沿用23小时冻结续接和完成释放机制。

2026-10-20 08:32 UTC原任务2404/5321，9工程失败；近1–4小时约96–108题/小时，单组预计剩约30小时。两组同时运行后初估15–19小时含长尾/Judge，资源排队及交接另计；尚未测得两组稳定吞吐，不能声称已实测2倍加速。

CPU `ap-k8sCxdXF6YMsshPDFfaBHB`已通过：9B/27B实际冻结driver只改分片计数、待测耗时均衡/失败保留/互斥覆盖、历史5321评分原样汇总及重复题拒绝、RSI四分片调用者回归、完整项目compileall。无需新推理或Judge完成这些检查。初始分片代码`0f8035e`，交接控制器`0ab49d3`，均已远端备份。

08:42 UTC额外8H100 Sandbox `sb-ukvl24pb5RlGob5p3qsaRd`仍排队，不能称16卡已同时推理。唯一交接host781681，日志modal-gpu `/tmp/lenswalk-27b-parallel-20261020/transition.log`；额外卡申请owner778550，原27B watcher4129397仍继续，其他实验未改。后台控制器在资源就绪后自动推进；实际启动和新增题验证待补。
