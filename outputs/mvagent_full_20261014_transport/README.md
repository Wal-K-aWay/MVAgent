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

当前阶段：准备恢复快照及远端验证，尚不能称全量已恢复推理。部署实例为`mvagent-full-20261013`，Sandbox `sb-avRFplVDedzMxeQh67o88z`。
准备任务`mvagent_full_20261014_prepare`；验证通过后从新冻结目录运行原run_full_mvagent.py，并启动带新tag的host watcher。

本轮不重跑已验收的一致性矩阵，也不改变最终答案格式规则。2 GiB有界传输限制覆盖本次101个已知反例，不能据此保证任意大小请求。
