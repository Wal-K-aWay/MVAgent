# Video-RSI剩余评测恢复

原`devbox/rsi_full_35b_20261016`于2026-10-17 10:20:24 UTC因拼接末帧duration相差0.033367秒停止；11:58复查仍1440/5321、phase=failed，旧Sandbox已退出、后台控制器不存在。

新目录`devbox/rsi_full_35b_recovery_20261017`计划继承1417个无工程故障的模型结果（1394终答、23invalid_decision），只补3881未完成题及23工程失败，共3904题。题目清单不重抽，原始结果/失败证据保持原样，继承以单个JSON索引引用原轨迹和文件SHA；旧模型无效决策不重跑。实际初始化和启动状态在下方追加。

媒体修复逐字复用LensWalk已验收的`prepare.py`，SHA256 `c9f065768b5ad071adea3cb4ecd6d0e4b2cbe93eb7bb15be0b2ac2757c5d8234`：修正末帧显示时长、忽略非法描述性metadata、保留色彩信息及跨片段默认色彩状态；无损编码使用本地scratch，保持原尺寸、原帧时间和严格RGB校验。此前八组合、OR440全部1090帧及真实NC851边界102帧已通过，不重复扩大媒体测试。新准备可复用原RSI及LensWalk已发布的有效媒体缓存。

RSI的模型、官方final_harness/策略、prompt、宽768、8192输出token、T0、11步/64服务调用/256帧、1800秒solver和600秒HTTP均不变；继续8×H100独立TP1/C1、BF16、seed0、thinking/prefix/MM cache关闭。模型身份和token审计断言仍保留；媒体错误转为单题记录。旧冻结运行不热改，新运行使用自己的冻结快照。

CPU `ap-HnGbtFJZ1MtQVNLjpwD7AJ` rc0：继承/失败筛选/保留invalid_decision及原件SHA/锁定配置/缓存引用自检，真实RSI请求的token和worker审计、失败分类、无压缩归档校验，以及完整compileall通过。尚未将代码准备完成当作新GPU推理已完成。
