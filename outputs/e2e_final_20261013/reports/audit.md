# 三模型最终结果核对（2026-10-13）

Modal CPU离线核对完成，原始结果与评分均未修改。主结果见[分析报告](final_results.md)。

## 实际核对范围

- 三模型各5321条成功推理与5321条逐题评分，ID集合逐一一致；仅CVBench64–66不在可测集合。
- 每条成功记录的完整输出token ID数量与usage一致，保存有输入哈希；三模型相同5321题输入哈希逐一相同。
  本轮没有重新推理，不将跨模型输入一致写成输出重复性验证。
- 逐题分重新聚合与summary一致，包括CCQA按点数加权、CrossVid十task macro。三模型scoring_code_matches_inference均为true。
- 717条CCQA回答逐一匹配原始模型输出、官方题库评分点数、coverage/correctness布尔数组及得分公式；全部status=ok，Judge型号一致。
- 根据冻结的SCORE_PROMPT、官方题库与原始回答重新计算Judge缓存键。715条评分匹配现存缓存，35B两条差异见下。
- 本轮只运行CPU分析；Actor/Judge新增调用均为0。CPU分析任务已结束，没有新GPU申请。

## Judge共享缓存差异

每模型239个题号对应214个独特Judge请求文本。20组重复文本合计多25条记录。
重复不代表视频一定相同；这里核对的是Judge看到的问题、标准答案、评分点与模型输出全文。

| 35B题号组 | 第一条评分 | 第二条评分 | 现存缓存 |
|---|---:|---:|---:|
| CCQA733 / CCQA742 | 0 | 1/3 | 1/3 |
| CCQA737 / CCQA740 | 0 | 1/3 | 1/3 |

两组差异都只涉及第一个评分点的coverage/correctness，从false/false变为true/true。
同组Judge输入SHA相同；现存缓存与组内后一个题号的评分一致。原scored文件保留两次不同判定。
代码的缓存键仅包含model+prompt，相同键的并发请求可以各自执行并覆盖同一个缓存文件；这是与观察相符的机制，
但没有请求级时序日志证明实际覆盖顺序，也未定位Judge数值不一致的底层原因。
Actor的Qwen3.5 固定配置重复性验收不能外推到独立Qwen3 Judge服务。

本次没有未评分条目，因此没有补启动Judge。保留原始分数，并计算现存缓存统一口径的敏感性：
35B CCQA36.4597→36.7239，CrossVid macro32.1111→32.1375；27B领先结论不变。
未来若要求Judge结果可完全重建，应先合并同键请求、保留每次原始响应，再对Judge本身做针对性验证；本次未修改评分实现。

## 同题比较

表中为27B相对另一个模型的“分数更高 / 更低 / 相同”题数；FSA/CCQA是连续分数比较，不能称为答对/答错题数。
CrossVid题级胜负不按macro权重汇总，不替代官方总分。

| 对照 | benchmark | 官方分 | 稳健分 |
|---|---|---:|---:|
| 27B vs 9B | CVBench | 131 / 71 / 795 | 132 / 69 / 796 |
| 27B vs 9B | MVU-Eval | 636 / 82 / 1106 | 316 / 179 / 1329 |
| 27B vs 9B | CrossVid | 519 / 233 / 1748 | 551 / 229 / 1720 |
| 27B vs 35B | CVBench | 116 / 77 / 804 | 116 / 75 / 806 |
| 27B vs 35B | MVU-Eval | 505 / 118 / 1201 | 293 / 209 / 1322 |
| 27B vs 35B | CrossVid | 570 / 300 / 1630 | 564 / 315 / 1621 |

MVU从官方改用稳健解析：9B有613题分数上升、57题下降；27B164上升、25下降；35B447上升、5下降。
反向变化说明首字符偶然命中也存在，不能将所有分数差直接当作被救回的正确答案数。
MVU输出token中位数9B237.5、27B2、35B162；达到8192输出上限的题数30、2、10。
这是输出长度观测，不是耗时或因果结论。输入与生成协议不变。

## 来源与复现

原始结果volume：`wxu-evolve-agent-runs-20261006`。
9B在`devbox/e2e_full_20261012/9B`；27B/35B在`devbox/e2e_full_20261013_timeout/{27B,35B-A3B}`。
各自父目录的`frozen_repo`保留实际源码和配置。共同HEAD为`4eb309ba973856ac4ae4b2dcb067535d143bdac7`，含未提交代码，不能仅凭HEAD复现。
E2E无skill，manifest的skill_library为null。

- split SHA256：`5e1cf0e4a0967e365b85f3ad0f5eddb4871beaebd24f421a1b09daac62b8262f`。
- 9B runtime SHA256：`524536b0b3ec5b07aab64b926878635afc1ec4fb2cd438922365953ba1096ccd`。
- 27B/35B runtime SHA256：`90dc9280a3e3416288a302ff0c33a8e8ed02c93781631fb080991360281086f4`。
- 9B summary SHA256：`ba9d68959bdb0521e52aeb3c9bd4ea8ec71ffeba283aa90fd20a9f9f3b894d8a`。
- 27B summary SHA256：`f5bd6cb8c5a04b56aa84fc41144107aea92c96c27a34aa99b9cc075ddc6ce0fa`。
- 35B summary SHA256：`0643d914cd600dc9fe37d7d647eb525396ac4f4826f340af03359eee3032a2ab`。

分析目录`devbox/e2e_results_analysis_20261013/`：`analysis_source.py`为发现缓存差异时失败的初版，
`analysis_source_v2.py`与`analysis.json`保留完整逐项统计，`cache_audit_source.py`与`cache_audit.json`保留共享键追查与敏感性。
后两次CPU任务均rc0；第一次assert失败保留，不写作全通过。
