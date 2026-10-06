# Qwen3.5-35B-A3B MVAgent No-Skill 三 Benchmark 结果

## 测试配置

| 配置项 | 值 |
|---|---|
| 模型 | /home/kww/models/Qwen3.5/Qwen3.5-35B-A3B |
| Agent 系统 | MVAgent（GlobalAgent / VideoAgent Planner / Observer 同一模型） |
| Skill | 均禁用（no-skill） |
| 视觉帧容量 | 每次视觉请求最多 512 帧 |
| 最近执行的并发 | 6 个模型副本；6 个共享题目 worker |
| 总用时 | 16 小时 50 分 |

## 总览

| Benchmark | 主指标 | 分数（%） | 覆盖 |
|---|---|---:|---:|
| CVBench | Overall strict-letter accuracy | 65.70 | 1000/1000 |
| MVU-Eval | Overall strict-normalized option accuracy | 52.52 | 1824/1824 |
| CrossVid | O.Avg 十任务宏平均（CCQA 用官方 deepseek judge 口径） | 39.80 | 9015/9015 |

## CVBench

| Object Association | Event Association | Complex Reasoning | Overall（严格字母） | 正确数 | 覆盖 |
|---:|---:|---:|---:|---:|---:|
| 68.55 | 65.68 | 63.87 | 65.70 | 657 | 1000/1000 |

| 官方任务 | 正确数/总数 | Accuracy |
|---|---:|---:|
| Cross-video Anomaly Detection | 45/84 | 53.57% |
| Cross-video Counterfactual Reasoning | 32/52 | 61.54% |
| Cross-video Entity Matching | 54/74 | 72.97% |
| Cross-video Event Retrieval | 31/49 | 63.27% |
| Cross-video Object Recognition | 49/68 | 72.06% |
| Cross-video Procedural Transfer | 37/51 | 72.55% |
| Cross-video Scene Recognition | 105/149 | 70.47% |
| Joint-video Counting | 29/60 | 48.33% |
| Joint-video Spatial Navigating | 16/42 | 38.10% |
| Joint-video Summarization | 38/52 | 73.08% |
| Multi-video Attribute Recognition | 38/46 | 82.61% |
| Multi-video Key-Action Recognition | 62/88 | 70.45% |
| Multi-video Temporal Reasoning | 46/75 | 61.33% |
| Multi-view Scene Understanding | 44/55 | 80.00% |
| Video Difference Caption | 31/55 | 56.36% |

## MVU-Eval

| Overall | Comparison | Counting | ICL | KIR | OR | RAG | SU | TR | 覆盖 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 52.52 | 66.67 | 63.00 | 34.15 | 37.72 | 42.86 | 50.15 | 50.28 | 66.76 | 1824/1824 |

## CrossVid

| Task | BU | NC | CC | PEA | PI | FSA | PSS | MSR | MOC | CCQA |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 分数（%） | 40.80 | 46.76 | 54.39 | 27.39 | 66.53 | 19.89 | 41.72 | 40.24 | 36.93 | 23.34 |
| 样例数 | 848 | 1221 | 798 | 953 | 251 | 2248 | 664 | 594 | 566 | 872 |

| #Frames | O.Avg | C.Avg | T.Avg | M.Avg（严格） | CCQA |
|---:|---:|---:|---:|---:|---:|
| 512 | 39.80 | 42.33 | 42.71 | 38.58 | 23.34 |

按题型家族：choice 42.57（5231） ｜ ordering 41.72（664） ｜ open_qa 23.34（872） ｜ temporal 19.89（2248）。

## 数据完整性

- cvbench: 1000/1000 完成，0 错误，0 待跑。
- mvu_eval: 1824/1824 完成，0 错误，0 待跑。
- crossvid: 9015/9015 完成，0 错误，0 待跑。


## 输出解析口径

全部题目得分为主结果；条件得分只用于诊断，剔除无法满足选项输出合同的答案，不是新的公平对照。下表 CrossVid 仅含选择题，不含 FSA/PSS/CCQA。

| 数据集 | 全部选择题 | 无法解析 | 正确数 | 全题得分 | 可解析题得分 |
|---|---:|---:|---:|---:|---:|
| cvbench | 1000 | 10 | 657 | 65.70% | 66.36% |
| mvu_eval | 1824 | 26 | 958 | 52.52% | 53.28% |
| crossvid | 5231 | 458 | 2227 | 42.57% | 46.66% |

## Judge 与稳定性

872 道 CCQA 全部评分成功，按评分点数量加权。请求模型为 `deepseek-v4-flash`，成功响应缓存均返回 `deepseek-flash`；服务端别名已发生版本变化，不视为与历史 V4 Judge 完全相同。原始推理的 summary.json 和 result.json 保留 deferred 状态，完整评分读取 summary_scored.json；评分明细、模型及用量审计见 score/。

前置两次 24 题轨迹逐 token 对比一致；全量运行对应 24 题和后置 24 题复核均一致。这是抽样稳定性证据，不是任意输入永久确定的保证。
