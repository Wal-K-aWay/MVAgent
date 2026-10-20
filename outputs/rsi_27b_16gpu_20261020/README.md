# Video-RSI 27B：16 H100全量评测

用户授权使用16张H100测试本地Qwen3.5-27B。范围沿用同一批CVBench997、MVU-Eval1824、CrossVid Lite2500，共5321题；从头推理27B答案，不继承35B或9B的答案。

复用已完成Video-RSI35B的冻结源码`/runs/devbox/rsi_full_35b_parallel_media_20261018/frozen_repo`。只改模型路径、分片题数、进度模型名和扁平结果存储，模型以外的运行源码逐文件SHA一致。保留final_harness和技能、8192输出token、temperature0、seed0、11步、64次服务调用、256帧、图像宽768、HTTP600秒、solver1800秒、整题外层7200秒，以及已确认的通用答案和多视频拼接适配。媒体按题临时准备并清理，时间说明保留两位小数；无额外448限制。BF16、TP1/C1、prefix/MM processor cache关闭。

两组各8张H100，每卡独立处理一道题。按35B历史准备、推理、归档耗时均衡题单，仅使用耗时安排任务，历史答案不进入输入；组内保留原面板顺序，并将每个benchmark的一道题前置用于实际集成确认。题号互斥且并集5321；断点续跑跳过所有已保存结果，包括模型负结果和工程失败。每题分别保存推理、准备、归档耗时。

共用入口为`eval/external_methods/rsi_parallel.py`（由原9B四组入口改名）：

```bash
python eval/external_methods/rsi_parallel.py initialize \
  --model 27B --groups 2 --output /runs/devbox/rsi_27b_16gpu_20261020
```

主控复用`scripts/watch_lenswalk_partition.py --merge-script eval/external_methods/rsi_parallel.py`。各组独立推理及所属CCQA Judge，结束后释放GPU，唯一主控随后CPU合并并核验5321题唯一完整。实际执行根为`devbox/rsi_27b_16gpu_20261020-shard0/1`；主控日志位于modal-gpu的`/tmp/rsi-27b-16gpu-20261020/controller.log`。

原始答案、轨迹、评分及耗时只保存在Modal runs volume，不把图片编码、权重或原始数据放入Git。已有RSI9B和LensWalk任务沿用各自冻结源，不改它们的控制器。

2026-10-20 09:25 UTC远端CPU `ap-l2RyoktjAKUxuHnSmBKowP`完成、rc0：项目compileall、两组/四组互斥均衡、实际9B冻结driver逐字一致、27B原协议保留、失败记录跳过、扁平Judge写入、5321条历史评分原样合并，以及估速排除工程失败的自检通过；这些检查没有新推理或Judge，日志中的4条估速自检是合成数据。

运行冻结源码`f2232db325ec455c56d9b6c1b31de1cc52308e1c`。两组题数2660/2661，历史35B工作量990303.67/990319.42秒；若27B与35B同速，16卡约34.39小时，仅为初始占位，不能代替27B实测速度。

唯一主控799426，两子控799430/799431，于09:25提交以下资源：

| 组 | Sandbox | 请求GPU | 题数 |
|---|---|---:|---:|
| 0 | `sb-NZEumzkn84a8CZCaReKpqN` | 8×H100 | 2660 |
| 1 | `sb-C2dlZNjfbVASpeBrxytnAj` | 8×H100 | 2661 |

09:29组0实际启动并进入模型加载，组1仍排队；尚无实际27B结果。一次启动核验进程799614等待每组新增结果后，检查16个不同GPU UUID、27B权重及执行配置、缓存关闭和题号互斥，写父根`startup_audit.json`。控制器会在资源就绪后自动继续，无需重复提交。实际双组推理和输出证据待补。
