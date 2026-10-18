# Video-RSI / LensWalk 剩余评测：按题临时媒体

用户已于2026-10-18明确授权恢复两项剩余评测，取代此前暂停。旧结果与已退役媒体索引不改写；新目录分别是`devbox/rsi_full_35b_temp_20261018`和`devbox/lenswalk_full_35b_temp_20261018`。

## 恢复范围

同一5321题清单：CVBench997（保留64–66三条损坏输入排除）、MVU-Eval1824、CrossVid既有Lite2500。不重新抽题，不使用存储A/B小测答案代替正式结果。

| 方法 | 旧已记录 | 复用非工程失败结果 | 旧工程失败重试 | 尚无记录 | 本次待执行 |
|---|---:|---:|---:|---:|---:|
| Video-RSI | 2614 | 2597 | 17 | 2707 | 2724 |
| LensWalk | 3664 | 3658 | 6 | 1657 | 1663 |

原始正常空答案、未收尾与格式不合格均原样继承，不重跑择优。每个继承结果记录原路径与SHA，恢复完成后复核原文件未被改写。CCQA沿用固定Qwen3-30B-A3B-Instruct-2507及原官方评分，缺少Judge分数在推理结束后补齐；不把Judge失败记零分。

## 唯一执行改动

分别复制各自最后一批冻结源码，保留原模型适配、服务、上游工程、Prompt、预算、超时、媒体编码及严格帧/时间校验。恢复源码`ac5f0dd6284b513048b7e3a309b37095e38169f0`只对各自冻结driver加入临时文件寿命、两路预处理信号量、原服务身份比对；新增独立辅助函数和恢复测试。旧源码除driver及Git HEAD外逐文件SHA必须一致，实际服务的execution/weights_manifest必须与旧批次完全一致。

每方法独立8×H100，单卡TP1/DP1/C1、整题固定副本、seed0及prefix/MM cache关闭。Video-RSI HTTP600秒/solver1800秒/外层7200秒；LensWalk HTTP600秒/外层1800秒，与各自上一批一致。模型输出预算与原图像设置不变。

拼接文件在容器`/work/external-media-*`创建，整题工具调用共同使用；客户端停止后，无论成功、失败还是中断，都删除该题目录。每方法最多8个在途题、最多2路同时拼接；无全量预生成、持久媒体缓存或额外预取。相同视频组合跨题/跨方法会重新准备，牺牲跨题缓存来避免长期累积。

原始请求/回答仍归档并逐文件校验，新增保存题目输入、timeline（含源与拼接视频SHA/尺寸/帧时间）、文件大小和清理记录。分别记录准备、推理、归档耗时；准备耗时包括等待两路预处理名额，timeline还保留实际原预处理耗时。原始视频、权重、历史结果不删除。

## 验证与运行状态

此前4题×2方法存储A/B已通过8/8有效对照、69对模型调用一致；5/5媒体对（含完整NC80长视频）字节相同。该验收直接复用，不重复完整矩阵；详见[存储小测](../external_temp_media_20261018/README.md)。

本次新增远端CPU检查覆盖临时媒体在客户端存活时可读、成功/异常后清理、准备失败清理、继承负结果、工程失败/未测分离、旧文件不变和两个真实冻结driver修改契约。远端compileall及两项正式初始化均通过，CPU任务`ap-1diTlcXwTtlySX3BmzDsHq` rc0；分别保留839/838份原冻结源码，未发现已完成但未提交的孤立attempt需要抢救。

| 方法 | DEVBOX_NAME | Sandbox | Host控制器 |
|---|---|---|---:|
| Video-RSI | mvagent-rsi-temp-35b-20261018 | sb-5FcZS2JO3US6V4BqUcK8Yt | 3514200 |
| LensWalk | mvagent-lenswalk-temp-35b-20261018 | sb-sYmo8jYAFso3e3tiJfEAv9 | 3514203 |

05:09 UTC实查两项均已进入`inference`，每箱8个不同H100 worker的`execution`与`weights_manifest`全部等于各自原服务。实际清单位于各root的`episodes/<episode>/pool_verification.json`；RSI episode `1792299804949185366`，Lens episode `1792299814965409639`。

RSI首批7题推理/1题准备，Lens6题推理/2题准备，输入实为`/work/external-media-*/prepared/media/*/concatenated.mp4`且题内仍可读。已有真实HTTP200输出：RSI CC349首调用102 token/8.41秒，生成`overview`观察请求；Lens MSR62首调用330 token/24.33秒，说明需要跟踪B5/A2并列出两个拼接区间。两条响应实际cached_tokens均为0，完整请求/token保存在各attempt的requests.jsonl。这些是进行中的真实调用，并非本轮已完成整题答案；05:09新完整record仍0。

两项后台日志为`~/wxu-evolve-agent/devbox/watch-{rsi,lenswalk}_full_35b_temp_20261018.log`，实际进度以各新root的progress.json为准。首批真实输出计入本次结果，不重复运行挑选。

17条旧RSI工程失败均为`candidate exited during service call`，整题约1800–2120秒；6条旧LensWalk工程失败包含HTTP错误。它们按原设置重试一次；若模型长输出继续耗尽预算，保留失败，不为追求零失败延长原时间或改生成内容。

后台恢复控制器沿用`scripts/watch_full_mvagent.py`，23小时续接冻结源，有限故障重启，完成或明确失败后释放对应Sandbox。独立检查代理只在本会话内每15分钟检查，不操作作业；会话结束后仅后台控制器继续。

当前不宣称剩余题或完整准确率已完成。长视频仍有无损转码成本，按题临时目录不提供模型推理加速；上轮长视频10.88GB成品/21.76GB采样峰值，后续实际空闲空间与错误随运行记录，不把该单例当作任意题的空间上限。
