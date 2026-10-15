# 9B 固定证据回答协议对照

用户授权的小规模诊断；正式 src/eval/configs、两组全量任务及原始结果不变。结果只保存到 Modal runs volume 的 `devbox/answer_ablation_20261015`。

## 冻结方案

- 25个已完成9B检查点：每benchmark固定4个仅`}`、2个可提取且正确、2个可提取但错误，加CV712拒绝选项案例。共12个`}`、6个正确、6个错误、1个拒答。包含Comparison1232和CV664锚点，其余seed0抽样。
- 只选主动answer检查点，CrossVid限单选任务；不包含CCQA、多选、排序和时间定位。是刻意富集失败的开发诊断集，不能将面板准确率外推全量。
- 复用同一问题和公开History，不重看视频或改变取证结果；逐组校验原文子串和证据SHA。上一轮decision reason只额外传给第三组。
- 当前独立回答器：精确重放保存的messages/schema；同时核对历史input hash、完整token IDs、文本和结束原因。
- 旧式直接回答：使用冻结决策System，在一次生成中输出reason/action/parameters.answer；只开放answer动作；删除独立回答器未收到的视频元数据，替换动作说明与结束策略。旧PRO完整Prompt缺失，因此是调用结构复原，不是逐字重建旧版本。
- 加决策reason：当前独立回答器的messages/schema完全保留，仅在User末尾添加`Previous decision rationale`及原始reason，不改写或注入参考答案。
- 三组同为BF16、TP1/DP1/C1、H100、seed0/T0/top_p1、thinking关闭、FlashInfer GDN/native GemmaRMSNorm、prefix/MM cache关闭。各响应2048token；三组reason均无字符上限，answer非空且2400字符，不加选项枚举。沿用一次结构化repair。
- 每题先重放基线，再运行两个候选；候选顺序按题交替。共75次逻辑调用，实际响应数可能含repair。以首次完成的三组配对即开始产出测量。

## 隔离与复核

独立`DEVBOX_NAME=mvagent-answer-ablation-20261015`，1×H100，Sandbox `sb-adNLKaajR6LtDQo4Pm0zxW`。仅访问这个Sandbox内的8100端口；不向生产服务发送任何请求。

运行时从`devbox/mvagent_full_20261014_transport/frozen_repo`复制到本实验目录，配置只在实验目录设独立cache与一个副本。保存运行时文件SHA、实验脚本SHA、来源记录SHA、面板、三组完整请求和实际响应token。历史冻结profile标识保持原值。

入口为`scripts/probe_answer_protocol.py`，`--prepare`在Modal CPU冻结与检查，GPU阶段运行实验目录中的冻结脚本。准备阶段已通过远端语法检查、25题共同证据断言、三组schema验证及与既有分数的一致性检查；正式模型调用结果尚待补充。

准备命令须经modal-gpu，先将devbox的prelaunch源码放到其repo根`.probe_prelaunch.py`，然后CPU执行：

```bash
python scripts/probe_answer_protocol.py --prepare --output /runs/devbox/answer_ablation_20261015
```

独立GPU挂载需reload以读取CPU提交的面板，再执行：

```bash
python /runs/devbox/answer_ablation_20261015/probe_answer_protocol.py --output /runs/devbox/answer_ablation_20261015
```

不覆盖已有面板或results。新源码、新面板或协议变化另用结果目录。原始结果先落盘再评分，官方分与保守提取分分别记录；没有Judge调用。
