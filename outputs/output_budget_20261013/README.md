# 当前 Prompt 下放宽输出预算（2026-10-13）

已完成 35B 对照。只增加 token 上限没有改变所测输出；同时放宽决策 reason，仍有理由写满新上限，
并改变了取证决策。完整样例输出更长、调用更多，没有消除循环。正式默认仍为 2048 token / Global 决策 reason 1200 字符。

## 设置与范围

| 设置 | 每次完整响应 token 上限 | Global 决策 reason 字符上限 |
|---|---:|---:|
| 当前基线 | 2048 | 1200 |
| 只放宽 token | 4096 | 1200 |
| 两者放宽 | 4096 | 2400 |

token 上限针对每次模型调用，不是整条 Agent 的累计输出。
当前“简洁表达＋最佳判断”两个 System 文本不变；两者放宽仅在实验副本中同步 Global schema 和 User 动作示例的上限数字。
其他措辞、题目与冻结 History 不变。终答 reason 已无字符上限，VideoAgent reason 仍为 1200 字符。
取证指令总额度保留 3600 字符，各视频额度不变，避免直接调共享 reason 常量时挤占指令空间。

35B BF16、seed=0、temperature=0、thinking 关闭，固定 固定同步后端，1×H100、TP1/DP1/C1，无 skill。
复用[上一轮](../validation_history.md#concise_system_smoke_20261013-readme)的 4 题旧响应；新跑 8 次只放宽 token 请求、
4 次两者放宽的决策，再完整跑两者放宽的 CV712。两组终答请求相同，只执行一组并共享结果。
未评分、未调用 Judge、未重跑重复性矩阵。

## 冻结请求结果

只放宽 token 的 **8/8 次完整输出 token 序列与基线相同**；请求体除 `max_tokens` 外完全一致。
4 个终答仍只有 2 个直接给出选项，CV712 和 Counting88 仍返回“没有合适选项”的说明。

| 题目 | 基线决策 / reason 字符 | 两者放宽决策 / reason 字符 | 决策 token：前 → 后 |
|---|---|---|---:|
| CV712 | watch_videos / 1200 | answer / 423 | 416 → 105 |
| Counting88 | answer / 1200 | answer / 2400 | 303 → 543 |
| CV376 | answer / 1200 | answer / 2400 | 262 → 526 |
| BU504 | answer / 320 | answer / 415 | 85 → 104 |

Counting88 和 CV376 的理由末尾分别停在 `the summary says 'no fan` 和 `compared to the '`，仍未完整结束。
CV712 变短，却以“证据不支持任一选项”为由结束，失去了原来的继续观看动作。
因此达到字符上限的题数由 3 减至 2，不能直接解读为策略改善。
四决策合计 1066 → 1278 token（+19.9%）。旧基线 / 同机只放宽 token / 两者放宽的累计秒数为
75.54 / 94.77 / 100.31；同输出也有计时差异，跨运行耗时不能全部归因于上限变化。

## 完整 CV712

| 指标 | 当前基线 | 两者放宽 |
|---|---:|---:|
| 最终答案 | C | C |
| 模型调用 | 14 | 16 |
| 全轨迹输出 token | 2719 | 3591 |
| 整题实测秒数 | 174.10 | 296.80 |
| Global 决策理由字符 | 319 / 1200 / 1200 | 315 / 640 / 2400 |
| 独立终答理由字符 | 2555 | 4467 |

两条 Global 轨迹均为分析三个视频 → 向 video_3 索取补充报告 → 终答。
放宽版第二次 VideoAgent 调用增加了一次视觉观察，带来两次额外模型调用；旧版直接根据既有观察补充报告。
终答仍在“所有视频”与“其中两段”之间反复比较，最后选 C；同一字母不证明推理或正确率改善。

放宽版最长一次响应仅 **1154 token**，所有调用都未使用新增的 2048–4096 token 空间。
终答 reason 原本不限字符，其 4467 字符不受 Global 决策的 2400 字符限制。
全轨迹 token 增加约 32%，实测耗时增加约 70%；耗时还受跨运行速度波动影响，不能作为精确因果成本估计。

## 验证与限制

本轮 12 重放 + 16 完整任务调用，共 28 次实际调用：0 模型错误、0 结构化错误、0 JSON 修复、0 token-budget 截断。
完整 token 数量、实际 4096 请求及 Global 2400 schema 已核验。自然 stop 不代表字符受限的理由语义完整。
远端 compileall、2 项既有测试和候选自检通过：2400 字符通过、2401 被拒绝，System/指令/Video 额度不变。

修改仅在 runs 的冻结实验副本，正式 src/configs 未改。这批证据不支持单靠放宽预算解决循环、提前终答或答案形式问题。
未验证 9B/27B、大样本、非空 skill、新预算重复性或准确率；不能声称其他输入永远不需要超过 2048 token。

## 留档

原始数据只存 runs volume `wxu-evolve-agent-runs-20261006` 的 `devbox/output_budget_20261013/`：
manifest、`frozen_repo/`、`combined_repo/`、driver、配置/样本、expected_contract、候选自检、`replay/`、
`agent/records/`、日志、progress、analysis_source 和 analysis_summary。
manifest 保存基线/候选源码哈希、commit、模型/采样配置及预算。复现以冻结工作区为准，
commit 为 `4eb309ba973856ac4ae4b2dcb067535d143bdac7`。
09:39:34 UTC 完成推理；外部 volume 读取最终审计、progress、manifest 和完整原始记录确认持久化。
约 09:43 UTC 显式 down 测试 Sandbox，返回 `terminated`。
独立检查代理确认 down 后最终记录仍可读取、目标 dev box 已不存在，巡检结束。
