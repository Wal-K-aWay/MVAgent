# 恢复直接回答协议后的三模型扩样

2026-10-16，用户要求恢复此前900条面板的方案，在整体约9小时预算内尽可能增加题量。

主工作区及隔离分支恢复四个Global/Engine文件：主动answer同次决策提交，耗尽时decide(answer_only=True)，History位于Available actions之后；删除独立回答器。保留当前System、FFmpeg、2048token、取证reason1200字符、终答reason无字符硬限，以及固定H100/BF16/TP1/C1/seed0/T0/FlashInfer/native norm/cache0配置。公开eval接口不变，其他运行中任务不热更新。

使用两个独立8H100 Sandbox，各承接不重叠的题目分片，三模型依次加载。每题在同一单卡副本完成。按模型和逐题历史耗时估算成本，预留25%吞吐波动与45分钟加载、Judge及收尾；选不超过8.75小时预测值的最大分层面板。控制器10小时封顶并保留未完成记录，不能把未测题记作有效答案。该时间是预测，不是GPU排队或长尾耗时保证。

从已有E2E的5321可测题抽样：CV997、MVU1824、Cross Lite2500。三模型同题，抽样seed0，不按正确率选题；CV/MVU按task人口比例，Cross十task近等额，纳入CCQA。抽中旧900面板且全部推理源码哈希一致的结果原样只读复用，保存SHA。新旧题分开统计，不能把复用开发题称作独立留出验证；不为新日期重跑一致性矩阵。

主对照为同题E2E，MVU使用指令移后结果；另报历史独立回答器。官方评分不改：CV/MVU在子集按task人口权重估计，Cross十task宏平均，CCQA按评分点加权。使用固定Qwen3-30B-A3B-Instruct-2507 Judge；Judge失败报错，不记零。逐模型和benchmark保留配对差值、2000次task内配对bootstrap区间、新题子集、格式/空答案/仅右花括号、截断/修复、工程故障及耗时。区间未按共享视频聚类、未多重校正；不承诺九格均为正。

正式推理复用原CLI。遇到顶层失败时，实验控制器保留失败轨迹，重启本组服务后最多完整重试一轮；其他组继续。不改模型输出、不从reason提取答案、不更改schema选项限制。两组完成后各评分并释放GPU，最后用Modal CPU汇总；原始结果只保留runs volume。

结果根：`/runs/devbox/direct_answer_large_20261016`；冻结源码`frozen_repo`，抽样/成本`selection.json`，身份`manifest.json`，分片`shard0`/`shard1`，最终逐题与摘要`analysis/`。旧结果与既有任务保持原样。

## 启动核验（2026-10-16 16:10 UTC）

抽样已冻结：每benchmark500题，每模型1500题，三模型4500份结果；每模型复用112条，共336条，新推理4164条。Cross每task50题，含50 CCQA。题目来自完整5321题候选集，未按正确率选择；两个分片分别694/806题，历史复用全部落在后者，但预计新增计算负载均衡。按旧逐题耗时校准的预算为8.54小时，550题/benchmark方案预测9.38小时，故留出余量选500；该余量用于长轨迹、初始化与评分。

Modal CPU `ap-Z7DFj6RcHUwLSY0Vv8CtJJ` 完整compileall、13项接口检查、抽样和评分bootstrap自检通过。CPU容器曾被平台抢占自动重启；最后写manifest时因CPU镜像无Git失败，已经保存的题目清单未重抽。CPU `ap-E6LHcqFobMGyt612BPeLPb` 用冻结HEAD文件补齐来源清单，selection SHA保持不变，失败脚本/记录保存在`preparation_attempts/git_unavailable`。此CPU命令末尾额外执行host watcher自检因没有Modal客户端失败；该自检已在实际modal-gpu SDK环境通过，不将两个CPU包装命令的整体退出码写为0。

当前冻结基点7344e07，控制器准备补丁8782d3f；实际源码以manifest逐文件SHA为准。所有src/models、src/mvagent、inference YAML和公开eval runner逐文件匹配900条参考manifest，数值profile相同。当前分支还修正了原有smoke脚本对强制终答方法的调用；该辅助脚本不参与本轮Actor。

两个实际8H100 80GB实例：
- shard0：`sb-jk4FXhwWVr37ngC76DiQpu`，devbox `mvagent-direct-large-20261016-s0`，15:58开始加载，16:03进入9B推理。
- shard1：`sb-8UcIKksenXSGuc9oByhvV6`，devbox `mvagent-direct-large-20261016-s1`，16:01开始加载，16:06进入9B推理。

16:09:55现场核对：新增54＋33＝87份完整9B结果，0顶层运行失败；不把336条预置复用算作本轮新增。两组全部16份实际服务manifest与参考profile/9B权重清单一致。抽查16条新轨迹共182次调用，seed0/T0/2048、实际token长度、输入hash、每题单副本、cached_tokens=0通过；没有重跑双遍。实例子目录保留`startup_audit.json`（shard0）和两份`startup_calls_audit.json`。例：CV445答A、CV477答D、FSA1804答350,375；CCQA498正常输出自然语言比较。这些是运行证据，不是准确率结论。

modal-gpu后台控制器PID2817504，日志`~/wxu-evolve-agent/devbox/watch-direct_answer_large_20261016.log`；负责模型切换、每组Judge、GPU释放与最后CPU聚合。当前正在两组并行跑9B，随后27B、35B自动依次执行；尚未取得本轮后两模型或最终评分。用户此前要求正常启动后退出会话，本轮仅启动核验，结束后不维持独立代理巡检，不宣称存在无人值守的模型代理。后台控制器仍持续运行。

按预算预计16:10 UTC起剩余约8–9小时；实际负载或服务失败可能变化。控制器10小时上限会保留未完成记录，不把失败/未测题补成正常答案。各组阶段读`shard*/progress.json`；根progress在最终CPU聚合前仍可能显示prepared，不能只看根状态。

本轮是系统级Agent/E2E比较，两者取证与调用预算不同。已测到的仅为成功启动和首批交付，效果需等全批和CCQA Judge完成。
