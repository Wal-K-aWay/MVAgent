# MVAgent 全量评测：视频请求传输修复与续跑

目标仍为三模型 × 三 benchmark，共 15963 条有效轨迹：每模型 CVBench997、MVU-Eval1824、CrossVid原Lite2500。

## 已确认的停止原因

原任务9B最终落盘5321题，其中5220成功、101失败。旧root进度在退出前最后一次轮询少1条失败，曾显示100错误。
逐条检查原run_manifest的101条失败：全部存在超过512 MiB的HTTP请求，最大1,545,373,160字节。
例如CrossVid NC50的某个视频请求为551,523,424字节。客户端以base64发送视频，旧服务在读取请求体前拒绝过大的Content-Length；
客户端出现Connection reset by peer，同题后继调用再报Pinned replica failed。不是模型生成的答案格式错误。
所有失败聚合为Incomplete batch，原控制器停止，未进入27B/35B。

## 恢复方式

- 新runs目录：`devbox/mvagent_full_20261014_transport`；原目录`devbox/mvagent_full_20261013`及101条失败记录保持原样。
- 从原冻结源码建立新快照，只提高HTTP请求体上限至2 GiB；另仅重定位prelaunch导入路径。模型权重、推理配置、prompt、schema、帧数和输出预算不变。
- 保留原冻结服务名称；不会用新工作区客户端连接旧服务。核对所有原source_hashes，要求业务源码差异只有HTTP大小检查及对应错误消息。
- 5220条成功result.json在新目录引用原记录，补跑其余101题。既有评分写入采用原子替换，不改写源文件；新recovery.json列明所有来源、大小及失败请求大小。
- 9B完成后原冻结控制器自动跑27B、35B-A3B，最后用原Judge补CCQA并输出与原E2E的同题比较。
- 仍为8×H100、每卡TP1/DP1/并发1、BF16、seed0、temperature0、prefix cache关闭。新目录的media缓存复用原内容键。

## 实际恢复验证（2026-10-14 14:13 北京时间）

远端compileall、14项接口测试、恢复补丁自检和生命周期自检均通过。8个实际manifest核验不同H100、TP1/并发1、prefix关闭和修复后源码SHA一致。
5220条继承记录已并行读取，逐条核对status=ok并记录SHA256（inherited_hashes.json），合计2,557,003,337字节。
实际已补回2条完整轨迹，当前合计5222/5321；新增2条status均ok：

| 样例 | 最大HTTP请求字节 | 实际模型调用 | 最终原始答案 |
|---|---:|---:|---|
| CrossVid NC672 | 1,335,732,913 | 15 | `}` |
| CrossVid NC701 | 559,089,756 | 15 | `}` |

两个超过旧上限的请求已实际完成模型调用；运行恢复不代表答案格式正确。格式偏差按原评分规则保留，不修改答案约束或prompt。
其余99题继续补测，随后原控制器自动进入27B、35B，再完成Judge与比较。数字是本次核查快照，不是最终全量结果。

DEVBOX_NAME=`mvagent-full-20261013`，Sandbox `sb-avRFplVDedzMxeQh67o88z`；主控制器PID3079。
host watcher PID1749260，参数`--tag mvagent_full_20261014_transport`，每23小时续接实例；实际跨时限续接仍待发生。
独立检查代理按15分钟间隔只读核验进展。

准备阶段的两个错误已保留：最后打印的flush参数位置错误发生在产物写完后；随后新manifest把/assets别名与正式入口解析后的挂载路径混用，导致首次resume被拒。
已修复准备脚本，以官方_prepare_output(resume=True)重新核验全部身份通过；修正前manifest另存preparation_manifest_before_path_fix.json，未改原运行或原始结果。
恢复前加载继承记录较慢，另用16线程读取并核验，耗时201.43秒；不新增模型推理。暂停的旧watcher已替换，当前watcher已确认接管新控制器。

本轮不重跑已验收的一致性矩阵，也不改变最终答案格式规则。2 GiB有界传输限制覆盖本次101个已知反例，不能据此保证任意大小请求。
