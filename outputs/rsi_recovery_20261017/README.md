# Video-RSI剩余评测恢复

原`devbox/rsi_full_35b_20261016`于2026-10-17 10:20:24 UTC因拼接末帧duration相差0.033367秒停止；11:58复查仍1440/5321、phase=failed，旧Sandbox已退出、后台控制器不存在。

新目录`devbox/rsi_full_35b_recovery_20261017`已继承1417个无工程故障的模型结果（1394终答、23invalid_decision），只补3881未完成题及23工程失败，共3904题。题目清单不重抽，原始结果/失败证据保持原样，继承以单个JSON索引引用原轨迹和文件SHA；旧模型无效决策不重跑。实际初始化和启动状态见下方。

媒体修复逐字复用LensWalk已验收的`prepare.py`，SHA256 `c9f065768b5ad071adea3cb4ecd6d0e4b2cbe93eb7bb15be0b2ac2757c5d8234`：修正末帧显示时长、忽略非法描述性metadata、保留色彩信息及跨片段默认色彩状态；无损编码使用本地scratch，保持原尺寸、原帧时间和严格RGB校验。此前八组合、OR440全部1090帧及真实NC851边界102帧已通过，不重复扩大媒体测试。新准备可复用原RSI及LensWalk已发布的有效媒体缓存。

RSI的模型、官方final_harness/策略、prompt、宽768、8192输出token、T0、11步/64服务调用/256帧、1800秒solver和600秒HTTP均不变；继续8×H100独立TP1/C1、BF16、seed0、thinking/prefix/MM cache关闭。模型身份和token审计断言仍保留；媒体错误转为单题记录。旧冻结运行不热改，新运行使用自己的冻结快照。

CPU `ap-HnGbtFJZ1MtQVNLjpwD7AJ` rc0：继承/失败筛选/保留invalid_decision及原件SHA/锁定配置/缓存引用自检，真实RSI请求的token和worker审计、失败分类、无压缩归档校验，以及完整compileall通过。尚未将代码准备完成当作新GPU推理已完成。

## 实际准备与启动

CPU `ap-UtE6jFi0h6ghP6TuVIOFyn` rc0，12:06:20完成实际初始化：1417继承、3904待处理、1164组媒体缓存复用。冻结源码`fde6a1a0ca7d26d0ebc50b751a118dba7736e48c`；driver SHA `ad1dad6d9e8d05da55493c080da91020ec020d34aecbb1d06246bcca41951755`。原冻结源码除列明媒体/恢复调度及测试文件外全部SHA保持一致；官方均分、十任务macro、CCQA评分点权重和工程失败分母测试通过。

外部Volume SDK已核验新progress、commit、driver、5321题清单SHA及原始method_settings。题目SHA仍为`4287d2221aac79865d24016dbd0d0a34d137a5b42745856d55f62aecf1915bd2`。旧raw和record不改，逐题继承证据与待补列表在`recovery_manifest.json`。

host watcher PID3158291，`~/wxu-evolve-agent/devbox/watch-rsi_full_35b_recovery_20261017.log`，DEVBOX_NAME=`mvagent-rsi-recovery-35b-20261017`。控制器沿用原23小时续跑、结束或明确失败释放机制，源码SHA `ceb088e3c556c2564e8484df05b9ebc5e0288a31e89e5193be187660cc970dc3`。仅管理本恢复任务。

新Sandbox `sb-8LQ1W2nCsdPMrxL5Pmhj9V`申请H100!:8成功，driver PID41于12:07:55 UTC进入`starting_models`，episode `1792238875949979278`。此时累计1417条均为继承，没有新推理结果。OR440、NC889优先检查修复后的媒体；正常启动后继续原待测顺序和评分。

## 已恢复真实推理

12:11:45 UTC，八路开始推理；12:15:34快照1419条（1417继承＋2新增）、1396终答、23保留的invalid_decision、0新增工程失败。新目录计数先剔除23旧工程失败并将它们排回待处理，因此不能把1419与旧1440直接作进度差，也不能把重试计成新的不同题目。

| 首批题目 | 实际答案 | 终态 | 官方分 | 推理秒 | 准备秒 |
|---|---|---|---:|---:|---:|
| MVU OR440 | A | finish | 0 | 57.59 | 0.04 |
| CrossVid NC442 | C | finish | 1 | 60.15 | 11.77 |

OR440的拼接阻断已解除，模型答错作为负结果保留。两题共6次模型调用、0 HTTP错误；运行时逐请求token、输入和worker审计通过。八张实际H100 80GB、八个不同GPU副本，execution与weights_manifest逐项等于原批次；profile为`qwen35-bf16-external-upstream`，TP1/C1、BF16、seed0、prefix/MM processor cache关闭。实际原始tar中的effective_config再次验证HTTP600、8192/8192、T0、11步/64调用/256帧/solver1800和图像宽768。证据保存在`startup_verification.json`，并从外部Volume SDK复读确认持久化。

剩余约3902题。按旧批次20.86小时处理1440题的整体速度粗估约56.5小时，暂按2–3天预留；新批次复用更多媒体，首批也集中补故障，尚无稳定的新吞吐估计。全部Actor结束后自动执行原CCQA Judge和汇总；工程错误与模型负结果继续分开记录。后台控制器继续，结束时会释放GPU；会话内独立检查停止后，不宣称会话外仍有AI巡检。
