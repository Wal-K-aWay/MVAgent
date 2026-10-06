# Qwen3.5-27B MVAgent No-Skill 三 Benchmark 结果

## 测试配置

| 配置项 | 值 |
|---|---|
| 模型 | /home/kww/models/Qwen3.5/Qwen3.5-27B |
| Agent 系统 | MVAgent（GlobalAgent / VideoAgent Planner / Observer 同一模型） |
| Skill | 均禁用（no-skill） |
| 视觉帧容量 | 每次视觉请求最多 512 帧 |
| 最近执行的并发 | 6 个模型副本；6 个共享题目 worker |
| 总用时 | 23 小时 33 分 |

## 总览

| Benchmark | 主指标 | 分数（%） | 覆盖 |
|---|---|---:|---:|
| CVBench | Overall strict-letter accuracy | 68.80 | 1000/1000 |
| MVU-Eval | Overall strict-normalized option accuracy | 54.50 | 1824/1824 |
| CrossVid | O.Avg 十任务宏平均（CCQA 用官方 deepseek judge 口径） | 46.74 | 2500/2500 |

## CVBench

| Object Association | Event Association | Complex Reasoning | Overall（严格字母） | 正确数 | 覆盖 |
|---:|---:|---:|---:|---:|---:|
| 69.76 | 67.57 | 69.37 | 68.80 | 688 | 1000/1000 |

| 官方任务 | 正确数/总数 | Accuracy |
|---|---:|---:|
| Cross-video Anomaly Detection | 54/84 | 64.29% |
| Cross-video Counterfactual Reasoning | 35/52 | 67.31% |
| Cross-video Entity Matching | 53/74 | 71.62% |
| Cross-video Event Retrieval | 30/49 | 61.22% |
| Cross-video Object Recognition | 48/68 | 70.59% |
| Cross-video Procedural Transfer | 35/51 | 68.63% |
| Cross-video Scene Recognition | 109/149 | 73.15% |
| Joint-video Counting | 33/60 | 55.00% |
| Joint-video Spatial Navigating | 21/42 | 50.00% |
| Joint-video Summarization | 40/52 | 76.92% |
| Multi-video Attribute Recognition | 39/46 | 84.78% |
| Multi-video Key-Action Recognition | 57/88 | 64.77% |
| Multi-video Temporal Reasoning | 57/75 | 76.00% |
| Multi-view Scene Understanding | 47/55 | 85.45% |
| Video Difference Caption | 30/55 | 54.55% |

## MVU-Eval

| Overall | Comparison | Counting | ICL | KIR | OR | RAG | SU | TR | 覆盖 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 54.50 | 70.37 | 66.52 | 26.22 | 38.43 | 49.21 | 48.38 | 54.19 | 73.46 | 1824/1824 |

## CrossVid

| Task | BU | NC | CC | PEA | PI | FSA | PSS | MSR | MOC | CCQA |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 分数（%） | 42.24 | 53.29 | 54.13 | 36.78 | 79.00 | 26.73 | 54.95 | 47.24 | 41.94 | 31.11 |
| 样例数 | 232 | 334 | 218 | 261 | 100 | 616 | 182 | 163 | 155 | 239 |

| #Frames | O.Avg | C.Avg | T.Avg | M.Avg（严格） | CCQA |
|---:|---:|---:|---:|---:|---:|
| 512 | 46.74 | 46.61 | 53.56 | 44.59 | 31.11 |

按题型家族：choice 48.60（1463） ｜ ordering 54.95（182） ｜ open_qa 31.11（239） ｜ temporal 26.73（616）。

### 与端到端（e2e）对照

| Task | MVAgent no-skill | e2e | 差值 |
|---|---:|---:|---:|
| BU | 42.24 | 43.51 | -1.27 |
| NC | 53.29 | 42.18 | +11.11 |
| CC | 54.13 | 71.95 | -17.82 |
| PEA | 36.78 | 45.23 | -8.45 |
| PI | 79.00 | 81.27 | -2.27 |
| FSA | 26.73 | 1.62 | +25.11 |
| PSS | 54.95 | 3.61 | +51.34 |
| MSR | 47.24 | 25.25 | +21.99 |
| MOC | 41.94 | 37.81 | +4.13 |
| CCQA | 31.11 | 46.83 | -15.72 |
| **O.Avg** | **46.74** | **39.93** | **+6.81** |

注意：CCQA 双方为同一官方 deepseek judge 协议，直接可比；choice 类与 CVBench/MVU 官方口径可比；MSR/MOC（e2e 用最终选项解析）与 FSA/PSS（e2e 对自由文本严格解析，Agent 输出天然满足格式契约）存在解析口径差异，对比需谨慎。

## 数据完整性

- cvbench: 1000/1000 完成，0 错误，0 待跑。
- mvu_eval: 1824/1824 完成，0 错误，0 待跑。
- crossvid: 2500/2500 完成，0 错误，0 待跑。

