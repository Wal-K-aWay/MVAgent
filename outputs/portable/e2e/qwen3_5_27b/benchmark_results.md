# Qwen3.5-27B 三 Benchmark 端到端结果

## 测试配置

| 配置项 | 值 |
|---|---|
| 模型 | Qwen3.5-27B |
| 推理框架 | 本地 vLLM，OpenAI-compatible API |
| 每题总帧数上限 | 512 |
| 图像最长边上限 | 720 |
| CrossVid M.Avg 解析 | MSR、MOC 均抽取模型回答中的最终选项 |
| CCQA Judge | DeepSeek-v4-flash，官方 Coverage/Correctness Prompt |

## 总览

| Benchmark | 主指标 | 分数（%） | 覆盖 |
|---|---|---:|---:|
| CVBench | Overall micro accuracy | 64.99 | 997/1000 |
| MVU-Eval | 官方首字符 Overall accuracy | 56.47 | 1824/1824 |
| CrossVid | O.Avg，M.Avg 使用最终选项 | 39.93 | 各 task 见下表 |

## CVBench

类别分数为论文任务分组内的 micro accuracy，Overall 为全体已完成样例的官方 micro accuracy。

| Object Association | Event Association | Complex Reasoning | Overall | 正确数 | 覆盖 |
|---:|---:|---:|---:|---:|---:|
| 66.53 | 65.41 | 63.59 | 64.99 | 648 | 997/1000 |

## MVU-Eval

| Overall | Comparison | Counting | ICL | KIR | OR | RAG | SU | TR | 覆盖 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 56.47 | 85.19 | 59.03 | 31.10 | 48.40 | 51.59 | 52.80 | 55.87 | 67.02 | 1824/1824 |

## CrossVid

| #Frames | O.Avg | C.Avg | T.Avg | M.Avg（最终选项） | CCQA |
|---:|---:|---:|---:|---:|---:|
| 512 | 39.93 | 50.72 | 28.84 | 31.53 | 46.83 |

| Task | BU | NC | CC | PEA | PI | FSA | PSS | MSR（最终选项） | MOC（最终选项） | CCQA |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 分数（%） | 43.51 | 42.18 | 71.95 | 45.23 | 81.27 | 1.62 | 3.61 | 25.25 | 37.81 | 46.83 |
| 有效样例 | 848 | 1221 | 795 | 953 | 251 | 2246 | 664 | 594 | 566 | 871 |

O.Avg 是十个 task 分数的非加权宏平均；C.Avg 为 BU、NC、CC、PEA 的宏平均；T.Avg 为 PI、FSA、PSS 的宏平均；M.Avg 为最终选项解析后的 MSR、MOC 宏平均。最终选项解析将原严格 M.Avg 的 30.84 提高到 31.53，并将 O.Avg 从 39.79 修正为 39.93。

## 数据完整性说明

- CVBench 的 3 条缺失来自损坏样例，不计入 997 条有效样例的分母。
- CrossVid 的 CC、FSA、CCQA 分别缺少 3、2、1 条损坏样例。
- MVU-Eval 使用官方首字符解析；CrossVid 仅 MSR、MOC 按本次约定改用最终选项抽取。

