# TP8 + prefix cache 巡检

## 2026-10-13 17:25 UTC

- 阶段：r2 的 `tp8_prefix_c16` 已加载并通过 API 就绪探针，进入 repeat0 推理阶段；与原全量任务隔离的 Sandbox 仍在运行。
- 已完成实验单元：0；有效完整轨迹/样本：0；主吞吐：尚无可计算结果。
- 实测证据：`progress.json` 显示 `phase=inference`、`repeat=0`、`passes=[]`、错误为空；`startup.log` 记录 TP8 API 已于约 260.3 秒后就绪。repeat0 日志目前只有 endpoint probe，尚无落盘轨迹。GPU 状态显示八卡空闲，health 报告该 app 有 2 个任务、近一小时 traceback 为 0。
- 当前阻塞：没有已知外部阻塞；首轮推理尚未产出可计数轨迹，因此暂不能比较吞吐或重复性。
- 下一动作：让正在运行的 repeat0 继续，等待完整 Agent 轨迹写入后统计有效样本与墙钟吞吐。
- 首轮失败记录：旧 `devbox/tp8_cache_20261014` 中 TP8 API 因 volume 下过长 `TMPDIR` 导致 ZMQ IPC socket 路径超过限制，0 推理结果；r2 已设 `TMPDIR=/tmp` 并启动成功。全量任务未检查或操作。

## 2026-10-13 17:40 UTC

- 阶段：r2 已结束并自动释放 Sandbox；TP1 开启 prefix cache 的实验配置 两遍完整测量完成。主执行者正在准备同名 devbox 的新 allocation，以补跑 TP8 两遍（r3）；本次巡检尚未看到 r3 的 volume 目录或任务名。
- 已完成实验单元：TP1 开启 prefix cache 的实验配置 repeat0/1，各16/16，共32条完整轨迹；主吞吐分别4.38和4.63题/分钟（墙钟219.165秒、207.407秒）。每遍152次调用；加权缓存命中率7.53%/16.42%。16条成对轨迹及157组相同输入调用比较均无差异。
- TP8证据：r2 repeat0 的 summary.json 明确记录16/16完成；控制器 progress.json 因 `usage.prompt_tokens_details` 为 null，在总结时抛出 `AttributeError`，因此没有写入该遍的 passes 统计。主执行者从原始记录核出约257秒、9并发请求、prefix命中约3.3%，并已修复null按零缓存处理的统计逻辑。TP8 repeat1 尚未完成；r2中没有任何TP8 repeat1目录。
- 当前实例实况：devbox health 为 deployed、2 tasks、近1小时0 traceback；status没有运行中的benchmark job、全部GPU仅4 MiB占用且服务端点均down；volume中仍只见r2，尚未见r3。故当前可确认TP1完成、TP8首遍有16条原始轨迹；不能声称TP8冷热重复已完成，也没有r3主吞吐结果。现象符合新任务尚处于分配/启动准备阶段，未见外部故障证据。
- 下一动作：主执行者继续启动r3并补跑TP8两遍；产物出现后再读进度和完整轨迹计数。旧 `mvagent-full-20261013` 未检查或操作。

## 2026-10-13 17:55 UTC

- 阶段：r3 的 TP8 repeat0/1 均已完成；`progress.json` 为 `phase=completed`，最近更新时间17:54:49 UTC。devbox `status` 返回 Modal Sandbox 正在关闭，health 为 deployed、1 task、近1小时0 traceback；GPU/端点状态未能读取，错误是 teardown 中的 `ConflictError`，并非任务失败。
- 已完成实验单元：TP1 开启 prefix cache 的实验配置 r2 两遍各16/16；TP8 r2 repeat0 16/16（原始有效轨迹，汇总器曾因null缓存字段报错）；TP8 r3 两遍各16/16。TP8 r3耗时312.864秒与255.962秒，吞吐3.07与3.75题/分钟；每遍无模型错误、结构错误、修复或截断；加权缓存命中10.68%与45.61%。
- 重复性结果：r3两遍成对轨迹16/16均有变化；24组完全相同输入调用比较中18组token不一致，最早分歧在第4个token。需将整题后继调用变化与相同输入反例分开解释；r2 TP1此前16条轨迹与157组相同输入比较均一致。
- 当前阻塞：无待完成推理或样本；本阶段数据已经产出。待主执行者解读TP8不同分配的首遍/次遍速度差异与重复性差异。TP8 r2首遍约257秒、cache约3.3%、9个并发请求的有效结果仍由原始记录核实，控制器曾因null usage而漏写统计；r3的统计修复后完整落盘。
- 下一动作：主执行者分析并报告结果/限制；巡检停止，不安排无活动后的后台监控。完整MVAgent任务未读取、未操作。
