# Video-RSI × Qwen3.5-35B-A3B 全量评测

用户授权启动CVBench997、MVU-Eval1824与CrossVid既有Lite2500，共5321题。沿用固定题目清单，排除CVBench64–66已知损坏视频；不因先前小面板NC808准备失败而将该题从全量范围删除。

官方Video-RSI版本5ad0144，运行发布的final_harness及内置策略，不重新进化。规划与视觉均为本地35B-A3B，8192输出token、temperature0、11步、64服务调用、256帧、原宽768串行抽帧、1次provider重试及1800秒solver预算。保留多视频拼接/两位小数时间说明/通用非空答案，HTTP600秒，外层进程7200秒故障兜底。Modal无Landlock，保留seccomp与外层Sandbox。客户端复用原22项锁定依赖，模型为固定BF16、seed0、thinking/prefix/MM cache关闭、8张H100独立TP1/C1，整题固定副本。

本轮不复用旧65题模型答案，全部重新推理。媒体复用旧已验证拼接和初始化时已提交的LensWalk媒体缓存；其余按原尺寸/原帧时间准备，不缩放或转换FPS。缓存按有序视频组合区分，每题单独生成题面。不会改写正在运行的LensWalk冻结源码或媒体文件。

复用全量调度入口`eval/external_methods/lenswalk_full.py --initialize --method rsi`；执行和续跑从新目录的冻结源码读manifest选择RSI。逐题先保存原始输出和请求/token，再官方评分；invalid_decision作为模型未能交付答案计零，基础设施错误单列。原始attempt以未压缩tar逐文件SHA核验后归档，减少散文件；记录预处理、推理和归档用时。连续基础设施失败超过3次停止，避免批量写入无效结果。

CVBench/MVU按题平均，CrossVid十任务macro，CCQA按评分点加权。推理后同一节点切换固定Qwen3-30B-A3B-Instruct-2507 Judge，失败报错不填零。原始数据、冻结源码、输入/模型/依赖元数据均留Modal runs volume。

固定目录`devbox/rsi_full_35b_20261016`，DEVBOX_NAME=`mvagent-rsi-full-35b-20261016`。复用`watch_full_mvagent.py`在后台管理24小时实例、约23小时续跑、跳过已保存记录，并在完成或明确失败后释放GPU。

## 已启动与实测证据

2026-10-16 13:37 UTC：已进入8路真实推理，首批12/5321题全部产生终答（CV7/MVU4/Cross1），75次模型调用、0 HTTP错误、0基础设施失败。样本很少且优先复用已准备媒体，不能据此估计最终准确率。

| 实际输出例子 | 答案 | 官方逐题分 | 推理时间 |
|---|---|---:|---:|
| CVBench335 | B | 1 | 96.15秒 |
| MVU-Eval KIR526 | A | 0 | 84.07秒 |
| CrossVid BU806 | A | 0 | 100.11秒 |

实际8张NVIDIA H100 80GB、8个独立worker身份均已核验；服务profile为`qwen35-bf16-external-upstream`，底层固定BF16数值配置，prefix/MM cache关闭。逐题审计通过完整token、请求/输入hash与固定worker；从原始未压缩tar复读effective_config确认HTTP600、8192/8192、T0、11步/64调用/256帧/1800秒及宽768。证据为`startup_verification.json`和`episodes/1792157338090871141/pool_verification.json`。

- Sandbox：`sb-ePIHdBg91VaZ6W113TVdQG`，13:27:47 UTC分配，driver PID41，13:28:58启动。
- modal-gpu watcher：PID2775586，日志`~/wxu-evolve-agent/devbox/watch-rsi_full_35b_20261016.log`；管理器源码SHA为`ceb088e3c556c2564e8484df05b9ebc5e0288a31e89e5193be187660cc970dc3`。
- 生产代码提交：`cc18f7798fb13030c2bbeb1053d205f0adede6c0`；driver SHA为`76dbe0b96835b415e0db18b4e359a593514759e3a0878fb7a27d8b4f70922808`。
- 5321题清单SHA为`4287d2221aac79865d24016dbd0d0a34d137a5b42745856d55f62aecf1915bd2`，与既有LensWalk全量清单逐字一致；初始化复用569组媒体，全部共4298个有序组合。
- CPU检查app `ap-Et7d88W4ug4GWckDhJbQgn` rc0：准备、真实RSI响应审计、模型失败/基础设施错误分离、归档字节、缓存题面隔离、官方聚合、HTTP参数与完整语法编译通过。
- 首CPU app `ap-q9lb1oDLNwpFGVa7LyoHPT`因CPU镜像缺git命令，在提交元数据阶段退出；0推理结果保留于`rsi_full_35b_20261016_prepare_initial`。后续读取同步好的commit文件修复，不安装新依赖。

本轮全量尚未完成，CCQA Judge在Actor结束后自动执行。会话内独立检查结束后，只有modal-gpu管理器继续常驻；不宣称会话外有独立15分钟巡检。
