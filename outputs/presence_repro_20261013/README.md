# presence_penalty 小规模重复性测试（2026-10-13）

已完成：presence_penalty=0.5和1.5各6次对首遍比较，全部逐token一致；合计6次同卡、6次跨卡比较，0差异。
3条零惩罚锚点也精确匹配历史输出。该小样本未观察到presence_penalty破坏重复性。

目标：检查固定贪心解码下，设置presence_penalty后同输入是否仍逐token一致；附带观察生成长度、自然结束及JSON结构。
正式代码、Prompt和默认配置不变，结果以本目录报告与Modal原始记录为准。

## 设置与输入

- 35B-A3B BF16，固定配置同步后端，2×H100、每卡独立TP1/DP1/C1，temperature=0、seed=0、thinking关闭。
- presence_penalty取0.5和1.5；每个值每个输入在GPU0跑两次、GPU1跑一次。
  GPU1的输入顺序与GPU0首遍不同，GPU0第二遍也反向排列输入；每个服务进程保持不变。
- 三个输入：当前Counting88触顶Global决策、当前BU504短Global决策、历史CV712长终答。
  消息、reason在前的顺序、JSON grammar与每次2048token预算均保留各自原样。终答使用的是当时的提示协议，不混称当前System结果。
- 18次非零惩罚请求产生12次对首遍比较（6同卡、6跨卡）；额外3次不传presence_penalty的零惩罚请求，逐token核对历史输出。
  共21次实际请求。比较完整token IDs、文本、结束原因、实际prompt哈希、请求及完整输入哈希。
- 同一惩罚值内部比较才计入可重复性；不同惩罚值之间输出改变是处理条件不同，不计为重复失败。

## 实现边界

仅Modal冻结源码中的`sync_server.validate_request`增加presence_penalty字段白名单、有限数值范围校验与向SamplingParams的传递。
AST核对其余服务实现不变；参数进入SamplingParams的值和非法输入拒绝均做断言，远端语法检查通过。
正式源码未开放此参数；候选服务的源码哈希与正式服务不同，不应当作原协议直接投入评测。

使用原始HTTP请求重放，保留首次模型输出并校验JSON；不进行修复，不运行完整Agent轨迹或视觉调用，不评分。
每张卡单独串行请求，两个副本可以同时运行；每次记录实际PID、GPU UUID与模型对象身份。

## 结果

| presence_penalty | 非零惩罚请求 | 同卡比较 | 跨卡比较 | 完整token/文本/结束原因差异 |
|---|---:|---:|---:|---:|
| 0.5 | 9 | 3 | 3 | 0 |
| 1.5 | 9 | 3 | 3 | 0 |

同卡两遍PID、GPU UUID、模型对象保持相同；跨卡使用另一个常驻进程、不同GPU UUID。
每个参数值下，相同输入的请求SHA、完整input SHA和实际prompt SHA均一致。
全部21响应与服务端原始token及实际presence_penalty值逐一核验，参数确实进入生成过程。

附带效果如下，列出每个条件的一遍；非零条件另外两遍完整一致：

| 输入 | penalty=0 | penalty=0.5 | penalty=1.5 |
|---|---|---|---|
| Counting88决策 | 303 token，reason1200字符，answer动作 | 282 token，reason1200字符，answer动作 | 298 token，reason1200字符，answer动作 |
| BU504短决策 | 85 token，reason320字符 | 85 token，reason320字符 | 85 token，reason320字符 |
| CV712历史终答 | 2048 token，length，JSON未完成 | 155 token，stop，reason581字符 | 877 token，stop，reason3485字符 |

CV712在0.5下输出的answer为`None of the options are consistently shown across all videos.`，仍未满足题目选择选项的要求；
1.5下answer为`A`，但reason仍有反复讨论“所有”与“多数”的现象。Counting88两档仍触及1200字符、末尾不完整。
因此本轮证明的是已测输入下的重复一致，不能把JSON有效或自然stop当作通用格式问题已解决。

18条非零惩罚响应均自然stop且通过JSON/schema校验；3条零惩罚锚点中，旧CV712的2048-token截断也如实复现。
共7782输出token，0服务错误，无repair。不同参数之间答案或措辞变化属于条件改变，不是重复性失败。

原始输入、输出、源码和配置均只在runs volume的`devbox/presence_repro_20261013/`。
`manifest.json`保存协议、来源和源码哈希，`service_patch.diff`保存唯一服务改动，`requests/`保存21条原始响应；
`analysis_summary.json`于13:04:25 UTC完成，已由外部SDK确认持久化。13:06后显式down返回`terminated`，GPU已释放。
独立只读检查见[progress_checks.md](progress_checks.md)。

## 限制

这是3个复用开发输入、单个35B模型的冻结请求测试；不代表所有输入、9B/27B、完整多轮Agent或跨进程重启的验收。
输出逐token一致、JSON合格和答案正确是不同指标。本次不检验准确率不退步，也不据此修改正式默认值。
