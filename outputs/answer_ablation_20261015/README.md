# 9B 固定证据回答协议对照

用户授权的小规模诊断；正式 src/eval/configs、两组全量任务及原始结果不变。结果只保存到 Modal runs volume 的 `devbox/answer_ablation_20261015`。

2026-10-15 16:34北京时间完成75/75逻辑调用，共78次实际响应。结果：**复原旧式直接回答在本面板消除了全部12个`}`，最终25/25格式合格，正确数6→15；追加上一轮reason只有部分改善，仍有8个`}`，正确数6→10。** 两候选均保留6/6原正确题。小规模开发面板不等于全量保证，不据此修改正式配置。

## 实测结果

所有指标均保留25题作为分母。正确率使用现有官方闭式评分；本面板官方分与保守提取分完全相同。

| 方式 | 最终仅`}` | 最终格式合格 | 正确数 / 准确率 | 原正确6题保留 | 初次截断 / 修复成功 |
|---|---:|---:|---:|---:|---:|
| 当前独立回答器 | 12/25 | 12/25（48%） | 6/25（24%） | 6/6 | 1 / 1 |
| 旧式直接回答（结构复原） | **0/25** | **25/25（100%）** | **15/25（60%）** | 6/6 | 1 / 1 |
| 独立回答器追加决策reason | 8/25 | 17/25（68%） | 10/25（40%） | 6/6 | 1 / 1 |

- 直接组：12个原`}`全部变为合格选项，其中7个正确、5个错误；另修正1个原可读错误及CV712拒答。合计9题由错到对，0题由对到错。
- 加reason组：12个原`}`修复5个，其中3个正确，仍残留7个；另外CV93由正常选项变为`}`，所以最终共8个。加上CV712修正，4题由错到对、0题由对到错，但有1题格式退步。
- 每组都有1次初始响应2048token截断，均由既有一次repair完成JSON；最终没有空答案。不是“全程没有结构化错误”。78次响应无服务/网络错误，三次structured_invalid均对应上述截断。

| Benchmark（本面板题数） | 独立：正确 / 格式合格 | 直接：正确 / 格式合格 | 加reason：正确 / 格式合格 |
|---|---:|---:|---:|
| CVBench（9） | 2 / 4 | 5 / 9 | 4 / 6 |
| MVU-Eval（8） | 2 / 4 | 5 / 8 | 4 / 6 |
| CrossVid单选（8） | 2 / 4 | 5 / 8 | 2 / 5 |

这里是所选题的直接计数，不是benchmark全集指标或CrossVid十任务macro。

### 代表案例

| 题目 | 当前独立回答 | 直接回答 | 加上一轮reason |
|---|---|---|---|
| MVU Comparison:1232 | `}`，理由明确A；127token | **A正确**，73token | 仍为`}`，理由仍支持A；102token |
| CVBench:712 | 拒绝全部选项，145token | **A正确**，102token | **A正确**，128token |
| CVBench:664 | B正确，66token | B正确，46token | B正确，64token |
| CVBench:93 | C，格式正常但错误 | C，格式正常但错误 | **`}`，新增格式失败**，70token |

Comparison1232尤其重要：上一轮decision reason明确说A，新增reason后模型最终理由也仍支持A，却再次提交`}`。因此“回答器只是因为没看到前一轮reason才输出`}`”已被这个对照反例否定。

CV712问所有视频中“提到或展示”的共同动作。基线拒绝选项；直接组和加reason组都保留“视频1文字提及、视频2/3展示榨汁机”的判定，正确提交A。可见传递reason对某些前后判断不一致案例有帮助，但不是普遍的格式修复。

### 截断和长尾

- 当前独立组：CrossVid PEA950初次2048token截断，repair166token完成，最终D错误，约71.05秒；这一整段也精确匹配历史输出。
- 直接组：MVU TR1443初次2048token仍在讨论证据顺序与选项不一致；repair68token提交B，格式合格但答案错误，约70.03秒。直接回答并未消除理由循环的所有风险。
- 加reason组：CrossVid NC19初次2048token截断，repair仍输出1470token、reason5378字符，最终B错误，约111.98秒。这说明加入历史判断也可能继续拉长争论。

### 回答阶段耗时

| 方式 | 25题累计调用耗时（含repair） | 单题中位数 | 输出token总数 |
|---|---:|---:|---:|
| 独立 | 220.96秒 | 3.86秒 | 6547 |
| 直接 | 135.39秒 | 2.53秒 | 4081 |
| 加reason | 185.48秒 | 2.99秒 | 5727 |

