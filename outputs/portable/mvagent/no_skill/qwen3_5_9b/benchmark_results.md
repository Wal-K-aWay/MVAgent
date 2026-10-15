# Qwen3.5-9B MVAgent No-Skill 三 Benchmark 结果

## 测试配置

| 配置项 | 值 |
|---|---|
| 模型 | /home/kww/models/Qwen3.5/Qwen3.5-9B |
| Agent 系统 | MVAgent（GlobalAgent / VideoAgent Planner / Observer 同一模型） |
| Skill | 均禁用（no-skill） |
| 视觉帧容量 | 每次视觉请求最多 512 帧 |
| 并发 | 4 副本 × 2 worker |
| 总用时 | 45 小时 12 分 |

## 总览

| Benchmark | 主指标 | 分数（%） | 覆盖 |
|---|---|---:|---:|
| CVBench | Overall strict-letter accuracy | 64.10 | 1000/1000 |
| MVU-Eval | Overall first-char accuracy（与严格字母一致） | 51.54 | 1824/1824 |
| CrossVid | O.Avg 十任务宏平均（CCQA 用官方 deepseek judge 口径） | 34.01 | 9015/9015 |

## CVBench

| Object Association | Event Association | Complex Reasoning | Overall（严格字母） | 正确数 | 覆盖 |
|---:|---:|---:|---:|---:|---:|
| 67.34 | 66.76 | 59.42 | 64.10 | 641 | 1000/1000 |

| 官方任务 | 正确数/总数 | Accuracy |
|---|---:|---:|
| Cross-video Anomaly Detection | 51/84 | 60.71% |
| Cross-video Counterfactual Reasoning | 28/52 | 53.85% |
| Cross-video Entity Matching | 50/74 | 67.57% |
| Cross-video Event Retrieval | 35/49 | 71.43% |
| Cross-video Object Recognition | 50/68 | 73.53% |
| Cross-video Procedural Transfer | 24/51 | 47.06% |
| Cross-video Scene Recognition | 104/149 | 69.80% |
| Joint-video Counting | 30/60 | 50.00% |
| Joint-video Spatial Navigating | 18/42 | 42.86% |
| Joint-video Summarization | 39/52 | 75.00% |
| Multi-video Attribute Recognition | 37/46 | 80.43% |
| Multi-video Key-Action Recognition | 57/88 | 64.77% |
| Multi-video Temporal Reasoning | 44/75 | 58.67% |
| Multi-view Scene Understanding | 45/55 | 81.82% |
| Video Difference Caption | 29/55 | 52.73% |

## MVU-Eval

| Overall | Comparison | Counting | ICL | KIR | OR | RAG | SU | TR | 覆盖 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 51.54 | 60.00 | 65.64 | 28.66 | 35.59 | 50.00 | 49.56 | 46.37 | 66.76 | 1824/1824 |

## CrossVid

| Task | BU | NC | CC | PEA | PI | FSA | PSS | MSR | MOC | CCQA |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 分数（%） | 38.80 | 41.03 | 51.00 | 29.70 | 54.98 | 9.88 | 28.77 | 37.04 | 33.04 | 15.84 |
| 样例数 | 848 | 1221 | 798 | 953 | 251 | 2248 | 664 | 594 | 566 | 872 |

| #Frames | O.Avg | C.Avg | T.Avg | M.Avg（严格） | CCQA |
|---:|---:|---:|---:|---:|---:|
| 512 | 34.01 | 40.13 | 31.21 | 35.04 | 15.84 |

按题型家族：choice 39.48（5231） ｜ ordering 28.77（664） ｜ open_qa 15.84（872） ｜ temporal 9.88（2248）。

### 与端到端（e2e）对照

| Task | MVAgent no-skill | e2e | 差值 |
|---|---:|---:|---:|
| BU | 38.80 | 18.16 | +20.64 |
| NC | 41.03 | 28.83 | +12.20 |
| CC | 51.00 | 51.45 | -0.45 |
| PEA | 29.70 | 26.44 | +3.26 |
| PI | 54.98 | 76.49 | -21.51 |
| FSA | 9.88 | 4.55 | +5.33 |
| PSS | 28.77 | 4.22 | +24.55 |
| MSR | 37.04 | 27.95 | +9.09 |
| MOC | 33.04 | 39.58 | -6.54 |
| CCQA | 15.84 | 34.60 | -18.76 |
| **O.Avg** | **34.01** | **31.23** | **+2.78** |

注意：CCQA 双方为同一官方 deepseek judge 协议，直接可比；choice 类与 CVBench/MVU 官方口径可比；MSR/MOC（e2e 用最终选项解析）与 FSA/PSS（e2e 对自由文本严格解析，Agent 输出天然满足格式契约）存在解析口径差异，对比需谨慎。

## 数据完整性

- cvbench: 1000/1000 完成，0 错误，0 待跑。
- mvu_eval: 1824/1824 完成，0 错误，0 待跑。
- crossvid: 9015/9015 完成，0 错误，0 待跑。

