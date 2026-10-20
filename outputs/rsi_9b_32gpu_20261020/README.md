# Video-RSI 9B：32 H100 全量评测

用户授权新建 Qwen3.5-9B 的三个 benchmark 全量测试并估计速度。题目仍为 CVBench997、MVU-Eval1824、CrossVid Lite2500，共5321；不继承35B或其他方法的答案。

使用4组各8张H100，每卡TP1/C1独立处理一道题，每组8路按题临时视频准备。按已完成Video-RSI35B的准备、推理、归档耗时均衡四份题号清单，再沿用原面板顺序（各benchmark一个集成题前置）；仅调度使用历史耗时，原答案不进入9B输入。清单互斥、并集完整，每题只有一个owner。断点续跑跳过所有已保存结果，包括负结果和工程失败。

来源为 `/runs/devbox/rsi_full_35b_parallel_media_20261018/frozen_repo` 的实际冻结源。只修改模型路径、分片计数、进度模型名和扁平结果存储；upstream final_harness、skills、Prompt、OCR、视频预处理、原生图像设置和服务代码逐文件保持相同。保留已确认的多视频拼接/两位小数说明、通用答案适配、Modal隔离差异及HTTP600秒。生成上限8192、温度0、seed0、max_steps11、max_service_calls64、max_frames256、宽768、solver1800秒、整题外层7200秒均沿用既有设置。prefix/MM cache关闭。

每个分片独立完成推理和所属CCQA Judge，结束后释放GPU；唯一主控在四份评分完成后调用CPU合并，断言5321题唯一且完整。逐题推理、准备、归档耗时均保留。原始请求/图片编码只留Modal原始tar，不迁入Git或本机。

- 总根：`/runs/devbox/rsi_9b_32gpu_20261020`
- 分片：同总根名称加 `-shard0` 至 `-shard3`；实时进度读各自的 `progress.json`。
- 准备/速度估计：`eval/external_methods/rsi_9b_32gpu.py initialize|estimate`。
- 主控：复用 `scripts/watch_lenswalk_partition.py --merge-script eval/external_methods/rsi_9b_32gpu.py`。
- 主控日志：modal-gpu `/tmp/rsi-9b-32gpu-20261020/controller.log`。

相对同配置8卡，32卡的并发容量上限是4倍，尚不能称为实测4倍加速。历史35B逐题工作量除以32约17小时，只是启动参考；9B可能产生不同轨迹和输出长度。运行中速度估计用同题已完成且无工程错误的9B/35B推理时间比校正，按最慢分片估剩余时间；短题先结束会造成偏差，排队、加载和最终Judge另计。没有为了对照重跑已有题。

远端CPU已通过四分片互斥/覆盖、原逻辑保留、失败结果跳过、扁平Judge写入、5321条历史评分重汇总和项目语法检查。实际启动、样本与GPU证据待补；不能把资源申请当作32卡已同时推理。
