# Video-RSI × Qwen3.5-35B-A3B 全量评测

用户授权启动CVBench997、MVU-Eval1824与CrossVid既有Lite2500，共5321题。沿用固定题目清单，排除CVBench64–66已知损坏视频；不因先前小面板NC808准备失败而将该题从全量范围删除。

官方Video-RSI版本5ad0144，运行发布的final_harness及内置策略，不重新进化。规划与视觉均为本地35B-A3B，8192输出token、temperature0、11步、64服务调用、256帧、原宽768串行抽帧、1次provider重试及1800秒solver预算。保留多视频拼接/两位小数时间说明/通用非空答案，HTTP600秒，外层进程7200秒故障兜底。Modal无Landlock，保留seccomp与外层Sandbox。客户端复用原22项锁定依赖，模型为固定BF16、seed0、thinking/prefix/MM cache关闭、8张H100独立TP1/C1，整题固定副本。

本轮不复用旧65题模型答案，全部重新推理。媒体复用旧已验证拼接和初始化时已提交的LensWalk媒体缓存；其余按原尺寸/原帧时间准备，不缩放或转换FPS。缓存按有序视频组合区分，每题单独生成题面。不会改写正在运行的LensWalk冻结源码或媒体文件。

复用全量调度入口`eval/external_methods/lenswalk_full.py --initialize --method rsi`；执行和续跑从新目录的冻结源码读manifest选择RSI。逐题先保存原始输出和请求/token，再官方评分；invalid_decision作为模型未能交付答案计零，基础设施错误单列。原始attempt以未压缩tar逐文件SHA核验后归档，减少散文件；记录预处理、推理和归档用时。连续基础设施失败超过3次停止，避免批量写入无效结果。

CVBench/MVU按题平均，CrossVid十任务macro，CCQA按评分点加权。推理后同一节点切换固定Qwen3-30B-A3B-Instruct-2507 Judge，失败报错不填零。原始数据、冻结源码、输入/模型/依赖元数据均留Modal runs volume。

计划目录`devbox/rsi_full_35b_20261016`，DEVBOX_NAME=`mvagent-rsi-full-35b-20261016`。复用`watch_full_mvagent.py`在后台管理24小时实例、约23小时续跑、跳过已保存记录，并在完成或明确失败后释放GPU。启动前CPU检查和首批GPU实测尚待完成，不将代码准备视为已开始推理。
