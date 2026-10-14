# 最终回答器 reason 字符限制对照（2026-10-13）

用户要求放宽reason上限，观察由模型自然结束理由的效果。当前候选只取消最终回答器reason的
JSON Schema maxLength及Prompt中1200字符提示，仍要求非空理由、简洁表达；每次2048输出token预算保留。
其他决策reason的1200字符上限、analyze指令预算、answer开放非空字符串及原长度限制均保留。
不是生成后字符串切片；原上限作用于结构化解码。

## 最终结论（2026-10-13 06:39 UTC）

本次保留schema与Prompt同步取消终答reason字符上限的改动。它帮助两道原逗号题直接自然完成，
但没有解决全部答题格式问题，并增加了终答计算量；没有更改答案枚举、最佳判断策略或取证策略。

三组各8题×2终答重放全部完成：48次终答测试，含原有JSON repair共60次实际模型响应，
24组跨卡终答比较（30组实际模型调用比较）均无差异。原配置的全部请求SHA/prompt SHA/完整token精确匹配历史记录。

| 每组首遍8题 | 最终答案形式合格 | 不经修复且形式合格 | 需JSON修复的题 | 总生成token（含修复） | 终答总秒数 |
|---|---:|---:|---:|---:|---:|
| 原schema与Prompt均限1200字符 | 3 | 3 | 0 | 1847 | 119.99 |
| 仅取消schema上限 | 6 | 2 | 4 | 9450 | 555.21 |
| schema与Prompt均取消上限 | 6 | 4 | 2 | 6089 | 360.16 |

基线表中的“不经修复”不代表reason字段没有受到字符限制；它仅表示没有token-budget截断和JSON修复。
这些是按历史失败选出的诊断题，不是无偏全量样本；耗时只覆盖终答，不是整体Agent吞吐比。

| 样例 | 原答案 | 当前答案 | 当前终答情况 |
|---|---|---|---|
| cvbench:75 | `,` | `A` | reason3382字符，863token，stop，无修复 |
| mvu_eval:TR:1398 | `,` | `D` | reason567字符，134token，stop，无修复 |
| crossvid:NC:928 | 不选择选项 | `}` | reason1086字符，231token，stop，仍格式失败 |
| cvbench:712 | 不选择选项 | `A` | 初始2048token length，现有repair再生成93token |
| mvu_eval:Counting:88 | 不选择选项 | 不选择选项 | 133token，stop，仍格式失败 |
| crossvid:PEA:525 | `C` | `D` | 初始2048token length，repair再生成139token，正常对照的答案也改变 |
| cvbench:376 | `C` | `C` | reason1465字符，294token，stop，无修复 |
| crossvid:BU:504 | `A` | `A` | reason415字符，106token，stop，无修复 |

随后通过正式CLI重新做完整8题×2：**16轨迹、198调用、99配对调用、8组轨迹比较均0差异**。
0模型服务错误、0整题错误、0空答案、0强制步数终止；4个初始响应达到2048token，产生4次structured_invalid，
均由已有JSON修复成功处理。不能把这些初始结构化失败写成0。
每遍仍有NC928/Counting88两个形式不合格的答案。8题全部终答前的作用域input/prompt/token与旧基线一致，
最终请求和输出也匹配本轮重放，说明效果在正式流程重现。

移除schema时，各题prompt token完全相同；CV75前260个、TR1398前364个输出token与原设置相同，
随后在原理由边界附近分叉。与此同时，完整放宽后NC928在无reason字符限制时仍输出`}`，
说明字符限制不能单独解释所有标点答案。

远端完整compileall及2项契约测试通过。原始结果、输入/配置/源码快照与分析代码均在runs volume，
最终分析为`analysis_summary.json`，来源脚本为`analysis_source.py`。06:38:29控制器完成，
06:39已明确释放本Sandbox；独立Luna确认devbox不存在、项目仍仅E2E一个任务、近1h0traceback后结束巡检。
未评正确率、未重测9B/27B及大样本；有限比较不证明所有输入都自然结束或格式合格。

以下保留设计和运行过程。

## 固定实验

- 35B-A3B BF16、固定配置同步后端，2独立H100、TP1/DP1/C1，seed0、temperature0、thinking关闭。
- 固定8个开发样例：5个历史失败（CV75、MVUTR1398、NC928、CV712、Counting88），
  2个理由达1200字符但正常作答的对照（PEA525、CV376），1个短理由对照（BU504）。
- 首先重放历史保存的题目与公开History，仅运行最终回答器。三组各8题×2遍：
  原设置、只移除schema reason上限、同时移除schema与Prompt的reason上限。
  两遍分别路由到两张卡，记录实际token/input/worker。原设置须逐token/请求hash匹配历史结果。
- 然后候选通过正式eval/agent_eval/run.py运行完整8题×2遍，比较完整轨迹重复性，
  并核对终答前调用是否与历史基线完全相同。复用pilot媒体缓存。不评分、不启Judge。
- 原始结果、冻结源码、配置与抽样来源哈希均保存在runs volume的devbox/reason_relaxation_20261013。

## 运行

DEVBOX_NAME=mvagent-reason-20261013；Sandbox sb-zPqrR8E0PEPzPMH7drUrPB，2×H100、3小时上限。
05:40 UTC提交PID59。入口scripts/test_reason_relaxation.py；结束自动释放自身Sandbox，不影响E2E。
模型加载前执行远端compileall与2个文本契约回归。实际阶段见progress.json；重放摘要为replay_summary.json，
完整rollout位于repeat0/与repeat1/，对照报告为agent_report.json。

## 中途证据

远端compileall与2个契约测试通过，两张卡约206秒加载完成。原设置8题×2遍均精确匹配历史
request SHA、prompt SHA、完整token/text/finish；跨卡两遍也完全一致。

schema_only首遍8题全部完成：最终形式合格6/8，但4题依赖JSON修复；直接自然完成且形式合格只有2/8。
CV75、TR1398、CV712、PEA525的初始输出都达到2048 token且没有完整JSON，随后修复为B/C/A/C；
四题单次含修复约127–132秒。NC928/Counting88仍然放弃选项。CV376理由1312字符并自然stop、答C；
短理由BU504保持答A。第二卡已完成的配对均一致，余下两组仍在自动执行。
这不能作为完整放宽版本或正式Agent回归已经通过的结论。

小面板含已知失败，不能用其通过率估计全量准确率或格式失败率。

完整放宽(schema+Prompt)首遍8题：最终形式合格6/8，2题依赖JSON修复，4题不经修复且格式合格。
CV75以3382字符reason/863输出token自然stop并答A；TR1398以567字符/134token自然stop并答D。
NC928仍不合格，且输出变为`}`（reason1086字符，未触及已取消的字符限制）；Counting88仍不选择。
因此字符上限不是所有标点答案的充分解释。CV712及PEA525仍先到2048 token再经修复。
第二卡已返回的5题全一致，完整Agent阶段尚待完成。

06:19三组重放已全部完成，24组跨卡配对均完全一致（含初始输出及repair）。
首遍终答总输出token（含repair）为1847/9450/6089，总耗时119.99/555.21/360.16秒，
分别对应原设置/schema_only/schema+Prompt放宽。最后一组对该诊断面板的终答耗时约为原来的3倍。
这是终答重放，不能当作整个benchmark吞吐比。PEA525在完整放宽版由原C改为D，说明正常样例的答案也可能改变。

06:29完整Agent首遍8/8完成；8题终答前的作用域token/input均与旧基线一致，终答请求和输出与重放一致。
第二遍已经开始，06:31进度2/8。实验没有改进取证策略或增加答案格式枚举；正确率未评估。