直接组这一批回答调用累计少约38.7%，但只是冻结证据后的回答重放，不包含重新取证或完整Agent调度，不能外推全程提速。实验08:21:36 UTC开始初始化、08:34:06结束，约12分30秒含加载；实际三组调用合计约9分2秒。

## 结论与边界

在权重、后端、问题、已有证据与输出预算固定时，改变回答协议可以显著改善本面板的交付和准确率，说明这些`}`并非由视觉证据不足不可避免地产生。直接回答值得优先进一步验证；只追加上一轮reason不能作为已解决`}`问题的修复。

直接组同时使用决策System、直接提交动作以及嵌套答案结构，且将可用动作限制为answer；因此本次验证的是这一套终答协议，不能分离为“答案嵌套位置”“某句Prompt”或“独立调用本身”的单因素结论。没有完整重跑Global/Video决策路径，也没有验证27B/35B或大规模随机留出集。6/6原正确题保留是本次观察，不是任意输入准确率不降的保证。

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

入口为`scripts/probe_answer_protocol.py`，`--prepare`在Modal CPU冻结与检查，GPU阶段运行实验目录中的冻结脚本。准备阶段已通过远端语法检查、25题共同证据断言、三组schema验证及与既有分数的一致性检查；GPU阶段已完成75次逻辑调用及78次实际响应审计。

准备命令须经modal-gpu，先将devbox的prelaunch源码放到其repo根`.probe_prelaunch.py`，然后CPU执行：

```bash
python scripts/probe_answer_protocol.py --prepare --output /runs/devbox/answer_ablation_20261015
```

独立GPU挂载需reload以读取CPU提交的面板，再执行：

```bash
python /runs/devbox/answer_ablation_20261015/probe_answer_protocol.py --output /runs/devbox/answer_ablation_20261015
```

不覆盖已有面板或results。新源码、新面板或协议变化另用结果目录。原始结果先落盘再评分，官方分与保守提取分分别记录；没有Judge调用。

## 审计与产物

- 25/25当前独立回答重放的请求SHA、prompt token SHA、完整输出token、文本、结束原因与原始记录精确一致，含一次repair。不是另换配置后只比较答案文字。
- 75个实际structured_request与面板记录逐一相同，三组共享问题/History哈希；参考答案仅用于离线评分。78个model_request均为temperature0/top_p1/max_tokens2048/seed0。
- 服务manifest证实1个H100 80GB worker、BF16/TP1/max_num_seqs1、prefix/MM cache关闭、FlashInfer GDN及native GemmaRMSNorm。thinking由冻结服务器默认并强制关闭，HTTP payload没有显式chat_template_kwargs。此历史冻结服务未记录逐请求cache计数，不能把缺失值写成实测0。
- 78个响应token长度与usage一致，实际forward计数>0，全部同一PID261、GPU UUID `2f0785c5-af5b-50e1-043f-db704e3e7b77`。vLLM0.19.1、torch2.10.0、transformers4.57.6、xgrammar0.2.2、FlashInfer0.6.6。
- 实验脚本SHA256 `59ac6006705dbcd9abd1173870c857b4ecb083ff031eeda6018b02eca496b240`，与已提交源码一致；服务源码SHA256 `2e9902f1374a073ba64de1a08e3e592bcda2d40ae8a4543c0149207ab59f0e2f`。代码检查点`075f6f1`，正式源码来自记录的冻结transport目录，完整文件SHA在manifest。
- `panel.json`：面板、来源记录SHA、问题/History、决策reason、三组请求、历史响应；`results/<variant>/<sample_id>.json`：逐次原始结果和事件；`summary.json`：75行配对指标；`analysis.json`：汇总、配对改善/退步、案例、审计；`analyze.py`：汇总复核脚本；`runtime_cache/`：实际服务身份和日志。
- CPU准备曾发现路径符号链接和旧Prompt段落顺序不同，修正后才开始推理；旧准备错误保留为`preparation_failure.json`。最终进度与有效结果以completed状态及analysis为准。75次正式实验不受准备失败影响。
- 结果已通过modal-gpu外部Volume SDK读取核验持久化。仅释放本实验1卡，原两组全量任务不变；本地只有源码与Markdown，原始数据留Modal。
