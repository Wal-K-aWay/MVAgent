# LensWalk 输出审计修复与剩余评测

2026-10-17 12:54 UTC实查，`devbox/lenswalk_full_35b_recovery_20261017`已于11:51:37因输出审计断言停止：2404/5321题，CV468/MVU828/Cross1108，1461终答、742未收尾、197空答案、4工程失败。旧Sandbox `sb-o16sAXluaafjXIWFVcunaU` poll137，watcher2983720及媒体补测队列3098699均退出。

CrossVid MOC169第一轮生成了未被解析为工具调用的规划文本，后四轮继续观察但没有finish。原版LensWalk将第一轮文本保留为`output_text`并写入最终`answer`；它与`all_conversations.jsonl`的answer完全一致，却不等于最后assistant消息。我们额外添加的`last.content == result.answer`断言不符合原版行为，因此错误地停止了整批。

修复只调整结果审计：核对适配器答案与上游保存答案一致；留存较早文本、最后仍在取证的情况归为未收尾。原始答案、评分规则、模型与原版Agent代码均不修改。原MOC169的9次调用全部通过token/worker/cache审计，0 HTTP错误；原文本以未收尾结果计0分直接继承，不通过重跑改善答案。恢复计时保留其适配器95.666秒，并明确标记原外层客户端墙钟未落盘。

新root为`devbox/lenswalk_full_35b_audit_recovery_20261017`，冻结提交`7b45d4be60b6a269402049d6108e84f5a7da9aa5`。13:03:28 UTC准备完成：

- 继承2404条：旧2404条移出待补媒体失败NC851，再加入原已完成但未登记的MOC169。
- 待执行2917题，包含NC851和未完成题；空答案、未收尾与3条旧HTTP故障保留。
- 保留的HTTP故障为MVU Counting11、Counting619、SU1218；未再次重试。
- 复用406组待测题对应的已验证媒体缓存。新冻结源码包含此前已验证的跨片段色彩状态修复，NC851完整补测仍待实际运行。
- 题目清单SHA仍为`4287d2221aac79865d24016dbd0d0a34d137a5b42745856d55f62aecf1915bd2`，原样本与来源记录未变。
- 原模型、上游Prompt/工具/5轮、512最长边、180/32/128帧、Observer温度0.2、Planner缺省温度、无额外输出上限、600秒HTTP及1800秒整题上限均保持。固定本地Qwen3.5-35B-A3B、8独立H100、seed0及prefix/MM cache关闭不变。

原六题真实输出/138次调用审计、终态分类和禁止改写答案回归、继承/缓存复用/原件不变检查与完整compileall已通过。首CPU `ap-zp2g2PgKLLf5qCgqot8Z0Z`在准备阶段被抢占，自动重试因禁止覆盖半成品而rc1；半成品原样移到`devbox/lenswalk_full_35b_audit_recovery_20261017_prepare_interrupted`。后续CPU `ap-QhfK26lLbmTwYZV6KxCn9y`实际初始化rc0，外部Volume SDK复读确认prepared、2404/2917及来源配置。不会把第一次CLI退出0误当内部成功。

后台host watcher PID3181417，DEVBOX_NAME=`mvagent-lenswalk-audit-recovery-35b-20261017`，日志`~/wxu-evolve-agent/devbox/watch-lenswalk_full_35b_audit_recovery_20261017.log`。沿用23小时续跑、完成后CCQA Judge与释放机制，控制器SHA `ceb088e3c556c2564e8484df05b9ebc5e0288a31e89e5193be187660cc970dc3`。旧媒体队列不再启动；本新批次直接包含已验媒体补丁。

driver SHA `2578d49cd45a481fc751ceb0de215d0406a57b719ca68ccf87c20ea7602a3891`，源码差异白名单和原件SHA检查通过。所有原始结果、归档与派生JSON只留runs volume。

## 已恢复真实推理

新Sandbox `sb-T6nYT5Y2IrWlLXoCQxyDFF`实际分配8张H100，13:05:25 UTC开始加载、13:09:29进入8路任务。13:11:13核验八个独立worker的execution和weights_manifest均与旧批次完全相同，prefix/MM cache关闭，实际客户端原参数一致；20个已完成请求全部通过token/worker/cache审计，0 HTTP错误。证据保存为新root的`startup_verification.json`。

此时4题推理、4题媒体准备，仍为2404条继承结果，尚无新增完整题；不能把请求次数当已完成题数。健康检查共享GPU app有2个活动任务、近10分钟0 traceback。本批次后台控制器继续原23小时续跑和最终评分流程，不能将启动成功描述为全量评测完成。
