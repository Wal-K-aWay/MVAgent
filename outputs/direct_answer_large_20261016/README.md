# 恢复直接回答协议后的三模型扩样

2026-10-16，用户要求恢复此前900条面板的方案，在整体约9小时预算内尽可能增加题量。

主工作区及隔离分支恢复四个Global/Engine文件：主动answer同次决策提交，耗尽时decide(answer_only=True)，History位于Available actions之后；删除独立回答器。保留当前System、FFmpeg、2048token、取证reason1200字符、终答reason无字符硬限，以及固定H100/BF16/TP1/C1/seed0/T0/FlashInfer/native norm/cache0配置。公开eval接口不变，其他运行中任务不热更新。

使用两个独立8H100 Sandbox，各承接不重叠的题目分片，三模型依次加载。每题在同一单卡副本完成。按模型和逐题历史耗时估算成本，预留25%吞吐波动与45分钟加载、Judge及收尾；选不超过8.75小时预测值的最大分层面板。控制器10小时封顶并保留未完成记录，不能把未测题记作有效答案。该时间是预测，不是GPU排队或长尾耗时保证。

从已有E2E的5321可测题抽样：CV997、MVU1824、Cross Lite2500。三模型同题，抽样seed0，不按正确率选题；CV/MVU按task人口比例，Cross十task近等额，纳入CCQA。抽中旧900面板且全部推理源码哈希一致的结果原样只读复用，保存SHA。新旧题分开统计，不能把复用开发题称作独立留出验证；不为新日期重跑一致性矩阵。

主对照为同题E2E，MVU使用指令移后结果；另报历史独立回答器。官方评分不改：CV/MVU在子集按task人口权重估计，Cross十task宏平均，CCQA按评分点加权。使用固定Qwen3-30B-A3B-Instruct-2507 Judge；Judge失败报错，不记零。逐模型和benchmark保留配对差值、2000次task内配对bootstrap区间、新题子集、格式/空答案/仅右花括号、截断/修复、工程故障及耗时。区间未按共享视频聚类、未多重校正；不承诺九格均为正。

正式推理复用原CLI。遇到顶层失败时，实验控制器保留失败轨迹，重启本组服务后最多完整重试一轮；其他组继续。不改模型输出、不从reason提取答案、不更改schema选项限制。两组完成后各评分并释放GPU，最后用Modal CPU汇总；原始结果只保留runs volume。

结果根：`/runs/devbox/direct_answer_large_20261016`；冻结源码`frozen_repo`，抽样/成本`selection.json`，身份`manifest.json`，分片`shard0`/`shard1`，最终逐题与摘要`analysis/`。旧结果与既有任务保持原样。

当前状态：代码已恢复、备份；Modal CPU检查/抽样准备进行中，GPU尚未启动。实际题量、启动核验和验证结果将在取得证据后补充。
